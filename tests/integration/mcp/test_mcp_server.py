from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from mcp import Client, ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from industrial_mcp.server import create
from simulator.ground_truth import load_ground_truth
from simulator.reset import reset_dataset

WINDOW = {"start": "2026-11-02T06:00:00Z", "end": "2026-11-02T14:00:01Z"}


async def call(client, name: str, args: dict) -> tuple[bool, dict]:  # noqa: ANN001
    r = await client.call_tool(name, args)
    return r.is_error, (json.loads(r.content[0].text) if r.is_error else r.structured_content)


async def test_stdio_transport_lists_tools(data_dir: Path, tmp_path: Path) -> None:
    p = StdioServerParameters(command=sys.executable, args=[
        "-m", "industrial_mcp", "--dataset", "ds-00", "--data-dir", str(data_dir), "--log-dir", str(tmp_path / "logs")])
    async with stdio_client(p) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = {t.name for t in (await s.list_tools()).tools}
        assert names == {"get_factory_context", "get_eol_summary", "get_product_traces", "get_equipment_events",
                         "get_process_changes", "get_reference_sample_checks", "get_source_records",
                         "run_simulated_verification"}
        res = await s.call_tool("get_factory_context", {})
        assert res.structured_content["record_counts"]["product_count"] == 800
    log = (tmp_path / "logs" / "mcp" / "ds-00.jsonl").read_text().splitlines()
    assert json.loads(log[-1])["tool"] == "get_factory_context"


async def test_eol_summary_matches_sql(data_dir: Path, tmp_path: Path) -> None:
    async with Client(create("ds-01", data_dir, tmp_path)) as c:
        err, body = await call(c, "get_eol_summary", WINDOW)
    assert not err and body["call_id"].startswith("MCP-")
    conn = sqlite3.connect(data_dir / "ds-01" / "factory.db")
    for row in body["by_tester"]:
        n, f = conn.execute("SELECT COUNT(*), SUM(result='FAIL') FROM eol_tests WHERE is_retest=0 AND "
                            "origin='historical' AND tester_id=?", (row["tester_id"],)).fetchone()
        assert (row["test_count"], row["fail_count"]) == (n, f)
        assert row["fail_rate"] == round(f / n, 4)
    assert body["totals"]["test_count"] == 800
    assert sum(b["test_count"] for b in body["buckets"]) == 800
    assert body["retest_summary"]["by_path"][0]["path"] == "EOL-B->EOL-A"


async def test_errors_are_structured(data_dir: Path, tmp_path: Path) -> None:
    async with Client(create("ds-00", data_dir, tmp_path)) as c:
        err, body = await call(c, "get_eol_summary", {"start": "2026-11-02T10:00:00Z", "end": "2026-11-02T09:00:00Z"})
        assert err and body["error_code"] == "INVALID_ARGUMENT"
        err, body = await call(c, "get_eol_summary", {**WINDOW, "tester_id": "EOL-Z"})
        assert err and body["error_code"] == "INVALID_ARGUMENT"
        err, body = await call(c, "get_product_traces", {"serial_numbers": [f"SN-{2600001 + i}" for i in range(21)]})
        assert err and body["error_code"] == "LIMIT_EXCEEDED"
        err, body = await call(c, "get_product_traces", {"serial_numbers": ["SN-9999999"]})
        assert err and body["error_code"] == "NOT_FOUND"
        err, body = await call(c, "get_equipment_events", {"equipment_id": "XX-99", **WINDOW})
        assert err and body["error_code"] == "NOT_FOUND"
        err, body = await call(c, "get_source_records", {"refs": ["secrets:1"]})
        assert err and body["error_code"] == "INVALID_ARGUMENT"
        err, body = await call(c, "get_reference_sample_checks", {"tester_id": "EOL-A",
                                                                   "start": "2026-11-02T15:00:00Z",
                                                                   "end": "2026-11-02T16:00:00Z"})
        assert not err and body["count"] == 0 and body["checks"] == []
    async with Client(create("ds-99", data_dir, tmp_path)) as c:
        err, body = await call(c, "get_factory_context", {})
        assert err and body["error_code"] == "UNAVAILABLE" and str(data_dir) not in body["message"]


async def test_traces_events_and_source_records(data_dir: Path, tmp_path: Path) -> None:
    async with Client(create("ds-02", data_dir, tmp_path)) as c:
        _, summary = await call(c, "get_eol_summary", WINDOW)
        sns = [x["sn"] for x in summary["failed_sn_sample"]["items"][:3]]
        _, traces = await call(c, "get_product_traces", {"serial_numbers": sns + ["SN-9999999"]})
        assert [t["sn"] for t in traces["traces"]] == sns and traces["not_found"] == ["SN-9999999"]
        assert len(traces["traces"][0]["process_steps"]) == 3
        _, ev = await call(c, "get_equipment_events", {"equipment_id": "ST-20", **WINDOW, "include_measurements": True})
        assert ev["measurement_total_count"] == 1600 and ev["measurements_truncated"] is False
        assert {s["program_version"] for s in ev["parameter_stats"]["overall"]} == {"P-2.3", "P-2.4"}
        assert ev["step_total_count"] == 800
        _, ch = await call(c, "get_process_changes", WINDOW)
        assert ch["count"] == 1 and ch["changes"][0]["new_value"] == "P-2.4"
        refs = [f"eol_tests:{traces['traces'][0]['eol_tests'][0]['test_id']}", f"products:{sns[0]}",
                f"process_changes:{ch['changes'][0]['change_id']}"]
        _, src = await call(c, "get_source_records", {"refs": refs})
        assert [r["ref"] for r in src["records"]] == refs


async def _verify(c, vtype: str, params: dict, approval: str) -> dict:  # noqa: ANN001
    err, body = await call(c, "run_simulated_verification", {"verification_type": vtype, "params": params,
                                                             "approval_id": approval, "approved_by": "test"})
    assert not err, body
    assert body["simulation"] is True
    return body


@pytest.mark.parametrize("dataset_id", ["ds-01", "ds-02", "ds-03"])
async def test_verification_outcomes_match_ground_truth(data_dir: Path, tmp_path: Path, dataset_id: str) -> None:
    gt = load_ground_truth(data_dir / dataset_id / "ground_truth.json")
    exp = gt.expected_verification_outcomes
    async with Client(create(dataset_id, data_dir, tmp_path)) as c:
        failed = {r[0] for r in sqlite3.connect(data_dir / dataset_id / "factory.db").execute(
            "SELECT sn FROM eol_tests WHERE is_retest=0 AND result='FAIL'")}
        sns = sorted(set(gt.affected_sns) & failed)[:3]
        assert len(sns) == 3
        rt = await _verify(c, "cross_retest", {"serial_numbers": sns, "target_tester_id": exp.cross_retest_target_tester},
                           "APR-1")
        outcomes = [o["outcome"] for o in rt["outcomes"]]
        assert outcomes.count(exp.cross_retest.value) >= 2, outcomes
        ref = await _verify(c, "reference_sample_check", {"tester_id": exp.reference_check_tester}, "APR-2")
        assert ref["outcomes"][0]["outcome"] == exp.reference_sample_check.value
        cfg = await _verify(c, "process_config_check", {"equipment_id": exp.config_check_equipment}, "APR-3")
        assert cfg["outcomes"][0]["outcome"] == exp.config_check.value
        _, src = await call(c, "get_source_records", {"refs": rt["created_refs"]})
        assert len(src["records"]) == len(rt["created_refs"]) and not src["not_found"]


async def test_verification_idempotent_and_reproducible_after_reset(data_dir: Path, tmp_path: Path) -> None:
    gt = load_ground_truth(data_dir / "ds-01" / "ground_truth.json")
    params = {"serial_numbers": gt.affected_sns[:2], "target_tester_id": "EOL-A"}
    async with Client(create("ds-01", data_dir, tmp_path)) as c:
        first = await _verify(c, "cross_retest", params, "APR-X")
        again = await _verify(c, "cross_retest", params, "APR-X")
        assert again["replayed"] and again["created_refs"] == first["created_refs"]
        err, body = await call(c, "run_simulated_verification", {"verification_type": "cross_retest",
                                                                 "params": {**params, "target_tester_id": "EOL-B"},
                                                                 "approval_id": "APR-X", "approved_by": "test"})
        assert err and body["error_code"] == "INVALID_ARGUMENT"
        reset_dataset("ds-01", data_dir)
        after = await _verify(c, "cross_retest", params, "APR-X")
        assert not after["replayed"]
        assert [o["measured_value"] for o in after["outcomes"]] == [o["measured_value"] for o in first["outcomes"]]
        assert after["created_refs"] == first["created_refs"]


async def test_verification_rejects_bad_params(data_dir: Path, tmp_path: Path) -> None:
    async with Client(create("ds-01", data_dir, tmp_path)) as c:
        cases = [
            ("cross_retest", {"serial_numbers": ["SN-2600001"] * 2, "target_tester_id": "EOL-A"}, "INVALID_ARGUMENT"),
            ("cross_retest", {"serial_numbers": [f"SN-{2600001 + i}" for i in range(6)], "target_tester_id": "EOL-A"},
             "LIMIT_EXCEEDED"),
            ("cross_retest", {"serial_numbers": ["SN-9999999"], "target_tester_id": "EOL-A"}, "NOT_FOUND"),
            ("reference_sample_check", {"tester_id": "ST-20"}, "INVALID_ARGUMENT"),
            ("process_config_check", {"equipment_id": "EOL-A"}, "INVALID_ARGUMENT"),
            ("calibrate_robot", {}, "INVALID_ARGUMENT"),
        ]
        for i, (vtype, params, code) in enumerate(cases):
            err, body = await call(c, "run_simulated_verification", {"verification_type": vtype, "params": params,
                                                                     "approval_id": f"APR-B{i}", "approved_by": "t"})
            assert err and body["error_code"] == code, (vtype, body)
    assert sqlite3.connect(data_dir / "ds-01" / "factory.db").execute(
        "SELECT COUNT(*) FROM eol_tests WHERE origin='verification'").fetchone()[0] == 0


def test_server_never_opens_ground_truth(data_dir: Path, tmp_path: Path) -> None:
    """Run every tool under a Python audit hook and record opened files."""
    script = f"""
import asyncio, sys, json
opened = []
sys.addaudithook(lambda ev, args: opened.append(str(args[0])) if ev == "open" and args and isinstance(args[0], str) else None)
from mcp import Client
from industrial_mcp.server import create
async def main():
    async with Client(create("ds-01", {str(data_dir)!r}, {str(tmp_path)!r})) as c:
        w = {{"start": "2026-11-02T06:00:00Z", "end": "2026-11-02T14:00:01Z"}}
        for name, args in [("get_factory_context", {{}}), ("get_eol_summary", w),
                           ("get_equipment_events", {{"equipment_id": "ST-20", **w}}),
                           ("get_process_changes", w), ("get_reference_sample_checks", {{"tester_id": "EOL-B", **w}})]:
            await c.call_tool(name, args)
        before = len([p for p in opened if p.endswith("world_state.json")])
        await c.call_tool("run_simulated_verification", {{"verification_type": "process_config_check",
            "params": {{"equipment_id": "ST-20"}}, "approval_id": "APR-A", "approved_by": "t"}})
        print(json.dumps({{"gt": [p for p in opened if p.endswith("ground_truth.json")], "ws_before": before}}))
asyncio.run(main())
"""
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out == {"gt": [], "ws_before": 0}, r.stderr


def test_source_has_no_ground_truth_reference() -> None:
    root = Path(__file__).resolve().parents[3] / "industrial_mcp"
    for f in root.rglob("*.py"):
        assert "ground_truth" not in f.read_text(), f
