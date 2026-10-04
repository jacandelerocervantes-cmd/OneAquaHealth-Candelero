"""Period statistics, the change block, flags and the per-period view: the pure arithmetic of the comparison.

Constants are documented in ``docs/period_change.md``; every one can be overridden by the caller of ``compare_site`` and
``compare_country``.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from oah.indices.period_change.periods import Cell, ParameterContext, Period, month_text

# --- constants (documented in docs/period_change.md; every one can be overridden by the caller) ---------------------


MIN_SAMPLES_PER_PERIOD = 3  # quantified samples a period needs at one site (monthly sources)
MIN_AGGREGATES_PER_PERIOD = 1  # aggregate records a period needs for an annual-only source (each record already summarises many samples)
FEW_SITES_THRESHOLD = 5  # fewer paired sites than this carries the flag ``few-sites``
COMPARISON_DECIMALS = 6  # two means equal after rounding to this many decimals are ``no-change`` (a float-noise guard, not a tolerance)
VALUE_DECIMALS = 6  # decimals of the numbers in the output
PERCENT_DECIMALS = 4  # decimals of a relative percent in the output


INTERVAL_SCALE_UNITS = frozenset({"Cel", "pH"})  # a percent change of a Celsius or pH mean is not meaningful (flag only)


# --- rounding -------------------------------------------------------------------------------------------------------


def _out(value: float | None, decimals: int = VALUE_DECIMALS) -> float | None:
    """A number for output: rounded, never ``-0.0``, None stays None."""
    if value is None:
        return None
    rounded = round(value, decimals)
    return 0.0 if rounded == 0 else rounded


def _same(a: float, b: float, decimals: int) -> bool:
    return round(a, decimals) == round(b, decimals)


# --- period statistics ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PeriodStats:
    months_in_period: int
    n_samples: int
    n_months_with_data: int
    mean: float | None
    low: float | None
    high: float | None
    n_below_loq: int
    n_lower_reliability: int
    has_records: bool  # any record at all (quantified or below the limit of quantification) inside the period
    n_partial_overlap: int  # annual-only cells that cross the period edge and are therefore left out
    months_mask: int = 0  # bit ``m - period.first`` set for every month ``m`` with a quantified value (the union over sites is an OR)

    @property
    def below_loq_share(self) -> float | None:
        total = self.n_samples + self.n_below_loq
        return self.n_below_loq / total if total else None


@dataclass(frozen=True)
class WindowAggregate:
    """What ONE site holds inside ONE period, already summed by the data layer (the input of the aggregated country path).

    ``total`` is the exactly rounded sum of the quantified values (``math.fsum`` of the converted monthly sums), ``low``
    and ``high`` the extremes of the months that hold a quantified value, ``months`` the bitmask of those months
    relative to ``period.first``. Built from the same rows as the cells, it gives the same ``PeriodStats``.
    """

    n: int
    n_below_loq: int
    n_lower_reliability: int
    low: float | None
    high: float | None
    total: float
    months: int


def _span_bits(first: int, last: int, origin: int) -> int:
    """The bits of the months ``first`` to ``last`` (month positions) relative to ``origin``."""
    return ((1 << (last - first + 1)) - 1) << (first - origin)


def _stats(
    period: Period, n: int, below: int, unreliable: int, partial: int, total: float, low: float | None, high: float | None,
    months: int, has_records: bool,
) -> PeriodStats:
    mean = total / n if n else None
    if mean is not None and low is not None and high is not None:
        mean = min(max(mean, low), high)  # float rounding must never put the mean outside [min, max]
    return PeriodStats(period.months, n, months.bit_count(), mean, low, high, below, unreliable, has_records, partial, months)


def period_stats(cells: Iterable[Cell], period: Period) -> PeriodStats:
    """Statistics of the cells that lie INSIDE the period (a cell that crosses its edge is left out and counted)."""
    n = below = unreliable = partial = 0
    totals: list[float] = []
    low: float | None = None
    high: float | None = None
    months = 0
    has_records = False
    for cell in cells:
        if not period.intersects(cell.first_month, cell.last_month):
            continue
        if not period.contains(cell.first_month, cell.last_month):
            partial += 1
            continue
        if cell.n + cell.n_below_loq > 0:
            has_records = True
        n += cell.n
        below += cell.n_below_loq
        unreliable += cell.n_lower_reliability
        if cell.n > 0:
            totals.append(cell.total)
            months |= _span_bits(cell.first_month, cell.last_month, period.first)
            if cell.low is not None:
                low = cell.low if low is None else min(low, cell.low)
            if cell.high is not None:
                high = cell.high if high is None else max(high, cell.high)
    return _stats(period, n, below, unreliable, partial, math.fsum(totals), low, high, months, has_records)


def aggregate_stats(aggregate: WindowAggregate | None, period: Period) -> PeriodStats:
    """The statistics of one site in one period from its ``WindowAggregate`` (None: the site has no row in the period)."""
    if aggregate is None:
        return _stats(period, 0, 0, 0, 0, 0.0, None, None, 0, False)
    return _stats(
        period, aggregate.n, aggregate.n_below_loq, aggregate.n_lower_reliability, 0, aggregate.total, aggregate.low,
        aggregate.high, aggregate.months, aggregate.n + aggregate.n_below_loq > 0,
    )


# --- the change -------------------------------------------------------------------------------------------------------


def change_block(
    mean_a: float | None, mean_b: float | None, unit: str | None, decimals: int = COMPARISON_DECIMALS
) -> dict[str, Any]:
    """Absolute and relative change from ``mean_a`` to ``mean_b`` and the direction (rule in the module docstring)."""
    block: dict[str, Any] = {
        "absolute": None, "relative_percent": None, "relative_percent_note": None, "direction": None,
    }
    if mean_a is None or mean_b is None:
        block["relative_percent_note"] = "baseline-missing" if mean_a is None else "comparison-missing"
        return block
    difference = mean_b - mean_a
    block["absolute"] = _out(difference)
    block["direction"] = "no-change" if _same(mean_a, mean_b, decimals) else ("increased" if mean_b > mean_a else "decreased")
    if round(mean_a, decimals) == 0:
        block["relative_percent_note"] = "baseline-zero"
    else:
        block["relative_percent"] = _out(100.0 * difference / abs(mean_a), PERCENT_DECIMALS)
        if unit in INTERVAL_SCALE_UNITS:
            block["relative_percent_note"] = "interval-scale"
    return block


# --- flags ------------------------------------------------------------------------------------------------------------


def _data_range_view(data_range: tuple[int, int] | None) -> dict[str, str | None]:
    if data_range is None:
        return {"first": None, "last": None}
    return {"first": month_text(data_range[0]), "last": month_text(data_range[1])}


def _period_flags(
    stats: PeriodStats, period: Period, data_range: tuple[int, int] | None, annual_only: bool
) -> list[str]:
    flags: list[str] = []
    if data_range is None or period.last > data_range[1]:
        flags.append("period-outside-data")
    if data_range is not None and period.last < data_range[0]:
        flags.append("period-before-data")
    if 0 < stats.n_months_with_data < stats.months_in_period:
        flags.append("partial-period")
    if stats.n_below_loq > 0:
        flags.append("below-loq-excluded-bias-upward")
    if annual_only:
        flags.append("annual-only")
    if stats.n_partial_overlap:
        flags.append("records-crossing-period-edge-excluded")
    return flags


def _period_view(
    stats: PeriodStats, period: Period, parameter: ParameterContext, minimum: int,
    data_range: tuple[int, int] | None,
) -> dict[str, Any]:
    return {
        "start": period.start,
        "end": period.end,
        "months_in_period": stats.months_in_period,
        "n_samples": stats.n_samples,
        "n_unit": parameter.n_unit,
        "n_months_with_data": stats.n_months_with_data,
        "mean": _out(stats.mean),
        "min": _out(stats.low),
        "max": _out(stats.high),
        "n_below_loq": stats.n_below_loq,
        "below_loq_share": _out(stats.below_loq_share),
        "n_lower_reliability": stats.n_lower_reliability,
        "n_records_excluded_crossing_period_edge": stats.n_partial_overlap,
        "meets_minimum_samples": stats.n_samples >= minimum,
        "flags": _period_flags(stats, period, data_range, parameter.resolution == "annual-only"),
        "assessment": None,
    }


def _minimum(parameter: ParameterContext, override: int | None) -> int:
    if override is not None:
        return max(1, int(override))
    return MIN_AGGREGATES_PER_PERIOD if parameter.resolution == "annual-only" else MIN_SAMPLES_PER_PERIOD


def _union_flags(*groups: Iterable[str]) -> list[str]:
    return sorted({flag for group in groups for flag in group})


def _top_flags(
    periods: Sequence[Mapping[str, Any]], period_a: Period, period_b: Period, change: Mapping[str, Any],
    data_range: tuple[int, int] | None,
) -> list[str]:
    flags = set(_union_flags(*(p["flags"] for p in periods)))
    if data_range is None:
        flags.add("no-data-for-scope")
    if period_a.intersects(period_b.first, period_b.last):
        flags.add("periods-overlap")
    if change["relative_percent_note"] in ("baseline-zero", "baseline-missing", "comparison-missing"):
        flags.add("relative-change-undefined")
    if change["relative_percent_note"] == "interval-scale":
        flags.add("relative-change-interval-scale")
    return sorted(flags)
