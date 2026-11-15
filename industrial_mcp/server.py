"""Industrial MCP Server: simulated MES / PPM / EOL systems of Factory Alpha over MCP (stdio).

One process serves one dataset. Used at runtime by the backend (one session per dataset) and at
development time by Kiro's agent via .kiro/settings/mcp.json. Both paths behave identically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from industrial_mcp.common import ServerContext
from industrial_mcp.queries import tools as q
from industrial_mcp.verification.engine import run_simulated_verification as _verify

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
TS = Annotated[str, Field(description="UTC timestamp YYYY-MM-DDTHH:MM:SSZ")]


def _result(body: dict, is_error: bool) -> CallToolResult:
    text = json.dumps(body, sort_keys=True)
    if is_error:
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=True)
    return CallToolResult(content=[TextContent(type="text", text=text)], structured_content=body)


def build_server(ctx: ServerContext) -> MCPServer:
    srv = MCPServer(
        "industrial-mcp",
        instructions=(
            "Simulated industrial systems (MES, equipment monitoring/PPM, EOL test) of the fictional "
            f"Factory Alpha, Line A. Dataset {ctx.dataset_id}. All data is simulated. Time windows are "
            "half-open [start, end) in UTC. Verifications are simulated and require a human approval id."
        ),
    )

    @srv.tool(annotations=READ_ONLY)
    def get_factory_context() -> CallToolResult:
        """Factory structure: stations, equipment, product models with output_voltage limits, data time range
        and record counts."""
        return _result(*ctx.run("get_factory_context", q.get_factory_context, {}))

    @srv.tool(annotations=READ_ONLY)
    def get_eol_summary(
        start: TS, end: TS,
        tester_id: Annotated[str | None, Field(description="EOL-A or EOL-B")] = None,
        model_id: Annotated[str | None, Field(description="MODEL-A or MODEL-B")] = None,
        bucket_minutes: Annotated[int, Field(ge=15, le=240)] = 60,
    ) -> CallToolResult:
        """EOL first-test results in a window: FAIL_Rate by tester, model and tester×model, time buckets per
        tester, top failure codes, retest summary, verification tests and a failed SN sample (≤50)."""
        args = {"start": start, "end": end, "tester_id": tester_id, "model_id": model_id,
                "bucket_minutes": bucket_minutes}
        return _result(*ctx.run("get_eol_summary", q.get_eol_summary, args))

    @srv.tool(annotations=READ_ONLY)
    def get_product_traces(
        serial_numbers: Annotated[list[str], Field(min_length=1, description="1–20 serial numbers SN-1234567")],
    ) -> CallToolResult:
        """Full manufacturing history per SN: order, model, material lot, process steps with recipe versions,
        ST-20 torque/angle with program version, and all EOL tests including retests."""
        return _result(*ctx.run("get_product_traces", q.get_product_traces, {"serial_numbers": serial_numbers}))

    @srv.tool(annotations=READ_ONLY)
    def get_equipment_events(
        equipment_id: Annotated[str, Field(description="ST-10, ST-20, ST-30, EOL-A or EOL-B")],
        start: TS, end: TS,
        event_types: Annotated[list[str] | None, Field(description="state, alarm, maintenance, calibration")] = None,
        bucket_minutes: Annotated[int, Field(ge=15, le=240)] = 60,
        include_measurements: Annotated[bool, Field(description="raw ST-20 rows (≤2000)")] = False,
    ) -> CallToolResult:
        """Equipment events in a window; for stations per-bucket step counts; for ST-20 torque/angle statistics
        per bucket and program version."""
        args = {"equipment_id": equipment_id, "start": start, "end": end, "event_types": event_types,
                "bucket_minutes": bucket_minutes, "include_measurements": include_measurements}
        return _result(*ctx.run("get_equipment_events", q.get_equipment_events, args))

    @srv.tool(annotations=READ_ONLY)
    def get_process_changes(
        start: TS, end: TS, equipment_id: Annotated[str | None, Field(description="optional filter")] = None,
    ) -> CallToolResult:
        """Recipe / program / configuration changes in a window."""
        args = {"start": start, "end": end, "equipment_id": equipment_id}
        return _result(*ctx.run("get_process_changes", q.get_process_changes, args))

    @srv.tool(annotations=READ_ONLY)
    def get_reference_sample_checks(
        tester_id: Annotated[str, Field(description="EOL-A or EOL-B")], start: TS, end: TS,
    ) -> CallToolResult:
        """Reference (golden) sample checks of an EOL tester in a window; an empty list means none recorded."""
        args = {"tester_id": tester_id, "start": start, "end": end}
        return _result(*ctx.run("get_reference_sample_checks", q.get_reference_sample_checks, args))

    @srv.tool(annotations=READ_ONLY)
    def get_source_records(
        refs: Annotated[list[str], Field(min_length=1, description="1–50 refs '<table>:<primary key>'")],
    ) -> CallToolResult:
        """Raw rows for evidence traceability, e.g. 'eol_tests:T-000123'."""
        return _result(*ctx.run("get_source_records", q.get_source_records, {"refs": refs}))

    @srv.tool(annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True,
                                          openWorldHint=False))
    def run_simulated_verification(
        verification_type: Annotated[str, Field(description="cross_retest | reference_sample_check | "
                                                            "process_config_check")],
        params: Annotated[dict, Field(description="cross_retest: {serial_numbers (1–5), target_tester_id}; "
                                                  "reference_sample_check: {tester_id}; "
                                                  "process_config_check: {equipment_id}")],
        approval_id: Annotated[str, Field(description="id of the human approval decision")],
        approved_by: Annotated[str, Field(description="approving engineer")],
    ) -> CallToolResult:
        """SIMULATED verification after human approval. Appends verification-origin records. Never touches
        real equipment. Idempotent per approval_id."""
        args = {"verification_type": verification_type, "params": params, "approval_id": approval_id,
                "approved_by": approved_by}
        return _result(*ctx.run("run_simulated_verification", _verify, args))

    return srv


def create(dataset_id: str, data_dir: str | Path, log_dir: str | Path = "logs") -> MCPServer:
    return build_server(ServerContext(dataset_id, Path(data_dir).resolve(), Path(log_dir).resolve()))
