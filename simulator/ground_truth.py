"""Answer key (ground_truth.json). Only tests, evaluation and simulator.writer may import this module."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from factory_data.enums import (
    ConclusionCategory,
    ConfigOutcome,
    ReferenceOutcome,
    RetestOutcome,
    SupportLevel,
)
from factory_data.timeutil import format_ts, is_ts, parse_ts
from simulator.generator import GeneratedDataset


class GroundTruthError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AcceptableConclusion(_Strict):
    category: ConclusionCategory
    max_support: SupportLevel


class AnomalyWindow(_Strict):
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _ts(cls, v: str) -> str:
        if not is_ts(v):
            raise ValueError(f"not a UTC timestamp: {v!r}")
        return v

    @model_validator(mode="after")
    def _order(self) -> AnomalyWindow:
        if parse_ts(self.start) >= parse_ts(self.end):
            raise ValueError("window start must be before end")
        return self


class ExpectedOutcomes(_Strict):
    cross_retest: RetestOutcome
    reference_sample_check: ReferenceOutcome
    config_check: ConfigOutcome
    cross_retest_target_tester: str
    reference_check_tester: str
    config_check_equipment: str


class GroundTruth(_Strict):
    dataset_id: str
    expected_anomaly_equipment: str | None
    expected_flagged_testers: list[str]
    anomaly_window: AnomalyWindow | None
    expected_conclusion: ConclusionCategory
    acceptable_conclusions: list[AcceptableConclusion] = Field(min_length=1)
    affected_sns: list[str]
    key_signals: list[str]
    expected_verification_outcomes: ExpectedOutcomes

    @model_validator(mode="after")
    def _consistency(self) -> GroundTruth:
        cats = [a.category for a in self.acceptable_conclusions]
        if len(cats) != len(set(cats)):
            raise ValueError("each category may appear at most once in acceptable_conclusions")
        if self.expected_conclusion not in cats:
            raise ValueError("expected_conclusion must be in acceptable_conclusions")
        if len(set(self.affected_sns)) != len(self.affected_sns):
            raise ValueError("affected_sns contains duplicates")
        return self

    def is_acceptable(self, category: str, support: str) -> bool:
        for a in self.acceptable_conclusions:
            if a.category == category:
                return SupportLevel(support) <= a.max_support
        return False

    def to_json(self) -> str:
        return self.model_dump_json(indent=1) + "\n"


def load_ground_truth(path: str | Path) -> GroundTruth:
    p = Path(path)
    try:
        return GroundTruth.model_validate(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        raise GroundTruthError(f"invalid ground truth {p.name}: {exc}") from exc


def build_ground_truth(ds: GeneratedDataset) -> GroundTruth:
    sc, rows, ws, cfg = ds.scenario, ds.rows, ds.world_state, ds.config
    first = [t for t in rows["eol_tests"] if not t["is_retest"]]
    limits = {m.model_id: (m.ov_lower, m.ov_upper) for m in cfg.models}

    def inside(sn: str, model_id: str) -> bool:
        lo, hi = limits[model_id]
        return lo <= ws.true_values[sn] <= hi

    acc = AcceptableConclusion
    C = ConclusionCategory
    S = SupportLevel
    if sc.drift:
        onset = ws.tester_bias[sc.drift.tester_id].onset
        assert onset is not None
        affected = sorted(
            t["sn"] for t in first
            if t["tester_id"] == sc.drift.tester_id and t["result"] == "FAIL"
            and parse_ts(t["ts"]) >= parse_ts(onset) and inside(t["sn"], t["model_id"])
        )
        return GroundTruth(
            dataset_id=ds.dataset_id, expected_anomaly_equipment=sc.drift.tester_id,
            expected_flagged_testers=[sc.drift.tester_id],
            anomaly_window=AnomalyWindow(start=onset, end=cfg.shift_end),
            expected_conclusion=C.TESTER_MEASUREMENT_DRIFT,
            acceptable_conclusions=[acc(category=C.TESTER_MEASUREMENT_DRIFT, max_support=S.HIGH)],
            affected_sns=affected,
            key_signals=[
                f"{sc.drift.tester_id} FAIL rate rises after {onset} while EOL-A stays normal",
                f"{sc.drift.tester_id} reference sample deviation grows over time and leaves tolerance",
                f"{sc.drift.tester_id} failures pass when retested on EOL-A",
                "ST-20 process parameters unchanged",
            ],
            expected_verification_outcomes=ExpectedOutcomes(
                cross_retest=RetestOutcome.PASS, reference_sample_check=ReferenceOutcome.OUT_OF_TOLERANCE,
                config_check=ConfigOutcome.MATCH, cross_retest_target_tester="EOL-A",
                reference_check_tester=sc.drift.tester_id, config_check_equipment="ST-20",
            ),
        )
    if sc.program_change:
        pc = sc.program_change
        new_sns = {m["sn"] for m in rows["process_measurements"] if m["program_version"] == pc.new_version}
        change = rows["process_changes"][0]["ts"]
        return GroundTruth(
            dataset_id=ds.dataset_id, expected_anomaly_equipment=pc.equipment_id,
            expected_flagged_testers=["EOL-A", "EOL-B"],
            anomaly_window=AnomalyWindow(start=change, end=cfg.shift_end),
            expected_conclusion=C.PROCESS_PARAMETER_DEVIATION,
            acceptable_conclusions=[acc(category=C.PROCESS_PARAMETER_DEVIATION, max_support=S.HIGH)],
            affected_sns=sorted(new_sns),
            key_signals=[
                f"{pc.equipment_id} program change {pc.old_version} -> {pc.new_version} at {change}",
                f"{pc.equipment_id} tightening angle shift after the change",
                "both EOL testers show elevated FAIL rates",
                "reference samples within tolerance",
            ],
            expected_verification_outcomes=ExpectedOutcomes(
                cross_retest=RetestOutcome.FAIL, reference_sample_check=ReferenceOutcome.WITHIN_TOLERANCE,
                config_check=ConfigOutcome.MISMATCH, cross_retest_target_tester="EOL-A",
                reference_check_tester="EOL-B", config_check_equipment=pc.equipment_id,
            ),
        )
    if sc.mix_shift:
        ms = sc.mix_shift
        window_start = format_ts(parse_ts(cfg.shift_start).replace() + _hours(ms.window_offset_h))
        affected = sorted(
            t["sn"] for t in first
            if t["model_id"] == "MODEL-B" and t["tester_id"] == "EOL-B" and t["result"] == "FAIL"
            and parse_ts(t["ts"]) >= parse_ts(window_start)
        )
        return GroundTruth(
            dataset_id=ds.dataset_id, expected_anomaly_equipment=None, expected_flagged_testers=["EOL-B"],
            anomaly_window=AnomalyWindow(start=window_start, end=cfg.shift_end),
            expected_conclusion=C.INSUFFICIENT_EVIDENCE,
            acceptable_conclusions=[
                acc(category=C.INSUFFICIENT_EVIDENCE, max_support=S.HIGH),
                acc(category=C.PRODUCT_MIX_SHIFT, max_support=S.MEDIUM),
                acc(category=C.TESTER_MEASUREMENT_DRIFT, max_support=S.LOW),
                acc(category=C.PROCESS_PARAMETER_DEVIATION, max_support=S.LOW),
            ],
            affected_sns=affected,
            key_signals=[
                "EOL-B FAIL rate increase in the anomaly window",
                "Model B share increase in the anomaly window",
                "no reference sample checks in the anomaly window",
            ],
            expected_verification_outcomes=ExpectedOutcomes(
                cross_retest=RetestOutcome.FAIL, reference_sample_check=ReferenceOutcome.UNAVAILABLE,
                config_check=ConfigOutcome.MATCH, cross_retest_target_tester="EOL-A",
                reference_check_tester=ms.unavailable_tester, config_check_equipment="ST-20",
            ),
        )
    return GroundTruth(
        dataset_id=ds.dataset_id, expected_anomaly_equipment=None, expected_flagged_testers=[],
        anomaly_window=None, expected_conclusion=C.INSUFFICIENT_EVIDENCE,
        acceptable_conclusions=[acc(category=C.INSUFFICIENT_EVIDENCE, max_support=S.HIGH)],
        affected_sns=[], key_signals=[],
        expected_verification_outcomes=ExpectedOutcomes(
            cross_retest=RetestOutcome.FAIL, reference_sample_check=ReferenceOutcome.WITHIN_TOLERANCE,
            config_check=ConfigOutcome.MATCH, cross_retest_target_tester="EOL-A",
            reference_check_tester="EOL-B", config_check_equipment="ST-20",
        ),
    )


def _hours(h: float):  # noqa: ANN202
    from datetime import timedelta

    return timedelta(hours=h)
