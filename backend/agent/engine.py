"""Investigation engine: explicit LangGraph StateGraph with human-in-the-loop verification."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any, TypedDict

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from backend.agent import prompts
from backend.agent.report import build_report, render_markdown
from backend.analytics import findings as F
from backend.evidence.models import (
    SUPPORT_RANK,
    ConclusionDraft,
    HypothesisSet,
    ProposalSet,
    ReportNarrative,
    apply_guardrails,
    assign_ids,
    cited_ids,
    decide_conclusion,
    hypothesis_errors,
    judgment_changes,
    overclaims,
)
from backend.llm.client import (
    BudgetExhaustedError,
    CaseRuntime,
    HealthChecker,
    LLMClient,
    LLMUnavailableError,
)
from backend.llm.structured import StructuredOutputError, structured_call
from backend.mcp_client.manager import MCPClientManager, MCPToolError
from backend.settings import Settings
from backend.store.db import Store
from factory_data.timeutil import format_ts

log = logging.getLogger("factory_csi.engine")
LLM_TOOLS = ("get_factory_context", "get_eol_summary", "get_product_traces", "get_equipment_events",
             "get_process_changes", "get_reference_sample_checks")
CLOSING_RESERVE = 6


class State(TypedDict, total=False):
    case_id: str
    dataset_id: str
    windows: dict
    anomaly: dict
    raw: dict | None
    hypotheses: list[dict]
    id_map: dict
    history: list[dict]
    proposals: list[dict]
    conclude_option: dict
    final_round: bool
    rejected: list[dict]
    executed: list[dict]
    decisions: list[dict]
    judgment: list[dict]
    rounds: int
    proposal_rounds: int
    reject_count: int
    decision: dict | None
    feedback: str | None
    last_verification: list[str]
    timeline: list[dict]
    conclusion: dict | None
    conclude_reason: str | None
    budget_exhausted: str | None


class CaseFailed(Exception):
    pass


def _now() -> str:
    return format_ts(datetime.now(UTC))


def _norm_params(p: dict) -> str:
    q = dict(p)
    if "serial_numbers" in q:
        q["serial_numbers"] = sorted(q["serial_numbers"])
    return json.dumps(q, sort_keys=True)


class InvestigationEngine:
    def __init__(self, settings: Settings, store: Store, mcp: MCPClientManager, llm: LLMClient,
                 health: HealthChecker):
        self.s, self.store, self.mcp, self.llm, self.health = settings, store, mcp, llm, health
        self.graph = None
        self._conn: aiosqlite.Connection | None = None
        self.tasks: dict[str, asyncio.Task] = {}

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self.s.checkpoint_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(str(self.s.checkpoint_db_path))
        self.graph = self._build().compile(checkpointer=AsyncSqliteSaver(self._conn))

    async def close(self) -> None:
        for t in self.tasks.values():
            t.cancel()
        if self._conn:
            await self._conn.close()

    def _cfg(self, case_id: str) -> dict:
        return {"configurable": {"thread_id": case_id}, "recursion_limit": 80}

    async def _runtime(self, st: State) -> CaseRuntime:
        mcp_used, llm_used = await self.store.count_calls(st["case_id"])
        cid = st["case_id"]

        async def emit(t: str, p: dict) -> None:
            await self.store.append_event(cid, t, p)

        return CaseRuntime(cid, st["dataset_id"], self.s.case_max_mcp_calls, self.s.case_max_llm_calls, mcp_used,
                           llm_used, emit=emit, record_llm=self.store.record_llm_call)

    # ------------------------------------------------------------------ running
    def launch(self, case_id: str, payload: Any) -> None:
        self.tasks[case_id] = asyncio.create_task(self._drive(case_id, payload))

    async def _drive(self, case_id: str, payload: Any) -> None:
        try:
            await self.graph.ainvoke(payload, self._cfg(case_id))
        except CaseFailed:
            pass
        except Exception as exc:  # noqa: BLE001
            log.exception("case %s crashed", case_id)
            await self._fail(case_id, "FAILED", f"internal error: {type(exc).__name__}")
        finally:
            self.tasks.pop(case_id, None)

    async def start_case(self, case_id: str, dataset_id: str) -> None:
        self.launch(case_id, {"case_id": case_id, "dataset_id": dataset_id})

    async def resume(self, case_id: str, decision: dict) -> None:
        self.launch(case_id, Command(resume=decision))

    async def retry(self, case_id: str) -> None:
        await self.store.update_case(case_id, status="RUNNING", error=None)
        await self.store.append_event(case_id, "status_changed", {"from": "FAILED_LLM", "to": "RUNNING",
                                                                  "reason": "retry"})
        self.launch(case_id, None)

    async def pending(self, case_id: str) -> dict | None:
        state = await self.graph.aget_state(self._cfg(case_id))
        for t in state.tasks:
            for i in t.interrupts:
                return i.value
        return None

    async def has_checkpoint(self, case_id: str) -> bool:
        state = await self.graph.aget_state(self._cfg(case_id))
        return bool(state.values)

    async def snapshot(self, case_id: str) -> dict:
        state = await self.graph.aget_state(self._cfg(case_id))
        v = dict(state.values or {})
        v.pop("raw", None)
        return v

    async def _fail(self, case_id: str, status: str, reason: str) -> None:
        case = await self.store.get_case(case_id)
        prev = case["status"] if case else "RUNNING"
        await self.store.update_case(case_id, status=status, error=reason,
                                     failure_epoch=await self.store.epoch(case["dataset_id"]) if case else None)
        await self.store.append_event(case_id, "error", {"code": status, "message": reason})
        await self.store.append_event(case_id, "status_changed", {"from": prev, "to": status, "reason": reason})
        await self.store.append_event(case_id, "completed", {"final_status": status})
        if status == "FAILED_LLM":
            self.health.mark_unavailable(reason)

    # ------------------------------------------------------------------ helpers
    async def _mcp(self, rt: CaseRuntime, tool: str, args: dict) -> dict:
        if rt.mcp_used >= rt.max_mcp:
            raise BudgetExhaustedError("mcp_calls", rt.max_mcp, rt.mcp_used)
        rt.mcp_used += 1
        try:
            body = await self.mcp.call(rt.dataset_id, tool, args, case_id=rt.case_id)
            await rt.emit("mcp_call", {"mcp_call_id": body.get("call_id"), "tool": tool,
                                       "arguments_summary": json.dumps(args, sort_keys=True)[:300], "status": "OK",
                                       "duration_ms": None})
            return body
        except MCPToolError as exc:
            await rt.emit("mcp_call", {"mcp_call_id": exc.call_id, "tool": tool,
                                       "arguments_summary": json.dumps(args, sort_keys=True)[:300],
                                       "status": "ERROR", "error_code": exc.code, "duration_ms": None})
            raise

    async def _evidence(self, case_id: str) -> list[dict]:
        return await self.store.evidence(case_id)

    async def _register(self, rt: CaseRuntime, f: F.Finding) -> dict:
        def make(eid: str) -> dict:
            return {"id": eid, "case_id": rt.case_id, "kind": f.kind, "source_system": f.source_system,
                    "title": f.title, "summary": f.summary,
                    "data": {**f.data, "ref_rows": f.ref_rows, "mechanism": f.mechanism},
                    "record_refs": f.record_refs[:50], "mcp_call_ids": [c for c in f.mcp_call_ids if c],
                    "ts": f.ts, "equipment": f.equipment, "created_at": _now()}
        item, new = await self.store.add_evidence(rt.case_id, f.key, make)
        if new:
            await rt.emit("evidence_added", {"evidence_id": item["id"], "kind": item["kind"],
                                             "source_system": item["source_system"], "title": item["title"]})
        return item

    def _digest(self, evidence: list[dict]) -> str:
        order = {"verification": 0, "statistic": 1, "absence": 2, "event": 3, "record": 4}
        ev = sorted(evidence, key=lambda e: (order.get(e["kind"], 5), e["id"]))
        lines, size = [], 0
        for e in ev:
            mech = e.get("data", {}).get("mechanism") or []
            tag = f" [shows: {', '.join(mech)}]" if mech else ""
            line = f"{e['id']} [{e['kind']}|{e['source_system']}]{tag} {e['title']}: {e['summary']}"
            if size + len(line) > self.s.evidence_payload_max_chars:
                lines.append(f"... {len(ev) - len(lines)} more evidence items omitted for length")
                break
            lines.append(line)
            size += len(line)
        return "\n".join(sorted(lines, key=lambda x: x[:7]))

    @staticmethod
    def _hyp_text(hyps: list[dict]) -> str:
        return json.dumps([{k: h[k] for k in ("hypothesis_id", "category", "title", "support",
                                              "supporting_evidence", "contradicting_evidence",
                                              "missing_evidence")} for h in hyps], indent=0)

    async def _node(self, st: State, name: str, fn) -> dict:  # noqa: ANN001
        rt = await self._runtime(st)
        await rt.emit("node_started", {"node": name})
        t0 = asyncio.get_running_loop().time()
        try:
            out = await fn(st, rt)
        except BudgetExhaustedError as exc:
            await rt.emit("budget_exhausted", {"budget": exc.budget, "limit": exc.limit, "used": exc.used})
            out = {"budget_exhausted": exc.budget}
        except (LLMUnavailableError, StructuredOutputError) as exc:
            await self._fail(st["case_id"], "FAILED_LLM", f"{name}: {str(exc)[:300]}")
            raise CaseFailed from exc
        except MCPToolError as exc:
            await self._fail(st["case_id"], "FAILED", f"{name}: MCP {exc.code}: {exc.message[:200]}")
            raise CaseFailed from exc
        await rt.emit("node_completed", {"node": name,
                                         "duration_ms": round((asyncio.get_running_loop().time() - t0) * 1000)})
        await self.store.update_case(st["case_id"], state=_public_state({**st, **out}))
        return out

    # ------------------------------------------------------------------ graph
    def _build(self) -> StateGraph:
        g = StateGraph(State)
        nodes = {
            "load_case": self._load_case, "detect_anomaly": self._detect, "collect_evidence": self._collect,
            "analyze_evidence": self._analyze, "generate_hypotheses": self._hypotheses,
            "propose_verification": self._propose, "human_approval": self._approval,
            "execute_verification": self._execute, "update_hypotheses": self._update,
            "finalize_conclusion": self._finalize, "generate_report": self._report,
        }
        def wrap(fn, name: str):  # noqa: ANN001, ANN202
            async def node(st: State) -> dict:
                return await self._node(st, name, fn)
            return node

        for name, fn in nodes.items():
            g.add_node(name, fn if name == "human_approval" else wrap(fn, name))
        g.add_edge(START, "load_case")
        g.add_edge("load_case", "detect_anomaly")
        g.add_conditional_edges("detect_anomaly", self._after_detect, ["collect_evidence", "generate_report"])
        g.add_conditional_edges("collect_evidence", self._ok_or_report, ["analyze_evidence", "generate_report"])
        g.add_conditional_edges("analyze_evidence", self._ok_or_report, ["generate_hypotheses", "generate_report"])
        g.add_conditional_edges("generate_hypotheses", self._ok_or_report, ["propose_verification", "generate_report"])
        g.add_conditional_edges("propose_verification", self._after_propose,
                                ["human_approval", "finalize_conclusion"])
        g.add_conditional_edges("human_approval", self._after_approval,
                                ["execute_verification", "propose_verification", "finalize_conclusion"])
        g.add_conditional_edges("execute_verification", self._after_execute,
                                ["update_hypotheses", "propose_verification", "finalize_conclusion"])
        g.add_conditional_edges("update_hypotheses", self._after_update,
                                ["propose_verification", "finalize_conclusion"])
        g.add_edge("finalize_conclusion", "generate_report")
        g.add_edge("generate_report", END)
        return g

    # routing
    @staticmethod
    def _after_detect(st: State) -> str:
        if st.get("budget_exhausted") or st["anomaly"]["status"] != "ANOMALY":
            return "generate_report"
        return "collect_evidence"

    @staticmethod
    def _ok_or_report(st: State) -> str:
        """collect → analyze → hypotheses → propose, unless a budget ran out."""
        if st.get("budget_exhausted"):
            return "generate_report"
        if st.get("raw") is not None:
            return "analyze_evidence"
        return "propose_verification" if st.get("hypotheses") else "generate_hypotheses"

    @staticmethod
    def _after_propose(st: State) -> str:
        return "finalize_conclusion" if st.get("conclude_reason") else "human_approval"

    @staticmethod
    def _after_approval(st: State) -> str:
        action = (st.get("decision") or {}).get("action")
        return {"approve": "execute_verification", "reject_all": "propose_verification"}.get(
            action, "finalize_conclusion")

    def _after_execute(self, st: State) -> str:
        if st.get("budget_exhausted"):
            return "finalize_conclusion"
        if not st.get("last_verification"):
            return "propose_verification" if st.get("rounds", 0) < self.s.max_verification_rounds else \
                "finalize_conclusion"
        return "update_hypotheses"

    def _after_update(self, st: State) -> str:
        if st.get("budget_exhausted") or st.get("rounds", 0) >= self.s.max_verification_rounds:
            return "finalize_conclusion"
        return "propose_verification"

    # ------------------------------------------------------------------ nodes
    async def _load_case(self, st: State, rt: CaseRuntime) -> dict:
        case = await self.store.get_case(st["case_id"])
        if case and case["status"] == "CREATED":
            await self.store.update_case(st["case_id"], status="RUNNING")
            await rt.emit("status_changed", {"from": "CREATED", "to": "RUNNING", "reason": "investigation started"})
        ctx = await self._mcp(rt, "get_factory_context", {})
        w = F.Windows.from_context(ctx)
        return {"windows": w.as_dict(), "rounds": 0, "proposal_rounds": 0, "reject_count": 0, "rejected": [],
                "executed": [], "decisions": [], "judgment": [], "history": [], "id_map": {}, "hypotheses": [],
                "raw": {"context_call": ctx["call_id"]}}

    async def _detect(self, st: State, rt: CaseRuntime) -> dict:
        w = F.Windows(**st["windows"])
        base = await self._mcp(rt, "get_eol_summary", {"start": w.data_start, "end": w.baseline_end})
        det = await self._mcp(rt, "get_eol_summary", {"start": w.detection_start, "end": w.data_end})
        anomaly = F.detect_anomaly(base, det, w)
        await rt.emit("anomaly_detected", {"anomalies": [{k: a[k] for k in ("equipment_id", "baseline_rate",
                                                                           "window_rate", "p_value")}
                                                         for a in anomaly["anomalies"]],
                                           "detected_window": anomaly["detected_window"], "status": anomaly["status"]})
        await self.store.update_case(st["case_id"], detected_at=_now())
        for f in F.anomaly_findings(anomaly, det, [base["call_id"], det["call_id"]]):
            await self._register(rt, f)
        return {"anomaly": anomaly, "raw": {**(st.get("raw") or {}), "baseline": base, "detection": det}}

    async def _collect(self, st: State, rt: CaseRuntime) -> dict:
        w = F.Windows(**st["windows"])
        raw = dict(st.get("raw") or {})
        full = {"start": w.data_start, "end": w.data_end}
        raw["full"] = await self._mcp(rt, "get_eol_summary", {**full, "bucket_minutes": 30})
        raw["changes"] = await self._mcp(rt, "get_process_changes", full)
        raw["refs"] = {t: await self._mcp(rt, "get_reference_sample_checks", {"tester_id": t, **full})
                       for t in F.TESTERS}
        raw["st20"] = await self._mcp(rt, "get_equipment_events", {"equipment_id": "ST-20", **full,
                                                                     "include_measurements": True})
        raw["events"] = {}
        for a in st["anomaly"]["anomalies"]:
            raw["events"][a["equipment_id"]] = await self._mcp(rt, "get_equipment_events",
                                                                {"equipment_id": a["equipment_id"], **full})
        raw["before_after"] = {}
        for ch in raw["changes"]["changes"][:1]:
            pre = await self._mcp(rt, "get_eol_summary", {"start": w.data_start, "end": ch["ts"]})
            post = await self._mcp(rt, "get_eol_summary", {"start": ch["ts"], "end": w.data_end})
            raw["before_after"][ch["change_id"]] = (pre, post)
        sns = [i["sn"] for i in raw["detection"]["failed_sn_sample"]["items"]][:20]
        raw["traces"] = await self._mcp(rt, "get_product_traces", {"serial_numbers": sns}) if sns else {"traces": []}
        # register deterministic findings before the LLM sees anything
        for f in self._analyze_raw(st, raw):
            await self._register(rt, f)
        # LLM tool loop for additional queries
        budget_left = rt.remaining_mcp() - (self.s.max_verification_rounds + 1)
        n = max(0, min(self.s.tool_loop_max_calls, budget_left))
        if n > 0:
            await self._tool_loop(st, rt, n)
        return {"raw": raw}

    async def _tool_loop(self, st: State, rt: CaseRuntime, n: int) -> None:
        tools = [t for t in await self.mcp.list_tools(st["dataset_id"]) if t.name in LLM_TOOLS]
        schemas = []
        for t in tools:
            params = json.loads(json.dumps(t.input_schema))
            params.get("properties", {}).pop("include_measurements", None)
            schemas.append({"type": "function", "function": {"name": t.name, "description": t.description or "",
                                                              "parameters": params}})
        w = st["windows"]
        msgs = [{"role": "system", "content": prompts.SYSTEM},
                {"role": "user", "content": prompts.COLLECT.format(
                    digest=self._digest(await self._evidence(st["case_id"])),
                    detection=f"{w['detection_start']} – {w['data_end']}",
                    baseline=f"{w['data_start']} – {w['baseline_end']}", n=n)}]
        used = 0
        while used < n:
            resp = await self.llm.complete(rt, "collect_evidence:tool_loop", msgs, tools=schemas)
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            if not calls:
                return
            msgs.append({"role": "assistant", "content": msg.content or "",
                         "tool_calls": [c.model_dump() for c in calls]})
            for c in calls:
                if used >= n or c.function.name not in LLM_TOOLS:
                    content = json.dumps({"error": "tool call not allowed or limit reached"})
                    await rt.emit("audit", {"name": "tool_call_rejected", "actor": "system",
                                            "details": {"tool": c.function.name}})
                else:
                    used += 1
                    try:
                        args = json.loads(c.function.arguments or "{}")
                        args.pop("include_measurements", None)
                        body = await self._mcp(rt, c.function.name, args)
                        f = _extra_finding(c.function.name, args, body)
                        item = await self._register(rt, f)
                        content = json.dumps({"evidence_id": item["id"], "summary": item["summary"],
                                              "result": _shrink(body)})[:6000]
                    except (json.JSONDecodeError, MCPToolError) as exc:
                        content = json.dumps({"error": str(exc)[:300]})
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": content})

    def _analyze_raw(self, st: State, raw: dict) -> list[F.Finding]:
        w = F.Windows(**st["windows"])
        out: list[F.Finding] = []
        out += F.reference_findings(raw["refs"], w, {t: raw["refs"][t]["call_id"] for t in F.TESTERS})
        out += F.retest_findings(raw["full"], raw["full"]["call_id"])
        out += F.onset_findings(raw["full"], st["anomaly"], raw["full"]["call_id"])
        out += F.comparison_findings(raw["baseline"], raw["detection"],
                                     [raw["baseline"]["call_id"], raw["detection"]["call_id"]])
        ba = raw.get("before_after") or {}
        ids = {"changes": raw["changes"]["call_id"], "st20": raw["st20"]["call_id"]}
        if ba:
            pre, post = next(iter(ba.values()))
            ids.update(before=pre["call_id"], after=post["call_id"])
        out += F.process_findings(raw["changes"], raw["st20"], w, ids, ba)
        out += F.material_findings(raw["traces"], raw["traces"].get("call_id", ""))
        out += F.event_findings(raw["events"], {k: v["call_id"] for k, v in raw["events"].items()})
        return out

    async def _analyze(self, st: State, rt: CaseRuntime) -> dict:
        """Deterministic: evidence was registered from raw tool output; build the timeline, drop raw data."""
        ev = await self._evidence(st["case_id"])
        return {"raw": None, "timeline": F.timeline(ev)}

    async def _hypotheses(self, st: State, rt: CaseRuntime) -> dict:
        ev = await self._evidence(st["case_id"])
        known = {e["id"]: e for e in ev}
        hs = await structured_call(
            self.llm, rt, "generate_hypotheses", prompts.SYSTEM,
            prompts.HYPOTHESES.format(anomaly=json.dumps(st["anomaly"]["anomalies"]), digest=self._digest(ev)),
            HypothesisSet, check=lambda h: hypothesis_errors(h, set(known)), sanitize=lambda h: h)
        hyps, events = apply_guardrails(hs, known)
        id_map = dict(st.get("id_map") or {})
        hyps = assign_ids(hyps, id_map)
        for e in events:
            await rt.emit(e["type"], e["payload"])
        await rt.emit("hypotheses_updated", {"round": 0, "hypotheses": hyps})
        return {"hypotheses": hyps, "id_map": id_map, "history": [{"round": 0, "hypotheses": hyps}]}

    def _candidates(self, st: State, ev: list[dict]) -> dict[str, list[dict]]:
        done = {sn for x in st.get("executed", []) for sn in x["params"].get("serial_numbers", [])}
        out: dict[str, list[dict]] = {t: [] for t in F.TESTERS}
        seen = set()
        for e in ev:
            for r in e.get("data", {}).get("ref_rows", []):
                if r.get("result") == "FAIL" and not r.get("is_retest") and r.get("sn") and \
                        r.get("tester_id") in out and r["sn"] not in seen and r["sn"] not in done:
                    seen.add(r["sn"])
                    out[r["tester_id"]].append({"sn": r["sn"], "ts": r["ts"], "model_id": r.get("model_id")})
        return {t: sorted(v, key=lambda x: x["ts"], reverse=True)[:20] for t, v in out.items()}

    def validate_proposal(self, p: dict, st: State, cands: dict, known: set[str]) -> str | None:
        t = p["verification_type"]
        if t == "cross_retest":
            sns = p.get("serial_numbers") or []
            allowed = {c["sn"] for v in cands.values() for c in v}
            if not 1 <= len(sns) <= 5 or len(set(sns)) != len(sns):
                return "cross_retest needs 1–5 distinct serial numbers"
            if any(s not in allowed for s in sns):
                return "serial numbers must come from the candidate list"
            if p.get("target_tester_id") not in F.TESTERS:
                return "target_tester_id must be EOL-A or EOL-B"
            params = {"serial_numbers": sns, "target_tester_id": p["target_tester_id"]}
        elif t == "reference_sample_check":
            if p.get("tester_id") not in F.TESTERS:
                return "tester_id must be EOL-A or EOL-B"
            params = {"tester_id": p["tester_id"]}
        else:
            if p.get("equipment_id") not in ("ST-10", "ST-20", "ST-30"):
                return "equipment_id must be ST-10, ST-20 or ST-30"
            params = {"equipment_id": p["equipment_id"]}
        key = t + _norm_params(params)
        if any(x["type"] + _norm_params(x["params"]) == key for x in st.get("executed", [])):
            return "identical verification already executed"
        if any(x["verification_type"] + _norm_params(x["params"]) == key for x in st.get("rejected", [])):
            return "identical proposal was rejected by the engineer"
        unknown = (set(p.get("cited_evidence", [])) | cited_ids(p.get("rationale", ""))) - known
        if unknown:
            return f"unknown evidence ids {sorted(unknown)}"
        p["params"] = params
        return None

    async def _propose(self, st: State, rt: CaseRuntime) -> dict:
        if rt.remaining_llm() < CLOSING_RESERVE + 6 or rt.remaining_mcp() < 1:
            await rt.emit("audit", {"name": "loop_auto_concluded", "actor": "system",
                                    "details": {"reason": "budget_exhausted"}})
            return {"conclude_reason": "budget_exhausted"}
        ev = await self._evidence(st["case_id"])
        known = {e["id"] for e in ev}
        cands = self._candidates(st, ev)
        rounds_left = self.s.max_verification_rounds - st.get("rounds", 0)
        valid: list[dict] = []
        rejected_by_validator: list[dict] = []

        def check(ps: ProposalSet) -> list[str]:
            errs = []
            for i, p in enumerate(ps.proposals):
                e = self.validate_proposal(p.model_dump(), st, cands, known)
                if e:
                    errs.append(f"proposal {i + 1}: {e}")
            if not ps.proposals and not ps.recommend_conclude:
                errs.append("give at least one proposal or recommend_conclude=true")
            return errs

        ps = await structured_call(
            self.llm, rt, "propose_verification", prompts.SYSTEM,
            prompts.PROPOSE.format(
                hypotheses=self._hyp_text(st["hypotheses"]), digest=self._digest(ev),
                candidates=json.dumps(cands), executed=json.dumps([{"type": x["type"], "params": x["params"]}
                                                                   for x in st.get("executed", [])]),
                rejected=json.dumps([{"type": x["verification_type"], "params": x["params"]}
                                     for x in st.get("rejected", [])]),
                feedback=st.get("feedback") or "none", rounds_left=rounds_left),
            ProposalSet, check=check, sanitize=lambda x: x)
        prnd = st.get("proposal_rounds", 0) + 1
        for p in ps.proposals:
            d = p.model_dump()
            err = self.validate_proposal(d, st, cands, known)
            if err:
                rejected_by_validator.append(d)
                await rt.emit("proposal_rejected_by_validator", {"proposal": d, "reason": err})
                continue
            if any(v["verification_type"] + _norm_params(v["params"]) == d["verification_type"] + _norm_params(d["params"])
                   for v in valid):
                continue
            d["rank"] = len(valid) + 1
            d["proposal_id"] = f"P-{prnd}-{d['rank']}"
            valid.append(d)
        conclude = {"recommended": bool(ps.recommend_conclude) or not valid,
                    "reason": ps.conclude_reason if ps.recommend_conclude else (
                        None if valid else "no valid verification proposal")}
        final_round = st.get("reject_count", 0) >= self.s.max_reject_all
        await self.store.update_case(st["case_id"], status="AWAITING_APPROVAL")
        await rt.emit("status_changed", {"from": "RUNNING", "to": "AWAITING_APPROVAL", "reason": "proposals ready"})
        await rt.emit("awaiting_approval", {
            "round": prnd, "proposals": valid, "conclude_option": conclude, "final_round_of_suggestions": final_round,
            "budgets": {"mcp_remaining": rt.remaining_mcp(), "llm_remaining": rt.remaining_llm(),
                        "rounds_remaining": rounds_left,
                        "reject_all_remaining": self.s.max_reject_all - st.get("reject_count", 0)}})
        return {"proposals": valid, "conclude_option": conclude, "final_round": final_round,
                "proposal_rounds": prnd, "decision": None, "conclude_reason": None}

    async def _approval(self, st: State) -> dict:
        decision = interrupt({"case_id": st["case_id"], "round": st.get("proposal_rounds"),
                              "proposals": st.get("proposals", []), "conclude_option": st.get("conclude_option"),
                              "final_round_of_suggestions": st.get("final_round", False)})
        upd: dict = {"decision": decision, "decisions": [*st.get("decisions", []), decision]}
        if decision["action"] == "reject_all":
            upd["rejected"] = [*st.get("rejected", []), *st.get("proposals", [])]
            upd["reject_count"] = st.get("reject_count", 0) + 1
            upd["feedback"] = decision.get("note")
        if decision["action"] == "conclude":
            upd["conclude_reason"] = "engineer concluded"
        return upd

    def validate_decision(self, pending: dict, reject_count: int, d: dict) -> str | None:
        """Returns an error code or None (API validates before resuming)."""
        action = d.get("action")
        if action not in ("approve", "reject_all", "conclude"):
            return "INVALID_ACTION"
        note = d.get("note")
        if note is not None and len(note) > 500:
            return "NOTE_TOO_LONG"
        actor = d.get("actor")
        if actor is not None and not (1 <= len(actor) <= 64):
            return "INVALID_ACTOR"
        ids = {p["proposal_id"] for p in pending.get("proposals", [])}
        if action == "approve":
            if not ids:
                return "ACTION_NOT_OFFERED"
            if d.get("proposal_id") not in ids:
                return "UNKNOWN_PROPOSAL"
        elif d.get("proposal_id"):
            return "UNEXPECTED_PROPOSAL_ID"
        if action == "reject_all":
            if not (note or "").strip():
                return "NOTE_REQUIRED"
            if reject_count >= self.s.max_reject_all:
                return "REJECT_LIMIT_REACHED"
            if not ids:
                return "ACTION_NOT_OFFERED"
        return None

    async def _execute(self, st: State, rt: CaseRuntime) -> dict:
        d = st.get("decision") or {}
        prop = next((p for p in st.get("proposals", []) if p["proposal_id"] == d.get("proposal_id")), None)
        if d.get("action") != "approve" or prop is None:  # defense in depth: never verify without approval
            await rt.emit("audit", {"name": "verification_blocked_no_approval", "actor": "system", "details": d})
            return {"last_verification": []}
        rnd = st.get("rounds", 0) + 1
        approval_id = f"APR-{st['case_id']}-{rnd}"
        actor = d.get("actor") or "engineer"
        try:
            body = await self._mcp(rt, "run_simulated_verification", {
                "verification_type": prop["verification_type"], "params": prop["params"],
                "approval_id": approval_id, "approved_by": actor})
        except MCPToolError as exc:
            await rt.emit("verification_failed", {"proposal_id": prop["proposal_id"], "approval_id": approval_id,
                                                  "error_code": exc.code})
            return {"rounds": rnd, "last_verification": []}
        outs = body["outcomes"]
        unavailable = any(o["outcome"] == "UNAVAILABLE" for o in outs)
        kinds = [o["outcome"] for o in outs]
        mech: list[str] = []
        if prop["verification_type"] == "cross_retest" and kinds.count("PASS") > len(kinds) / 2:
            mech = ["TESTER_MEASUREMENT_DRIFT"]
        elif "OUT_OF_TOLERANCE" in kinds:
            mech = ["TESTER_MEASUREMENT_DRIFT"]
        elif "MISMATCH" in kinds:
            mech = ["PROCESS_PARAMETER_DEVIATION"]
        f = F.Finding(
            f"verification:{approval_id}", "absence" if unavailable else "verification", "VERIFICATION",
            f"Simulated {prop['verification_type'].replace('_', ' ')} ({body['target']})", body["summary"],
            {"verification_id": body["verification_id"], "verification_type": prop["verification_type"],
             "params": prop["params"], "outcomes": outs, "approval_id": approval_id, "approved_by": actor,
             "simulation": True, "proposal_id": prop["proposal_id"]},
            body["created_refs"],
            [{"ref": f"eol_tests:{o['test_id']}", "sn": o["sn"], "tester_id": o["retest_tester_id"],
              "ts": body["simulated_ts"], "result": o["outcome"], "is_retest": True}
             for o in outs if o.get("test_id")],
            [body["call_id"]], body["simulated_ts"], [body["target"]], mech)
        item = await self._register(rt, f)
        await rt.emit("verification_executed", {"proposal_id": prop["proposal_id"], "approval_id": approval_id,
                                                "verification_id": body["verification_id"],
                                                "outcomes_summary": body["summary"], "evidence_ids": [item["id"]]})
        executed = [*st.get("executed", []), {"type": prop["verification_type"], "params": prop["params"],
                                              "proposal_id": prop["proposal_id"], "approval_id": approval_id,
                                              "actor": actor, "evidence_id": item["id"], "summary": body["summary"],
                                              "note": d.get("note")}]
        return {"rounds": rnd, "executed": executed, "last_verification": [item["id"]]}

    async def _update(self, st: State, rt: CaseRuntime) -> dict:
        ev = await self._evidence(st["case_id"])
        known = {e["id"]: e for e in ev}
        new = st.get("last_verification", [])
        new_text = "; ".join(f"{e['id']}: {e['summary']}" for e in ev if e["id"] in new)
        hs = await structured_call(
            self.llm, rt, "update_hypotheses", prompts.SYSTEM,
            prompts.UPDATE.format(hypotheses=self._hyp_text(st["hypotheses"]), new_evidence=new_text,
                                  digest=self._digest(ev)),
            HypothesisSet, check=lambda h: hypothesis_errors(h, set(known)), sanitize=lambda h: h)
        hyps, events = apply_guardrails(hs, known)
        id_map = dict(st.get("id_map") or {})
        hyps = assign_ids(hyps, id_map)
        for e in events:
            await rt.emit(e["type"], e["payload"])
        changes = judgment_changes(st["hypotheses"], hyps, new)
        prev = {h["category"]: h for h in st["hypotheses"]}
        final = []
        for h in hyps:
            ch = next(c for c in changes if c["category"] == h["category"])
            if ch["direction"] in ("up", "down") and not ch["because"]:
                await rt.emit("judgment_change_unattributed", {"hypothesis_id": h["hypothesis_id"]})
                h = {**h, "support": prev[h["category"]]["support"]}
                ch.update(after=h["support"], direction="unchanged")
            final.append(h)
        rnd = st.get("rounds", 0)
        changes = [c for c in changes if c["direction"] != "unchanged"]
        for c in changes:
            c["round"] = rnd
            await rt.emit("judgment_changed", {"change": c})
        await rt.emit("hypotheses_updated", {"round": rnd, "hypotheses": final})
        return {"hypotheses": final, "id_map": id_map, "judgment": [*st.get("judgment", []), *changes],
                "history": [*st.get("history", []), {"round": rnd, "hypotheses": final}]}

    async def _finalize(self, st: State, rt: CaseRuntime) -> dict:
        case = await self.store.get_case(st["case_id"])
        if case and case["status"] != "CONCLUDING":
            await self.store.update_case(st["case_id"], status="CONCLUDING")
            await rt.emit("status_changed", {"from": case["status"], "to": "CONCLUDING",
                                             "reason": st.get("conclude_reason") or "verification rounds complete"})
        hyps = st.get("hypotheses", [])
        category, support = decide_conclusion(hyps)
        ev = await self._evidence(st["case_id"])
        known = {e["id"] for e in ev}
        steps = [x["summary"] for x in st.get("executed", [])]

        def check(c: ConclusionDraft) -> list[str]:
            errs = []
            if c.category != category:
                errs.append(f"category must be {category}")
            bad = (set(c.cited_evidence) | cited_ids(c.statement)) - known
            if bad:
                errs.append(f"unknown evidence ids {sorted(bad)}")
            if overclaims(c.statement):
                errs.append("avoid overclaiming phrases such as 'confirmed root cause' or 'proven'")
            return errs

        draft = None
        if rt.remaining_llm() > 0:
            draft = await structured_call(
                self.llm, rt, "finalize_conclusion", prompts.SYSTEM,
                prompts.CONCLUDE.format(hypotheses=self._hyp_text(hyps), digest=self._digest(ev),
                                        steps=json.dumps(steps), category=category, support=support),
                ConclusionDraft, check=check, sanitize=lambda c: c)
        top = next((h for h in hyps if h["category"] == category), None)
        conclusion = {
            "category": category, "support": support,
            "label": ("Evidence-supported cause" if support == "HIGH" else "Suspected cause")
            if category != "INSUFFICIENT_EVIDENCE" else "Insufficient evidence for a conclusion",
            "statement": draft.statement if draft and draft.category == category else None,
            "cited_evidence": sorted(set(draft.cited_evidence) & known) if draft else
            (top or {}).get("supporting_evidence", []),
            "open_questions": draft.open_questions if draft else [],
            "reason": st.get("conclude_reason"),
        }
        await rt.emit("conclusion_finalized", {"conclusion": conclusion})
        return {"conclusion": conclusion}

    async def _report(self, st: State, rt: CaseRuntime) -> dict:
        ev = await self._evidence(st["case_id"])
        case = await self.store.get_case(st["case_id"])
        if case and case["status"] == "RUNNING":
            await self.store.update_case(st["case_id"], status="CONCLUDING")
            await rt.emit("status_changed", {"from": "RUNNING", "to": "CONCLUDING", "reason": "generating report"})
        events = await self.store.events_after(st["case_id"], 0)
        report = build_report(st, ev, events)
        known = {e["id"] for e in ev}
        narrative, marker = None, None
        if st.get("anomaly", {}).get("status") == "ANOMALY" and st.get("hypotheses"):
            if rt.remaining_llm() <= 0:
                marker = "Narrative unavailable – LLM budget exhausted"
            else:
                def check(n: ReportNarrative) -> list[str]:
                    text = n.overview + " " + " ".join(n.follow_up_actions) + " " + n.limitations
                    errs = []
                    bad = cited_ids(text) - known
                    if bad:
                        errs.append(f"unknown evidence ids {sorted(bad)}")
                    if overclaims(text):
                        errs.append("avoid overclaiming phrases such as 'confirmed root cause' or 'proven'")
                    return errs
                try:
                    narrative = await structured_call(
                        self.llm, rt, "generate_report", prompts.SYSTEM,
                        prompts.REPORT.format(conclusion=json.dumps(st.get("conclusion")),
                                              hypotheses=self._hyp_text(st.get("hypotheses", [])),
                                              steps=json.dumps([x["summary"] for x in st.get("executed", [])]),
                                              changes=json.dumps(st.get("judgment", [])), digest=self._digest(ev)),
                        ReportNarrative, check=check)
                except StructuredOutputError:
                    marker = "Narrative unavailable – LLM output failed validation"
                    await rt.emit("audit", {"name": "narrative_unavailable", "actor": "system",
                                            "details": {"reason": "validation"}})
        report["narrative"] = narrative.model_dump() if narrative else None
        report["narrative_marker"] = marker
        md = render_markdown(report)
        version = await self.store.save_report(st["case_id"], report, md)
        await rt.emit("report_generated", {"version": version})
        case = await self.store.get_case(st["case_id"])
        await self.store.update_case(st["case_id"], status="COMPLETED")
        await rt.emit("status_changed", {"from": case["status"] if case else "CONCLUDING", "to": "COMPLETED",
                                         "reason": "report generated"})
        await rt.emit("completed", {"final_status": "COMPLETED"})
        return {}


def _public_state(st: dict) -> dict:
    return {k: v for k, v in st.items() if k not in ("raw",)}


def _shrink(body: dict) -> dict:
    out = {}
    for k, v in body.items():
        if k in ("buckets", "measurements", "traces", "events", "checks"):
            out[k] = v[:8] if isinstance(v, list) else v
        else:
            out[k] = v
    return out


def _extra_finding(tool: str, args: dict, body: dict) -> F.Finding:
    """Evidence for an LLM-requested query: template summary + record refs."""
    key = f"extra:{tool}:{json.dumps(args, sort_keys=True)}"
    refs: list[str] = []
    rows: list[dict] = []
    if tool == "get_eol_summary":
        t = body["totals"]
        summ = (f"EOL summary {args.get('start')}–{args.get('end')} (tester={args.get('tester_id') or 'all'}, "
                f"model={args.get('model_id') or 'all'}): FAIL_Rate {F.pct(t['fail_rate'])} "
                f"({t['fail_count']}/{t['test_count']}).")
        for i in body["failed_sn_sample"]["items"][:20]:
            refs.append(f"eol_tests:{i['test_id']}")
            rows.append({"ref": refs[-1], "sn": i["sn"], "tester_id": i["tester_id"], "ts": i["ts"],
                         "result": "FAIL", "is_retest": False, "model_id": i["model_id"]})
    elif tool == "get_product_traces":
        tr = body["traces"]
        summ = f"Product traces of {len(tr)} serial numbers: " + "; ".join(
            f"{t['sn']} {t['model_id']} lot {t['material_lot']} tests "
            + ",".join(f"{x['tester_id']}:{x['result']}" for x in t["eol_tests"]) for t in tr[:10])
        refs = [f"products:{t['sn']}" for t in tr]
    elif tool == "get_reference_sample_checks":
        summ = (f"{body['count']} reference sample checks on {body['tester_id']} in "
                f"{args.get('start')}–{args.get('end')}" + (": " + ", ".join(
                    f"{c['ts']} {c['deviation']:+.4f} V {c['result']}" for c in body["checks"][:8]) if body["checks"]
                    else "."))
        refs = [f"reference_sample_checks:{c['check_id']}" for c in body["checks"]]
    elif tool == "get_process_changes":
        summ = f"{body['count']} process changes in {args.get('start')}–{args.get('end')}" + (": " + "; ".join(
            f"{c['ts']} {c['equipment_id']} {c['old_value']}→{c['new_value']}" for c in body["changes"])
            if body["changes"] else ".")
        refs = [f"process_changes:{c['change_id']}" for c in body["changes"]]
    elif tool == "get_equipment_events":
        evs = [e for e in body["events"] if e["event_type"] != "state"]
        summ = f"{body['equipment_id']}: {len(body['events'])} events ({len(evs)} non-state)" + (": " + "; ".join(
            f"{e['ts']} {e['event_type']} {e['details_json']}" for e in evs[:5]) if evs else ".")
        refs = [f"equipment_events:{e['event_id']}" for e in body["events"][:20]]
    else:
        summ = f"Factory context: {len(body.get('equipment', []))} equipment units."
    return F.Finding(key, "record", "ANALYTICS", f"Additional query: {tool}", summ, {"tool": tool, "args": args},
                     refs[:50], rows, [body.get("call_id", "")], None,
                     [x for x in (args.get("tester_id"), args.get("equipment_id")) if x])


_ = SUPPORT_RANK
