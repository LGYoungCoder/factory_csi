"""Shared vocabulary used by every module."""

from __future__ import annotations

from enum import StrEnum


class ConclusionCategory(StrEnum):
    TESTER_MEASUREMENT_DRIFT = "TESTER_MEASUREMENT_DRIFT"
    PROCESS_PARAMETER_DEVIATION = "PROCESS_PARAMETER_DEVIATION"
    PRODUCT_MIX_SHIFT = "PRODUCT_MIX_SHIFT"
    MATERIAL_LOT_ISSUE = "MATERIAL_LOT_ISSUE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


_SUPPORT_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}


class SupportLevel(StrEnum):
    """Ordered: LOW < MEDIUM < HIGH."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    @property
    def rank(self) -> int:
        return _SUPPORT_ORDER[self.value]

    def __lt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SupportLevel):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SupportLevel):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SupportLevel):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: object) -> bool:  # type: ignore[override]
        if not isinstance(other, SupportLevel):
            return NotImplemented
        return self.rank >= other.rank


class TestResult(StrEnum):
    __test__ = False  # not a pytest test class
    PASS = "PASS"
    FAIL = "FAIL"


class Origin(StrEnum):
    HISTORICAL = "historical"
    VERIFICATION = "verification"


class EventType(StrEnum):
    STATE = "state"
    ALARM = "alarm"
    MAINTENANCE = "maintenance"
    CALIBRATION = "calibration"


class Parameter(StrEnum):
    TORQUE = "torque"
    ANGLE = "angle"


class ReferenceAvailability(StrEnum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class VerificationType(StrEnum):
    CROSS_RETEST = "cross_retest"
    REFERENCE_SAMPLE_CHECK = "reference_sample_check"
    PROCESS_CONFIG_CHECK = "process_config_check"


class RetestOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReferenceOutcome(StrEnum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"
    UNAVAILABLE = "UNAVAILABLE"


class ConfigOutcome(StrEnum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"


#: failure_code written for an out-of-limit output_voltage measurement (historical and verification)
OUTPUT_VOLTAGE_FAILURE_CODE = "OV_OUT_OF_LIMIT"
OUTPUT_VOLTAGE_ITEM = "output_voltage"
