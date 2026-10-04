"""Kaplan-Meier summary statistics for left-censored (non-detect) concentration data.

Environmental non-detects are LEFT-censored (the true value is somewhere below a detection limit).
Kaplan-Meier handles right-censoring, so the data are "flipped": y = M - x with M the largest
observation, which turns "x < DL" into "y > M - DL" (right-censored). Statistics are computed on y
and mapped back. Nothing here imputes individual values: results are population summaries.

Convention (documented in docs/math_registry.md): if the smallest observation is a non-detect, the
largest flipped time is censored and the survival curve never reaches zero; it is then treated as
a detection at its detection limit, so the estimate is defined. Consequence: with a single
detection limit and non-detects below every detect, the KM mean equals substitution by that limit
(biased upward). The KM median is not affected by that convention when fewer than half of the
observations are censored.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

_TOLERANCE = 1e-12


@dataclass(frozen=True)
class CensoredSummary:
    n: int
    n_censored: int
    censored_fraction: float
    mean: float
    median: float
    smallest_treated_as_detect: bool


def kaplan_meier_left_censored(values: Sequence[float], censored: Sequence[bool]) -> CensoredSummary:
    """Mean and median of left-censored data by Kaplan-Meier on flipped values.

    ``values[i]`` is the measurement, or the detection limit when ``censored[i]`` is True.
    Requires at least one detected (uncensored) value; NaN, infinite and boolean values are rejected.
    """
    _validate(values, censored)

    top = float(max(values))
    flipped = [top - float(v) for v in values]
    events = [not c for c in censored]
    y_max = max(flipped)
    treated = False
    for i, y in enumerate(flipped):
        if y == y_max and not events[i]:
            events[i] = True
            treated = True

    order = sorted(range(len(flipped)), key=lambda i: flipped[i])
    times = [flipped[i] for i in order]
    is_event = [events[i] for i in order]

    steps: list[tuple[float, float]] = []  # (event time, survival just after it)
    survival = 1.0
    index, n = 0, len(times)
    while index < n:
        t = times[index]
        j = index
        deaths = 0
        while j < n and times[j] == t:
            deaths += is_event[j]
            j += 1
        if deaths:
            survival *= 1.0 - deaths / (n - index)
            steps.append((t, survival))
        index = j

    area, previous_t, previous_s = 0.0, 0.0, 1.0
    for t, s in steps:
        area += previous_s * (t - previous_t)
        previous_t, previous_s = t, s
    median_y = _median(steps)

    n_censored = sum(censored)
    return CensoredSummary(n, n_censored, n_censored / n, top - area, top - median_y, treated)


def _median(steps: list[tuple[float, float]]) -> float:
    for position, (t, s) in enumerate(steps):
        if s <= 0.5 + _TOLERANCE:
            if abs(s - 0.5) <= _TOLERANCE and position + 1 < len(steps):
                return (t + steps[position + 1][0]) / 2.0
            return t
    return steps[-1][0]


def ros_left_censored(values: Sequence[float], censored: Sequence[bool]) -> CensoredSummary:
    """Mean and median of left-censored data by regression on order statistics (log-normal).

    Detected values are regressed as ln(value) = a + b * z(plotting position); non-detects receive
    model-based values from the fitted line and are pooled with the detects for the summary.
    Plotting positions for multiple detection limits follow the Helsel-Cohn exceedance
    construction (see docs/math_registry.md). The imputed values are model output, never
    measurements, and are not returned. Requires at least 3 detected, strictly positive values
    with at least 2 distinct values (a log-normal line cannot be fitted otherwise).
    """
    import numpy as np
    from statistics import NormalDist

    _validate(values, censored)
    detects = sorted(float(v) for v, c in zip(values, censored) if not c)
    if len(detects) < 3 or len(set(detects)) < 2 or detects[0] <= 0:
        raise ValueError("ROS needs at least 3 detected, positive values with 2 distinct values.")
    limits = sorted({float(v) for v, c in zip(values, censored) if c})
    nondetects = [float(v) for v, c in zip(values, censored) if c]
    k = len(limits)
    bounds = [-math.inf, *limits, math.inf]

    def interval(v: float) -> int:
        return max(j for j in range(k + 1) if bounds[j] <= v)

    detects_in = [[v for v in detects if interval(v) == j] for j in range(k + 1)]
    exceed = [1.0] + [0.0] * (k + 1)  # exceed[j] = P(X > limit_j); exceed[0] = 1, exceed[k + 1] = 0
    for j in range(k, 0, -1):
        a = len(detects_in[j])
        b = sum(v < limits[j - 1] for v in detects) + sum(d <= limits[j - 1] for d in nondetects)
        exceed[j] = exceed[j + 1] + a / (a + b) * (1.0 - exceed[j + 1])

    positions: list[float] = []
    for j in range(k + 1):
        a = len(detects_in[j])
        positions += [(1.0 - exceed[j]) + (exceed[j] - exceed[j + 1]) * r / (a + 1) for r in range(1, a + 1)]
    z = np.array([NormalDist().inv_cdf(p) for p in positions])
    slope, intercept = np.polyfit(z, np.log(np.array([v for j in range(k + 1) for v in detects_in[j]])), 1)

    imputed: list[float] = []
    for j, limit in enumerate(limits, start=1):
        count = sum(d == limit for d in nondetects)
        imputed += [math.exp(intercept + slope * NormalDist().inv_cdf((1.0 - exceed[j]) * r / (count + 1))) for r in range(1, count + 1)]
    pooled = np.array([*detects, *imputed])
    return CensoredSummary(len(values), len(nondetects), len(nondetects) / len(values), float(pooled.mean()), float(np.median(pooled)), False)


def _validate(values: Sequence[float], censored: Sequence[bool]) -> None:
    if len(values) != len(censored):
        raise ValueError("values and censored must have the same length.")
    if not values:
        raise ValueError("At least one observation is required.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise ValueError("values must be finite numbers.")
    if all(censored):
        raise ValueError("At least one detected (uncensored) value is required.")


HIGH_CENSORING_FRACTION = 0.5  # project convention, from the simulations in tests/unit/test_censored_stats.py
SMALL_SAMPLE_SIZE = 20  # project convention: at n=20 every method's RMSE is large (see math registry)


@dataclass(frozen=True)
class CensoredReport:
    """Recommended summary of left-censored data, with the role of each method made explicit."""

    n: int
    n_censored: int
    median: float  # Kaplan-Meier: assumption-free, unbiased in every simulated scenario
    median_method: str
    mean: float  # ROS when applicable, otherwise the Kaplan-Meier mean
    mean_method: str
    km_mean: float  # always reported: biased upward when the smallest values are censored
    warnings: tuple[str, ...]


def summarize_censored(values: Sequence[float], censored: Sequence[bool]) -> CensoredReport:
    """Median by Kaplan-Meier, mean by ROS (falling back to the KM mean), plus explicit warnings."""
    km = kaplan_meier_left_censored(values, censored)
    warnings: list[str] = []
    try:
        mean, mean_method = ros_left_censored(values, censored).mean, "ros-lognormal"
    except ValueError:
        mean, mean_method = km.mean, "kaplan-meier"
        warnings.append(
            "ros-not-applicable: fewer than 3 positive detects or fewer than 2 distinct detects; mean may be biased high."
        )
    if km.n_censored == 0:
        mean, mean_method, warnings = km.mean, "sample-mean", []
    if km.censored_fraction > HIGH_CENSORING_FRACTION:
        warnings.append(f"high-censoring: {km.censored_fraction:.0%} of observations are non-detects.")
    if km.n < SMALL_SAMPLE_SIZE:
        warnings.append(f"small-sample: n={km.n} < {SMALL_SAMPLE_SIZE}; estimates are highly uncertain.")
    if km.smallest_treated_as_detect:
        warnings.append("smallest-observation-censored: treated as detected at its limit for Kaplan-Meier.")
    return CensoredReport(km.n, km.n_censored, km.median, "kaplan-meier", mean, mean_method, km.mean, tuple(warnings))
