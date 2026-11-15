"""Deterministic backend logic: analytics on generated datasets, guardrails, decisions, report rendering."""

from __future__ import annotations

from pathlib import Path

import pytest
from mcp import Client

from backend.agent.engine import InvestigationEngine
from backend.agent.report import SECTIONS, build_report, render_markdown
from backend.analytics import findings as F
from backend.evidence.models import (
    HypothesisSet,
    apply_guardrails,
    assign_ids,
    decide_conclusion,
    hypothesis_errors,
    judgment_changes,
)
from backend.settings import Settings
from industrial_mcp.server import create
from simulator.config import DEFAULT_CONFIG
from simulator.generator import generate
from simulator.registry import list_entries
from simulator.scenarios import scenario_for_key
from simulator.writer import write_dataset


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("data")
    for e in list_entries():
        write_dataset(out, generate(scenario_for_key(e.scenario_key), e.default_seed, DEFAULT_CONFIG))
    return out


async def _raw(data_dir: Path, ds: str, tmp: Path) -> dict:
    async with Client(create(ds, data_dir, tmp)) as c:
        async def call(name: str, args: dict) -> dict:
            return (await c.call_tool(name, args)).structured_content
        ctx = await call("get_factory_context", {})
        w = F.Windows.from_context(ctx)
        full = {"start": w.data_start, "end": w.data_end}
        raw = {"w": w, "baseline": await call("get_eol_summary", {"start": w.data_start, "end": w.baseline_end}),
               "detection": await call("get_eol_summary", {"start": w.detection_start, "end": w.data_end}),
               "full": await call("get_eol_summary", {**full, "bucket_minutes": 30}),
               "changes": await call("get_process_changes", full),
               "refs": {t: await call("get_reference_sample_checks", {"tester_id": t, **full}) for t in F.TESTERS},
               "st20": await call("get_equipment_events", {"equipment_id": "ST-20", **full,
                                                            "include_measurements": True})}
    raw["anomaly"] = F.detect_anomaly(raw["baseline"], raw["detection"], w)
    return raw


@pytest.mark.parametrize("ds,expected", [("ds-00", set()), ("ds-01", {"EOL-B"}), ("ds-02", {"EOL-A", "EOL-B"}),
                                         ("ds-03", {"EOL-B"})])
async def test_detect_anomaly(data_dir: Path, tmp_path: Path, ds: str, expected: set) -> None:
    raw = await _raw(data_dir, ds, tmp_path)
    assert {a["equipment_id"] for a in raw["anomaly"]["anomalies"]} == expected


async def test_analyzers_find_scenario_signals(data_dir: Path, tmp_path: Path) -> None:
    a = await _raw(data_dir, "ds-01", tmp_path)
    ref = {f.key: f for f in F.reference_findings(a["refs"], a["w"], {"EOL-A": "x", "EOL-B": "y"})}
    assert ref["ref_trend:EOL-B"].data["slope_v_per_h"] > 0 and ref["ref_trend:EOL-B"].data["slope_p"] < 0.01
    assert ref["ref_trend:EOL-A"].data["out_of_tolerance"] == 0
    assert F.retest_findings(a["full"], "c")[0].kind == "record"

    b = await _raw(data_dir, "ds-02", tmp_path)
    proc = {f.key.split(":")[0]: f for f in F.process_findings(b["changes"], b["st20"], b["w"],
                                                                {"changes": "c", "st20": "s"})}
    assert proc["change_effect"].data["shifted"] is True

    c = await _raw(data_dir, "ds-03", tmp_path)
    comp = {f.key: f for f in F.comparison_findings(c["baseline"], c["detection"], ["x"])}
    assert comp["stratified_by_model"].data["difference_within_model"] is False
    assert comp["model_mix"].data["shifted"] is True
    gaps = [f for f in F.reference_findings(c["refs"], c["w"], {"EOL-A": "x", "EOL-B": "y"}) if f.kind == "absence"]
    assert {f.key for f in gaps} == {"ref_gap:EOL-A", "ref_gap:EOL-B"}


def _hs(support: str, sup: list[str], cat: str = "TESTER_MEASUREMENT_DRIFT") -> HypothesisSet:
    return HypothesisSet.model_validate({"hypotheses": [{
        "category": cat, "title": "t", "statement": "see EV-001", "supporting_evidence": sup,
        "contradicting_evidence": [], "missing_evidence": [], "support": support}]})


def test_guardrails() -> None:
    mech = {"mechanism": ["TESTER_MEASUREMENT_DRIFT"]}
    ev = {"EV-001": {"kind": "statistic", "data": mech}, "EV-002": {"kind": "verification", "data": mech},
          "EV-003": {"kind": "statistic", "data": {"mechanism": []}}}
    assert hypothesis_errors(_hs("LOW", ["EV-009"]), set(ev)) != []
    hyps, events = apply_guardrails(_hs("HIGH", ["EV-001"]), ev)
    assert hyps[0]["support"] == "MEDIUM" and events[0]["type"] == "support_downgraded"
    hyps, events = apply_guardrails(_hs("MEDIUM", ["EV-003"]), ev)  # no evidence shows the mechanism
    assert hyps[0]["support"] == "LOW" and "mechanism" in events[0]["payload"]["reason"]
    hyps, _ = apply_guardrails(_hs("MEDIUM", ["EV-001"], "PROCESS_PARAMETER_DEVIATION"), ev)
    assert hyps[0]["support"] == "LOW"
    hyps, _ = apply_guardrails(_hs("HIGH", ["EV-001", "EV-002"]), ev)
    assert hyps[0]["support"] == "HIGH"
    hyps, events = apply_guardrails(_hs("MEDIUM", ["EV-404"]), ev)
    assert hyps[0]["support"] == "INSUFFICIENT" and {e["type"] for e in events} == {"citation_dropped",
                                                                                    "support_downgraded"}
    banned = HypothesisSet.model_validate({"hypotheses": [{
        "category": "PRODUCT_MIX_SHIFT", "title": "t", "statement": "The root cause is mix EV-001",
        "support": "LOW"}]})
    assert any("overclaiming" in e for e in hypothesis_errors(banned, set(ev)))
    hedged = HypothesisSet.model_validate({"hypotheses": [{
        "category": "PRODUCT_MIX_SHIFT", "title": "t", "statement": "No single root cause is established EV-001",
        "support": "LOW"}]})
    assert hypothesis_errors(hedged, set(ev)) == []
    from backend.evidence.models import overclaims
    assert overclaims("This is evidence-supported, not a proven root cause.") is None
    assert overclaims("It is proven that EOL-B drifts.") == "proven"
    assert overclaims("The root cause is the tester.") == "The root cause is"


def test_conclusion_rule_and_judgment_diff() -> None:
    id_map: dict = {}
    h = assign_ids([{"category": "TESTER_MEASUREMENT_DRIFT", "support": "HIGH"},
                    {"category": "PROCESS_PARAMETER_DEVIATION", "support": "LOW"}], id_map)
    assert decide_conclusion(h) == ("TESTER_MEASUREMENT_DRIFT", "HIGH")
    assert decide_conclusion([{"category": "PRODUCT_MIX_SHIFT", "support": "MEDIUM"},
                              {"category": "PROCESS_PARAMETER_DEVIATION", "support": "MEDIUM"}])[0] == \
        "INSUFFICIENT_EVIDENCE"
    assert decide_conclusion([{"category": "PRODUCT_MIX_SHIFT", "support": "LOW"}])[0] == "INSUFFICIENT_EVIDENCE"
    before = [{"hypothesis_id": "H-1", "category": "TESTER_MEASUREMENT_DRIFT", "support": "MEDIUM",
               "supporting_evidence": ["EV-001"], "contradicting_evidence": []}]
    after = [{**before[0], "support": "HIGH", "supporting_evidence": ["EV-001", "EV-009"]}]
    ch = judgment_changes(before, after, ["EV-009"])
    assert ch[0]["direction"] == "up" and ch[0]["because"] == ["EV-009"]


def test_decision_validation() -> None:
    eng = InvestigationEngine(Settings(), None, None, None, None)  # type: ignore[arg-type]
    pending = {"proposals": [{"proposal_id": "P-1-1"}, {"proposal_id": "P-1-2"}]}
    v = eng.validate_decision
    assert v(pending, 0, {"action": "approve", "proposal_id": "P-1-2"}) is None
    assert v(pending, 0, {"action": "approve", "proposal_id": "P-9-9"}) == "UNKNOWN_PROPOSAL"
    assert v(pending, 0, {"action": "reject_all"}) == "NOTE_REQUIRED"
    assert v(pending, 2, {"action": "reject_all", "note": "no"}) == "REJECT_LIMIT_REACHED"
    assert v(pending, 0, {"action": "conclude", "proposal_id": "P-1-1"}) == "UNEXPECTED_PROPOSAL_ID"
    assert v({"proposals": []}, 0, {"action": "approve", "proposal_id": "P-1-1"}) == "ACTION_NOT_OFFERED"
    assert v(pending, 0, {"action": "explode"}) == "INVALID_ACTION"
    assert v(pending, 0, {"action": "conclude", "note": "x" * 501}) == "NOTE_TOO_LONG"


def test_proposal_validator() -> None:
    eng = InvestigationEngine(Settings(), None, None, None, None)  # type: ignore[arg-type]
    cands = {"EOL-A": [], "EOL-B": [{"sn": "SN-2600500", "ts": "x"}]}
    st = {"executed": [{"type": "reference_sample_check", "params": {"tester_id": "EOL-B"}}], "rejected": []}
    ok = {"verification_type": "cross_retest", "serial_numbers": ["SN-2600500"], "target_tester_id": "EOL-A",
          "cited_evidence": ["EV-001"], "rationale": "r"}
    assert eng.validate_proposal(dict(ok), st, cands, {"EV-001"}) is None
    assert "candidate" in eng.validate_proposal({**ok, "serial_numbers": ["SN-2600999"]}, st, cands, {"EV-001"})
    assert "already executed" in eng.validate_proposal(
        {"verification_type": "reference_sample_check", "tester_id": "EOL-B", "rationale": "r"}, st, cands, set())
    assert "unknown evidence" in eng.validate_proposal({**ok, "cited_evidence": ["EV-777"]}, st, cands, {"EV-001"})
    assert "ST-10" in eng.validate_proposal({"verification_type": "process_config_check", "equipment_id": "EOL-A",
                                             "rationale": "r"}, st, cands, set())


def test_report_rendering_has_all_sections() -> None:
    ev = [{"id": "EV-001", "kind": "statistic", "source_system": "EOL", "title": "EOL-B FAIL_Rate elevated in the "
           "last 3 h", "summary": "s", "record_refs": ["eol_tests:T-000001"], "ts": "2026-11-02T11:00:00Z",
           "data": {"equipment_id": "EOL-B", "ref_rows": [{"sn": "SN-2600001"}]}}]
    st = {"case_id": "CASE-0001", "dataset_id": "ds-01",
          "anomaly": {"status": "ANOMALY", "testers": [{"equipment_id": "EOL-B", "baseline_rate": 0.01,
                                                        "window_rate": 0.17, "baseline_counts": [1, 100],
                                                        "window_counts": [25, 146], "p_value": 1e-5,
                                                        "flagged": True}],
                      "anomalies": [{"equipment_id": "EOL-B", "window_counts": [25, 146]}],
                      "detected_window": {}, "baseline_window": {}},
          "hypotheses": [{"hypothesis_id": "H-1", "category": "TESTER_MEASUREMENT_DRIFT", "title": "t",
                          "statement": "EV-001", "support": "MEDIUM", "supporting_evidence": ["EV-001"],
                          "contradicting_evidence": [], "missing_evidence": []}],
          "conclusion": {"category": "TESTER_MEASUREMENT_DRIFT", "support": "MEDIUM", "label": "Suspected cause",
                         "statement": "Suspected drift EV-001", "open_questions": ["q"]}}
    r = build_report(st, ev, [])
    r["narrative"] = {"overview": "o EV-001", "follow_up_actions": ["a"], "limitations": "l"}
    md = render_markdown(r)
    for i, title in enumerate(SECTIONS, 1):
        assert f"## {i}. {title}" in md
    assert "[EV-001](#ev-001)" in md and "#### EV-001" in md and "SN-2600001" in md
    assert "confirmed root cause" not in md.lower()
