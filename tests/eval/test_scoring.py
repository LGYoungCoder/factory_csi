"""Deterministic test of the evaluation scoring (no LLM)."""

from __future__ import annotations

from backend.agent.report import SECTIONS
from evaluation.harness import markdown, score, summarize
from simulator.generator import generate
from simulator.ground_truth import build_ground_truth
from simulator.scenarios import scenario_for_key


def test_score_and_markdown() -> None:
    gt = build_ground_truth(generate(scenario_for_key("a"), 2))
    md = "\n".join(f"## {i}. {s}" for i, s in enumerate(SECTIONS, 1)) + "\nsee [EV-001](#ev-001)"
    d = {
        "status": "COMPLETED", "anomaly": {"anomalies": [{"equipment_id": "EOL-B"}]},
        "conclusion": {"category": "TESTER_MEASUREMENT_DRIFT", "support": "HIGH"},
        "evidence": [{"id": "EV-001", "kind": "statistic", "data": {}},
                     {"id": "EV-002", "kind": "verification", "data": {"outcomes": [{"outcome": "PASS"}] * 3}}],
        "hypotheses": [{"supporting_evidence": ["EV-001", "EV-002"], "contradicting_evidence": []}],
        "verifications": [{"type": "cross_retest", "params": {"target_tester_id": "EOL-A"}, "evidence_id": "EV-002"}],
        "judgment_changes": [{"because": ["EV-002"]}],
        "budgets": {"llm_calls": {"used": 10}, "mcp_calls": {"used": 15}},
        "llm_usage": {"tokens_in": 1, "tokens_out": 1, "cost_usd": 0.01},
    }
    events = [{"type": "awaiting_approval", "payload": {"proposals": [1, 2, 3]}},
              {"type": "proposal_rejected_by_validator", "payload": {}}]
    r = score(d, events, md, gt, 12.0)
    assert r["anomaly_detection_correct"] and r["conclusion_acceptable"] and r["report_complete"]
    assert r["citation_validity"] == 1.0 and r["proposal_legality"] == 0.75
    assert r["verification_outcome_match"] == 1.0 and r["state_updated_rate"] == 1.0
    res = {"generated_at": "2026-11-16T00:00:00Z", "model": "m", "runs": 1,
           "results": {"ds-01": [r | {"run": 1, "case_id": "CASE-0001"}]}}
    text = markdown(res, summarize(res))
    assert "not evidence of production-grade" in text and "1/1" in text
