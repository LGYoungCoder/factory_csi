"""Scenario modifiers as parameter sets applied by the one generator code path."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DriftSpec:
    tester_id: str = "EOL-B"
    onset_offset_h: float = 3.0
    slope_per_hour: float = 0.153


@dataclass(frozen=True)
class ProgramChangeSpec:
    equipment_id: str = "ST-20"
    offset_s: int = 4 * 3600 + 8 * 60  # 10:08 for the default shift
    old_version: str = "P-2.3"
    new_version: str = "P-2.4"
    angle_shift: float = 12.0
    angle_sd: float = 2.5
    changed_by: str = "process-eng-07"


@dataclass(frozen=True)
class MixShiftSpec:
    window_offset_h: float = 3.0
    model_b_share_before: float = 0.10
    model_b_share_within: float = 0.45
    route_b_to_eol_b: float = 0.85
    route_a_to_eol_b: float = 0.35
    product_sd_model_a: float = 0.386  # ≈1.5 % inherent defects
    product_sd_model_b: float = 0.767  # ≈20 % inherent defects
    unavailable_tester: str = "EOL-B"
    unavailable_reason: str = "out for calibration"
    maintenance_offset_s: int = 2 * 3600 + 55 * 60  # 08:55


@dataclass(frozen=True)
class ScenarioParams:
    key: str
    dataset_id: str
    drift: DriftSpec | None = None
    program_change: ProgramChangeSpec | None = None
    mix_shift: MixShiftSpec | None = None
    historical_retests: tuple[int, int] | None = None


SCENARIOS: dict[str, ScenarioParams] = {
    "baseline": ScenarioParams("baseline", "ds-00"),
    "a": ScenarioParams("a", "ds-01", drift=DriftSpec(), historical_retests=(3, 7)),
    "b": ScenarioParams("b", "ds-02", program_change=ProgramChangeSpec()),
    "c": ScenarioParams("c", "ds-03", mix_shift=MixShiftSpec()),
}


def scenario_for_key(key: str) -> ScenarioParams:
    if key not in SCENARIOS:
        raise ValueError(f"unknown scenario {key!r}; valid: {', '.join(SCENARIOS)}")
    return SCENARIOS[key]
