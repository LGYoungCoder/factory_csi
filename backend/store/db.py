"""App database (var/app.db): cases, append-only case events, evidence, MCP/LLM call records, reports."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    Column,
    Engine,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    insert,
    select,
    update,
)

from factory_data.timeutil import format_ts

meta = MetaData()

cases = Table(
    "cases", meta,
    Column("case_id", String, primary_key=True),
    Column("dataset_id", String, nullable=False),
    Column("status", String, nullable=False),
    Column("created_at", String, nullable=False),
    Column("updated_at", String, nullable=False),
    Column("detected_at", String),
    Column("state_json", Text, nullable=False, default="{}"),
    Column("error", Text),
    Column("failure_epoch", Integer),
)
case_events = Table(
    "case_events", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String, nullable=False, index=True),
    Column("seq", Integer, nullable=False),
    Column("type", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", String, nullable=False),
    UniqueConstraint("case_id", "seq"),
)
evidence_items = Table(
    "evidence_items", meta,
    Column("case_id", String, primary_key=True),
    Column("evidence_id", String, primary_key=True),
    Column("finding_key", String, nullable=False),
    Column("item_json", Text, nullable=False),
    UniqueConstraint("case_id", "finding_key"),
)
mcp_calls = Table(
    "mcp_calls", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String, index=True),
    Column("dataset_id", String, nullable=False),
    Column("tool", String, nullable=False),
    Column("arguments", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("error_code", String),
    Column("duration_ms", Float, nullable=False),
    Column("mcp_call_id", String),
    Column("result_size", Integer),
    Column("result_summary", Text),
    Column("created_at", String, nullable=False),
)
llm_calls = Table(
    "llm_calls", meta,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("case_id", String, index=True),
    Column("purpose", String, nullable=False),
    Column("model", String, nullable=False),
    Column("tokens_in", Integer),
    Column("tokens_out", Integer),
    Column("latency_ms", Float),
    Column("status", String, nullable=False),
    Column("cost_usd", Float),
    Column("prompt", Text),
    Column("response", Text),
    Column("created_at", String, nullable=False),
)
reports = Table(
    "reports", meta,
    Column("case_id", String, primary_key=True),
    Column("version", Integer, primary_key=True),
    Column("report_json", Text, nullable=False),
    Column("markdown", Text, nullable=False),
    Column("created_at", String, nullable=False),
)
dataset_epochs = Table(
    "dataset_epochs", meta,
    Column("dataset_id", String, primary_key=True),
    Column("epoch", Integer, nullable=False),
)

ACTIVE = ("CREATED", "RUNNING", "AWAITING_APPROVAL", "CONCLUDING")
EVENT_TYPES = frozenset({
    "status_changed", "node_started", "node_completed", "mcp_call", "llm_call", "anomaly_detected",
    "evidence_added", "hypotheses_updated", "support_downgraded", "citation_dropped", "awaiting_approval",
    "proposal_rejected_by_validator", "decision_recorded", "verification_executed", "verification_failed",
    "judgment_changed", "judgment_change_unattributed", "conclusion_support_capped", "conclusion_finalized",
    "report_generated", "budget_exhausted", "error", "audit", "completed",
})


def now_ts() -> str:
    return format_ts(datetime.now(UTC))


class ConflictError(Exception):
    pass


class Store:
    """Sync SQLAlchemy Core engine; async wrappers run in a thread. Event notification via asyncio.Condition."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

        @event.listens_for(self.engine, "connect")
        def _pragma(conn, _rec):  # noqa: ANN001
            c = conn.cursor()
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=5000")
            c.close()

        meta.create_all(self.engine)
        self._conds: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        self._loop: asyncio.AbstractEventLoop | None = None

    # ---- helpers -------------------------------------------------------------------------
    async def _run(self, fn, *args):  # noqa: ANN001, ANN202
        return await asyncio.to_thread(fn, *args)

    # ---- cases ---------------------------------------------------------------------------
    def _create_case(self, dataset_id: str) -> dict:
        with self.engine.begin() as c:
            active = c.execute(select(cases.c.case_id).where(cases.c.dataset_id == dataset_id,
                                                              cases.c.status.in_(ACTIVE))).first()
            if active:
                raise ConflictError(f"case {active.case_id} is already active on {dataset_id}")
            n = c.execute(select(func.count()).select_from(cases)).scalar_one() + 1
            case_id = f"CASE-{n:04d}"
            ts = now_ts()
            c.execute(insert(cases).values(case_id=case_id, dataset_id=dataset_id, status="CREATED", created_at=ts,
                                           updated_at=ts, state_json="{}"))
            self._bump_epoch(c, dataset_id)
        return self._get_case(case_id)

    async def create_case(self, dataset_id: str) -> dict:
        return await self._run(self._create_case, dataset_id)

    def _get_case(self, case_id: str) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(cases).where(cases.c.case_id == case_id)).mappings().first()
            if r is None:
                return None
            d = dict(r)
            d["state"] = json.loads(d.pop("state_json") or "{}")
            d["last_event_seq"] = c.execute(
                select(func.coalesce(func.max(case_events.c.seq), 0)).where(case_events.c.case_id == case_id)
            ).scalar_one()
            return d

    async def get_case(self, case_id: str) -> dict | None:
        return await self._run(self._get_case, case_id)

    def _list_cases(self, dataset_id: str | None) -> list[dict]:
        with self.engine.connect() as c:
            q = select(cases.c.case_id, cases.c.dataset_id, cases.c.status, cases.c.created_at, cases.c.updated_at)
            if dataset_id:
                q = q.where(cases.c.dataset_id == dataset_id)
            return [dict(r) for r in c.execute(q.order_by(cases.c.created_at.desc(), cases.c.case_id.desc())
                                                .limit(50)).mappings()]

    async def list_cases(self, dataset_id: str | None = None) -> list[dict]:
        return await self._run(self._list_cases, dataset_id)

    def _update_case(self, case_id: str, **fields: Any) -> None:
        if "state" in fields:
            fields["state_json"] = json.dumps(fields.pop("state"), sort_keys=True, default=str)
        fields["updated_at"] = now_ts()
        with self.engine.begin() as c:
            c.execute(update(cases).where(cases.c.case_id == case_id).values(**fields))

    async def update_case(self, case_id: str, **fields: Any) -> None:
        await self._run(lambda: self._update_case(case_id, **fields))

    def _transition(self, case_id: str, allowed_from: tuple[str, ...], to: str) -> str:
        with self.engine.begin() as c:
            row = c.execute(select(cases.c.status).where(cases.c.case_id == case_id)).first()
            if row is None or row.status not in allowed_from:
                raise ConflictError(f"case status is {row.status if row else 'missing'}")
            c.execute(update(cases).where(cases.c.case_id == case_id).values(status=to, updated_at=now_ts()))
            return row.status

    async def transition(self, case_id: str, allowed_from: tuple[str, ...], to: str) -> str:
        return await self._run(self._transition, case_id, allowed_from, to)

    def _active_case(self, dataset_id: str) -> str | None:
        with self.engine.connect() as c:
            r = c.execute(select(cases.c.case_id).where(cases.c.dataset_id == dataset_id,
                                                         cases.c.status.in_(ACTIVE))).first()
            return r.case_id if r else None

    async def active_case(self, dataset_id: str) -> str | None:
        return await self._run(self._active_case, dataset_id)

    # ---- epochs --------------------------------------------------------------------------
    def _bump_epoch(self, c, dataset_id: str) -> int:  # noqa: ANN001
        cur = c.execute(select(dataset_epochs.c.epoch).where(dataset_epochs.c.dataset_id == dataset_id)).first()
        if cur is None:
            c.execute(insert(dataset_epochs).values(dataset_id=dataset_id, epoch=1))
            return 1
        c.execute(update(dataset_epochs).where(dataset_epochs.c.dataset_id == dataset_id).values(epoch=cur.epoch + 1))
        return cur.epoch + 1

    async def bump_epoch(self, dataset_id: str) -> int:
        def f() -> int:
            with self.engine.begin() as c:
                return self._bump_epoch(c, dataset_id)
        return await self._run(f)

    async def epoch(self, dataset_id: str) -> int:
        def f() -> int:
            with self.engine.connect() as c:
                r = c.execute(select(dataset_epochs.c.epoch).where(dataset_epochs.c.dataset_id == dataset_id)).first()
                return r.epoch if r else 0
        return await self._run(f)

    # ---- events --------------------------------------------------------------------------
    def _append_event(self, case_id: str, etype: str, payload: dict) -> int:
        with self.engine.begin() as c:
            seq = c.execute(select(func.coalesce(func.max(case_events.c.seq), 0))
                            .where(case_events.c.case_id == case_id)).scalar_one() + 1
            c.execute(insert(case_events).values(case_id=case_id, seq=seq, type=etype, created_at=now_ts(),
                                                 payload=json.dumps(payload, sort_keys=True, default=str)))
            return seq

    async def append_event(self, case_id: str, etype: str, payload: dict | None = None) -> int:
        if etype not in EVENT_TYPES:
            raise ValueError(f"unknown case event type {etype!r}")
        seq = await self._run(self._append_event, case_id, etype, payload or {})
        cond = self._conds[case_id]
        async with cond:
            cond.notify_all()
        return seq

    def _events_after(self, case_id: str, after: int) -> list[dict]:
        with self.engine.connect() as c:
            rs = c.execute(select(case_events).where(case_events.c.case_id == case_id, case_events.c.seq > after)
                           .order_by(case_events.c.seq)).mappings()
            return [{"seq": r["seq"], "type": r["type"], "payload": json.loads(r["payload"]),
                     "created_at": r["created_at"]} for r in rs]

    async def events_after(self, case_id: str, after: int = 0) -> list[dict]:
        return await self._run(self._events_after, case_id, after)

    async def wait_for_events(self, case_id: str, timeout: float) -> None:
        cond = self._conds[case_id]
        async with cond:
            try:
                await asyncio.wait_for(cond.wait(), timeout)
            except TimeoutError:
                pass

    # ---- evidence ------------------------------------------------------------------------
    def _add_evidence(self, case_id: str, finding_key: str, make_item) -> tuple[dict, bool]:  # noqa: ANN001
        with self.engine.begin() as c:
            row = c.execute(select(evidence_items.c.item_json).where(
                evidence_items.c.case_id == case_id, evidence_items.c.finding_key == finding_key)).first()
            if row:
                return json.loads(row.item_json), False
            n = c.execute(select(func.count()).select_from(evidence_items)
                          .where(evidence_items.c.case_id == case_id)).scalar_one() + 1
            item = make_item(f"EV-{n:03d}")
            c.execute(insert(evidence_items).values(case_id=case_id, evidence_id=item["id"], finding_key=finding_key,
                                                    item_json=json.dumps(item, sort_keys=True, default=str)))
            return item, True

    async def add_evidence(self, case_id: str, finding_key: str, make_item) -> tuple[dict, bool]:  # noqa: ANN001
        return await self._run(self._add_evidence, case_id, finding_key, make_item)

    def _evidence(self, case_id: str) -> list[dict]:
        with self.engine.connect() as c:
            rs = c.execute(select(evidence_items.c.item_json).where(evidence_items.c.case_id == case_id)
                           .order_by(evidence_items.c.evidence_id))
            return [json.loads(r.item_json) for r in rs]

    async def evidence(self, case_id: str) -> list[dict]:
        return await self._run(self._evidence, case_id)

    # ---- call records --------------------------------------------------------------------
    async def record_mcp_call(self, rec: dict) -> None:
        def f() -> None:
            with self.engine.begin() as c:
                c.execute(insert(mcp_calls).values(**rec, created_at=now_ts()))
        await self._run(f)

    async def record_llm_call(self, rec: dict) -> None:
        def f() -> None:
            with self.engine.begin() as c:
                c.execute(insert(llm_calls).values(**rec, created_at=now_ts()))
        await self._run(f)

    async def count_calls(self, case_id: str) -> tuple[int, int]:
        def f() -> tuple[int, int]:
            with self.engine.connect() as c:
                m = c.execute(select(func.count()).select_from(mcp_calls).where(mcp_calls.c.case_id == case_id)
                              ).scalar_one()
                lcount = c.execute(select(func.count()).select_from(llm_calls).where(llm_calls.c.case_id == case_id)
                                   ).scalar_one()
                return int(m), int(lcount)
        return await self._run(f)

    async def mcp_calls_for(self, case_id: str) -> list[dict]:
        def f() -> list[dict]:
            with self.engine.connect() as c:
                rs = c.execute(select(mcp_calls).where(mcp_calls.c.case_id == case_id).order_by(mcp_calls.c.id)
                               .limit(1000)).mappings()
                return [dict(r) for r in rs]
        return await self._run(f)

    async def llm_usage(self, case_id: str) -> dict:
        def f() -> dict:
            with self.engine.connect() as c:
                r = c.execute(select(func.count(), func.sum(llm_calls.c.tokens_in), func.sum(llm_calls.c.tokens_out),
                                     func.sum(llm_calls.c.cost_usd)).where(llm_calls.c.case_id == case_id)).first()
                return {"calls": r[0], "tokens_in": r[1] or 0, "tokens_out": r[2] or 0, "cost_usd": r[3] or 0.0}
        return await self._run(f)

    # ---- reports -------------------------------------------------------------------------
    async def save_report(self, case_id: str, report: dict, markdown: str) -> int:
        def f() -> int:
            with self.engine.begin() as c:
                v = c.execute(select(func.coalesce(func.max(reports.c.version), 0))
                              .where(reports.c.case_id == case_id)).scalar_one() + 1
                c.execute(insert(reports).values(case_id=case_id, version=v, created_at=now_ts(), markdown=markdown,
                                                 report_json=json.dumps(report, sort_keys=True, default=str)))
                return v
        return await self._run(f)

    async def latest_report(self, case_id: str) -> dict | None:
        def f() -> dict | None:
            with self.engine.connect() as c:
                r = c.execute(select(reports).where(reports.c.case_id == case_id)
                              .order_by(reports.c.version.desc()).limit(1)).mappings().first()
                if r is None:
                    return None
                return {"version": r["version"], "report": json.loads(r["report_json"]),
                        "markdown": r["markdown"], "created_at": r["created_at"]}
        return await self._run(f)

    async def cases_in(self, statuses: tuple[str, ...]) -> list[dict]:
        def f() -> list[dict]:
            with self.engine.connect() as c:
                return [dict(r) for r in c.execute(select(cases.c.case_id, cases.c.dataset_id, cases.c.status)
                                                   .where(cases.c.status.in_(statuses))).mappings()]
        return await self._run(f)
