"""Acceleration + RVOL + price scoring.

Score = (Acceleration x w_accel) + (RVOL x w_rvol) + (|Price% change| x w_price)

Acceleration is a multi-window gate, not just a magnitude: a ticker only
gets a nonzero acceleration score if volume growth is sustained across the
window ratios, per the spec. A single spike does not pass.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccelerationResult:
    ratios: list[float]
    sustained: bool
    score: float  # geometric mean of ratios if sustained, else 0.0


def compute_acceleration(window_deltas: list[int]) -> AccelerationResult:
    """window_deltas: consecutive per-minute volume deltas, oldest first.

    Needs at least 4 values (W1..W4) to produce 3 ratios (W1->W2, W2->W3, W3->W4).
    """
    if len(window_deltas) < 4:
        return AccelerationResult(ratios=[], sustained=False, score=0.0)

    windows = window_deltas[-4:]
    ratios: list[float] = []
    for prev, curr in zip(windows, windows[1:]):
        if prev <= 0:
            # No baseline volume in the prior window -- can't form a meaningful
            # ratio; treat as not sustained rather than dividing by zero.
            return AccelerationResult(ratios=ratios, sustained=False, score=0.0)
        ratios.append(curr / prev)

    non_decreasing = all(ratios[i] >= ratios[i - 1] for i in range(1, len(ratios)))
    all_growing = all(r > 1.0 for r in ratios)
    sustained = non_decreasing or all_growing

    if not sustained:
        return AccelerationResult(ratios=ratios, sustained=False, score=0.0)

    product = 1.0
    for r in ratios:
        product *= r
    geo_mean = product ** (1 / len(ratios))
    return AccelerationResult(ratios=ratios, sustained=True, score=geo_mean)


def compute_score(
    acceleration_score: float,
    rvol: float,
    price_change_pct_abs: float,
    weight_acceleration: float,
    weight_rvol: float,
    weight_price: float,
) -> float:
    return (
        acceleration_score * weight_acceleration
        + rvol * weight_rvol
        + price_change_pct_abs * weight_price
    )
