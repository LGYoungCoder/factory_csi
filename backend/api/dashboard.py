"""Dashboard data (overview, equipment detail, trends) — always obtained through the MCP server."""

from __future__ import annotations

from datetime import timedelta

from backend.analytics.findings import TESTERS, Windows, detect_anomaly
from backend.analytics.stats import ks_p
from backend.mcp_client.manager import MCPClientManager
from factory_data.timeutil import format_ts, parse_ts

EQUIPMENT = ("ST-10", "ST-20", "ST-30", "EOL-A", "EOL-B")


async def _ctx(mcp: MCPClientManager, ds: str) -> tuple[dict, Windows]:
    ctx = await mcp.call(ds, "get_factory_context", {})
    return ctx, Windows.from_context(ctx)


async def overview(mcp: MCPClientManager, ds: str) -> dict:
    ctx, w = await _ctx(mcp, ds)
    full = {"start": w.data_start, "end": w.data_end}
    last60 = format_ts(parse_ts(w.data_end) - timedelta(minutes=60))
    base = await mcp.call(ds, "get_eol_summary", {"start": w.data_start, "end": w.baseline_end})
    det = await mcp.call(ds, "get_eol_summary", {"start": w.detection_start, "end": w.data_end})
    recent = await mcp.call(ds, "get_eol_summary", {"start": last60, "end": w.data_end})
    whole = await mcp.call(ds, "get_eol_summary", full)
    anomaly = detect_anomaly(base, det, w)
    changes = await mcp.call(ds, "get_process_changes", full)
    refs = {t: await mcp.call(ds, "get_reference_sample_checks", {"tester_id": t, **full}) for t in TESTERS}
    events = {e: await mcp.call(ds, "get_equipment_events", {"equipment_id": e, "start": last60,
                                                               "end": w.data_end, "event_types": ["alarm"]})
              for e in EQUIPMENT}
    st20_shift = None
    st20_change = next((c for c in changes["changes"] if c["equipment_id"] == "ST-20"), None)
    if st20_change:
        st20 = await mcp.call(ds, "get_equipment_events", {"equipment_id": "ST-20", **full,
                                                             "include_measurements": True})
        meas = st20.get("measurements") or []
        a = [m["value"] for m in meas if m["parameter"] == "angle" and m["program_version"] == st20_change["old_value"]]
        b = [m["value"] for m in meas if m["parameter"] == "angle" and m["program_version"] == st20_change["new_value"]]
        st20_shift = ks_p(a, b) if len(a) >= 30 and len(b) >= 30 else None

    flagged = {a["equipment_id"] for a in anomaly["anomalies"]}
    base_by = {r["tester_id"]: r for r in base["by_tester"]}
    rec_by = {r["tester_id"]: r for r in recent["by_tester"]}
    statuses = []
    for e in EQUIPMENT:
        reasons = []
        status = "GREEN"
        if events[e]["events"]:
            status = "ORANGE"
            reasons.append({"code": "ALARM_RECENT", "message": f"{len(events[e]['events'])} alarm(s) in the last 60 min"})
        if e in TESTERS:
            fails = [c for c in refs[e]["checks"] if c["result"] == "FAIL"]
            if fails:
                status = "ORANGE"
                reasons.append({"code": "REFERENCE_CHECK_FAILED",
                                "message": f"{len(fails)} reference sample check(s) out of tolerance"})
            r, b = rec_by[e], base_by[e]
            if r["test_count"] >= 20 and r["fail_count"] >= 3 and (r["fail_rate"] or 0) >= 2 * max(b["fail_rate"] or 0,
                                                                                               0.005):
                status = "ORANGE" if status != "RED" else status
                reasons.append({"code": "FAIL_RATE_RISING", "message": "last-60-min FAIL_Rate ≥ 2× baseline"})
            if e in flagged:
                status = "RED"
                reasons.insert(0, {"code": "ANOMALY_DETECTED",
                                   "message": "FAIL_Rate significantly elevated (statistical detection)"})
        if e == "ST-20" and st20_change and st20_shift is not None and st20_shift < 0.01:
            status = "RED"
            reasons.insert(0, {"code": "PARAMETER_SHIFT_AFTER_CHANGE",
                               "message": f"tightening angle distribution changed after {st20_change['new_value']}"})
        statuses.append({"equipment_id": e, "status": status, "reasons": reasons})

    return {
        "dataset_id": ds, "mode": "SIMULATION", "factory": ctx["factory"], "line": ctx["line"],
        "topology": {"stations": ctx["stations"], "equipment": ctx["equipment"], "line_order": ctx["line_order"]},
        "data_time_range": ctx["data_time_range"], "record_counts": ctx["record_counts"],
        "equipment_status": statuses,
        "fail_rates": {t: {"last_60_min": rec_by[t]["fail_rate"], "full_range": next(
            r for r in whole["by_tester"] if r["tester_id"] == t)["fail_rate"]} for t in TESTERS},
        "overall_fail_rate": whole["totals"]["fail_rate"],
        "anomaly_detection": anomaly,
    }


async def equipment_detail(mcp: MCPClientManager, ds: str, eid: str) -> dict:
    ctx, w = await _ctx(mcp, ds)
    full = {"start": w.data_start, "end": w.data_end}
    ov = await overview(mcp, ds)
    st = next(s for s in ov["equipment_status"] if s["equipment_id"] == eid)
    eq = next(e for e in ctx["equipment"] if e["equipment_id"] == eid)
    ev = await mcp.call(ds, "get_equipment_events", {"equipment_id": eid, **full, "bucket_minutes": 30})
    out = {"equipment_id": eid, "station_id": eq["station_id"], "name": eq["name"], "status": st["status"],
           "reasons": st["reasons"], "events": ev["events"]}
    if eid in TESTERS:
        s = await mcp.call(ds, "get_eol_summary", {**full, "tester_id": eid, "bucket_minutes": 30})
        refs = await mcp.call(ds, "get_reference_sample_checks", {"tester_id": eid, **full})
        fails = sorted(s["failed_sn_sample"]["items"], key=lambda x: x["ts"], reverse=True)[:20]
        out.update(fail_rate_buckets=[{k: b[k] for k in ("bucket_start", "test_count", "fail_count", "fail_rate")}
                                      for b in s["buckets"]],
                   by_model=s["by_model"], totals=s["totals"], recent_failures=fails, reference_checks=refs["checks"],
                   retest_summary=s["retest_summary"], verification_tests=s["verification_tests"])
    elif eid == "ST-20":
        changes = await mcp.call(ds, "get_process_changes", {**full, "equipment_id": eid})
        out.update(parameter_stats=ev["parameter_stats"], process_changes=changes["changes"],
                   step_counts=ev["step_counts"], step_total_count=ev["step_total_count"])
    else:
        out.update(step_counts=ev["step_counts"], step_total_count=ev["step_total_count"])
    return out


async def trends(mcp: MCPClientManager, ds: str, bucket_minutes: int) -> dict:
    _, w = await _ctx(mcp, ds)
    full = {"start": w.data_start, "end": w.data_end}
    s = await mcp.call(ds, "get_eol_summary", {**full, "bucket_minutes": bucket_minutes})
    st20 = await mcp.call(ds, "get_equipment_events", {"equipment_id": "ST-20", **full,
                                                         "bucket_minutes": bucket_minutes})
    changes = await mcp.call(ds, "get_process_changes", full)
    refs = {t: await mcp.call(ds, "get_reference_sample_checks", {"tester_id": t, **full}) for t in TESTERS}
    return {
        "bucket_minutes": bucket_minutes, "data_time_range": {"start": w.data_start, "end": w.data_end},
        "fail_rate": [{k: b[k] for k in ("tester_id", "bucket_start", "test_count", "fail_count", "fail_rate")}
                      for b in s["buckets"]],
        "st20": [{k: b[k] for k in ("bucket_start", "parameter", "program_version", "count", "mean", "p5", "p95")}
                 for b in (st20["parameter_stats"] or {}).get("buckets", [])],
        "reference_deviations": {t: [{k: c[k] for k in ("ts", "deviation", "result", "origin")}
                                     for c in refs[t]["checks"]] for t in TESTERS},
        "process_changes": changes["changes"],
    }
