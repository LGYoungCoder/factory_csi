"""Factory CSI REST + SSE API (``backend.api.app:app``)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.agent.engine import InvestigationEngine
from backend.api import dashboard
from backend.llm.client import HealthChecker, LLMClient
from backend.mcp_client.manager import MCPClientManager, MCPToolError
from backend.settings import Settings, get_settings
from backend.store.db import ACTIVE, ConflictError, Store
from simulator.registry import RegistryError, get_entry, list_entries
from simulator.reset import ResetError, reset_dataset

log = logging.getLogger("factory_csi.api")
VERSION = "0.1.0"
HTTP = {"INVALID_ARGUMENT": 400, "NOT_FOUND": 404, "CONFLICT": 409, "DATASET_CHANGED": 409,
        "PAYLOAD_TOO_LARGE": 413, "LLM_UNAVAILABLE": 503, "DATASET_UNAVAILABLE": 503, "INTERNAL": 500}
DECISION_CODES = {"INVALID_ACTION", "ACTION_NOT_OFFERED", "UNKNOWN_PROPOSAL", "UNEXPECTED_PROPOSAL_ID",
                  "NOTE_REQUIRED", "NOTE_TOO_LONG", "INVALID_ACTOR", "REJECT_LIMIT_REACHED"}


class ApiError(Exception):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details or {}

    @property
    def status(self) -> int:
        return 400 if self.code in DECISION_CODES else HTTP.get(self.code, 500)


class CreateCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str

class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str
    proposal_id: str | None = None
    note: str | None = Field(default=None, max_length=10_000)
    actor: str | None = None


class Services:
    def __init__(self, s: Settings):
        self.settings = s
        self.store = Store(s.app_db_path)
        self.mcp = MCPClientManager(s.data_dir, s.log_dir, recorder=self.store.record_mcp_call)
        self.llm = LLMClient(s)
        self.health = HealthChecker(self.llm)
        self.engine = InvestigationEngine(s, self.store, self.mcp, self.llm, self.health)
        self._health_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.engine.start()
        await self._recover()
        self._health_task = asyncio.create_task(self._health_loop())

    async def _health_loop(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                await self.health.check()
            await asyncio.sleep(60)

    async def _recover(self) -> None:
        for c in await self.store.cases_in(("CREATED", "RUNNING", "CONCLUDING")):
            has_cp = await self.engine.has_checkpoint(c["case_id"])
            status = "FAILED_LLM" if has_cp and c["status"] != "CREATED" else "FAILED"
            await self.store.update_case(c["case_id"], status=status, error="server restarted",
                                         failure_epoch=await self.store.epoch(c["dataset_id"]))
            await self.store.append_event(c["case_id"], "status_changed", {"from": c["status"], "to": status,
                                                                           "reason": "server restarted"})
            await self.store.append_event(c["case_id"], "completed", {"final_status": status})

    async def stop(self) -> None:
        if self._health_task:
            self._health_task.cancel()
        await self.engine.close()
        await self.mcp.close()


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc = Services(s)
        app.state.svc = svc
        await svc.start()
        try:
            yield
        finally:
            await svc.stop()

    app = FastAPI(title="Factory CSI API", version=VERSION, lifespan=lifespan, docs_url="/api/docs",
                  openapi_url="/api/openapi.json")
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_methods=["GET", "POST"],
                       allow_headers=["*"])

    @app.middleware("http")
    async def body_limit(request: Request, call_next):  # noqa: ANN001, ANN202
        if int(request.headers.get("content-length") or 0) > 64 * 1024:
            return _err(ApiError("PAYLOAD_TOO_LARGE", "request body exceeds 64 KB"))
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def _api_error(_r: Request, exc: ApiError) -> JSONResponse:
        return _err(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation(_r: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"loc": list(e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return _err(ApiError("INVALID_ARGUMENT", "request validation failed", {"errors": details}))

    @app.exception_handler(MCPToolError)
    async def _mcp_error(_r: Request, exc: MCPToolError) -> JSONResponse:
        code = {"NOT_FOUND": "NOT_FOUND", "INVALID_ARGUMENT": "INVALID_ARGUMENT"}.get(exc.code, "DATASET_UNAVAILABLE")
        return _err(ApiError(code, exc.message))

    def svc(request: Request) -> Services:
        return request.app.state.svc

    def dataset(request: Request, dataset_id: str) -> None:
        try:
            get_entry(dataset_id)
        except RegistryError as exc:
            raise ApiError("NOT_FOUND", str(exc)) from exc
        if not svc(request).mcp.available(dataset_id):
            raise ApiError("DATASET_UNAVAILABLE", f"dataset {dataset_id} is not generated; run `make seed`")

    # ---------------------------------------------------------------- health / llm / scenarios
    @app.get("/api/health")
    async def health(request: Request) -> dict:
        sv = svc(request)
        return {"status": "ok", "version": VERSION,
                "datasets": [{"dataset_id": e.dataset_id, "available": sv.mcp.available(e.dataset_id)}
                             for e in list_entries()], "mcp": sv.mcp.status()}

    @app.get("/api/llm/status")
    async def llm_status(request: Request) -> dict:
        return svc(request).health.result.as_dict()

    @app.post("/api/llm/status/refresh")
    async def llm_refresh(request: Request) -> dict:
        return (await svc(request).health.check()).as_dict()

    @app.get("/api/scenarios")
    async def scenarios(request: Request) -> list[dict]:
        sv = svc(request)
        return [{"dataset_id": e.dataset_id, "key": e.scenario_key, "label": e.label, "description": e.description,
                 "available": sv.mcp.available(e.dataset_id)} for e in list_entries()]

    # ---------------------------------------------------------------- datasets
    @app.post("/api/datasets/{dataset_id}/reset")
    async def reset(request: Request, dataset_id: str) -> dict:
        try:
            get_entry(dataset_id)
        except RegistryError as exc:
            raise ApiError("NOT_FOUND", str(exc)) from exc
        sv = svc(request)
        active = await sv.store.active_case(dataset_id)
        if active:
            raise ApiError("CONFLICT", f"case {active} is active on {dataset_id}; reset is not allowed")
        try:
            await asyncio.to_thread(reset_dataset, dataset_id, sv.settings.data_dir)
        except ResetError as exc:
            raise ApiError("INTERNAL", "dataset reset failed") from exc
        epoch = await sv.store.bump_epoch(dataset_id)
        ctx = await sv.mcp.call(dataset_id, "get_factory_context", {})
        return {"dataset_id": dataset_id, "epoch": epoch, "counts": {"products": ctx["record_counts"]["product_count"],
                **ctx["record_counts"]}, "data_time_range": ctx["data_time_range"]}

    @app.get("/api/datasets/{dataset_id}/overview")
    async def overview(request: Request, dataset_id: str) -> dict:
        dataset(request, dataset_id)
        return await dashboard.overview(svc(request).mcp, dataset_id)

    @app.get("/api/datasets/{dataset_id}/equipment/{equipment_id}")
    async def equipment(request: Request, dataset_id: str, equipment_id: str) -> dict:
        dataset(request, dataset_id)
        if equipment_id not in dashboard.EQUIPMENT:
            raise ApiError("NOT_FOUND", f"equipment {equipment_id!r} not found")
        return await dashboard.equipment_detail(svc(request).mcp, dataset_id, equipment_id)

    @app.get("/api/datasets/{dataset_id}/trends")
    async def trends(request: Request, dataset_id: str, bucket_minutes: int = Query(30, ge=15, le=240)) -> dict:
        dataset(request, dataset_id)
        return await dashboard.trends(svc(request).mcp, dataset_id, bucket_minutes)

    # ---------------------------------------------------------------- cases
    async def require_llm(sv: Services) -> None:
        h = await sv.health.ensure_fresh(60)
        if h.status != "OK":
            raise ApiError("LLM_UNAVAILABLE", "LLM unavailable – AI investigation is disabled",
                           {"llm_status": h.status, "reason": h.reason})

    @app.post("/api/cases", status_code=201)
    async def create_case(request: Request, body: CreateCase) -> dict:
        sv = svc(request)
        dataset(request, body.dataset_id)
        await require_llm(sv)
        try:
            case = await sv.store.create_case(body.dataset_id)
        except ConflictError as exc:
            raise ApiError("CONFLICT", str(exc)) from exc
        await sv.engine.start_case(case["case_id"], body.dataset_id)
        return await case_detail(sv, case["case_id"])

    @app.get("/api/cases")
    async def list_cases(request: Request, dataset_id: str | None = None) -> list[dict]:
        return await svc(request).store.list_cases(dataset_id)

    async def case_detail(sv: Services, case_id: str) -> dict:
        case = await sv.store.get_case(case_id)
        if case is None:
            raise ApiError("NOT_FOUND", f"case {case_id} not found")
        st = case.pop("state")
        mcp_used, llm_used = await sv.store.count_calls(case_id)
        pending = await sv.engine.pending(case_id) if case["status"] == "AWAITING_APPROVAL" else None
        s = sv.settings
        rounds = st.get("rounds", 0)
        rejects = st.get("reject_count", 0)

        def b(used: int, limit: int) -> dict:
            return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

        return {
            **case, "anomaly": st.get("anomaly"), "evidence": await sv.store.evidence(case_id),
            "timeline": st.get("timeline", []), "hypotheses": st.get("hypotheses", []),
            "hypothesis_history": st.get("history", []), "pending": pending, "decisions": st.get("decisions", []),
            "verifications": st.get("executed", []), "judgment_changes": st.get("judgment", []),
            "conclusion": st.get("conclusion"),
            "budgets": {"mcp_calls": b(mcp_used, s.case_max_mcp_calls), "llm_calls": b(llm_used, s.case_max_llm_calls),
                        "verification_rounds": b(rounds, s.max_verification_rounds),
                        "reject_all": b(rejects, s.max_reject_all)},
            "llm_usage": await sv.store.llm_usage(case_id),
            "report_available": (await sv.store.latest_report(case_id)) is not None,
        }

    @app.get("/api/cases/{case_id}")
    async def get_case(request: Request, case_id: str) -> dict:
        return await case_detail(svc(request), case_id)

    @app.get("/api/cases/{case_id}/events")
    async def events(request: Request, case_id: str, after: int = Query(0, ge=0),
                     last_event_id: str | None = Header(default=None)) -> StreamingResponse:
        sv = svc(request)
        if await sv.store.get_case(case_id) is None:
            raise ApiError("NOT_FOUND", f"case {case_id} not found")
        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after

        async def gen() -> AsyncIterator[str]:
            cursor = start
            seen_completed = False
            while True:
                batch = await sv.store.events_after(case_id, cursor)
                for e in batch:
                    cursor = e["seq"]
                    seen_completed = seen_completed or e["type"] == "completed"
                    data = json.dumps({**e["payload"], "_seq": e["seq"], "_ts": e["created_at"]})
                    yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {data}\n\n"
                if seen_completed:
                    # `completed` may be followed by trailing node events; close once the case is terminal
                    # (a completed replayed from before a retry does not close the stream)
                    case = await sv.store.get_case(case_id)
                    if case and case["status"] in ("COMPLETED", "FAILED", "FAILED_LLM"):
                        await asyncio.sleep(0.2)
                        for e in await sv.store.events_after(case_id, cursor):
                            cursor = e["seq"]
                            data = json.dumps({**e["payload"], "_seq": e["seq"], "_ts": e["created_at"]})
                            yield f"id: {e['seq']}\nevent: {e['type']}\ndata: {data}\n\n"
                        return
                    seen_completed = False
                if await request.is_disconnected():
                    return
                if not batch:
                    await sv.store.wait_for_events(case_id, 15)
                    if not await sv.store.events_after(case_id, cursor):
                        yield ": heartbeat\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/cases/{case_id}/decision", status_code=202)
    async def decision(request: Request, case_id: str, body: Decision) -> dict:
        sv = svc(request)
        case = await sv.store.get_case(case_id)
        if case is None:
            raise ApiError("NOT_FOUND", f"case {case_id} not found")
        if case["status"] != "AWAITING_APPROVAL":
            raise ApiError("CONFLICT", "case is not awaiting approval", {"status": case["status"]})
        pending = await sv.engine.pending(case_id) or {}
        d = body.model_dump()
        code = sv.engine.validate_decision(pending, case["state"].get("reject_count", 0), d)
        if code:
            raise ApiError(code, f"decision rejected: {code}")
        d["actor"] = d.get("actor") or "engineer"
        target = "CONCLUDING" if d["action"] == "conclude" else "RUNNING"
        try:
            await sv.store.transition(case_id, ("AWAITING_APPROVAL",), target)
        except ConflictError as exc:
            raise ApiError("CONFLICT", str(exc)) from exc
        await sv.store.append_event(case_id, "decision_recorded", {k: d[k] for k in ("action", "proposal_id", "note",
                                                                                       "actor")})
        await sv.store.append_event(case_id, "status_changed", {"from": "AWAITING_APPROVAL", "to": target,
                                                                "reason": f"decision {d['action']}"})
        await sv.engine.resume(case_id, d)
        return {"case_id": case_id, "status": target}

    @app.get("/api/cases/{case_id}/evidence/{evidence_id}")
    async def evidence(request: Request, case_id: str, evidence_id: str) -> dict:
        sv = svc(request)
        case = await sv.store.get_case(case_id)
        if case is None:
            raise ApiError("NOT_FOUND", f"case {case_id} not found")
        item = next((e for e in await sv.store.evidence(case_id) if e["id"] == evidence_id), None)
        if item is None:
            raise ApiError("NOT_FOUND", f"evidence {evidence_id} not found")
        out: dict[str, Any] = {"evidence": item, "source_records": [], "source_records_error": None}
        if item["record_refs"]:
            try:
                res = await sv.mcp.call(case["dataset_id"], "get_source_records", {"refs": item["record_refs"][:50]})
                out["source_records"] = res["records"]
                out["not_found"] = res["not_found"]
            except MCPToolError as exc:
                out["source_records_error"] = exc.message
        return out

    @app.get("/api/cases/{case_id}/mcp-calls")
    async def mcp_calls(request: Request, case_id: str) -> list[dict]:
        return await svc(request).store.mcp_calls_for(case_id)

    @app.get("/api/cases/{case_id}/report")
    async def report(request: Request, case_id: str) -> dict:
        r = await svc(request).store.latest_report(case_id)
        if r is None:
            raise ApiError("NOT_FOUND", "report not generated yet")
        return r

    @app.get("/api/cases/{case_id}/report.md")
    async def report_md(request: Request, case_id: str) -> PlainTextResponse:
        r = await svc(request).store.latest_report(case_id)
        if r is None:
            raise ApiError("NOT_FOUND", "report not generated yet")
        return PlainTextResponse(r["markdown"], media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="{case_id}-report.md"'})

    @app.post("/api/cases/{case_id}/retry", status_code=202)
    async def retry(request: Request, case_id: str) -> dict:
        sv = svc(request)
        case = await sv.store.get_case(case_id)
        if case is None:
            raise ApiError("NOT_FOUND", f"case {case_id} not found")
        if case["status"] != "FAILED_LLM":
            raise ApiError("CONFLICT", "only FAILED_LLM cases can be retried", {"status": case["status"]})
        if case["failure_epoch"] is not None and case["failure_epoch"] != await sv.store.epoch(case["dataset_id"]):
            raise ApiError("DATASET_CHANGED", "the dataset was reset or used by another case since the failure")
        if await sv.store.active_case(case["dataset_id"]):
            raise ApiError("CONFLICT", "another case is active on this dataset")
        await require_llm(sv)
        await sv.engine.retry(case_id)
        return {"case_id": case_id, "status": "RUNNING"}

    _ = ACTIVE
    return app


def _err(exc: ApiError) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
                        status_code=exc.status)


app = create_app()
