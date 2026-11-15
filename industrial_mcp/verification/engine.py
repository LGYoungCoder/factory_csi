"""Simulated verification. The ONLY module that reads world_state.json. No real device is ever contacted."""

from __future__ import annotations

import fcntl
import hashlib
import json
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import numpy as np

from factory_data.append import (
    AppendError,
    EolTestInput,
    MeasurementInput,
    RefCheckInput,
    append_verification_records,
)
from factory_data.db import make_engine
from factory_data.enums import (
    OUTPUT_VOLTAGE_FAILURE_CODE,
    OUTPUT_VOLTAGE_ITEM,
    ReferenceAvailability,
    TestResult,
    VerificationType,
)
from factory_data.physics import measure_no_flip
from factory_data.timeutil import format_ts, parse_ts
from factory_data.world_state import WorldStateError, load_world_state
from industrial_mcp.common import (
    STATION_EQUIPMENT,
    ServerContext,
    ToolFailure,
    check_sn_list,
    check_tester,
    invalid,
)

ID_SAFE = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_.:")


def _check_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise invalid(name, "must be a non-empty string of at most 64 characters")
    if name == "approval_id" and not set(value) <= ID_SAFE:
        raise invalid(name, "may contain only letters, digits and - _ . :")
    return value


@contextmanager
def _lock(ctx: ServerContext):  # noqa: ANN202
    d = ctx.log_dir / "mcp" / "verifications"
    d.mkdir(parents=True, exist_ok=True)
    with (d / f"{ctx.dataset_id}.lock").open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield d / f"{ctx.dataset_id}.jsonl"
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _ledger_lookup(path, approval_id: str, conn) -> dict | None:  # noqa: ANN001
    if not path.exists():
        return None
    hit = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("approval_id") == approval_id:
            hit = e
    if hit is None:
        return None
    for ref in hit["result"].get("created_refs", []):
        table, _, pk = ref.partition(":")
        col = {"eol_tests": "test_id", "eol_measurements": "meas_id", "reference_sample_checks": "check_id"}[table]
        if conn.execute(f'SELECT 1 FROM "{table}" WHERE "{col}"=?', (pk,)).fetchone() is None:  # noqa: S608
            return None  # dataset was reset since; the old approval no longer applies
    return hit


def _rng(seed: int, k: int, vtype: str, target: str) -> np.random.Generator:
    digest = hashlib.sha256(f"{seed}:{k}:{vtype}:{target}".encode()).digest()
    return np.random.default_rng(int.from_bytes(digest[:8], "big"))


def run_simulated_verification(ctx: ServerContext, verification_type: str, params: dict,
                               approval_id: str, approved_by: str) -> dict:
    try:
        vtype = VerificationType(verification_type)
    except ValueError as exc:
        raise invalid("verification_type", f"must be one of {[v.value for v in VerificationType]}") from exc
    _check_text(approval_id, "approval_id")
    _check_text(approved_by, "approved_by")
    if not isinstance(params, dict):
        raise invalid("params", "must be an object")
    request_key = json.dumps({"type": vtype.value, "params": params}, sort_keys=True)

    with _lock(ctx) as ledger_path:
        conn = ctx.connect()
        try:
            prior = _ledger_lookup(ledger_path, approval_id, conn)
            if prior is not None:
                if prior["request_key"] != request_key or prior["approved_by"] != approved_by:
                    raise invalid("approval_id", "already used for a different verification request")
                return {**prior["result"], "replayed": True}
            try:
                ws = load_world_state(ctx.world_state_path)
            except WorldStateError as exc:
                raise ToolFailure("UNAVAILABLE", "world state of the simulated factory is unavailable") from exc
            hist_end = conn.execute(
                "SELECT MAX(ts) FROM (SELECT ts FROM eol_tests WHERE origin='historical' "
                "UNION ALL SELECT ts FROM reference_sample_checks WHERE origin='historical')").fetchone()[0]
            k = 1 + conn.execute(
                "SELECT COUNT(DISTINCT ts) FROM (SELECT ts FROM eol_tests WHERE origin='verification' "
                "UNION ALL SELECT ts FROM reference_sample_checks WHERE origin='verification')").fetchone()[0]
            vts = format_ts(parse_ts(hist_end) + timedelta(minutes=10 * k))

            if vtype == VerificationType.CROSS_RETEST:
                result, batch = _cross_retest(conn, ws, params, vts, k)
            elif vtype == VerificationType.REFERENCE_SAMPLE_CHECK:
                result, batch = _reference_check(ws, params, vts, k)
            else:
                result, batch = _config_check(ws, params), None
        finally:
            conn.close()

        created: list[str] = []
        if batch:
            engine = make_engine(ctx.db_path)
            try:
                res = append_verification_records(engine, batch.get("tests"), batch.get("checks"))
            except AppendError as exc:
                raise ToolFailure("INVALID_ARGUMENT", str(exc)) from exc
            finally:
                engine.dispose()
            created = res.refs
            for o, tid in zip(result["outcomes"], res.test_ids, strict=False):
                o["test_id"] = tid
            if res.check_ids:
                result["outcomes"][0]["check_id"] = res.check_ids[0]
        body = {
            "simulation": True,
            "verification_id": "VER-" + hashlib.sha256(f"{ctx.dataset_id}:{approval_id}".encode()).hexdigest()[:12],
            "verification_type": vtype.value,
            "approval_id": approval_id,
            "approved_by": approved_by,
            "simulated_ts": vts if batch or vtype != VerificationType.PROCESS_CONFIG_CHECK else vts,
            **result,
            "created_refs": created,
            "replayed": False,
        }
        with ledger_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"approval_id": approval_id, "approved_by": approved_by,
                                 "request_key": request_key, "result": body}, sort_keys=True) + "\n")
        return body


def _cross_retest(conn, ws, params: dict, vts: str, k: int):  # noqa: ANN001, ANN202
    extra = set(params) - {"serial_numbers", "target_tester_id"}
    if extra:
        raise invalid("params", f"unknown fields {sorted(extra)}")
    sns = check_sn_list(params.get("serial_numbers"), 5, allow_duplicates=False)
    target = check_tester(params.get("target_tester_id"), "params.target_tester_id")
    tests, outcomes = [], []
    for sn in sns:
        p = conn.execute("SELECT model_id FROM products WHERE sn=?", (sn,)).fetchone()
        first = conn.execute(
            "SELECT test_id FROM eol_tests WHERE sn=? AND is_retest=0 AND origin='historical'", (sn,)).fetchone()
        if p is None or first is None:
            raise ToolFailure("NOT_FOUND", f"serial number {sn} has no first EOL test", {"field": "serial_numbers"})
        latest = conn.execute(
            "SELECT test_id, tester_id, result FROM eol_tests WHERE sn=? ORDER BY ts DESC, test_id DESC LIMIT 1",
            (sn,)).fetchone()
        lim = conn.execute("SELECT ov_lower, ov_upper FROM product_models WHERE model_id=?", (p["model_id"],)).fetchone()
        scale = ws.model_scales[p["model_id"]]
        true_z = (ws.true_value(sn) - scale.midpoint) / scale.half_width
        rng = _rng(ws.seed, k, "cross_retest", sn)
        value, res = measure_no_flip(true_z, ws.bias_at(target, vts),
                                     lambda r=rng: float(r.normal(0.0, ws.measurement_noise_sd)),
                                     scale.midpoint, scale.half_width)
        tests.append(EolTestInput(
            sn=sn, tester_id=target, ts=vts, model_id=p["model_id"], result=res,
            failure_code=OUTPUT_VOLTAGE_FAILURE_CODE if res == TestResult.FAIL else None,
            is_retest=True, retest_of=latest["test_id"],
            measurements=[MeasurementInput(OUTPUT_VOLTAGE_ITEM, value, lim["ov_lower"], lim["ov_upper"], res)],
        ))
        outcomes.append({"sn": sn, "original_test_id": latest["test_id"], "original_tester_id": latest["tester_id"],
                         "original_result": latest["result"], "retest_tester_id": target,
                         "measured_value": value, "lower_limit": lim["ov_lower"], "upper_limit": lim["ov_upper"],
                         "outcome": res.value})
    passed = sum(o["outcome"] == "PASS" for o in outcomes)
    summary = (f"Simulated cross retest on {target}: {passed} of {len(outcomes)} serial numbers passed "
               f"({', '.join(o['sn'] + ' ' + o['outcome'] for o in outcomes)}).")
    return {"target": target, "outcomes": outcomes, "summary": summary}, {"tests": tests}


def _reference_check(ws, params: dict, vts: str, k: int):  # noqa: ANN001, ANN202
    extra = set(params) - {"tester_id"}
    if extra:
        raise invalid("params", f"unknown fields {sorted(extra)}")
    tester = check_tester(params.get("tester_id"), "params.tester_id")
    ref = ws.reference_samples[tester]
    if ref.availability == ReferenceAvailability.UNAVAILABLE:
        return ({"target": tester, "outcomes": [{"tester_id": tester, "sample_id": ref.sample_id,
                                                  "outcome": "UNAVAILABLE", "reason": ref.reason}],
                 "summary": f"Reference sample check on {tester} not possible: reference sample {ref.sample_id} is "
                            f"{ref.reason}."}, None)
    rng = _rng(ws.seed, k, "reference_sample_check", tester)
    measured = round(ref.nominal + ref.half_width * (ws.bias_at(tester, vts) + float(rng.normal(0.0, ws.reference_noise_sd))), 4)
    dev = round(measured - ref.nominal, 4)
    within = abs(dev) <= ref.tolerance
    outcome = "WITHIN_TOLERANCE" if within else "OUT_OF_TOLERANCE"
    check = RefCheckInput(tester, vts, ref.sample_id, ref.test_item, ref.nominal, measured,
                          TestResult.PASS if within else TestResult.FAIL)
    return ({"target": tester, "outcomes": [{"tester_id": tester, "sample_id": ref.sample_id, "nominal": ref.nominal,
                                              "measured": measured, "deviation": dev, "tolerance": ref.tolerance,
                                              "outcome": outcome}],
             "summary": f"Simulated reference sample check on {tester}: deviation {dev:+.4f} V against tolerance "
                        f"±{ref.tolerance} V → {outcome}."}, {"checks": [check]})


def _config_check(ws, params: dict) -> dict:  # noqa: ANN001
    extra = set(params) - {"equipment_id"}
    if extra:
        raise invalid("params", f"unknown fields {sorted(extra)}")
    eq = params.get("equipment_id")
    if eq not in STATION_EQUIPMENT:
        raise invalid("params.equipment_id", f"must be one of {list(STATION_EQUIPMENT)}")
    actual, approved = ws.actual_config[eq], ws.approved_config[eq]
    match = actual == approved
    diffs = [f for f in ("recipe_version", "program_version") if getattr(actual, f) != getattr(approved, f)]
    outcome = "MATCH" if match else "MISMATCH"
    return {"target": eq, "outcomes": [{
        "equipment_id": eq, "outcome": outcome,
        "actual": actual.model_dump(), "approved": approved.model_dump(), "differences": diffs}],
        "summary": f"Simulated configuration audit of {eq}: {outcome}"
                   + (f" ({', '.join(f'{d}: actual {getattr(actual, d)} vs approved {getattr(approved, d)}' for d in diffs)})."
                      if diffs else " (recipe and program versions equal the approved configuration).")}
