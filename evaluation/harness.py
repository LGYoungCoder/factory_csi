"""Evaluation harness: N real-LLM investigations per scenario, scored against the hidden ground truth.

Runs in-process through the same FastAPI app (TestClient) in an isolated working dir var/eval/,
auto-approving the rank-1 proposal. This package may read ground truth; product code may not import it.
"""

from __future__ import annotations

import json
import re
import shutil
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from backend.agent.report import SECTIONS
from backend.api.app import create_app
from backend.evidence.models import overclaims
from backend.settings import Settings
from simulator.config import DEFAULT_CONFIG
from simulator.generator import generate
from simulator.ground_truth import GroundTruth, load_ground_truth
from simulator.registry import get_entry
from simulator.scenarios import scenario_for_key
from simulator.writer import write_dataset

EV = re.compile(r"\bEV-\d{3,}\b")
LIMITATION = ("3 synthetic scenarios, {n} runs each; not evidence of production-grade root-cause accuracy. "
              "All data is simulated by the project's own generator.")


def _run_case(c: TestClient, ds: str, timeout: float) -> tuple[dict, float]:
    t0 = time.time()
    r = c.post("/api/cases", json={"dataset_id": ds})
    if r.status_code != 201:
        raise RuntimeError(f"case creation failed: {r.status_code} {r.text}")
    cid = r.json()["case_id"]
    while time.time() - t0 < timeout:
        d = c.get(f"/api/cases/{cid}").json()
        if d["status"] == "AWAITING_APPROVAL" and d["pending"]:
            props = d["pending"]["proposals"]
            body = {"action": "approve", "proposal_id": props[0]["proposal_id"]} if props else {"action": "conclude"}
            c.post(f"/api/cases/{cid}/decision", json=body)
        elif d["status"] in ("COMPLETED", "FAILED", "FAILED_LLM"):
            return d, time.time() - t0
        time.sleep(1.0)
    return c.get(f"/api/cases/{cid}").json() | {"status": "TIMEOUT"}, time.time() - t0


def _events(c: TestClient, cid: str) -> list[dict]:
    text = c.get(f"/api/cases/{cid}/events").text
    out = []
    for block in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in lines:
            out.append({"type": lines["event"], "payload": json.loads(lines["data"])})
    return out


def _verification_match(v: dict, ev: dict, gt: GroundTruth) -> bool | None:
    exp = gt.expected_verification_outcomes
    outs = [o["outcome"] for o in ev["data"].get("outcomes", [])]
    if not outs:
        return None
    t, p = v["type"], v["params"]
    if t == "cross_retest":
        if p.get("target_tester_id") != exp.cross_retest_target_tester:
            return None
        return Counter(outs).most_common(1)[0][0] == exp.cross_retest.value
    if t == "reference_sample_check":
        return outs[0] == exp.reference_sample_check.value if p.get("tester_id") == exp.reference_check_tester else None
    if t == "process_config_check":
        return outs[0] == exp.config_check.value if p.get("equipment_id") == exp.config_check_equipment else None
    return None


def score(d: dict, events: list[dict], md: str, gt: GroundTruth, duration: float) -> dict:
    ev_by_id = {e["id"]: e for e in d["evidence"]}
    flagged = sorted(a["equipment_id"] for a in (d.get("anomaly") or {}).get("anomalies", []))
    concl = d.get("conclusion") or {}
    cited = [x for h in d["hypotheses"] for x in h["supporting_evidence"] + h["contradicting_evidence"]]
    cited += EV.findall(md)
    dropped = sum(len(e["payload"].get("invalid_ids", [])) for e in events if e["type"] == "citation_dropped")
    accepted = sum(len(e["payload"].get("proposals", [])) for e in events if e["type"] == "awaiting_approval")
    rejected = sum(1 for e in events if e["type"] == "proposal_rejected_by_validator")
    matches, updated, incorporated = [], [], []
    cited_final = {x for h in d["hypotheses"] for x in h["supporting_evidence"] + h["contradicting_evidence"]}
    for v in d["verifications"]:
        ev = ev_by_id.get(v["evidence_id"])
        if ev:
            matches.append(_verification_match(v, ev, gt))
        updated.append(any(v["evidence_id"] in j["because"] for j in d["judgment_changes"]))
        incorporated.append(v["evidence_id"] in cited_final)
    m = [x for x in matches if x is not None]
    sections_ok = all(f"## {i}. {s}" in md for i, s in enumerate(SECTIONS, 1))
    return {
        "status": d["status"],
        "anomaly_detection_correct": flagged == sorted(gt.expected_flagged_testers),
        "flagged": flagged,
        "conclusion": {"category": concl.get("category"), "support": concl.get("support")},
        "conclusion_acceptable": bool(concl) and gt.is_acceptable(concl["category"], concl["support"]),
        "citation_validity": round(sum(1 for x in cited if x in ev_by_id) / len(cited), 4) if cited else None,
        "dropped_citations": dropped,
        "proposal_legality": round(accepted / (accepted + rejected), 4) if accepted + rejected else None,
        "verifications": len(d["verifications"]),
        "verification_types": [v["type"] for v in d["verifications"]],
        "verification_outcome_match": round(sum(m) / len(m), 4) if m else None,
        "state_updated_rate": round(sum(updated) / len(updated), 4) if updated else None,
        "verification_incorporated_rate": round(sum(incorporated) / len(incorporated), 4) if incorporated else None,
        "report_complete": sections_ok and set(EV.findall(md)) <= set(ev_by_id) and not overclaims(md),
        "duration_s": round(duration, 1),
        "llm_calls": d["budgets"]["llm_calls"]["used"],
        "mcp_calls": d["budgets"]["mcp_calls"]["used"],
        "tokens_in": d["llm_usage"]["tokens_in"],
        "tokens_out": d["llm_usage"]["tokens_out"],
        "cost_usd": round(d["llm_usage"]["cost_usd"] or 0.0, 5),
    }


def run(datasets: list[str], runs: int, workdir: Path, timeout: float = 900, log=print) -> dict:  # noqa: ANN001
    if workdir.exists():
        shutil.rmtree(workdir)
    data = workdir / "data"
    for ds in datasets:
        e = get_entry(ds)
        write_dataset(data, generate(scenario_for_key(e.scenario_key), e.default_seed, DEFAULT_CONFIG))
    s = Settings(data_dir=data, app_db_path=workdir / "app.db", checkpoint_db_path=workdir / "cp.db",
                 log_dir=workdir / "logs")
    results: dict[str, list[dict]] = {ds: [] for ds in datasets}
    with TestClient(create_app(s)) as c:
        st = c.post("/api/llm/status/refresh").json()
        if st["status"] != "OK":
            raise SystemExit(f"LLM status is {st['status']} ({st.get('reason')}); evaluation needs a working LLM")
        model = st["model"]
        for ds in datasets:
            gt = load_ground_truth(data / ds / "ground_truth.json")
            for i in range(runs):
                c.post(f"/api/datasets/{ds}/reset")
                d, dur = _run_case(c, ds, timeout)
                md = c.get(f"/api/cases/{d['case_id']}/report.md").text if d["status"] == "COMPLETED" else ""
                r = score(d, _events(c, d["case_id"]), md, gt, dur) | {"case_id": d["case_id"], "run": i + 1}
                results[ds].append(r)
                log(f"{ds} run {i + 1}: {r['status']} conclusion={r['conclusion']} acceptable={r['conclusion_acceptable']}"
                    f" {r['duration_s']}s ${r['cost_usd']}")
    return {"generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": model, "runs": runs,
            "datasets": datasets, "results": results}


def summarize(res: dict) -> dict:
    out = {}
    for ds, rows in res["results"].items():
        def rate(key: str, rows: list = rows) -> str:
            vals = [r[key] for r in rows if r[key] is not None]
            return f"{sum(1 for v in vals if v is True)}/{len(vals)}" if vals and isinstance(vals[0], bool) else "n/a"

        def mean(key: str, rows: list = rows) -> float | None:
            vals = [r[key] for r in rows if r[key] is not None]
            return round(statistics.mean(vals), 3) if vals else None
        out[ds] = {
            "completed": f"{sum(r['status'] == 'COMPLETED' for r in rows)}/{len(rows)}",
            "anomaly_detection_correct": rate("anomaly_detection_correct"),
            "conclusion_acceptable": rate("conclusion_acceptable"),
            "report_complete": rate("report_complete"),
            "citation_validity_mean": mean("citation_validity"),
            "dropped_citations_total": sum(r["dropped_citations"] for r in rows),
            "proposal_legality_mean": mean("proposal_legality"),
            "verification_outcome_match_mean": mean("verification_outcome_match"),
            "state_updated_rate_mean": mean("state_updated_rate"),
            "verification_incorporated_mean": mean("verification_incorporated_rate"),
            "duration_s_mean": mean("duration_s"),
            "duration_s_median": round(statistics.median([r["duration_s"] for r in rows]), 1),
            "llm_calls_mean": mean("llm_calls"),
            "mcp_calls_mean": mean("mcp_calls"),
            "cost_usd_mean": mean("cost_usd"),
            "conclusions": dict(Counter(f"{r['conclusion']['category']}/{r['conclusion']['support']}" for r in rows)),
        }
    return out


def markdown(res: dict, summary: dict) -> str:
    labels = {"ds-01": "Scenario A – EOL Tester Drift", "ds-02": "Scenario B – Manufacturing Process Defect",
              "ds-03": "Scenario C – Insufficient Evidence"}
    lines = ["# Evaluation", "", f"Generated {res['generated_at']} with `{res['model']}` by `make eval` "
             f"(auto-approve the rank-1 proposal, max 3 verification rounds).", "",
             f"> Limitations: {LIMITATION.format(n=res['runs'])}", "",
             "| Metric | " + " | ".join(labels.get(d, d) for d in summary) + " |",
             "|---|" + "---|" * len(summary)]
    rows = [("Completed runs", "completed"), ("Anomaly detection correct", "anomaly_detection_correct"),
            ("Conclusion acceptable (category and support ≤ allowed)", "conclusion_acceptable"),
            ("Report complete (10 sections, valid EV ids, no banned wording)", "report_complete"),
            ("Citation validity (mean)", "citation_validity_mean"), ("Dropped citations (total)", "dropped_citations_total"),
            ("Proposal legality (mean)", "proposal_legality_mean"),
            ("Verification outcome = ground truth (mean, comparable checks)", "verification_outcome_match_mean"),
            ("Verification evidence cited by the final hypotheses (mean)", "verification_incorporated_mean"),
            ("Verification that changed a support level, citing it (mean)", "state_updated_rate_mean"),
            ("Duration s (mean / median)", None), ("LLM calls (mean)", "llm_calls_mean"),
            ("MCP calls (mean)", "mcp_calls_mean"), ("Cost USD (mean, LiteLLM estimate)", "cost_usd_mean")]
    for name, key in rows:
        if key is None:
            vals = [f"{s['duration_s_mean']} / {s['duration_s_median']}" for s in summary.values()]
        else:
            vals = [str(s[key]) for s in summary.values()]
        lines.append(f"| {name} | " + " | ".join(vals) + " |")
    lines += ["", "## Final conclusions per scenario", ""]
    for ds, s in summary.items():
        lines.append(f"- **{labels.get(ds, ds)}**: " + ", ".join(f"`{k}` ×{v}" for k, v in s["conclusions"].items()))
    lines += ["", "## Per run", "", "| Dataset | Run | Status | Conclusion | Acceptable | Verifications | s | $ |",
              "|---|---|---|---|---|---|---|---|"]
    for ds, rs in res["results"].items():
        for r in rs:
            lines.append(f"| {ds} | {r['run']} | {r['status']} | {r['conclusion']['category']}/{r['conclusion']['support']} "
                         f"| {r['conclusion_acceptable']} | {', '.join(r['verification_types'])} | {r['duration_s']} | "
                         f"{r['cost_usd']} |")
    lines += ["", "A verification outcome is compared with the ground truth only when it targets the scenario's reference "
              "check (e.g. the cross retest on EOL-A or the reference check on the scenario's tester); other checks are "
              "counted as not comparable.", ""]
    return "\n".join(lines)
