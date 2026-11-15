"""Baseline generator with scenario modifiers. Produces observable rows and the hidden world state.

All randomness comes from one ``numpy.random.Generator`` seeded with the given seed and drawn in a
fixed order; all timestamps derive from the configured shift window.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from factory_data import ids
from factory_data.enums import (
    OUTPUT_VOLTAGE_FAILURE_CODE,
    OUTPUT_VOLTAGE_ITEM,
    EventType,
    Origin,
    ReferenceAvailability,
    TestResult,
)
from factory_data.physics import classify, measure_no_flip
from factory_data.timeutil import format_ts, parse_ts
from factory_data.world_state import (
    ModelScale,
    ReferenceSample,
    StationConfig,
    TesterBias,
    WorldState,
)
from simulator.config import DEFAULT_CONFIG, FactoryConfig
from simulator.scenarios import ScenarioParams

Rows = dict[str, list[dict]]
TESTERS = ("EOL-A", "EOL-B")
REF_SAMPLE_IDS = {"EOL-A": "RS-EOLA-01", "EOL-B": "RS-EOLB-01"}
MAX_SEED = 4_294_967_295


class GenerationError(RuntimeError):
    pass


@dataclass
class GeneratedDataset:
    dataset_id: str
    scenario: ScenarioParams
    seed: int
    config: FactoryConfig
    rows: Rows
    world_state: WorldState


def _ts(dt: datetime) -> str:
    return format_ts(dt)


def validate_seed(seed: object) -> int:
    if not isinstance(seed, int) or isinstance(seed, bool) or not (0 <= seed <= MAX_SEED):
        raise GenerationError(f"seed must be an integer from 0 to {MAX_SEED}, got {seed!r}")
    return seed


def _model_sequence(rng, n: int, release: list[datetime], cfg: FactoryConfig, sc: ScenarioParams) -> list[str]:
    if sc.mix_shift is None:
        n_a = round(n * cfg.model_a_share)
        seq = np.array(["MODEL-A"] * n_a + ["MODEL-B"] * (n - n_a))
        return [str(x) for x in rng.permutation(seq)]
    ms = sc.mix_shift
    window = parse_ts(cfg.shift_start) + timedelta(hours=ms.window_offset_h)
    # products released this long before the window reach EOL inside it
    cutoff = window - timedelta(seconds=150)
    before = [i for i, t in enumerate(release) if t < cutoff]
    within = [i for i, t in enumerate(release) if t >= cutoff]
    out = [""] * n
    for idx, share in ((before, ms.model_b_share_before), (within, ms.model_b_share_within)):
        nb = round(len(idx) * share)
        seq = rng.permutation(np.array(["MODEL-B"] * nb + ["MODEL-A"] * (len(idx) - nb)))
        for i, m in zip(idx, seq, strict=True):
            out[i] = str(m)
    return out


def generate(scenario: ScenarioParams, seed: int, config: FactoryConfig = DEFAULT_CONFIG) -> GeneratedDataset:
    config.validate()
    validate_seed(seed)
    cfg, sc = config, scenario
    rng = np.random.default_rng(seed)
    start, end = parse_ts(cfg.shift_start), parse_ts(cfg.shift_end)
    n = cfg.product_count

    # --- tester bias (hidden) -------------------------------------------------------------
    bias = {t: TesterBias(base=0.0) for t in TESTERS}
    if sc.drift:
        bias[sc.drift.tester_id] = TesterBias(
            base=0.0,
            onset=_ts(start + timedelta(hours=sc.drift.onset_offset_h)),
            slope_per_hour=sc.drift.slope_per_hour,
        )
    change_ts = start + timedelta(seconds=sc.program_change.offset_s) if sc.program_change else None
    window_ts = start + timedelta(hours=sc.mix_shift.window_offset_h) if sc.mix_shift else None

    # --- release plan -----------------------------------------------------------------------
    usable = (end - start).total_seconds() - 300
    takt = usable / n
    release = [start + timedelta(seconds=math.floor(i * takt + rng.uniform(0, takt * 0.5))) for i in range(n)]
    models = _model_sequence(rng, n, release, cfg, sc)

    rows: Rows = {name: [] for name in (
        "stations", "equipment", "product_models", "production_orders", "products", "process_steps",
        "process_measurements", "equipment_events", "process_changes", "eol_tests", "eol_measurements",
        "reference_sample_checks",
    )}
    rows["stations"] = [{"station_id": s.station_id, "name": s.name, "sequence": s.sequence} for s in cfg.stations]
    rows["equipment"] = [
        {"equipment_id": e.equipment_id, "station_id": e.station_id, "name": e.name,
         "equipment_type": e.equipment_type}
        for e in cfg.equipment
    ]
    rows["product_models"] = [
        {"model_id": m.model_id, "name": m.name, "ov_lower": m.ov_lower, "ov_upper": m.ov_upper} for m in cfg.models
    ]

    # --- orders -----------------------------------------------------------------------------
    order_of: list[str] = []
    lot_of: list[str] = []
    open_order: dict[str, dict] = {}
    lot_counter: dict[str, int] = {}
    for i, m in enumerate(models):
        cur = open_order.get(m)
        if cur is None or cur["qty"] >= cfg.order_size:
            lot_counter[m] = lot_counter.get(m, 0) + 1
            cur = {
                "order_id": ids.make_id("order_id", 260000 + len(rows["production_orders"]) + 1),
                "model_id": m,
                "qty": 0,
                "start_ts": _ts(release[i]),
                "_lot": f"LOT-{cfg.model(m).code}-{lot_counter[m]:03d}",
            }
            rows["production_orders"].append(cur)
            open_order[m] = cur
        cur["qty"] += 1
        order_of.append(cur["order_id"])
        lot_of.append(cur["_lot"])
    for o in rows["production_orders"]:
        o.pop("_lot")

    # --- per product route ----------------------------------------------------------------
    step_no = meas_no = test_no = 0
    true_values: dict[str, float] = {}
    first_tests: list[dict] = []
    sd_override = (
        {"MODEL-A": sc.mix_shift.product_sd_model_a, "MODEL-B": sc.mix_shift.product_sd_model_b}
        if sc.mix_shift else {}
    )

    def noise() -> float:
        return float(rng.normal(0.0, cfg.measurement_noise_sd))

    for i in range(n):
        sn = ids.make_id("sn", 2600000 + i + 1)
        model = cfg.model(models[i])
        created = release[i]
        rows["products"].append({
            "sn": sn, "order_id": order_of[i], "model_id": model.model_id,
            "material_lot": lot_of[i], "created_ts": _ts(created),
        })
        d10, d20, d30 = 28 + int(rng.integers(0, 5)), 33 + int(rng.integers(0, 5)), 28 + int(rng.integers(0, 5))
        g1, g2, wait = int(rng.integers(3, 10)), int(rng.integers(3, 10)), int(rng.integers(20, 90))
        s10 = created
        e10 = s10 + timedelta(seconds=d10)
        s20 = e10 + timedelta(seconds=g1)
        if change_ts is not None and s20 < change_ts < s20 + timedelta(seconds=d20):
            s20 = change_ts
        e20 = s20 + timedelta(seconds=d20)
        s30 = e20 + timedelta(seconds=g2)
        e30 = s30 + timedelta(seconds=d30)
        eol_ts = e30 + timedelta(seconds=wait)

        step_ids = {}
        for station, s, e in (("ST-10", s10, e10), ("ST-20", s20, e20), ("ST-30", s30, e30)):
            step_no += 1
            step_id = ids.make_id("step_id", step_no)
            step_ids[station] = step_id
            rows["process_steps"].append({
                "step_id": step_id, "sn": sn, "station_id": station, "equipment_id": station,
                "start_ts": _ts(s), "end_ts": _ts(e), "recipe_version": cfg.initial_recipe[station],
                "result": "PASS",
            })

        new_prog = sc.program_change is not None and change_ts is not None and s20 >= change_ts
        program = sc.program_change.new_version if new_prog else cfg.initial_program["ST-20"]
        a_mean = cfg.nominal_angle + (sc.program_change.angle_shift if new_prog else 0.0)
        a_sd = sc.program_change.angle_sd if new_prog else cfg.angle_sd
        angle = round(float(rng.normal(a_mean, a_sd)), 2)
        torque = round(float(rng.normal(cfg.torque_nominal + 0.02 * (angle - cfg.nominal_angle), 0.3)), 2)
        m_ts = _ts(e20 - timedelta(seconds=2))
        for param, value, unit in (("torque", torque, "N·m"), ("angle", angle, "deg")):
            meas_no += 1
            rows["process_measurements"].append({
                "meas_id": ids.make_id("meas_id", meas_no), "step_id": step_ids["ST-20"], "sn": sn,
                "equipment_id": "ST-20", "ts": m_ts, "parameter": param, "value": value, "unit": unit,
                "program_version": program,
            })

        sd = sd_override.get(model.model_id, cfg.product_sd)
        true_z = cfg.angle_coef * (angle - cfg.nominal_angle) + float(rng.normal(0.0, sd))
        true_values[sn] = model.midpoint + model.half_width * true_z

        if window_ts is not None and eol_ts >= window_ts:
            p_b = sc.mix_shift.route_b_to_eol_b if model.model_id == "MODEL-B" else sc.mix_shift.route_a_to_eol_b
        else:
            p_b = 0.5
        tester = "EOL-B" if rng.random() < p_b else "EOL-A"
        eol_ts_s = _ts(eol_ts)
        value, result = measure_no_flip(true_z, bias[tester].at(eol_ts_s), noise, model.midpoint, model.half_width)
        test_no += 1
        test_id = ids.make_id("test_id", test_no)
        test = {
            "test_id": test_id, "sn": sn, "tester_id": tester, "ts": eol_ts_s, "model_id": model.model_id,
            "result": result.value,
            "failure_code": OUTPUT_VOLTAGE_FAILURE_CODE if result == TestResult.FAIL else None,
            "is_retest": False, "retest_of": None, "origin": Origin.HISTORICAL.value,
        }
        rows["eol_tests"].append(test)
        first_tests.append({**test, "_true_z": true_z, "_model": model})
        meas_no += 1
        rows["eol_measurements"].append({
            "meas_id": ids.make_id("meas_id", meas_no), "test_id": test_id, "test_item": OUTPUT_VOLTAGE_ITEM,
            "value": value, "lower_limit": model.ov_lower, "upper_limit": model.ov_upper, "result": result.value,
        })

    # --- historical retests (scenario A) ----------------------------------------------------
    if sc.historical_retests and sc.drift:
        onset = parse_ts(bias[sc.drift.tester_id].onset or cfg.shift_start)
        cands = [
            t for t in first_tests
            if t["tester_id"] == sc.drift.tester_id and t["result"] == "FAIL" and parse_ts(t["ts"]) >= onset
            and abs(t["_true_z"]) <= 0.9 and parse_ts(t["ts"]) <= end - timedelta(minutes=20)
        ]
        lo, hi = sc.historical_retests
        k = min(len(cands), int(rng.integers(lo, hi + 1)))
        if k < 2:
            raise GenerationError("scenario a: fewer than 2 retest candidates; choose another seed")
        picks = sorted(rng.choice(len(cands), size=k, replace=False).tolist())
        other = "EOL-A" if sc.drift.tester_id == "EOL-B" else "EOL-B"
        for p in picks:
            orig = cands[p]
            model = orig["_model"]
            rts = _ts(parse_ts(orig["ts"]) + timedelta(seconds=int(rng.integers(300, 900))))
            value, result = measure_no_flip(orig["_true_z"], bias[other].at(rts), noise, model.midpoint,
                                            model.half_width)
            test_no += 1
            test_id = ids.make_id("test_id", test_no)
            rows["eol_tests"].append({
                "test_id": test_id, "sn": orig["sn"], "tester_id": other, "ts": rts, "model_id": model.model_id,
                "result": result.value,
                "failure_code": OUTPUT_VOLTAGE_FAILURE_CODE if result == TestResult.FAIL else None,
                "is_retest": True, "retest_of": orig["test_id"], "origin": Origin.HISTORICAL.value,
            })
            meas_no += 1
            rows["eol_measurements"].append({
                "meas_id": ids.make_id("meas_id", meas_no), "test_id": test_id, "test_item": OUTPUT_VOLTAGE_ITEM,
                "value": value, "lower_limit": model.ov_lower, "upper_limit": model.ov_upper,
                "result": result.value,
            })

    # --- reference sample checks ------------------------------------------------------------
    ref_model = cfg.model("MODEL-A")
    tol_volts = round(cfg.reference_tolerance_z * ref_model.half_width, 6)
    check_no = 0
    for k in range(8):
        ts_dt = start + timedelta(hours=k, minutes=5)
        if window_ts is not None and ts_dt >= window_ts:
            continue
        for tester in TESTERS:
            ts = _ts(ts_dt)
            measured = round(
                ref_model.midpoint
                + ref_model.half_width * (bias[tester].at(ts) + float(rng.normal(0.0, cfg.reference_noise_sd))),
                4,
            )
            dev = round(measured - ref_model.midpoint, 4)
            check_no += 1
            rows["reference_sample_checks"].append({
                "check_id": ids.make_id("check_id", check_no), "tester_id": tester, "ts": ts,
                "sample_id": REF_SAMPLE_IDS[tester], "test_item": OUTPUT_VOLTAGE_ITEM,
                "nominal": ref_model.midpoint, "measured": measured, "deviation": dev,
                "result": "PASS" if abs(dev) <= tol_volts else "FAIL", "origin": Origin.HISTORICAL.value,
            })

    # --- equipment events and process changes -------------------------------------------
    ev_no = 0
    for e in cfg.equipment:
        ev_no += 1
        rows["equipment_events"].append({
            "event_id": ids.make_id("event_id", ev_no), "equipment_id": e.equipment_id, "ts": _ts(start),
            "event_type": EventType.STATE.value, "severity": "info",
            "details_json": json.dumps({"state": "RUNNING", "mode": "production"}, sort_keys=True),
        })
    if sc.mix_shift:
        ev_no += 1
        rows["equipment_events"].append({
            "event_id": ids.make_id("event_id", ev_no), "equipment_id": sc.mix_shift.unavailable_tester,
            "ts": _ts(start + timedelta(seconds=sc.mix_shift.maintenance_offset_s)),
            "event_type": EventType.MAINTENANCE.value, "severity": "info",
            "details_json": json.dumps(
                {"action": "reference sample sent to external calibration lab",
                 "sample_id": REF_SAMPLE_IDS[sc.mix_shift.unavailable_tester]},
                sort_keys=True,
            ),
        })
    if sc.program_change and change_ts is not None:
        pc = sc.program_change
        rows["process_changes"].append({
            "change_id": ids.make_id("change_id", 1), "equipment_id": pc.equipment_id, "ts": _ts(change_ts),
            "change_type": "program_version", "old_value": pc.old_version, "new_value": pc.new_version,
            "changed_by": pc.changed_by,
        })

    # --- world state ------------------------------------------------------------------------
    approved = {
        eq: StationConfig(recipe_version=cfg.initial_recipe[eq], program_version=cfg.initial_program[eq])
        for eq in ("ST-10", "ST-20", "ST-30")
    }
    actual = dict(approved)
    if sc.program_change:
        actual[sc.program_change.equipment_id] = StationConfig(
            recipe_version=cfg.initial_recipe[sc.program_change.equipment_id],
            program_version=sc.program_change.new_version,
        )
    refs = {}
    for tester in TESTERS:
        unavailable = sc.mix_shift is not None and sc.mix_shift.unavailable_tester == tester
        refs[tester] = ReferenceSample(
            availability=ReferenceAvailability.UNAVAILABLE if unavailable else ReferenceAvailability.AVAILABLE,
            reason=sc.mix_shift.unavailable_reason if unavailable else None,
            tolerance=tol_volts, sample_id=REF_SAMPLE_IDS[tester], test_item=OUTPUT_VOLTAGE_ITEM,
            nominal=ref_model.midpoint, half_width=ref_model.half_width,
        )
    ws = WorldState(
        dataset_id=sc.dataset_id, seed=seed, measurement_noise_sd=cfg.measurement_noise_sd,
        reference_noise_sd=cfg.reference_noise_sd,
        model_scales={m.model_id: ModelScale(midpoint=m.midpoint, half_width=m.half_width) for m in cfg.models},
        true_values=true_values, tester_bias=bias, reference_samples=refs,
        approved_config=approved, actual_config=actual,
    )
    validate_rows(rows, cfg)
    return GeneratedDataset(sc.dataset_id, sc, seed, cfg, rows, ws)


def validate_rows(rows: Rows, cfg: FactoryConfig) -> None:
    """Requirement 6 consistency checks; raises GenerationError naming the record."""
    start, end = parse_ts(cfg.shift_start), parse_ts(cfg.shift_end)

    def in_shift(ts: str, rid: str) -> None:
        t = parse_ts(ts)
        if not (start <= t <= end):
            raise GenerationError(f"timestamp {ts} of {rid} outside shift window")

    orders = {o["order_id"]: o for o in rows["production_orders"]}
    for o in rows["production_orders"]:
        in_shift(o["start_ts"], o["order_id"])
    steps_by_sn: dict[str, dict[str, dict]] = {}
    for s in rows["process_steps"]:
        steps_by_sn.setdefault(s["sn"], {})[s["station_id"]] = s
        in_shift(s["start_ts"], s["step_id"])
        in_shift(s["end_ts"], s["step_id"])
        if parse_ts(s["end_ts"]) <= parse_ts(s["start_ts"]):
            raise GenerationError(f"step {s['step_id']} ends before it starts")
    for p in rows["products"]:
        in_shift(p["created_ts"], p["sn"])
        if parse_ts(orders[p["order_id"]]["start_ts"]) > parse_ts(p["created_ts"]):
            raise GenerationError(f"order {p['order_id']} starts after product {p['sn']}")
        st = steps_by_sn[p["sn"]]
        if parse_ts(p["created_ts"]) > parse_ts(st["ST-10"]["start_ts"]):
            raise GenerationError(f"product {p['sn']} created after ST-10 start")
        for a, b in (("ST-10", "ST-20"), ("ST-20", "ST-30")):
            if parse_ts(st[b]["start_ts"]) < parse_ts(st[a]["end_ts"]):
                raise GenerationError(f"route order violated for {p['sn']} at {b}")
    steps = {s["step_id"]: s for s in rows["process_steps"]}
    for m in rows["process_measurements"]:
        s = steps[m["step_id"]]
        if not (parse_ts(s["start_ts"]) <= parse_ts(m["ts"]) <= parse_ts(s["end_ts"])):
            raise GenerationError(f"measurement {m['meas_id']} outside its step")
    tests = {t["test_id"]: t for t in rows["eol_tests"]}
    for t in rows["eol_tests"]:
        in_shift(t["ts"], t["test_id"])
        if t["is_retest"]:
            if parse_ts(t["ts"]) <= parse_ts(tests[t["retest_of"]]["ts"]):
                raise GenerationError(f"retest {t['test_id']} not after original test")
        elif parse_ts(t["ts"]) < parse_ts(steps_by_sn[t["sn"]]["ST-30"]["end_ts"]):
            raise GenerationError(f"EOL test {t['test_id']} before ST-30 end")
    for tbl, col in (("equipment_events", "event_id"), ("process_changes", "change_id"),
                     ("reference_sample_checks", "check_id")):
        for r in rows[tbl]:
            in_shift(r["ts"], r[col])
    for mrow in rows["eol_measurements"]:
        cls = classify(mrow["value"], mrow["lower_limit"], mrow["upper_limit"])
        if cls.value != mrow["result"] or tests[mrow["test_id"]]["result"] != mrow["result"]:
            raise GenerationError(f"EOL measurement {mrow['meas_id']} result inconsistent")
