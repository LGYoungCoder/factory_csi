"""API integration tests without an LLM (empty key ⇒ MISCONFIGURED). Real MCP stdio subprocesses."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from backend.api.app import create_app
from backend.settings import Settings
from simulator.config import DEFAULT_CONFIG
from simulator.generator import generate
from simulator.registry import list_entries
from simulator.scenarios import scenario_for_key
from simulator.writer import write_dataset


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory):  # noqa: ANN201
    root = tmp_path_factory.mktemp("api")
    data = root / "data"
    for e in list_entries():
        write_dataset(data, generate(scenario_for_key(e.scenario_key), e.default_seed, DEFAULT_CONFIG))
    s = Settings(_env_file=None, llm_api_key=SecretStr(""), data_dir=data, app_db_path=root / "var/app.db",
                 checkpoint_db_path=root / "var/cp.db", log_dir=root / "logs")
    with TestClient(create_app(s)) as c:
        yield c


def test_health_and_scenarios(client: TestClient) -> None:
    h = client.get("/api/health").json()
    assert h["status"] == "ok" and all(d["available"] for d in h["datasets"])
    sc = client.get("/api/scenarios").json()
    assert [s["dataset_id"] for s in sc] == ["ds-00", "ds-01", "ds-02", "ds-03"]
    st = client.get("/api/llm/status").json()
    assert st["status"] == "MISCONFIGURED" and "key" not in str(st.get("reason", "")).lower().replace("api_key", "")


@pytest.mark.parametrize("ds,red", [("ds-00", set()), ("ds-01", {"EOL-B"}), ("ds-02", {"ST-20"}),
                                    ("ds-03", {"EOL-B"})])
def test_overview_status_colors(client: TestClient, ds: str, red: set) -> None:
    ov = client.get(f"/api/datasets/{ds}/overview").json()
    assert ov["mode"] == "SIMULATION"
    reds = {e["equipment_id"] for e in ov["equipment_status"] if e["status"] == "RED"}
    assert red <= reds
    if ds == "ds-00":
        assert all(e["status"] == "GREEN" for e in ov["equipment_status"])
    if ds in ("ds-01", "ds-03"):
        assert "ST-20" not in reds


def test_trends_and_equipment(client: TestClient) -> None:
    t = client.get("/api/datasets/ds-02/trends", params={"bucket_minutes": 60}).json()
    assert len([b for b in t["fail_rate"] if b["tester_id"] == "EOL-A"]) == 8
    assert t["process_changes"][0]["new_value"] == "P-2.4"
    assert client.get("/api/datasets/ds-02/trends", params={"bucket_minutes": 14}).status_code == 400
    e = client.get("/api/datasets/ds-01/equipment/EOL-B").json()
    assert e["status"] == "RED" and len(e["reference_checks"]) == 8
    assert client.get("/api/datasets/ds-01/equipment/ST-10").json()["step_total_count"] == 800
    r = client.get("/api/datasets/ds-01/equipment/XX")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/datasets/ds-99/overview").status_code == 404


def test_case_creation_disabled_without_llm(client: TestClient) -> None:
    r = client.post("/api/cases", json={"dataset_id": "ds-01"})
    assert r.status_code == 503
    body = r.json()["error"]
    assert body["code"] == "LLM_UNAVAILABLE" and body["details"]["llm_status"] == "MISCONFIGURED"
    assert client.get("/api/cases").json() == []
    assert client.post("/api/cases", json={"dataset_id": "ds-01", "label": "x"}).status_code == 400


def test_reset_and_errors(client: TestClient) -> None:
    r = client.post("/api/datasets/ds-01/reset").json()
    assert r["counts"]["products"] == 800 and r["counts"]["verification_eol_test_count"] == 0
    assert client.post("/api/datasets/ds-77/reset").status_code == 404
    r = client.post("/api/cases/CASE-0404/decision", json={"action": "approve"})
    assert r.status_code == 404
    r = client.post("/api/cases", content=b"x" * 70_000, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_sse_replay_and_decision_conflict(client: TestClient) -> None:
    store = client.app.state.svc.store

    async def seed() -> str:
        case = await store.create_case("ds-00")
        cid = case["case_id"]
        await store.update_case(cid, status="COMPLETED")
        for t, p in (("status_changed", {"from": "CREATED", "to": "RUNNING"}), ("node_started", {"node": "x"}),
                     ("completed", {"final_status": "COMPLETED"})):
            await store.append_event(cid, t, p)
        return cid

    cid = client.portal.call(seed)
    text = client.get(f"/api/cases/{cid}/events").text
    assert text.count("event: ") == 3 and "id: 3" in text
    text = client.get(f"/api/cases/{cid}/events", headers={"Last-Event-ID": "2"}).text
    assert text.count("event: ") == 1 and "event: completed" in text
    d = client.get(f"/api/cases/{cid}").json()
    assert d["last_event_seq"] == 3 and d["budgets"]["mcp_calls"]["limit"] == 20
    r = client.post(f"/api/cases/{cid}/decision", json={"action": "conclude"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "CONFLICT"
    assert client.post(f"/api/cases/{cid}/retry").status_code == 409
