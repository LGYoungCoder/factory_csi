from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from factory_data.append import (
    AppendError,
    EolTestInput,
    MeasurementInput,
    RefCheckInput,
    append_verification_records,
)
from factory_data.db import make_engine
from factory_data.enums import ConclusionCategory, TestResult
from factory_data.world_state import load_world_state
from simulator.config import DEFAULT_CONFIG, ConfigError, FactoryConfig
from simulator.generator import GenerationError, generate
from simulator.ground_truth import GroundTruth, load_ground_truth
from simulator.hashing import HashError, content_hash
from simulator.registry import RegistryError, get_entry, list_entries
from simulator.reset import reset_dataset
from simulator.scenarios import scenario_for_key
from simulator.writer import write_dataset
from tests.unit.simulator.checks import CHECKS, load_rows

DATASETS = ["ds-00", "ds-01", "ds-02", "ds-03"]


@pytest.mark.parametrize("dataset_id", DATASETS)
def test_scenario_statistics(data_dir: Path, dataset_id: str) -> None:
    rows = load_rows(data_dir / dataset_id / "factory.db")
    assert CHECKS[dataset_id](rows) == []


@pytest.mark.parametrize("dataset_id", DATASETS)
def test_artifacts_and_integrity(data_dir: Path, dataset_id: str) -> None:
    d = data_dir / dataset_id
    assert sorted(p.name for p in d.iterdir()) == ["factory.db", "ground_truth.json", "world_state.json"]
    conn = sqlite3.connect(d / "factory.db")
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    # route order and one first test per SN
    bad = conn.execute(
        "SELECT p.sn FROM products p WHERE (SELECT COUNT(*) FROM process_steps s WHERE s.sn=p.sn) != 3 "
        "OR (SELECT COUNT(*) FROM eol_tests t WHERE t.sn=p.sn AND t.is_retest=0) != 1"
    ).fetchall()
    assert bad == []
    assert conn.execute("SELECT COUNT(*) FROM eol_tests WHERE origin='verification'").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM eol_tests t JOIN products p ON p.sn=t.sn WHERE t.model_id != p.model_id"
    ).fetchone()[0] == 0
    conn.close()
    ws = load_world_state(d / "world_state.json")
    gt = load_ground_truth(d / "ground_truth.json")
    rows = load_rows(d / "factory.db")
    assert set(ws.true_values) == {p["sn"] for p in rows["products"]}
    assert set(gt.affected_sns) <= set(ws.true_values)


@pytest.mark.parametrize("dataset_id", DATASETS)
def test_no_answer_key_leak(data_dir: Path, dataset_id: str) -> None:
    """factory.db holds no scenario names, labels, categories or ground-truth field names."""
    banned = [e.label.lower() for e in list_entries()] + [
        "tester drift", "manufacturing process defect", "insufficient evidence", "world_state", "ground_truth",
        "within_tolerance", "out_of_tolerance", "mismatch",
    ] + [c.value.lower() for c in ConclusionCategory]
    gt_fields = set(GroundTruth.model_fields)
    conn = sqlite3.connect(data_dir / dataset_id / "factory.db")
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]
        for name in [table, *cols]:
            assert name not in gt_fields, f"{table}.{name}"
        for row in conn.execute(f'SELECT * FROM "{table}"'):
            for col, v in zip(cols, row, strict=True):
                if isinstance(v, str):
                    low = v.lower()
                    hit = [b for b in banned if b in low] + ([v] if v in gt_fields else [])
                    assert not hit, f"{table}.{col} = {v!r} matches {hit}"
    conn.close()


def test_ground_truth_contents(data_dir: Path) -> None:
    a = load_ground_truth(data_dir / "ds-01" / "ground_truth.json")
    assert a.expected_anomaly_equipment == "EOL-B" and a.affected_sns
    assert a.expected_verification_outcomes.cross_retest == "PASS"
    b = load_ground_truth(data_dir / "ds-02" / "ground_truth.json")
    assert b.expected_verification_outcomes.config_check == "MISMATCH"
    c = load_ground_truth(data_dir / "ds-03" / "ground_truth.json")
    assert c.is_acceptable("INSUFFICIENT_EVIDENCE", "HIGH") and not c.is_acceptable("TESTER_MEASUREMENT_DRIFT", "HIGH")
    assert c.is_acceptable("PRODUCT_MIX_SHIFT", "MEDIUM") and not c.is_acceptable("PRODUCT_MIX_SHIFT", "HIGH")
    base = load_ground_truth(data_dir / "ds-00" / "ground_truth.json")
    assert base.affected_sns == [] and base.expected_anomaly_equipment is None and base.anomaly_window is None
    ws_c = load_world_state(data_dir / "ds-03" / "world_state.json")
    assert ws_c.reference_samples["EOL-B"].availability == "UNAVAILABLE"
    ws_b = load_world_state(data_dir / "ds-02" / "world_state.json")
    assert ws_b.actual_config["ST-20"].program_version == "P-2.4"
    assert ws_b.approved_config["ST-20"].program_version == "P-2.3"


@pytest.mark.parametrize("key", ["baseline", "a", "b", "c"])
def test_reproducible_content_hash(tmp_path: Path, key: str) -> None:
    seed = get_entry({"baseline": "ds-00", "a": "ds-01", "b": "ds-02", "c": "ds-03"}[key]).default_seed
    d1 = write_dataset(tmp_path / "one", generate(scenario_for_key(key), seed))
    d2 = write_dataset(tmp_path / "two", generate(scenario_for_key(key), seed))
    d3 = write_dataset(tmp_path / "three", generate(scenario_for_key(key), seed + 1000))
    assert content_hash(d1) == content_hash(d2)
    assert content_hash(d1) != content_hash(d3)
    assert len(content_hash(d1)) == 64


def test_hash_errors(tmp_path: Path) -> None:
    with pytest.raises(HashError):
        content_hash(tmp_path / "missing")
    (tmp_path / "x").mkdir()
    with pytest.raises(HashError, match="missing artifact"):
        content_hash(tmp_path / "x")


def test_reset_restores_and_keeps_ground_truth(tmp_path: Path) -> None:
    e = get_entry("ds-01")
    target = write_dataset(tmp_path, generate(scenario_for_key("a"), e.default_seed))
    before = content_hash(target)
    gt_bytes = (target / "ground_truth.json").read_bytes()
    engine = make_engine(target / "factory.db")
    sn = sqlite3.connect(target / "factory.db").execute(
        "SELECT sn, test_id FROM eol_tests WHERE is_retest=0 LIMIT 1").fetchone()
    res = append_verification_records(engine, [EolTestInput(
        sn=sn[0], tester_id="EOL-A", ts="2026-11-02T14:10:00Z", model_id=load_rows(target / "factory.db")["products"][0]["model_id"],
        result=TestResult.PASS, failure_code=None, is_retest=True, retest_of=sn[1],
        measurements=[MeasurementInput("output_voltage", 12.0, 11.4, 12.6, TestResult.PASS)])],
        [RefCheckInput("EOL-B", "2026-11-02T14:10:00Z", "RS-EOLB-01", "output_voltage", 12.0, 12.3, TestResult.FAIL)])
    engine.dispose()
    assert res.test_ids == ["T-V00001"] and res.check_ids == ["RC-V0001"]
    assert content_hash(target) != before
    reset_dataset("ds-01", tmp_path)
    assert content_hash(target) == before
    assert (target / "ground_truth.json").read_bytes() == gt_bytes
    with pytest.raises(RegistryError):
        reset_dataset("ds-99", tmp_path)


def test_append_validation_is_atomic(data_dir: Path, tmp_path: Path) -> None:
    target = write_dataset(tmp_path, generate(scenario_for_key("baseline"), 1))
    engine = make_engine(target / "factory.db")
    good = MeasurementInput("output_voltage", 12.0, 11.4, 12.6, TestResult.PASS)
    sn, tid, model = sqlite3.connect(target / "factory.db").execute(
        "SELECT sn, test_id, model_id FROM eol_tests LIMIT 1").fetchone()
    ok = EolTestInput(sn, "EOL-A", "2026-11-02T14:10:00Z", model, TestResult.PASS, None, True, tid, [good])
    with pytest.raises(AppendError, match="tester_id"):
        append_verification_records(engine, [ok, EolTestInput(sn, "ST-20", ok.ts, model, TestResult.PASS, None,
                                                               True, tid, [good])])
    with pytest.raises(AppendError, match="foreign_key"):
        append_verification_records(engine, [ok, EolTestInput("SN-9999999", "EOL-A", ok.ts, model,
                                                               TestResult.PASS, None, False, None, [good])])
    with pytest.raises(AppendError, match="empty"):
        append_verification_records(engine, [])
    with pytest.raises(AppendError, match="at most 5"):
        append_verification_records(engine, [ok] * 6)
    assert sqlite3.connect(target / "factory.db").execute(
        "SELECT COUNT(*) FROM eol_tests WHERE origin='verification'").fetchone()[0] == 0
    engine.dispose()


def test_config_and_seed_validation() -> None:
    with pytest.raises(ConfigError, match="500 to 1000"):
        generate(scenario_for_key("baseline"), 1, FactoryConfig(product_count=499))
    with pytest.raises(ConfigError, match="65%"):
        generate(scenario_for_key("baseline"), 1, FactoryConfig(model_a_share=0.8))
    with pytest.raises(GenerationError, match="seed"):
        generate(scenario_for_key("baseline"), -1, DEFAULT_CONFIG)


def test_cli_errors_and_success(tmp_path: Path) -> None:
    run = lambda *a: subprocess.run([sys.executable, "-m", "simulator", *a], capture_output=True, text=True)  # noqa: E731
    r = run("generate", "--scenario", "x", "--out", str(tmp_path))
    assert r.returncode != 0 and "invalid choice" in r.stderr
    r = run("generate", "--scenario", "a", "--seed", "abc", "--out", str(tmp_path))
    assert r.returncode != 0 and "--seed" in r.stderr
    r = run("generate", "--scenario", "b", "--out", str(tmp_path))
    assert r.returncode == 0 and "ds-02" in r.stdout and "Scenario" not in r.stdout


def test_reset_does_not_load_ground_truth_module(tmp_path: Path) -> None:
    code = (
        "import sys; from simulator.reset import reset_dataset; "
        f"reset_dataset('ds-00', {str(tmp_path)!r}); "
        "assert 'simulator.ground_truth' not in sys.modules; print('ok')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.stdout.strip() == "ok", r.stderr
    assert not (tmp_path / "ds-00" / "ground_truth.json").exists()
