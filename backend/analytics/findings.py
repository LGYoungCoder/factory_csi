"""Analyzers: pure functions over MCP tool outputs → Findings (become Evidence items).

Order is MSA first: reference samples and retests, then tester comparison, stratification, process,
material and events. Summaries are fixed templates; the LLM never writes them.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from backend.analytics.stats import chi2_p, fisher_p, fmt_p, ks_p, mwu_p, ols, pct, rate, sig4
from factory_data.timeutil import format_ts, parse_ts

TESTERS = ("EOL-A", "EOL-B")
BASELINE_HOURS = 2
DETECTION_HOURS = 3


@dataclass
class Finding:
    key: str
    kind: str  # statistic | event | record | verification | absence
    source_system: str  # MES | PPM | EOL | ANALYTICS | VERIFICATION
    title: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    record_refs: list[str] = field(default_factory=list)
    ref_rows: list[dict] = field(default_factory=list)
    mcp_call_ids: list[str] = field(default_factory=list)
    ts: str | None = None  # timeline position
    equipment: list[str] = field(default_factory=list)
    #: hypothesis categories whose physical mechanism this finding directly shows (see guardrails)
    mechanism: list[str] = field(default_factory=list)


@dataclass
class Windows:
    data_start: str
    data_end: str  # exclusive end used in queries (max ts + 1 s)
    baseline_end: str
    detection_start: str

    @classmethod
    def from_context(cls, ctx: dict) -> Windows:
        s = parse_ts(ctx["data_time_range"]["start"])
        e = parse_ts(ctx["data_time_range"]["end"]) + timedelta(seconds=1)
        return cls(format_ts(s), format_ts(e), format_ts(s + timedelta(hours=BASELINE_HOURS)),
                   format_ts(e - timedelta(hours=DETECTION_HOURS)))

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _by_tester(summary: dict) -> dict[str, dict]:
    return {r["tester_id"]: r for r in summary["by_tester"]}


def _failed_refs(summary: dict, tester: str | None = None, limit: int = 20) -> tuple[list[str], list[dict]]:
    items = [i for i in summary["failed_sn_sample"]["items"] if tester is None or i["tester_id"] == tester][:limit]
    rows = [{"ref": f"eol_tests:{i['test_id']}", "sn": i["sn"], "tester_id": i["tester_id"], "ts": i["ts"],
             "result": "FAIL", "is_retest": False, "model_id": i["model_id"]} for i in items]
    return [r["ref"] for r in rows], rows


# --- anomaly detection --------------------------------------------------------------------
def detect_anomaly(baseline: dict, detection: dict, windows: Windows) -> dict:
    """Per tester: Fisher two-sided p < 0.01 AND detection rate ≥ 2 × max(baseline rate, 0.5 %)."""
    b, d = _by_tester(baseline), _by_tester(detection)
    out = []
    for t in TESTERS:
        nb, fb = b[t]["test_count"], b[t]["fail_count"]
        nd, fd = d[t]["test_count"], d[t]["fail_count"]
        rb, rd = rate(fb, nb) or 0.0, rate(fd, nd) or 0.0
        p = fisher_p(fb, nb, fd, nd)
        flagged = p < 0.01 and rd >= 2 * max(rb, 0.005)
        out.append({"equipment_id": t, "baseline_rate": rb, "window_rate": rd, "baseline_counts": [fb, nb],
                    "window_counts": [fd, nd], "p_value": sig4(p), "flagged": flagged})
    return {
        "status": "ANOMALY" if any(x["flagged"] for x in out) else "NO_ANOMALY",
        "anomalies": [x for x in out if x["flagged"]],
        "testers": out,
        "detected_window": {"start": windows.detection_start, "end": windows.data_end},
        "baseline_window": {"start": windows.data_start, "end": windows.baseline_end},
    }


def anomaly_findings(anomaly: dict, detection: dict, call_ids: list[str]) -> list[Finding]:
    out = []
    for t in anomaly["testers"]:
        fb, nb = t["baseline_counts"]
        fd, nd = t["window_counts"]
        refs, rows = _failed_refs(detection, t["equipment_id"])
        if t["flagged"]:
            out.append(Finding(
                f"anomaly:{t['equipment_id']}", "statistic", "EOL",
                f"{t['equipment_id']} FAIL_Rate elevated in the last {DETECTION_HOURS} h",
                f"{t['equipment_id']} FAIL_Rate rose from {pct(t['baseline_rate'])} ({fb}/{nb}) in the first "
                f"{BASELINE_HOURS} h to {pct(t['window_rate'])} ({fd}/{nd}) in the last {DETECTION_HOURS} h "
                f"(Fisher p={fmt_p(t['p_value'])}).",
                {**t}, refs, rows, call_ids, anomaly["detected_window"]["start"], [t["equipment_id"]]))
        else:
            out.append(Finding(
                f"stable:{t['equipment_id']}", "statistic", "EOL",
                f"{t['equipment_id']} FAIL_Rate without significant change",
                f"{t['equipment_id']} FAIL_Rate was {pct(t['baseline_rate'])} ({fb}/{nb}) in the first "
                f"{BASELINE_HOURS} h and {pct(t['window_rate'])} ({fd}/{nd}) in the last {DETECTION_HOURS} h "
                f"(Fisher p={fmt_p(t['p_value'])}); not flagged.",
                {**t}, refs[:5], rows[:5], call_ids, None, [t["equipment_id"]]))
    return out


def onset_findings(full: dict, anomaly: dict, call_id: str) -> list[Finding]:
    """First bucket where a flagged tester exceeds 2× the baseline rate with ≥10 tests."""
    out = []
    for a in anomaly["anomalies"]:
        thr = 2 * max(a["baseline_rate"], 0.005)
        for b in full["buckets"]:
            if b["tester_id"] == a["equipment_id"] and b["test_count"] >= 10 and (b["fail_rate"] or 0) >= thr \
                    and b["bucket_start"] >= anomaly["baseline_window"]["end"]:
                out.append(Finding(
                    f"onset:{a['equipment_id']}", "statistic", "ANALYTICS",
                    f"{a['equipment_id']} FAIL_Rate first exceeds 2× baseline",
                    f"First {a['equipment_id']} time bucket at or above {pct(thr)}: {b['bucket_start']} – "
                    f"{b['bucket_end']} with {pct(b['fail_rate'])} ({b['fail_count']}/{b['test_count']}).",
                    {"bucket": b, "threshold": thr}, [], [], [call_id], b["bucket_start"], [a["equipment_id"]]))
                break
    return out


# --- MSA: reference samples and retests -----------------------------------------------------
def reference_findings(checks_by_tester: dict[str, dict], windows: Windows, call_ids: dict[str, str]) -> list[Finding]:
    out = []
    end = parse_ts(windows.data_end)
    for t in TESTERS:
        res = checks_by_tester[t]
        checks = [c for c in res["checks"] if c["origin"] == "historical"]
        cid = [call_ids[t]]
        if not checks:
            out.append(Finding(f"ref_absent:{t}", "absence", "EOL", f"No reference sample checks on {t}",
                               f"No reference sample checks were recorded on {t} in the data range.",
                               {"tester_id": t, "count": 0}, [], [], cid, None, [t]))
            continue
        x = [(parse_ts(c["ts"]) - parse_ts(windows.data_start)).total_seconds() / 3600 for c in checks]
        y = [c["deviation"] for c in checks]
        slope, p = ols(x, y)
        fails = [c for c in checks if c["result"] == "FAIL"]
        last = checks[-1]
        refs = [f"reference_sample_checks:{c['check_id']}" for c in checks]
        rows = [{"ref": f"reference_sample_checks:{c['check_id']}", "tester_id": t, "ts": c["ts"],
                 "result": c["result"], "deviation": c["deviation"]} for c in checks]
        trend = (f"deviation trend {slope:+.4f} V/h (p={fmt_p(p)})" if slope is not None else "no trend estimate")
        out.append(Finding(
            f"ref_trend:{t}", "statistic", "EOL", f"{t} reference sample checks",
            f"{t}: {len(checks)} reference checks, {len(fails)} out of tolerance; {trend}; last check {last['ts']} "
            f"deviation {last['deviation']:+.4f} V ({last['result']}).",
            {"tester_id": t, "count": len(checks), "out_of_tolerance": len(fails), "slope_v_per_h": sig4(slope),
             "slope_p": sig4(p), "last_deviation": last["deviation"], "last_result": last["result"],
             "last_ts": last["ts"]}, refs, rows, cid, (fails[0]["ts"] if fails else None), [t],
            ["TESTER_MEASUREMENT_DRIFT"] if fails or (slope is not None and slope > 0 and (p or 1) < 0.01) else []))
        gap_h = (end - parse_ts(last["ts"])).total_seconds() / 3600
        if gap_h > 2:
            out.append(Finding(
                f"ref_gap:{t}", "absence", "EOL", f"No recent reference sample check on {t}",
                f"The last reference sample check on {t} was at {last['ts']}; no check in the final "
                f"{gap_h:.1f} h of data, so the measurement system state during that time is unverified.",
                {"tester_id": t, "last_ts": last["ts"], "gap_hours": round(gap_h, 2)},
                [refs[-1]], [rows[-1]], cid, last["ts"], [t]))
    return out


def retest_findings(full: dict, call_id: str) -> list[Finding]:
    rs = full["retest_summary"]
    if rs["test_count"] == 0:
        return [Finding("retests_absent", "absence", "EOL", "No historical retests",
                        "No historical retest records exist in the data range.", {"count": 0}, [], [], [call_id])]
    refs = [f"eol_tests:{r['test_id']}" for r in rs["retests"]]
    rows = [{"ref": f"eol_tests:{r['test_id']}", "sn": r["sn"], "tester_id": r["tester_id"], "ts": r["ts"],
             "result": r["result"], "is_retest": True} for r in rs["retests"]]
    paths = "; ".join(f"{p['path']}: {p['pass_count']} PASS / {p['fail_count']} FAIL" for p in rs["by_path"])
    return [Finding("retests", "record", "EOL", "Historical retests",
                    f"{rs['test_count']} historical retests: {paths}.", {"by_path": rs["by_path"]}, refs, rows,
                    [call_id], rs["retests"][0]["ts"] if rs["retests"] else None,
                    sorted({r["tester_id"] for r in rs["retests"]}),
                    ["TESTER_MEASUREMENT_DRIFT"] if any(p["pass_count"] > 0 for p in rs["by_path"]) else [])]


# --- tester comparison and stratification -------------------------------------------------
def comparison_findings(baseline: dict, detection: dict, call_ids: list[str]) -> list[Finding]:
    out = []
    d = _by_tester(detection)
    a, b = d["EOL-A"], d["EOL-B"]
    p = fisher_p(a["fail_count"], a["test_count"], b["fail_count"], b["test_count"])
    out.append(Finding(
        "tester_comparison", "statistic", "ANALYTICS", "EOL-A vs EOL-B in the detection window",
        f"Last {DETECTION_HOURS} h: EOL-A {pct(a['fail_rate'])} ({a['fail_count']}/{a['test_count']}) vs "
        f"EOL-B {pct(b['fail_rate'])} ({b['fail_count']}/{b['test_count']}), Fisher p={fmt_p(p)}.",
        {"EOL-A": a, "EOL-B": b, "p_value": sig4(p)}, [], [], call_ids, None, list(TESTERS)))
    # stratification by model inside the detection window
    strata = []
    for m in sorted({r["model_id"] for r in detection["by_tester_model"]}):
        ra = next(r for r in detection["by_tester_model"] if r["tester_id"] == "EOL-A" and r["model_id"] == m)
        rb = next(r for r in detection["by_tester_model"] if r["tester_id"] == "EOL-B" and r["model_id"] == m)
        pm = fisher_p(ra["fail_count"], ra["test_count"], rb["fail_count"], rb["test_count"])
        strata.append({"model_id": m, "EOL-A": ra, "EOL-B": rb, "p_value": sig4(pm)})
    parts = "; ".join(
        f"{s['model_id']}: EOL-A {pct(s['EOL-A']['fail_rate'])} ({s['EOL-A']['fail_count']}/{s['EOL-A']['test_count']})"
        f" vs EOL-B {pct(s['EOL-B']['fail_rate'])} ({s['EOL-B']['fail_count']}/{s['EOL-B']['test_count']}), "
        f"p={fmt_p(s['p_value'])}" for s in strata)
    sig_any = any((s["p_value"] or 1) < 0.05 for s in strata)
    out.append(Finding(
        "stratified_by_model", "statistic", "ANALYTICS", "Tester comparison stratified by product model",
        f"Within each model (last {DETECTION_HOURS} h): {parts}. "
        + ("A tester difference remains within at least one model." if sig_any
           else "No significant tester difference within any model."),
        {"strata": strata, "difference_within_model": sig_any}, [], [], call_ids, None, list(TESTERS),
        ["TESTER_MEASUREMENT_DRIFT"] if sig_any else ["PRODUCT_MIX_SHIFT"]))
    # model mix shift baseline vs detection, overall and per tester
    def share_b(summary: dict, tester: str | None) -> tuple[int, int]:
        rows = [r for r in summary["by_tester_model"] if tester is None or r["tester_id"] == tester]
        n = sum(r["test_count"] for r in rows)
        nb = sum(r["test_count"] for r in rows if r["model_id"] == "MODEL-B")
        return nb, n
    mix = {}
    for t in (None, *TESTERS):
        b0, n0 = share_b(baseline, t)
        b1, n1 = share_b(detection, t)
        mix[t or "ALL"] = {"baseline_share_b": rate(b0, n0), "window_share_b": rate(b1, n1),
                           "p_value": sig4(chi2_p([[b0, n0 - b0], [b1, n1 - b1]]))}
    shifted = (mix["ALL"]["p_value"] or 1) < 0.01 or any((mix[t]["p_value"] or 1) < 0.01 for t in TESTERS)
    out.append(Finding(
        "model_mix", "statistic", "MES", "Product model mix: baseline vs detection window",
        "MODEL-B share " + "; ".join(
            f"{k}: {pct(v['baseline_share_b'])} → {pct(v['window_share_b'])} (p={fmt_p(v['p_value'])})"
            for k, v in mix.items()) + (". The model mix changed significantly." if shifted
                                        else ". No significant model mix change."),
        {"mix": mix, "shifted": shifted}, [], [], call_ids, None, list(TESTERS),
        ["PRODUCT_MIX_SHIFT"] if shifted else []))
    return out


# --- process -------------------------------------------------------------------------------
def process_findings(changes: dict, st20: dict, windows: Windows, call_ids: dict[str, str],
                     before_after: dict[str, tuple[dict, dict]] | None = None) -> list[Finding]:
    out = []
    meas = st20.get("measurements") or []
    if not changes["changes"]:
        out.append(Finding("process_changes_absent", "absence", "MES", "No process changes recorded",
                           "No recipe, program or configuration changes were recorded in the data range.",
                           {"count": 0}, [], [], [call_ids["changes"]]))
        base = [m for m in meas if m["ts"] < windows.baseline_end]
        det = [m for m in meas if m["ts"] >= windows.detection_start]
        res = {}
        for param in ("angle", "torque"):
            a = [m["value"] for m in base if m["parameter"] == param]
            b = [m["value"] for m in det if m["parameter"] == param]
            res[param] = {"baseline_mean": sig4(sum(a) / len(a)) if a else None,
                          "window_mean": sig4(sum(b) / len(b)) if b else None, "ks_p": sig4(ks_p(a, b))}
        shifted = any((v["ks_p"] or 1) < 0.01 for v in res.values())
        sample = [m for m in det[:6]]
        out.append(Finding(
            "st20_parameters", "statistic", "PPM", "ST-20 tightening parameters: baseline vs detection window",
            "ST-20 " + "; ".join(f"{p} mean {v['baseline_mean']} → {v['window_mean']} (KS p={fmt_p(v['ks_p'])})"
                                 for p, v in res.items())
            + (". Distribution shift detected." if shifted else ". No significant shift."),
            {"parameters": res, "shifted": shifted}, [f"process_measurements:{m['meas_id']}" for m in sample],
            [{"ref": f"process_measurements:{m['meas_id']}", "sn": m["sn"], "equipment_id": "ST-20", "ts": m["ts"],
              "program_version": m["program_version"]} for m in sample], [call_ids["st20"]], None, ["ST-20"],
            ["PROCESS_PARAMETER_DEVIATION"] if shifted else []))
        return out
    for ch in changes["changes"]:
        ref = f"process_changes:{ch['change_id']}"
        out.append(Finding(
            f"change:{ch['change_id']}", "event", "MES", f"{ch['equipment_id']} {ch['change_type']} change",
            f"{ch['ts']}: {ch['equipment_id']} {ch['change_type']} changed from {ch['old_value']} to "
            f"{ch['new_value']} by {ch['changed_by']}.", dict(ch), [ref],
            [{"ref": ref, "equipment_id": ch["equipment_id"], "ts": ch["ts"], "program_version": ch["new_value"]}],
            [call_ids["changes"]], ch["ts"], [ch["equipment_id"]], ["PROCESS_PARAMETER_DEVIATION"]))
        if ch["equipment_id"] == "ST-20" and meas:
            res = {}
            for param in ("angle", "torque"):
                a = [m["value"] for m in meas if m["parameter"] == param and m["ts"] < ch["ts"]]
                b = [m["value"] for m in meas if m["parameter"] == param and m["ts"] >= ch["ts"]]
                res[param] = {"before_mean": sig4(sum(a) / len(a)) if a else None,
                              "after_mean": sig4(sum(b) / len(b)) if b else None, "n_before": len(a),
                              "n_after": len(b), "ks_p": sig4(ks_p(a, b)), "mwu_p": sig4(mwu_p(a, b))}
            after = [m for m in meas if m["ts"] >= ch["ts"]][:6]
            shifted = any((v["ks_p"] or 1) < 0.01 for v in res.values())
            out.append(Finding(
                f"change_effect:{ch['change_id']}", "statistic", "PPM",
                f"ST-20 parameters before vs after {ch['new_value']}",
                "ST-20 " + "; ".join(
                    f"{p} mean {v['before_mean']} → {v['after_mean']} (n={v['n_before']}/{v['n_after']}, "
                    f"KS p={fmt_p(v['ks_p'])}, Mann–Whitney p={fmt_p(v['mwu_p'])})" for p, v in res.items())
                + (". Significant distribution shift after the change." if shifted else ". No significant shift."),
                {"change_id": ch["change_id"], "parameters": res, "shifted": shifted},
                [ref] + [f"process_measurements:{m['meas_id']}" for m in after],
                [{"ref": f"process_measurements:{m['meas_id']}", "sn": m["sn"], "equipment_id": "ST-20",
                  "ts": m["ts"], "program_version": m["program_version"]} for m in after],
                [call_ids["st20"]], ch["ts"], ["ST-20"], ["PROCESS_PARAMETER_DEVIATION"] if shifted else []))
        if before_after and ch["change_id"] in before_after:
            pre, post = before_after[ch["change_id"]]
            rows = []
            for t in TESTERS:
                a, b = _by_tester(pre)[t], _by_tester(post)[t]
                rows.append({"tester_id": t, "before": a, "after": b,
                             "p_value": sig4(fisher_p(a["fail_count"], a["test_count"], b["fail_count"],
                                                      b["test_count"]))})
            refs, rrows = _failed_refs(post, None, 10)
            out.append(Finding(
                f"change_fail_rate:{ch['change_id']}", "statistic", "ANALYTICS",
                f"FAIL_Rate before vs after the {ch['equipment_id']} change",
                "EOL first-test FAIL_Rate before → after " + ch["ts"] + ": " + "; ".join(
                    f"{r['tester_id']} {pct(r['before']['fail_rate'])} → {pct(r['after']['fail_rate'])} "
                    f"(p={fmt_p(r['p_value'])})" for r in rows) + ".",
                {"change_id": ch["change_id"], "by_tester": rows}, [ref] + refs, rrows,
                [call_ids.get("before", ""), call_ids.get("after", "")], ch["ts"], list(TESTERS) + ["ST-20"],
                ["PROCESS_PARAMETER_DEVIATION"] if all((r["p_value"] or 1) < 0.01 and (r["after"]["fail_rate"] or 0) >
                                                       (r["before"]["fail_rate"] or 0) for r in rows) else []))
    return out


def material_findings(traces: dict, call_id: str) -> list[Finding]:
    tr = traces.get("traces", [])
    if not tr:
        return []
    lots = Counter(t["material_lot"] for t in tr)
    top, n = lots.most_common(1)[0]
    return [Finding("material_lots", "statistic", "MES", "Material lots of sampled failed products",
                    f"{len(tr)} sampled failed products come from {len(lots)} material lots; the most frequent lot "
                    f"{top} accounts for {n} ({pct(n / len(tr))}). Descriptive only (sample of failures).",
                    {"lots": dict(lots.most_common())}, [f"products:{t['sn']}" for t in tr[:20]],
                    [{"ref": f"products:{t['sn']}", "sn": t["sn"]} for t in tr[:20]], [call_id], None, [],
                    ["MATERIAL_LOT_ISSUE"] if n / len(tr) >= 0.5 else [])]


def event_findings(events_by_eq: dict[str, dict], call_ids: dict[str, str]) -> list[Finding]:
    out = []
    for eq, res in events_by_eq.items():
        for e in res["events"]:
            if e["event_type"] == "state":
                continue
            ref = f"equipment_events:{e['event_id']}"
            out.append(Finding(
                f"event:{e['event_id']}", "event", "PPM", f"{eq} {e['event_type']} event",
                f"{e['ts']}: {eq} {e['event_type']} ({e['severity']}): {e['details_json']}.", dict(e), [ref],
                [{"ref": ref, "equipment_id": eq, "ts": e["ts"]}], [call_ids[eq]], e["ts"], [eq]))
    return out


def timeline(evidence: list[dict]) -> list[dict]:
    rows = [{"ts": e["ts"], "source_system": e["source_system"], "description": e["title"], "evidence_id": e["id"]}
            for e in evidence if e.get("ts")]
    return sorted(rows, key=lambda r: (r["ts"], r["evidence_id"]))
