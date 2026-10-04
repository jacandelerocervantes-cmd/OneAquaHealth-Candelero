"""The two comparisons: ONE parameter at ONE site, and across the PAIRED sites of ONE country (see the package docstring)."""
from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from oah.indices.period_change.limits import _assessment_view, assess_mean, crossing
from oah.indices.period_change.periods import Cell, ParameterContext, Period, SiteContext
from oah.indices.period_change.stats import (
    COMPARISON_DECIMALS,
    FEW_SITES_THRESHOLD,
    PERCENT_DECIMALS,
    PeriodStats,
    _data_range_view,
    _minimum,
    _out,
    _period_view,
    _same,
    _top_flags,
    _union_flags,
    change_block,
    period_stats,
)
from oah.indices.regimes import SURFACE


def compare_site(
    cells: Sequence[Cell],
    parameter: ParameterContext,
    site: SiteContext,
    period_a: Period,
    period_b: Period,
    *,
    data_range: tuple[int, int] | None,
    min_samples: int | None = None,
    decimals: int = COMPARISON_DECIMALS,
) -> dict[str, Any]:
    """The comparison of ONE site and ONE parameter between two periods (see the module docstring).

    ``data_range`` is the first and last month position the site holds for this parameter over ALL time (None when it
    holds none). The result always carries the numbers it could compute; ``status`` is ``insufficient-data`` when a
    period has fewer samples than the minimum (the change is still given, with the flags saying why it is weak).
    """
    minimum = _minimum(parameter, min_samples)
    stats_a, stats_b = period_stats(cells, period_a), period_stats(cells, period_b)
    view_a = _period_view(stats_a, period_a, parameter, minimum, data_range)
    view_b = _period_view(stats_b, period_b, parameter, minimum, data_range)
    assessments = []
    for view, stats, period in ((view_a, stats_a, period_a), (view_b, stats_b, period_b)):
        assessment = assess_mean(parameter, site, stats.mean, period.last)
        view["assessment"] = _assessment_view(assessment)
        assessments.append(assessment)
    change = change_block(stats_a.mean, stats_b.mean, parameter.unit, decimals)
    enough = stats_a.n_samples >= minimum and stats_b.n_samples >= minimum
    crossed = crossing(assessments[0]["status"], assessments[1]["status"]) if enough else None
    return {
        "parameter": parameter.name,
        "unit": parameter.unit,
        "group": parameter.group,
        "resolution": parameter.resolution,
        "status": "ok" if enough else "insufficient-data",
        "min_samples_per_period": minimum,
        "periods": {"a": view_a, "b": view_b},
        "change": change,
        "crossed_limit": crossed,
        "data_range": _data_range_view(data_range),
        "flags": _top_flags([view_a, view_b], period_a, period_b, change, data_range),
    }


# --- one country (paired sites only) ------------------------------------------------------------------------------------


def compare_country(
    cells_by_site: Mapping[str, Sequence[Cell]],
    sites: Mapping[str, SiteContext],
    parameter: ParameterContext,
    country: str,
    period_a: Period,
    period_b: Period,
    *,
    data_range: tuple[int, int] | None,
    min_samples: int | None = None,
    few_sites: int = FEW_SITES_THRESHOLD,
    decimals: int = COMPARISON_DECIMALS,
) -> dict[str, Any]:
    """The comparison of ONE parameter across the sites of ONE country, over PAIRED sites only.

    A site is paired when it meets the minimum number of samples in BOTH periods. A site with records in only one
    period, or too few in either, is excluded with a reason (``absent-in-period-a``, ``absent-in-period-b``,
    ``insufficient-samples``) and is never imputed; a site with no record in either period is not considered at all.
    Reported: the counts, the mean of the site means per period (and its change), the median of the per-site relative
    changes, how many sites increased, decreased or stayed unchanged, and, for river sites, how many exceeded the limit
    in each period. The same site set is used for both periods.

    The cells of every site are summarised per period (``period_stats``) and handed to ``compare_country_stats``, which
    holds the whole comparison; a data layer that has already summed the rows per site and period (the SQL aggregation
    of ``oah.waterbase``) calls ``compare_country_stats`` directly with ``aggregate_stats`` and gets the same result.
    """
    stats_by_site = {
        site_id: (period_stats(cells, period_a), period_stats(cells, period_b)) for site_id, cells in cells_by_site.items()
    }
    return compare_country_stats(
        stats_by_site, sites, parameter, country, period_a, period_b,
        data_range=data_range, min_samples=min_samples, few_sites=few_sites, decimals=decimals,
    )


def compare_country_stats(
    stats_by_site: Mapping[str, tuple[PeriodStats, PeriodStats]],
    sites: Mapping[str, SiteContext],
    parameter: ParameterContext,
    country: str,
    period_a: Period,
    period_b: Period,
    *,
    data_range: tuple[int, int] | None,
    min_samples: int | None = None,
    few_sites: int = FEW_SITES_THRESHOLD,
    decimals: int = COMPARISON_DECIMALS,
) -> dict[str, Any]:
    """``compare_country`` from the per-site, per-period statistics (see there for the rules); ``stats_by_site[site]`` is
    ``(statistics in period A, statistics in period B)``."""
    minimum = _minimum(parameter, min_samples)
    paired: list[dict[str, Any]] = []
    reasons = {"absent-in-period-a": 0, "absent-in-period-b": 0, "insufficient-samples": 0}
    considered = 0
    for site_id in sorted(stats_by_site):
        stats_a, stats_b = stats_by_site[site_id]
        has_a, has_b = stats_a.has_records, stats_b.has_records
        if not has_a and not has_b:
            continue
        considered += 1
        if not has_b:
            reasons["absent-in-period-b"] += 1
        elif not has_a:
            reasons["absent-in-period-a"] += 1
        elif stats_a.n_samples < minimum or stats_b.n_samples < minimum:
            reasons["insufficient-samples"] += 1
        else:
            paired.append({"id": site_id, "a": stats_a, "b": stats_b})
    excluded = considered - len(paired)

    sides: dict[str, dict[str, Any]] = {}
    for key, period in (("a", period_a), ("b", period_b)):
        stats_list: list[PeriodStats] = [item[key] for item in paired]
        months = 0
        for item in paired:
            months |= item[key].months_mask
        river_judged = river_over = 0
        for item in paired:
            context = sites.get(item["id"])
            if context is None or context.regime != SURFACE:
                continue
            assessment = assess_mean(parameter, context, item[key].mean, period.last)
            if assessment["status"] in ("within-limit", "exceeds-limit"):
                river_judged += 1
                river_over += assessment["status"] == "exceeds-limit"
        n_samples = sum(s.n_samples for s in stats_list)
        below = sum(s.n_below_loq for s in stats_list)
        sides[key] = {
            "start": period.start,
            "end": period.end,
            "months_in_period": period.months,
            "n_sites": len(paired),
            "n_samples": n_samples,
            "n_unit": parameter.n_unit,
            "n_months_with_data": months.bit_count(),
            "mean_of_site_means": _out(_mean_of_site_means(paired, key)),
            "n_below_loq": below,
            "below_loq_share": _out(below / (n_samples + below) if (n_samples + below) else None),
            "river_sites_judged": river_judged,
            "river_sites_over_limit": river_over,
            "flags": [],
            "_months": months.bit_count(),
        }
    # Flags per period (computed from the same rules as one site, over the paired sites).
    for key, period in (("a", period_a), ("b", period_b)):
        side = sides[key]
        flags = []
        if data_range is None or period.last > data_range[1]:
            flags.append("period-outside-data")
        if data_range is not None and period.last < data_range[0]:
            flags.append("period-before-data")
        if 0 < side["_months"] < period.months:
            flags.append("partial-period")
        if side["n_below_loq"] > 0:
            flags.append("below-loq-excluded-bias-upward")
        if parameter.resolution == "annual-only":
            flags.append("annual-only")
        side["flags"] = flags
        del side["_months"]

    change = change_block(_mean_of_site_means(paired, "a"), _mean_of_site_means(paired, "b"), parameter.unit, decimals)

    relative: list[float] = []
    increased = decreased = unchanged = undefined = 0
    for item in paired:
        a_mean, b_mean = item["a"].mean, item["b"].mean
        if a_mean is None or b_mean is None:
            continue
        if _same(a_mean, b_mean, decimals):
            unchanged += 1
        elif b_mean > a_mean:
            increased += 1
        else:
            decreased += 1
        if round(a_mean, decimals) == 0:
            undefined += 1
        else:
            relative.append(100.0 * (b_mean - a_mean) / abs(a_mean))
    median_relative = statistics.median(relative) if relative else None

    # The limit that applies to a river site of the country (one limit for the whole country and regime).
    reference = SiteContext("country-reference", country, SURFACE)
    river_limit = {
        "a": _limit_view(assess_mean(parameter, reference, None, period_a.last)),
        "b": _limit_view(assess_mean(parameter, reference, None, period_b.last)),
    }
    country_flags = set(_union_flags(sides["a"]["flags"], sides["b"]["flags"]))
    if data_range is None:
        country_flags.add("no-data-for-scope")
    if period_a.intersects(period_b.first, period_b.last):
        country_flags.add("periods-overlap")
    if 0 < len(paired) < few_sites:
        country_flags.add("few-sites")
    if change["relative_percent_note"] in ("baseline-zero", "baseline-missing", "comparison-missing"):
        country_flags.add("relative-change-undefined")
    if change["relative_percent_note"] == "interval-scale":
        country_flags.add("relative-change-interval-scale")
    return {
        "parameter": parameter.name,
        "unit": parameter.unit,
        "group": parameter.group,
        "resolution": parameter.resolution,
        "status": "ok" if paired else "insufficient-data",
        "min_samples_per_period": minimum,
        "few_sites_threshold": few_sites,
        "n_sites_considered": considered,
        "n_sites_paired": len(paired),
        "n_sites_excluded": excluded,
        "exclusion_reasons": {key: value for key, value in reasons.items() if value},
        "periods": {"a": sides["a"], "b": sides["b"]},
        "change_of_site_means": change,
        "median_site_relative_change_percent": _out(median_relative, PERCENT_DECIMALS),
        "n_sites_relative_change_undefined": undefined,
        "sites_increased": increased,
        "sites_decreased": decreased,
        "sites_unchanged": unchanged,
        "river_limit": river_limit,
        "data_range": _data_range_view(data_range),
        "flags": sorted(country_flags),
    }


def _mean_of_site_means(paired: Sequence[Mapping[str, Any]], key: str) -> float | None:
    """The unrounded mean of the site means of one period (the change is computed from exact values, not from shown ones)."""
    means = [item[key].mean for item in paired if item[key].mean is not None]
    return math.fsum(means) / len(means) if means else None


def _limit_view(assessment: Mapping[str, Any]) -> dict[str, Any]:
    """The limit part of an assessment (no status, no scored value): what applies to a river site of the country."""
    view = _assessment_view(assessment)
    return {key: view[key] for key in ("limit", "limit_unit", "limit_type", "limit_range", "limit_basis", "limit_regime", "flags")}
