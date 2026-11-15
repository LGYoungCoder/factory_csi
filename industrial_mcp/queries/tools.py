"""Read-only tool bodies. Pure SQL over factory.db; never touch world state."""

from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from factory_data.schema import TABLES, primary_key
from industrial_mcp.common import (
    ALL_EQUIPMENT,
    EOL_TESTERS,
    ServerContext,
    ToolFailure,
    bucket_edges,
    bucket_index,
    check_bucket,
    check_equipment,
    check_sn_list,
    check_tester,
    invalid,
    parse_window,
    r3,
    r4,
    rows,
)

FACTORY_NAME = "Factory Alpha"
LINE_NAME = "Line A – Automotive Component Assembly Line"
HIST_TS_SQL = """
SELECT MIN(ts) AS lo, MAX(ts) AS hi FROM (
  SELECT created_ts AS ts FROM products UNION ALL SELECT end_ts FROM process_steps
  UNION ALL SELECT start_ts FROM process_steps UNION ALL SELECT ts FROM equipment_events
  UNION ALL SELECT ts FROM process_changes
  UNION ALL SELECT ts FROM eol_tests WHERE origin='historical'
  UNION ALL SELECT ts FROM reference_sample_checks WHERE origin='historical')
"""


def _rate(fails: int, n: int) -> float | None:
    return r4(fails / n) if n else None


def _counts(tests: list[dict]) -> dict:
    n = len(tests)
    f = sum(1 for t in tests if t["result"] == "FAIL")
    return {"test_count": n, "pass_count": n - f, "fail_count": f, "fail_rate": _rate(f, n)}


def get_factory_context(ctx: ServerContext) -> dict:
    with ctx.connect() as conn:
        rng = conn.execute(HIST_TS_SQL).fetchone()
        count = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "factory": FACTORY_NAME,
            "line": LINE_NAME,
            "stations": rows(conn.execute("SELECT station_id, name, sequence FROM stations ORDER BY sequence")),
            "equipment": rows(conn.execute(
                "SELECT equipment_id, station_id, name, equipment_type FROM equipment ORDER BY equipment_id")),
            "product_models": rows(conn.execute(
                "SELECT model_id, name, ov_lower AS output_voltage_lower, ov_upper AS output_voltage_upper "
                "FROM product_models ORDER BY model_id")),
            "line_order": ["ST-10", "ST-20", "ST-30", ["EOL-A", "EOL-B"]],
            "data_time_range": {"start": rng["lo"], "end": rng["hi"]},
            "record_counts": {
                "product_count": count("SELECT COUNT(*) FROM products"),
                "first_historical_test_count": count(
                    "SELECT COUNT(*) FROM eol_tests WHERE is_retest=0 AND origin='historical'"),
                "retest_count": count("SELECT COUNT(*) FROM eol_tests WHERE is_retest=1 AND origin='historical'"),
                "verification_eol_test_count": count("SELECT COUNT(*) FROM eol_tests WHERE origin='verification'"),
                "verification_reference_check_count": count(
                    "SELECT COUNT(*) FROM reference_sample_checks WHERE origin='verification'"),
            },
            "notes": "Simulated factory data. Time windows are half-open [start, end), UTC.",
        }


def get_eol_summary(ctx: ServerContext, start: str, end: str, tester_id: str | None = None,
                    model_id: str | None = None, bucket_minutes: int = 60) -> dict:
    parse_window(start, end)
    check_bucket(bucket_minutes, start, end)
    if tester_id is not None:
        check_tester(tester_id)
    with ctx.connect() as conn:
        models = [r[0] for r in conn.execute("SELECT model_id FROM product_models ORDER BY model_id")]
        if model_id is not None and model_id not in models:
            raise ToolFailure("NOT_FOUND", f"model {model_id!r} not found", {"field": "model_id"})
        sql = ("SELECT test_id, sn, tester_id, model_id, ts, result, failure_code, is_retest, retest_of, origin "
               "FROM eol_tests WHERE ts >= ? AND ts < ? ORDER BY ts, sn, test_id")
        all_tests = rows(conn.execute(sql, (start, end)))
        orig_tester = {r[0]: r[1] for r in conn.execute("SELECT test_id, tester_id FROM eol_tests")}
    testers = [tester_id] if tester_id else list(EOL_TESTERS)
    mods = [model_id] if model_id else models

    def keep(t: dict) -> bool:
        return t["tester_id"] in testers and t["model_id"] in mods

    first = [t for t in all_tests if not t["is_retest"] and t["origin"] == "historical" and keep(t)]
    retests = [t for t in all_tests if t["is_retest"] and t["origin"] == "historical" and keep(t)]
    verif = [t for t in all_tests if t["origin"] == "verification" and keep(t)]
    edges = bucket_edges(start, end, bucket_minutes)
    per_bucket: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for t in first:
        per_bucket[(t["tester_id"], bucket_index(t["ts"], start, bucket_minutes))].append(t)
    pairs = Counter()
    pair_fail = Counter()
    for t in retests:
        key = f"{orig_tester.get(t['retest_of'], '?')}->{t['tester_id']}"
        pairs[key] += 1
        pair_fail[key] += t["result"] == "FAIL"
    fails = [t for t in first if t["result"] == "FAIL"]
    codes = Counter(t["failure_code"] for t in fails if t["failure_code"])
    return {
        "window": {"start": start, "end": end},
        "filters": {"tester_id": tester_id, "model_id": model_id},
        "population": "first historical EOL tests (is_retest=false, origin=historical)",
        "totals": _counts(first),
        "by_tester": [{"tester_id": te, **_counts([t for t in first if t["tester_id"] == te])} for te in testers],
        "by_model": [{"model_id": m, **_counts([t for t in first if t["model_id"] == m])} for m in mods],
        "by_tester_model": [
            {"tester_id": te, "model_id": m,
             **_counts([t for t in first if t["tester_id"] == te and t["model_id"] == m])}
            for te in testers for m in mods
        ],
        "buckets": [
            {"tester_id": te, "bucket_start": s, "bucket_end": e, **_counts(per_bucket[(te, i)])}
            for te in testers for i, (s, e) in enumerate(edges)
        ],
        "top_failure_codes": [{"failure_code": c, "count": n} for c, n in codes.most_common(10)],
        "retest_summary": {
            **_counts(retests),
            "by_path": [{"path": k, "count": pairs[k], "fail_count": pair_fail[k],
                         "pass_count": pairs[k] - pair_fail[k]} for k in sorted(pairs)],
            "retests": [{k: t[k] for k in ("test_id", "sn", "tester_id", "ts", "result", "retest_of")}
                        for t in retests[:50]],
        },
        "verification_tests": {
            **_counts(verif),
            "tests": [{k: t[k] for k in ("test_id", "sn", "tester_id", "ts", "result", "retest_of")}
                      for t in verif[:50]],
        },
        "failed_sn_sample": {
            "total_count": len(fails),
            "truncated": len(fails) > 50,
            "items": [{k: t[k] for k in ("sn", "test_id", "tester_id", "model_id", "ts")} for t in fails[:50]],
        },
    }


def get_product_traces(ctx: ServerContext, serial_numbers: list[str]) -> dict:
    sns = check_sn_list(serial_numbers, 20)
    traces, not_found = [], []
    with ctx.connect() as conn:
        for sn in sns:
            p = conn.execute(
                "SELECT p.sn, p.order_id, p.model_id, p.material_lot, p.created_ts FROM products p WHERE p.sn=?",
                (sn,)).fetchone()
            if p is None:
                not_found.append(sn)
                continue
            steps = rows(conn.execute(
                "SELECT step_id, station_id, equipment_id, start_ts, end_ts, recipe_version, result "
                "FROM process_steps WHERE sn=? ORDER BY start_ts", (sn,)))
            meas = rows(conn.execute(
                "SELECT meas_id, step_id, equipment_id, ts, parameter, value, unit, program_version "
                "FROM process_measurements WHERE sn=? ORDER BY ts, parameter", (sn,)))
            tests = rows(conn.execute(
                "SELECT test_id, tester_id, ts, result, failure_code, is_retest, retest_of, origin "
                "FROM eol_tests WHERE sn=? ORDER BY ts, test_id", (sn,)))
            for t in tests:
                t["is_retest"] = bool(t["is_retest"])
                t["measurements"] = rows(conn.execute(
                    "SELECT meas_id, test_item, value, lower_limit, upper_limit, result FROM eol_measurements "
                    "WHERE test_id=? ORDER BY meas_id", (t["test_id"],)))
            traces.append({**dict(p), "process_steps": steps, "process_measurements": meas, "eol_tests": tests})
    if not traces:
        raise ToolFailure("NOT_FOUND", "none of the serial numbers exist", {"not_found": not_found})
    return {"traces": traces, "not_found": not_found}


def _stats(values: list[float]) -> dict:
    a = np.array(values, dtype=float)
    if a.size == 0:
        return {"count": 0, "mean": None, "std": None, "min": None, "p5": None, "median": None, "p95": None,
                "max": None}
    return {"count": int(a.size), "mean": r3(a.mean()), "std": r3(a.std(ddof=1)) if a.size > 1 else 0.0,
            "min": r3(a.min()), "p5": r3(np.percentile(a, 5)), "median": r3(np.median(a)),
            "p95": r3(np.percentile(a, 95)), "max": r3(a.max())}


EVENT_TYPES = ("state", "alarm", "maintenance", "calibration")


def get_equipment_events(ctx: ServerContext, equipment_id: str, start: str, end: str,
                         event_types: list[str] | None = None, bucket_minutes: int = 60,
                         include_measurements: bool = False) -> dict:
    parse_window(start, end)
    check_bucket(bucket_minutes, start, end)
    if event_types is not None:
        if not event_types or any(e not in EVENT_TYPES for e in event_types):
            raise invalid("event_types", f"entries must be in {list(EVENT_TYPES)}")
    types = list(dict.fromkeys(event_types or EVENT_TYPES))
    with ctx.connect() as conn:
        check_equipment(conn, equipment_id)
        events = rows(conn.execute(
            f"SELECT event_id, equipment_id, ts, event_type, severity, details_json FROM equipment_events "
            f"WHERE equipment_id=? AND ts>=? AND ts<? AND event_type IN ({','.join('?' * len(types))}) "
            f"ORDER BY ts, event_id", (equipment_id, start, end, *types)))
        edges = bucket_edges(start, end, bucket_minutes)
        out: dict = {"equipment_id": equipment_id, "window": {"start": start, "end": end},
                     "events": events[:500], "events_truncated": len(events) > 500,
                     "parameter_stats": None, "step_counts": None, "step_total_count": None,
                     "measurements": None, "measurement_total_count": None, "measurements_truncated": None}
        if equipment_id in ("ST-10", "ST-20", "ST-30"):
            steps = rows(conn.execute(
                "SELECT start_ts, result FROM process_steps WHERE equipment_id=? AND start_ts>=? AND start_ts<?",
                (equipment_id, start, end)))
            per = defaultdict(Counter)
            for s in steps:
                per[bucket_index(s["start_ts"], start, bucket_minutes)][s["result"]] += 1
            out["step_counts"] = [{"bucket_start": s, "bucket_end": e, "step_count": sum(per[i].values()),
                                   "by_result": dict(sorted(per[i].items()))} for i, (s, e) in enumerate(edges)]
            out["step_total_count"] = len(steps)
        if equipment_id == "ST-20":
            meas = rows(conn.execute(
                "SELECT meas_id, sn, ts, parameter, value, unit, program_version FROM process_measurements "
                "WHERE equipment_id=? AND ts>=? AND ts<? ORDER BY ts, meas_id", (equipment_id, start, end)))
            groups: dict[tuple[int, str, str], list[float]] = defaultdict(list)
            versions = sorted({m["program_version"] for m in meas})
            for m in meas:
                groups[(bucket_index(m["ts"], start, bucket_minutes), m["parameter"], m["program_version"])].append(
                    m["value"])
            stats = []
            for i, (s, e) in enumerate(edges):
                for param in ("angle", "torque"):
                    for v in versions:
                        vals = groups.get((i, param, v), [])
                        if vals:
                            stats.append({"bucket_start": s, "bucket_end": e, "parameter": param,
                                          "program_version": v, **_stats(vals)})
            overall = [{"parameter": p, "program_version": v,
                        **_stats([m["value"] for m in meas if m["parameter"] == p and m["program_version"] == v])}
                       for p in ("angle", "torque") for v in versions]
            out["parameter_stats"] = {"buckets": stats, "overall": overall}
            if include_measurements:
                out["measurements"] = meas[:2000]
                out["measurement_total_count"] = len(meas)
                out["measurements_truncated"] = len(meas) > 2000
    return out


def get_process_changes(ctx: ServerContext, start: str, end: str, equipment_id: str | None = None) -> dict:
    parse_window(start, end)
    with ctx.connect() as conn:
        if equipment_id is not None:
            check_equipment(conn, equipment_id)
        sql = ("SELECT change_id, equipment_id, ts, change_type, old_value, new_value, changed_by FROM process_changes "
               "WHERE ts>=? AND ts<?" + (" AND equipment_id=?" if equipment_id else "") + " ORDER BY ts, change_id")
        params = (start, end, equipment_id) if equipment_id else (start, end)
        changes = rows(conn.execute(sql, params))
    return {"window": {"start": start, "end": end}, "count": len(changes), "changes": changes}


def get_reference_sample_checks(ctx: ServerContext, tester_id: str, start: str, end: str) -> dict:
    check_tester(tester_id)
    parse_window(start, end)
    with ctx.connect() as conn:
        checks = rows(conn.execute(
            "SELECT check_id, tester_id, ts, sample_id, test_item, nominal, measured, deviation, result, origin "
            "FROM reference_sample_checks WHERE tester_id=? AND ts>=? AND ts<? ORDER BY ts, check_id",
            (tester_id, start, end)))
    note = None if checks else f"no reference sample checks recorded for {tester_id} in this window"
    return {"tester_id": tester_id, "window": {"start": start, "end": end}, "count": len(checks),
            "checks": checks, "note": note}


def get_source_records(ctx: ServerContext, refs: list[str]) -> dict:
    if not isinstance(refs, list) or not refs:
        raise invalid("refs", "at least one ref required")
    if len(refs) > 50:
        raise ToolFailure("LIMIT_EXCEEDED", f"refs has {len(refs)} entries (max 50)",
                          {"field": "refs", "received": len(refs), "maximum": 50})
    parsed = []
    for ref in dict.fromkeys(refs):
        table, _, pk = ref.partition(":") if isinstance(ref, str) else ("", "", "")
        if table not in TABLES or not pk:
            raise invalid("refs", f"{ref!r} is not '<table>:<primary key>' with a factory table")
        parsed.append((ref, table, pk))
    records, not_found = [], []
    with ctx.connect() as conn:
        for ref, table, pk in parsed:
            row = conn.execute(f'SELECT * FROM "{table}" WHERE "{primary_key(table)}"=?', (pk,)).fetchone()  # noqa: S608
            if row is None:
                not_found.append(ref)
            else:
                records.append({"ref": ref, "table": table, "record": dict(row)})
    return {"records": records, "not_found": not_found}


_ = ALL_EQUIPMENT  # re-exported for server docs
