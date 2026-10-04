"""Period comparison of bathing-water SAMPLES (E. coli and intestinal enterococci), reusing ``oah.indices.period_change``.

The existing machinery does the work: ``Period`` (a range of calendar months, both ends included), ``compare_site`` and
``compare_country`` (n, mean = sum / n, min, max per period, coverage rules, flags, ``data_range``, the paired-site rule of
a country comparison, the change block with absolute and relative change and direction). Here the cells come from the
samples store (``store.month_cells``) and the parameter is declared MEASUREMENT ONLY, so:

* no limit exists: ``assess_mean`` returns the measurement-only basis and nothing is compared with a threshold, no
  ``crossed_limit`` is ever reported and no significance is claimed;
* only quantified values (kinds ``Q`` and ``C``) are in a statistic. Values flagged as below the limit of detection,
  missing or of an unrecognised status are counted apart per period and named in flags (the direction in which a
  detection-limit number censors the true value is not in the data, so no "bias" direction is claimed);
* besides the mean, each period reports the exact MEDIAN (the middle value, or the mean of the two middle values) of the
  quantified samples at one bathing water, and for a country the median of the per-bathing-water medians of the paired
  bathing waters; a change of the median is given beside the change of the mean.

Coverage is the existing rule: a period needs ``MIN_SAMPLES_PER_PERIOD`` quantified samples at one bathing water, a country
uses only the bathing waters that meet it in BOTH periods, and a period beyond the data is reported with ``data_range``
and never shifted. Bathing waters are sampled only during the bathing season, so periods that include months outside it
carry the flag ``partial-period`` (expected, see ``docs/bathing_samples_store.md``).
"""

from __future__ import annotations

import statistics
from typing import Any

from oah.bathing_samples import store
from oah.bathing_samples.constants import (
    INDICATOR_LABELS,
    INDICATORS,
    KIND_CONFIRMED,
    KIND_DETECTION,
    KIND_INVALID,
    KIND_MISSING,
    KIND_UNKNOWN,
    UNIT,
)
from oah.indices.period_change import (
    NO_LIMIT_REGIME,
    VALUE_DECIMALS,
    Cell,
    ParameterContext,
    Period,
    SiteContext,
    PeriodStats,
    WindowAggregate,
    aggregate_stats,
    change_block,
    compare_country_stats,
    compare_site,
    month_position,
    monthly_cell,
    period_stats,
)
from oah.indices.scope_guard import GUARD, ScopeTooLarge, file_signature
from oah.paths import bathing_samples_store_path

GROUP = "bathing-water-samples"
NOT_PAIRED_NOTE = "a bathing water is compared only when it has enough quantified samples in both periods"


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    rounded = round(value, VALUE_DECIMALS)
    return 0.0 if rounded == 0 else rounded


def _parameter(indicator: str) -> ParameterContext:
    return ParameterContext(
        name=INDICATOR_LABELS[indicator], unit=UNIT, group=GROUP, closed_name=None, measurement_only=True,
        resolution="monthly", source="real-eea-bathing-samples",
    )


def _data_range(scope: Any, key: str, indicator: str) -> tuple[int, int] | None:
    found = store.quantified_range(scope, key, indicator)
    if found is None:
        return None
    first, last = found
    return month_position(int(first[:4]), int(first[5:7])), month_position(int(last[:4]), int(last[5:7]))


def _cells(scope: Any, key: str, indicator: str, a: Period, b: Period) -> list[Cell]:
    return [
        monthly_cell(cell.bw_id, month_position(cell.year, cell.month), cell.n, float(cell.total), float(cell.low), float(cell.high))
        for cell in store.month_cells(scope, key, indicator, [(a.first, a.last), (b.first, b.last)])
    ]


def _kind_flags(counts: dict[str, int]) -> list[str]:
    flags = []
    if counts.get(KIND_DETECTION):
        flags.append("detection-limit-values-excluded")
    if counts.get(KIND_MISSING):
        flags.append("missing-values-excluded")
    if counts.get(KIND_UNKNOWN) or counts.get(KIND_INVALID):
        flags.append("unrecognised-status-values-excluded")
    if counts.get(KIND_CONFIRMED):
        flags.append("confirmed-high-values-included")
    return flags


def _kind_block(counts: dict[str, int]) -> dict[str, int]:
    return {
        "n_detection_limit": counts.get(KIND_DETECTION, 0),
        "n_missing": counts.get(KIND_MISSING, 0),
        "n_unrecognised": counts.get(KIND_UNKNOWN, 0) + counts.get(KIND_INVALID, 0),
        "n_confirmed_high": counts.get(KIND_CONFIRMED, 0),
    }


def _median(values: list[int]) -> float | None:
    return float(statistics.median(values)) if values else None


# --- one bathing water ------------------------------------------------------------------------------------------------


def _site_indicator(bw_id: str, country: str | None, indicator: str, a: Period, b: Period) -> dict[str, Any]:
    cells = _cells("site", bw_id, indicator, a, b)
    data_range = _data_range("site", bw_id, indicator)
    pure = compare_site(cells, _parameter(indicator), SiteContext(bw_id, country, NO_LIMIT_REGIME), a, b, data_range=data_range)
    periods: dict[str, dict[str, Any]] = {}
    medians: dict[str, float | None] = {}
    for key, period in (("a", a), ("b", b)):
        view = pure["periods"][key]
        values = store.window_values("site", bw_id, indicator, (period.first, period.last)).get(bw_id, [])
        counts = store.kind_counts("site", bw_id, indicator, (period.first, period.last))
        medians[key] = _median(values)
        flags = [flag for flag in view["flags"] if flag != "below-loq-excluded-bias-upward"] + _kind_flags(counts)
        periods[key] = {
            "start": view["start"], "end": view["end"], "months_in_period": view["months_in_period"],
            "n_samples": view["n_samples"], "n_months_with_data": view["n_months_with_data"],
            "mean": view["mean"], "median": _round(medians[key]), "min": view["min"], "max": view["max"],
            **_kind_block(counts), "meets_minimum_samples": view["meets_minimum_samples"], "flags": sorted(set(flags)),
        }
    top = sorted(
        {flag for flag in pure["flags"] if flag != "below-loq-excluded-bias-upward"}
        | {flag for item in periods.values() for flag in item["flags"]}
    )
    return {
        "indicator": indicator,
        "label": INDICATOR_LABELS[indicator],
        "unit": UNIT,
        "status": pure["status"],
        "min_samples_per_period": pure["min_samples_per_period"],
        "periods": periods,
        "change": pure["change"],
        "change_of_median": change_block(medians["a"], medians["b"], UNIT),
        "data_range": pure["data_range"],
        "flags": top,
    }


def site_change(bw_id: str, country: str | None, period_a: Period, period_b: Period) -> dict[str, Any]:
    """The comparison of one bathing water's samples between two periods, for both indicators."""
    return {
        "indicators": {name: _site_indicator(bw_id, country, name, period_a, period_b) for name in INDICATORS},
    }


# --- one country (paired bathing waters only) ---------------------------------------------------------------------------


def _window_aggregate(window: store.SampleWindow | None) -> WindowAggregate | None:
    if window is None:
        return None
    return WindowAggregate(window.n, 0, 0, float(window.low), float(window.high), float(window.total), window.months)


_TOO_LARGE = "This comparison is too large to run: it would read too many samples or take too long. Narrow the periods."


class _Scan:
    """What one indicator of a country comparison needs, per bathing water: its statistics and its median in each period."""

    def __init__(
        self, stats: dict[str, tuple[PeriodStats, PeriodStats]], medians: tuple[dict[str, float], dict[str, float]],
        counts: tuple[dict[str, int], dict[str, int]],
    ) -> None:
        self.stats, self.medians, self.counts = stats, medians, counts


def _scan_by_sql(country: str, indicator: str, a: Period, b: Period, kinds: dict[str, tuple[dict[str, int], ...]]) -> _Scan:
    """The default path: one pass over the partial index of the indicator (``store.country_window_aggregates``)."""
    try:
        found = store.country_window_aggregates(country, indicator, [(a.first, a.last), (b.first, b.last)])
    except store.RowCapExceeded:
        raise ScopeTooLarge(_TOO_LARGE) from None
    stats = {
        bw_id: (aggregate_stats(_window_aggregate(windows[0]), a), aggregate_stats(_window_aggregate(windows[1]), b))
        for bw_id, windows in found.items()
    }
    medians: tuple[dict[str, float], dict[str, float]] = (
        {bw_id: window.median for bw_id, windows in found.items() if (window := windows[0]) is not None},
        {bw_id: window.median for bw_id, windows in found.items() if (window := windows[1]) is not None},
    )
    counts = kinds[indicator]
    return _Scan(stats, medians, (counts[0], counts[1]))


def _scan_by_rows(country: str, indicator: str, a: Period, b: Period) -> _Scan:
    """The reference path of the parity tests: one cell per bathing water and month, every value read for the medians."""
    by_site: dict[str, list[Cell]] = {}
    for cell in _cells("country", country, indicator, a, b):
        by_site.setdefault(cell.site_id, []).append(cell)
    stats = {bw_id: (period_stats(cells, a), period_stats(cells, b)) for bw_id, cells in by_site.items()}
    medians = tuple(
        {bw_id: float(statistics.median(values)) for bw_id, values in store.window_values("country", country, indicator, (period.first, period.last)).items()}
        for period in (a, b)
    )
    counts = tuple(store.kind_counts("country", country, indicator, (period.first, period.last)) for period in (a, b))
    return _Scan(stats, (medians[0], medians[1]), (counts[0], counts[1]))


def _country_indicator(
    country: str, indicator: str, a: Period, b: Period, kinds: dict[str, tuple[dict[str, int], ...]] | None = None
) -> dict[str, Any]:
    scan = _scan_by_rows(country, indicator, a, b) if kinds is None else _scan_by_sql(country, indicator, a, b, kinds)
    stats_by_site = scan.stats
    sites = {bw_id: SiteContext(bw_id, country, NO_LIMIT_REGIME) for bw_id in stats_by_site}
    data_range = _data_range("country", country, indicator)
    parameter = _parameter(indicator)
    pure = compare_country_stats(stats_by_site, sites, parameter, country, a, b, data_range=data_range)
    minimum = pure["min_samples_per_period"]
    paired = [
        bw_id for bw_id, (stats_a, stats_b) in stats_by_site.items()
        if stats_a.n_samples >= minimum and stats_b.n_samples >= minimum
    ]
    periods: dict[str, dict[str, Any]] = {}
    site_medians: dict[str, dict[str, float]] = {}
    for index, (key, period) in enumerate((("a", a), ("b", b))):
        view = pure["periods"][key]
        medians_by_site = scan.medians[index]
        site_medians[key] = {bw_id: medians_by_site[bw_id] for bw_id in paired if bw_id in medians_by_site}
        counts = scan.counts[index]
        median_of_medians = _median_float(list(site_medians[key].values()))
        flags = [flag for flag in view["flags"] if flag != "below-loq-excluded-bias-upward"] + _kind_flags(counts)
        periods[key] = {
            "start": view["start"], "end": view["end"], "months_in_period": view["months_in_period"],
            "n_sites": view["n_sites"], "n_samples": view["n_samples"], "n_months_with_data": view["n_months_with_data"],
            "mean_of_site_means": view["mean_of_site_means"], "median_of_site_medians": _round(median_of_medians),
            **{f"{name}_all_sites": count for name, count in _kind_block(counts).items()},
            "flags": sorted(set(flags)),
        }
    medians_a = _median_float(list(site_medians["a"].values()))
    medians_b = _median_float(list(site_medians["b"].values()))
    flags = sorted(
        {flag for flag in pure["flags"] if flag != "below-loq-excluded-bias-upward"}
        | {flag for item in periods.values() for flag in item["flags"]}
    )
    return {
        "indicator": indicator,
        "label": INDICATOR_LABELS[indicator],
        "unit": UNIT,
        "status": pure["status"],
        "min_samples_per_period": minimum,
        "few_sites_threshold": pure["few_sites_threshold"],
        "n_sites_considered": pure["n_sites_considered"],
        "n_sites_paired": pure["n_sites_paired"],
        "n_sites_excluded": pure["n_sites_excluded"],
        "exclusion_reasons": pure["exclusion_reasons"],
        "periods": periods,
        "change_of_site_means": pure["change_of_site_means"],
        "change_of_site_medians": change_block(medians_a, medians_b, UNIT),
        "median_site_relative_change_percent": pure["median_site_relative_change_percent"],
        "n_sites_relative_change_undefined": pure["n_sites_relative_change_undefined"],
        "sites_increased": pure["sites_increased"],
        "sites_decreased": pure["sites_decreased"],
        "sites_unchanged": pure["sites_unchanged"],
        "data_range": pure["data_range"],
        "flags": flags,
    }


def _median_float(values: list[float]) -> float | None:
    return float(statistics.median(values)) if values else None


def country_change_rows(country: str, period_a: Period, period_b: Period) -> dict[str, Any]:
    """The country comparison through the earlier path (one cell per bathing water and month, all values read for the
    medians): the reference of the parity tests. The routes use ``country_change``."""
    return {"indicators": {name: _country_indicator(country, name, period_a, period_b) for name in INDICATORS}}


def country_change(country: str, period_a: Period, period_b: Period) -> dict[str, Any]:
    """The comparison of the samples of one country between two periods, for both indicators, over PAIRED bathing waters only.

    Runs under the process-wide guard (``oah.indices.scope_guard``): at most two country comparisons at a time, a bounded
    wait then ``ScopeBusy``, a small TTL + LRU result cache, and ``ScopeTooLarge`` past the hard row or time cap.
    """
    key = (
        "real-eea-bathing-samples", file_signature(bathing_samples_store_path()), country,
        (period_a.first, period_a.last), (period_b.first, period_b.last),
    )
    return GUARD.run(key, lambda: _country_by_sql(country, period_a, period_b))


def _country_by_sql(country: str, period_a: Period, period_b: Period) -> dict[str, Any]:
    try:
        kinds = store.country_kind_counts(country, [(period_a.first, period_a.last), (period_b.first, period_b.last)])
    except store.RowCapExceeded:
        raise ScopeTooLarge(_TOO_LARGE) from None
    if not kinds:  # no store: nothing to count (the routes check the store before they get here)
        kinds = {name: ({}, {}) for name in INDICATORS}
    return {"indicators": {name: _country_indicator(country, name, period_a, period_b, kinds) for name in INDICATORS}}
