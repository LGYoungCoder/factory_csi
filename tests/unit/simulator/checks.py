"""Statistical acceptance checks of the simulator spec, evaluated on observable rows.

Each ``check_*`` returns a list of failure messages (empty = all criteria hold).
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

import numpy as np
from scipy import stats

from factory_data.schema import TABLE_ORDER
from factory_data.timeutil import parse_ts

SHIFT_START = parse_ts("2026-11-02T06:00:00Z")
SHIFT_END = parse_ts("2026-11-02T14:00:00Z")


def h(hours: float):  # noqa: ANN201
    return SHIFT_START + timedelta(hours=hours)


def load_rows(db_path: Path) -> dict[str, list[dict]]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return {t.name: [dict(r) for r in conn.execute(f'SELECT * FROM "{t.name}"')] for t in TABLE_ORDER}
    finally:
        conn.close()


def first_tests(rows, tester=None, model=None, start=None, end=None) -> list[dict]:
    out = []
    for t in rows["eol_tests"]:
        if t["is_retest"] or t["origin"] != "historical":
            continue
        if tester and t["tester_id"] != tester:
            continue
        if model and t["model_id"] != model:
            continue
        ts = parse_ts(t["ts"])
        if start and ts < start:
            continue
        if end and ts >= end:
            continue
        out.append(t)
    return out


def rate(tests) -> tuple[float, int, int]:
    n = len(tests)
    f = sum(1 for t in tests if t["result"] == "FAIL")
    return (f / n if n else 0.0), f, n


def fisher(a: list[dict], b: list[dict]) -> float:
    _, fa, na = rate(a)
    _, fb, nb = rate(b)
    return float(stats.fisher_exact([[fa, na - fa], [fb, nb - fb]]).pvalue)


def flagged(rows, tester) -> bool:
    """Downstream detector rule: last 3 h vs first 2 h, Fisher p<0.01 and rate ≥ 2×max(base, 0.5%)."""
    base = first_tests(rows, tester, start=h(0), end=h(2))
    win = first_tests(rows, tester, start=h(5), end=SHIFT_END + timedelta(seconds=1))
    rb, rw = rate(base)[0], rate(win)[0]
    return fisher(base, win) < 0.01 and rw >= 2 * max(rb, 0.005)


def _in(lo, x, hi, msg, out) -> None:  # noqa: ANN001
    if not (lo <= x <= hi):
        out.append(f"{msg}: {x:.4f} not in [{lo}, {hi}]")


def check_common(rows) -> list[str]:
    out: list[str] = []
    n = len(rows["products"])
    share_a = sum(1 for p in rows["products"] if p["model_id"] == "MODEL-A") / n
    _in(0.65, share_a, 0.75, "Model A share", out)
    return out


def check_baseline(rows) -> list[str]:
    out = check_common(rows)
    for t in ("EOL-A", "EOL-B"):
        _in(0.005, rate(first_tests(rows, t))[0], 0.04, f"{t} FAIL_Rate", out)
        if flagged(rows, t):
            out.append(f"{t} flagged by detector in baseline")
    for m in ("MODEL-A", "MODEL-B"):
        share = len(first_tests(rows, "EOL-A", m)) / len(first_tests(rows, model=m))
        _in(0.40, share, 0.60, f"{m} share on EOL-A", out)
    if any(r["result"] != "PASS" for r in rows["reference_sample_checks"]):
        out.append("baseline reference check out of tolerance")
    return out


def check_a(rows) -> list[str]:
    out = check_common(rows)
    end = SHIFT_END + timedelta(seconds=1)
    _in(0.005, rate(first_tests(rows, "EOL-B", start=h(0), end=h(3)))[0], 0.04, "EOL-B first 3h", out)
    _in(0.12, rate(first_tests(rows, "EOL-B", start=h(6), end=end))[0], 0.25, "EOL-B last 2h", out)
    _in(0.005, rate(first_tests(rows, "EOL-A"))[0], 0.04, "EOL-A full shift", out)
    refs_b = sorted((r for r in rows["reference_sample_checks"] if r["tester_id"] == "EOL-B"), key=lambda r: r["ts"])
    x = [(parse_ts(r["ts"]) - SHIFT_START).total_seconds() / 3600 for r in refs_b]
    y = [r["deviation"] for r in refs_b]
    reg = stats.linregress(x, y)
    if len(refs_b) != 8 or not (reg.slope > 0 and reg.pvalue < 0.01):
        out.append(f"EOL-B reference trend slope={reg.slope:.4f} p={reg.pvalue:.4g} n={len(refs_b)}")
    if any(r["result"] != "PASS" for r in refs_b if parse_ts(r["ts"]) < h(3)):
        out.append("EOL-B pre-onset reference out of tolerance")
    if refs_b[-1]["result"] != "FAIL":
        out.append("final EOL-B reference check not out of tolerance")
    if any(r["result"] != "PASS" for r in rows["reference_sample_checks"] if r["tester_id"] == "EOL-A"):
        out.append("EOL-A reference out of tolerance")
    tests = {t["test_id"]: t for t in rows["eol_tests"]}
    retests = [t for t in rows["eol_tests"] if t["is_retest"]]
    if not 2 <= len(retests) <= 10:
        out.append(f"retest count {len(retests)}")
    for r in retests:
        o = tests[r["retest_of"]]
        if not (r["tester_id"] == "EOL-A" and r["result"] == "PASS" and o["tester_id"] == "EOL-B"
                and o["result"] == "FAIL"):
            out.append(f"retest {r['test_id']} pattern wrong")
    base_b = first_tests(rows, "EOL-B", start=h(0), end=h(2))
    win_b = first_tests(rows, "EOL-B", start=h(5), end=end)
    if not (rate(win_b)[0] >= 3 * rate(base_b)[0] and fisher(base_b, win_b) < 0.01):
        out.append("EOL-B final 3h not >=3x first 2h with p<0.01")
    if flagged(rows, "EOL-A"):
        out.append("EOL-A flagged")
    if rows["process_changes"]:
        out.append("process changes present")
    return out


def check_b(rows) -> list[str]:
    out = check_common(rows)
    end = SHIFT_END + timedelta(seconds=1)
    old = [m["value"] for m in rows["process_measurements"] if m["parameter"] == "angle" and m["program_version"] == "P-2.3"]
    new = [m["value"] for m in rows["process_measurements"] if m["parameter"] == "angle" and m["program_version"] == "P-2.4"]
    if not new or stats.ks_2samp(old, new).pvalue >= 0.01:
        out.append("angle KS not significant")
    prog = {m["sn"]: m["program_version"] for m in rows["process_measurements"]}
    for t in ("EOL-A", "EOL-B"):
        new_t = [x for x in first_tests(rows, t) if prog[x["sn"]] == "P-2.4"]
        old_t = [x for x in first_tests(rows, t) if prog[x["sn"]] == "P-2.3"]
        if len(new_t) < 100:
            out.append(f"{t} P-2.4 tests {len(new_t)} < 100")
        if rate(new_t)[0] < 0.12:
            out.append(f"{t} P-2.4 FAIL_Rate {rate(new_t)[0]:.3f} < 12%")
        _in(0.005, rate(old_t)[0], 0.04, f"{t} P-2.3 FAIL_Rate", out)
        base = first_tests(rows, t, start=h(0), end=h(2))
        win = first_tests(rows, t, start=h(5), end=end)
        if not (rate(win)[0] >= 2.5 * rate(base)[0] and fisher(base, win) < 0.01):
            out.append(f"{t} final 3h not >=2.5x first 2h with p<0.01")
        if not flagged(rows, t):
            out.append(f"{t} not flagged")
    if len(rows["process_changes"]) != 1:
        out.append("expected exactly one process change")
    return out


def check_c(rows) -> list[str]:
    out = check_common(rows)
    end = SHIFT_END + timedelta(seconds=1)
    win_start = h(3)
    share_a = sum(1 for p in rows["products"] if p["model_id"] == "MODEL-A") / len(rows["products"])
    _in(0.66, share_a, 0.70, "Model A full-shift share (default)", out)
    before = first_tests(rows, end=win_start)
    within = first_tests(rows, start=win_start, end=end)
    _in(0.05, sum(t["model_id"] == "MODEL-B" for t in before) / len(before), 0.15, "Model B share before", out)
    _in(0.40, sum(t["model_id"] == "MODEL-B" for t in within) / len(within), 0.50, "Model B share within", out)
    for m, lo, hi in (("MODEL-B", 0.80, 0.90), ("MODEL-A", 0.25, 0.45)):
        w = [t for t in within if t["model_id"] == m]
        _in(lo, sum(t["tester_id"] == "EOL-B" for t in w) / len(w), hi, f"{m} routed to EOL-B within", out)
        b = [t for t in before if t["model_id"] == m]
        _in(0.40, sum(t["tester_id"] == "EOL-B" for t in b) / len(b), 0.60, f"{m} routed to EOL-B before", out)
    base_b = first_tests(rows, "EOL-B", start=h(0), end=h(2))
    for label, ws in (("window", win_start), ("final 3h", h(5))):
        wb = first_tests(rows, "EOL-B", start=ws, end=end)
        wa = first_tests(rows, "EOL-A", start=ws, end=end)
        if not (rate(wb)[0] >= 2 * rate(base_b)[0] and fisher(base_b, wb) < 0.01 and rate(wb)[0] >= 1.5 * rate(wa)[0]):
            out.append(f"EOL-B {label} surface signal too weak: {rate(wb)} vs base {rate(base_b)} / A {rate(wa)}")
        for m in ("MODEL-A", "MODEL-B"):
            p = fisher(first_tests(rows, "EOL-A", m, ws, end), first_tests(rows, "EOL-B", m, ws, end))
            if p <= 0.05:
                out.append(f"{m} tester difference significant in {label}: p={p:.4f}")
    for m in ("MODEL-A", "MODEL-B"):
        p = fisher(first_tests(rows, "EOL-A", m), first_tests(rows, "EOL-B", m))
        if p <= 0.05:
            out.append(f"{m} tester difference significant over full shift: p={p:.4f}")
    if not flagged(rows, "EOL-B"):
        out.append("EOL-B not flagged")
    if any(parse_ts(r["ts"]) >= win_start for r in rows["reference_sample_checks"]):
        out.append("reference check inside window")
    if any(t["is_retest"] for t in rows["eol_tests"]):
        out.append("retest present")
    if any(parse_ts(r["ts"]) >= win_start for r in rows["equipment_events"]) or rows["process_changes"]:
        out.append("event/process change inside window")
    return out


CHECKS = {"ds-00": check_baseline, "ds-01": check_a, "ds-02": check_b, "ds-03": check_c}


def angle_summary(rows) -> str:  # debugging aid
    vals = np.array([m["value"] for m in rows["process_measurements"] if m["parameter"] == "angle"])
    return f"angle mean {vals.mean():.2f} sd {vals.std():.2f}"
