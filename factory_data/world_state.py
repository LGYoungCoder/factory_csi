"""Hidden physical truth of a dataset (world_state.json).

Read only by the simulator and by ``industrial_mcp.verification``. Never returned raw by any tool.
Bias values are in normalized units (fraction of the product model's tolerance half-width).
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from factory_data.enums import ReferenceAvailability
from factory_data.timeutil import hours_between, is_ts, parse_ts

TESTERS = ("EOL-A", "EOL-B")
STATION_EQUIPMENT = ("ST-10", "ST-20", "ST-30")


class WorldStateError(ValueError):
    """World state file missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TesterBias(_Strict):
    base: float
    onset: str | None = None
    slope_per_hour: float = 0.0

    @field_validator("onset")
    @classmethod
    def _onset_ts(cls, v: str | None) -> str | None:
        if v is not None and not is_ts(v):
            raise ValueError(f"onset must be a UTC timestamp YYYY-MM-DDTHH:MM:SSZ, got {v!r}")
        return v

    def at(self, ts: str) -> float:
        parse_ts(ts)
        if self.onset is None or parse_ts(ts) < parse_ts(self.onset):
            return self.base
        return self.base + self.slope_per_hour * hours_between(self.onset, ts)


class ReferenceSample(_Strict):
    availability: ReferenceAvailability
    reason: str | None = Field(default=None, min_length=1, max_length=200)
    tolerance: float = Field(gt=0, description="max |deviation| in volts that counts as in tolerance")
    sample_id: str
    test_item: str
    nominal: float
    half_width: float = Field(gt=0, description="volts per normalized unit for this sample")

    @model_validator(mode="after")
    def _reason_rule(self) -> ReferenceSample:
        if (self.availability == ReferenceAvailability.UNAVAILABLE) != (self.reason is not None):
            raise ValueError("reason must be present if and only if availability is UNAVAILABLE")
        return self


class StationConfig(_Strict):
    recipe_version: str = Field(min_length=1)
    program_version: str = Field(min_length=1)


class ModelScale(_Strict):
    midpoint: float
    half_width: float = Field(gt=0)


class WorldState(_Strict):
    dataset_id: str
    seed: int = Field(ge=0, le=4_294_967_295)
    measurement_noise_sd: float = Field(gt=0)
    reference_noise_sd: float = Field(gt=0)
    model_scales: dict[str, ModelScale]
    true_values: dict[str, float]
    tester_bias: dict[str, TesterBias]
    reference_samples: dict[str, ReferenceSample]
    approved_config: dict[str, StationConfig]
    actual_config: dict[str, StationConfig]

    @model_validator(mode="after")
    def _keys(self) -> WorldState:
        for name, mapping, keys in (
            ("tester_bias", self.tester_bias, TESTERS),
            ("reference_samples", self.reference_samples, TESTERS),
            ("approved_config", self.approved_config, STATION_EQUIPMENT),
            ("actual_config", self.actual_config, STATION_EQUIPMENT),
        ):
            if tuple(sorted(mapping)) != keys:
                raise ValueError(f"{name} must have exactly the keys {list(keys)}")
        return self

    # --- lookups -------------------------------------------------------------
    def true_value(self, sn: str) -> float:
        if sn not in self.true_values:
            raise WorldStateError(f"no true value for SN {sn!r}")
        return self.true_values[sn]

    def bias_at(self, tester_id: str, ts: str) -> float:
        if tester_id not in self.tester_bias:
            raise WorldStateError(f"unknown EOL tester {tester_id!r}; expected one of {list(TESTERS)}")
        if not is_ts(ts):
            raise WorldStateError(f"invalid UTC timestamp {ts!r}")
        return self.tester_bias[tester_id].at(ts)

    def to_json(self) -> str:
        return self.model_dump_json(indent=1) + "\n"


def load_world_state(path: str | Path) -> WorldState:
    p = Path(path)
    if not p.is_file():
        raise WorldStateError(f"world state file not found: {p.name}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorldStateError(f"world state is not valid JSON: {exc}") from exc
    try:
        return WorldState.model_validate(data)
    except ValidationError as exc:
        paths = "; ".join(".".join(str(x) for x in e["loc"]) + f": {e['msg']}" for e in exc.errors())
        raise WorldStateError(f"world state validation failed: {paths}") from exc
