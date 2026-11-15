"""Normalized measurement model shared by the generator and the verification engine.

z = (value - midpoint) / half_width; product limits are z = +-1.
No-flip rule: measurement noise never changes the PASS/FAIL class of ``true_z + bias``.
"""

from __future__ import annotations

from collections.abc import Callable

from factory_data.enums import TestResult

VOLTAGE_DECIMALS = 4
MAX_REDRAWS = 20


def classify(value: float, lower: float, upper: float) -> TestResult:
    return TestResult.PASS if lower <= value <= upper else TestResult.FAIL


def to_volts(z: float, midpoint: float, half_width: float) -> float:
    return midpoint + half_width * z


def measure_no_flip(
    true_z: float,
    bias: float,
    draw_noise: Callable[[], float],
    midpoint: float,
    half_width: float,
) -> tuple[float, TestResult]:
    """Return (rounded measured volts, result) whose class equals the class of true_z + bias."""
    lower, upper = midpoint - half_width, midpoint + half_width
    target = classify(round(to_volts(true_z + bias, midpoint, half_width), 9), lower, upper)
    for _ in range(MAX_REDRAWS):
        value = round(to_volts(true_z + bias + draw_noise(), midpoint, half_width), VOLTAGE_DECIMALS)
        if classify(value, lower, upper) == target:
            return value, target
    value = round(to_volts(true_z + bias, midpoint, half_width), VOLTAGE_DECIMALS)
    # rounding can still flip a value sitting exactly on a limit; nudge inward/outward
    if classify(value, lower, upper) != target:
        step = 10 ** (-VOLTAGE_DECIMALS)
        if target == TestResult.PASS:
            value = min(max(value, lower), upper)
        else:
            value = upper + step if value >= midpoint else lower - step
        value = round(value, VOLTAGE_DECIMALS)
    return value, target
