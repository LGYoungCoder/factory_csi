"""Deterministic statistics helpers (SciPy). Rounded outputs for reproducibility."""

from __future__ import annotations

import math

import numpy as np
from scipy import stats


def rate(fails: int, n: int) -> float | None:
    return round(fails / n, 4) if n else None


def fisher_p(f1: int, n1: int, f2: int, n2: int) -> float:
    if n1 == 0 or n2 == 0:
        return 1.0
    return float(stats.fisher_exact([[f1, n1 - f1], [f2, n2 - f2]]).pvalue)


def ks_p(a: list[float], b: list[float]) -> float | None:
    if len(a) < 5 or len(b) < 5:
        return None
    return float(stats.ks_2samp(a, b).pvalue)


def mwu_p(a: list[float], b: list[float]) -> float | None:
    if len(a) < 5 or len(b) < 5:
        return None
    return float(stats.mannwhitneyu(a, b, alternative="two-sided").pvalue)


def ols(x: list[float], y: list[float]) -> tuple[float | None, float | None]:
    if len(x) < 3 or len(set(x)) < 2:
        return None, None
    r = stats.linregress(x, y)
    p = float(r.pvalue) if not math.isnan(r.pvalue) else None
    return float(r.slope), p


def chi2_p(table: list[list[int]]) -> float | None:
    arr = np.array(table)
    if arr.sum() == 0 or (arr.sum(axis=0) == 0).any() or (arr.sum(axis=1) == 0).any():
        return None
    if arr.shape == (2, 2):
        return float(stats.fisher_exact(arr).pvalue)
    return float(stats.chi2_contingency(arr).pvalue)


def fmt_p(p: float | None) -> str:
    if p is None:
        return "n/a"
    return f"{p:.2e}" if p < 0.001 else f"{p:.3f}"


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def sig4(x: float | None) -> float | None:
    return None if x is None else float(f"{x:.4g}")
