"""Factory_Config: the one fictional factory every dataset describes."""

from __future__ import annotations

from dataclasses import dataclass, field

from factory_data.timeutil import parse_ts


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    name: str
    code: str
    ov_lower: float
    ov_upper: float

    @property
    def midpoint(self) -> float:
        return round((self.ov_lower + self.ov_upper) / 2, 6)

    @property
    def half_width(self) -> float:
        return round((self.ov_upper - self.ov_lower) / 2, 6)


@dataclass(frozen=True)
class StationSpec:
    station_id: str
    name: str
    sequence: int


@dataclass(frozen=True)
class EquipmentSpec:
    equipment_id: str
    station_id: str
    name: str
    equipment_type: str


@dataclass(frozen=True)
class FactoryConfig:
    factory_name: str = "Factory Alpha"
    line_name: str = "Line A – Automotive Component Assembly Line"
    shift_start: str = "2026-11-02T06:00:00Z"
    shift_end: str = "2026-11-02T14:00:00Z"
    product_count: int = 800
    model_a_share: float = 0.70
    order_size: int = 50
    models: tuple[ModelSpec, ...] = (
        ModelSpec("MODEL-A", "Model A", "MA", 11.40, 12.60),
        ModelSpec("MODEL-B", "Model B", "MB", 4.75, 5.25),
    )
    stations: tuple[StationSpec, ...] = (
        StationSpec("ST-10", "Component Assembly", 10),
        StationSpec("ST-20", "Automatic Bolt Tightening", 20),
        StationSpec("ST-30", "Functional Assembly", 30),
        StationSpec("EOL", "End-of-Line Test", 40),
    )
    equipment: tuple[EquipmentSpec, ...] = (
        EquipmentSpec("ST-10", "ST-10", "Assembly Cell 10", "assembly_cell"),
        EquipmentSpec("ST-20", "ST-20", "Nutrunner Cell 20", "nutrunner"),
        EquipmentSpec("ST-30", "ST-30", "Functional Assembly Cell 30", "assembly_cell"),
        EquipmentSpec("EOL-A", "EOL", "EOL Tester A", "eol_tester"),
        EquipmentSpec("EOL-B", "EOL", "EOL Tester B", "eol_tester"),
    )
    initial_recipe: dict[str, str] = field(
        default_factory=lambda: {"ST-10": "R-10.4", "ST-20": "R-20.2", "ST-30": "R-30.1"}
    )
    initial_program: dict[str, str] = field(
        default_factory=lambda: {"ST-10": "P-10.1", "ST-20": "P-2.3", "ST-30": "P-30.2"}
    )
    # physics (normalized z units, see docs/architecture.md §3)
    nominal_angle: float = 90.0
    angle_sd: float = 2.0
    angle_coef: float = 0.05
    product_sd: float = 0.40
    measurement_noise_sd: float = 0.10
    reference_noise_sd: float = 0.05
    reference_tolerance_z: float = 0.25
    torque_nominal: float = 12.0

    def model(self, model_id: str) -> ModelSpec:
        for m in self.models:
            if m.model_id == model_id:
                return m
        raise ConfigError(f"unknown model {model_id!r}")

    def validate(self) -> None:
        if not isinstance(self.product_count, int) or isinstance(self.product_count, bool) or not (
            500 <= self.product_count <= 1000
        ):
            raise ConfigError(f"product_count must be an integer from 500 to 1000, got {self.product_count!r}")
        if not (0.65 <= self.model_a_share <= 0.75):
            raise ConfigError(f"model_a_share (model mix) must be within 65%..75%, got {self.model_a_share!r}")
        start, end = parse_ts(self.shift_start), parse_ts(self.shift_end)
        if end <= start:
            raise ConfigError(f"shift window invalid: end {self.shift_end} is not after start {self.shift_start}")
        if (end - start).total_seconds() != 8 * 3600:
            raise ConfigError("shift window must be exactly 8 hours")
        if {s.station_id for s in self.stations} != {"ST-10", "ST-20", "ST-30", "EOL"}:
            raise ConfigError("stations must be exactly ST-10, ST-20, ST-30 and EOL")
        eq = {e.equipment_id: e.station_id for e in self.equipment}
        expected = {"ST-10": "ST-10", "ST-20": "ST-20", "ST-30": "ST-30", "EOL-A": "EOL", "EOL-B": "EOL"}
        if eq != expected or len(self.equipment) != 5:
            raise ConfigError(f"equipment must be exactly {expected}")
        if {m.model_id for m in self.models} != {"MODEL-A", "MODEL-B"}:
            raise ConfigError("product models must be exactly MODEL-A and MODEL-B")
        for m in self.models:
            if not m.ov_lower < m.ov_upper:
                raise ConfigError(f"model {m.model_id}: output_voltage lower limit must be below upper limit")


DEFAULT_CONFIG = FactoryConfig()
