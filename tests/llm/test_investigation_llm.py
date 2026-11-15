"""Real-LLM investigation tests (provider from .env). Properties only, never exact text.

Run: uv run pytest -m llm tests/llm -q    (≈5 min, a few US cents)
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.settings import Settings
from simulator.config import DEFAULT_CONFIG
from simulator.generator import generate
from simulator.ground_truth import load_ground_truth
from simulator.registry import list_entries
from simulator.scenarios import scenario_for_key
from simulator.writer import write_dataset

pytestmark = pytest.mark.llm
RANK = {"INSUFFICIENT": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


@pytest.fixture(scope="module")
def env(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201
    root = tmp_path_factory.mktemp("llm")
    data = root / "data"
    for e in list_entries():
        write_dataset(data, generate(scenario_for_key(e.scenario_key), e.default_seed, DEFAULT_CONFIG))
    s = Settings(data_dir=data, app_db_path=root / "var/app.db", checkpoint_db_path=root / "var/cp.db",
                 log_dir=root / "logs")
    with TestClient(create_app(s)) as c:
        st = c.post("/api/llm/status/refresh").json()
        if st["status"] != "OK":
            pytest.fail(f"LLM status {st['status']}: {st.get('reason')}")  # fail, never skip
        yield c, data


def run_case(c: TestClient, ds: str, policy, timeout: float = 600) -> dict:  # noqa: ANN001
    r = c.post("/api/cases", json={"dataset_id": ds})
    assert r.status_code == 201, r.text
    cid = r.json()["case_id"]
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = c.get(f"/api/cases/{cid}").json()
        if d["status"] == "AWAITING_APPROVAL" and d["pending"]:
            body = policy(d)
            assert c.post(f"/api/cases/{cid}/decision", json=body).status_code == 202
        elif d["status"] in ("COMPLETED", "FAILED", "FAILED_LLM"):
            return d
        time.sleep(1.5)
    pytest.fail(f"case {cid} did not finish in {timeout}s")


def approve_first(d: dict) -> dict:
    props = d["pending"]["proposals"]
    return {"action": "approve", "proposal_id": props[0]["proposal_id"]} if props else {"action": "conclude"}


def check_common(c: TestClient, d: dict) -> None:
    assert d["status"] == "COMPLETED", d.get("error")
    ids = {e["id"] for e in d["evidence"]}
    for h in d["hypotheses"]:
        assert set(h["supporting_evidence"]) | set(h["contradicting_evidence"]) <= ids
        if h["support"] == "HIGH":
            kinds = {e["kind"] for e in d["evidence"] if e["id"] in h["supporting_evidence"]}
            assert "verification" in kinds
    assert d["budgets"]["mcp_calls"]["used"] <= 20 and d["budgets"]["llm_calls"]["used"] <= 40
    assert d["budgets"]["verification_rounds"]["used"] <= 3
    md = c.get(f"/api/cases/{d['case_id']}/report.md").text
    for i in range(1, 11):
        assert f"## {i}." in md
    assert set(re.findall(r"EV-\d{3}", md)) <= ids
    assert "confirmed root cause" not in md.lower()


def test_scenario_a_tester_drift(env) -> None:  # noqa: ANN001
    c, data = env
    d = run_case(c, "ds-01", approve_first)
    check_common(c, d)
    gt = load_ground_truth(data / "ds-01" / "ground_truth.json")
    assert any(h["category"] == "TESTER_MEASUREMENT_DRIFT" for h in d["hypotheses"])
    assert gt.is_acceptable(d["conclusion"]["category"], d["conclusion"]["support"]), d["conclusion"]
    verif = {e["id"] for e in d["evidence"] if e["kind"] == "verification"}
    tester_changes = [j for j in d["judgment_changes"] if j["category"] == "TESTER_MEASUREMENT_DRIFT"]
    assert any(j["direction"] == "up" and set(j["because"]) & verif for j in tester_changes)


def test_scenario_b_process_defect(env) -> None:  # noqa: ANN001
    c, data = env
    d = run_case(c, "ds-02", approve_first)
    check_common(c, d)
    gt = load_ground_truth(data / "ds-02" / "ground_truth.json")
    assert any(h["category"] == "PROCESS_PARAMETER_DEVIATION" for h in d["hypotheses"])
    assert gt.is_acceptable(d["conclusion"]["category"], d["conclusion"]["support"]), d["conclusion"]


def test_scenario_c_insufficient_evidence_with_reject(env) -> None:  # noqa: ANN001
    c, data = env
    state = {"rejected": False, "first": None}

    def policy(d: dict) -> dict:
        props = d["pending"]["proposals"]
        if not state["rejected"] and props:
            state["rejected"], state["first"] = True, {(p["verification_type"], str(sorted(p["params"].items())))
                                                       for p in props}
            return {"action": "reject_all", "note": "Try a different angle first."}
        if state["first"] is not None:
            again = {(p["verification_type"], str(sorted(p["params"].items()))) for p in props}
            assert not (again & state["first"]), "rejected proposals were offered again"
            state["first"] = None
        return approve_first(d)

    d = run_case(c, "ds-03", policy)
    check_common(c, d)
    gt = load_ground_truth(data / "ds-03" / "ground_truth.json")
    concl = d["conclusion"]
    assert concl["category"] not in ("TESTER_MEASUREMENT_DRIFT", "PROCESS_PARAMETER_DEVIATION") or \
        concl["support"] != "HIGH"
    assert gt.is_acceptable(concl["category"], concl["support"]), concl
    assert any(x["action"] == "reject_all" for x in d["decisions"])


def test_conclude_immediately(env) -> None:  # noqa: ANN001
    c, _ = env
    c.post("/api/datasets/ds-01/reset")
    d = run_case(c, "ds-01", lambda d: {"action": "conclude", "note": "enough for now"})
    check_common(c, d)
    assert d["budgets"]["verification_rounds"]["used"] == 0
    assert all(h["support"] != "HIGH" for h in d["hypotheses"])


_ = Path
