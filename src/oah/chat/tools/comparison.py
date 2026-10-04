"""Chat tool ``compare_periods``: the deterministic period comparison, compacted for the model.

Every number is written as ``{amount, unit}`` so the grounding check pairs each figure with its unit.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from oah.chat.errors import ToolError
from oah.chat.tools.approximate import country_comparison_block, site_comparison_block
from oah.chat.tools.context import ToolContext
from oah.chat.tools.results import _amount
from oah.chat.tools.sites import _check_site_country
from oah.chat.tools.validation import (
    _COUNTRY_CODE,
    _LOCATION_ID,
    _parse_periods,
    _text_argument,
    normalise_country,
)
from oah.i18n.strings import ENGLISH
from oah.indices.site_measurements import parameter_names
from oah.waterbase.mapping import SOURCE_ID as WATERBASE_SOURCE
from oah.waterbase.mapping import parameter_names as waterbase_parameter_names


_INCREASE_DEFINITION = (
    "Increase and decrease mean mean_B minus mean_A as computed by this tool. Quote only the numbers of this result and "
    "always state n_samples and the flags."
)


def _percent(value: Any) -> dict[str, Any] | None:
    return _amount(value, "%")


def _compact_limit_check(assessment: Mapping[str, Any]) -> dict[str, Any]:
    check = {
        "status": assessment.get("status"),
        "limit_regime": assessment.get("limit_regime"),
        "limit_basis": assessment.get("limit_basis"),
        "limit": _amount(
            assessment.get("limit"), assessment.get("limit_unit"), type=assessment.get("limit_type"),
            range=assessment.get("limit_range"),
        ),
        "flags": list(assessment.get("flags") or []),
    }
    return {key: value for key, value in check.items() if value not in (None, [])}


def _compact_change(change: Mapping[str, Any], unit: Any) -> dict[str, Any]:
    out = {
        "absolute": _amount(change.get("absolute"), unit),
        "relative_percent": _percent(change.get("relative_percent")),
        "relative_percent_note": change.get("relative_percent_note"),
        "direction": change.get("direction"),
    }
    return {key: value for key, value in out.items() if value is not None}


def _share_percent(share: Any) -> dict[str, Any] | None:
    return _percent(round(float(share) * 100, 4)) if isinstance(share, (int, float)) and not isinstance(share, bool) else None


def _compact_site_period(view: Mapping[str, Any], unit: Any) -> dict[str, Any]:
    out = {
        "start": view.get("start"), "end": view.get("end"), "months_in_period": view.get("months_in_period"),
        "n_samples": view.get("n_samples"), "n_unit": view.get("n_unit"), "n_months_with_data": view.get("n_months_with_data"),
        "mean": _amount(view.get("mean"), unit), "min": _amount(view.get("min"), unit), "max": _amount(view.get("max"), unit),
        "n_below_loq": view.get("n_below_loq"), "below_loq_percent": _share_percent(view.get("below_loq_share")),
        "meets_minimum_samples": view.get("meets_minimum_samples"), "flags": list(view.get("flags") or []),
        "limit_check": _compact_limit_check(view.get("assessment") or {}),
    }
    return {key: value for key, value in out.items() if value is not None}


def compact_site_change(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The site comparison as the model sees it: every number with its unit, the limit with its basis, the flags."""
    unit = payload.get("unit")
    periods = payload.get("periods") or {}
    result: dict[str, Any] = {
        "origin": payload.get("origin"),
        "source": payload.get("source"),
        "attribution": payload.get("attribution"),
        "scope": payload.get("scope"),
        "parameter": payload.get("parameter"),
        "group": payload.get("group"),
        "unit": unit,
        "resolution": payload.get("resolution"),
        "status": payload.get("status"),
        "min_samples_per_period": payload.get("min_samples_per_period"),
        "period_a": _compact_site_period(periods.get("a") or {}, unit),
        "period_b": _compact_site_period(periods.get("b") or {}, unit),
        "change": _compact_change(payload.get("change") or {}, unit),
        "crossed_limit": payload.get("crossed_limit"),
        "data_range": payload.get("data_range"),
        "flags": list(payload.get("flags") or []),
        "definition": _INCREASE_DEFINITION,
        "approximation_notice": ENGLISH["approximation_notice"],
        "interpretation_notice": ENGLISH["interpretation_notice"],
    }
    result["approximate"] = site_comparison_block(result)  # presentation rounding next to the exact numbers (oah.chat.precision)
    if payload.get("source") == WATERBASE_SOURCE:
        result["data_freshness"] = {"status": "snapshot", "as_of": None}
    return {key: value for key, value in result.items() if value is not None}


def _compact_country_period(view: Mapping[str, Any], unit: Any) -> dict[str, Any]:
    out = {
        "start": view.get("start"), "end": view.get("end"), "months_in_period": view.get("months_in_period"),
        "n_sites": view.get("n_sites"), "n_samples": view.get("n_samples"), "n_unit": view.get("n_unit"),
        "n_months_with_data": view.get("n_months_with_data"),
        "mean_of_site_means": _amount(view.get("mean_of_site_means"), unit),
        "n_below_loq": view.get("n_below_loq"), "below_loq_percent": _share_percent(view.get("below_loq_share")),
        "river_sites_judged": view.get("river_sites_judged"), "river_sites_over_limit": view.get("river_sites_over_limit"),
        "flags": list(view.get("flags") or []),
    }
    return {key: value for key, value in out.items() if value is not None}


def compact_country_change(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The country comparison as the model sees it: one entry per source, paired sites only."""
    entries: list[dict[str, Any]] = []
    for item in payload.get("results") or []:
        unit = item.get("unit")
        periods = item.get("periods") or {}
        limits = item.get("river_limit") or {}
        entry: dict[str, Any] = {
            "origin": item.get("origin"),
            "source": item.get("source"),
            "attribution": item.get("attribution"),
            "parameter": item.get("parameter"),
            "group": item.get("group"),
            "unit": unit,
            "resolution": item.get("resolution"),
            "status": item.get("status"),
            "min_samples_per_period": item.get("min_samples_per_period"),
            "few_sites_threshold": item.get("few_sites_threshold"),
            "n_sites_considered": item.get("n_sites_considered"),
            "n_sites_paired": item.get("n_sites_paired"),
            "n_sites_excluded": item.get("n_sites_excluded"),
            "exclusion_reasons": item.get("exclusion_reasons"),
            "period_a": _compact_country_period(periods.get("a") or {}, unit),
            "period_b": _compact_country_period(periods.get("b") or {}, unit),
            "river_limit_period_a": _compact_limit_check(limits.get("a") or {}),
            "river_limit_period_b": _compact_limit_check(limits.get("b") or {}),
            "change_of_site_means": _compact_change(item.get("change_of_site_means") or {}, unit),
            "median_site_relative_change": _percent(item.get("median_site_relative_change_percent")),
            "n_sites_relative_change_undefined": item.get("n_sites_relative_change_undefined"),
            "sites_increased": item.get("sites_increased"),
            "sites_decreased": item.get("sites_decreased"),
            "sites_unchanged": item.get("sites_unchanged"),
            "data_range": item.get("data_range"),
            "flags": list(item.get("flags") or []),
        }
        entry["approximate"] = country_comparison_block(entry)
        if item.get("source") == WATERBASE_SOURCE:
            entry["data_freshness"] = {"status": "snapshot", "as_of": None}
        entries.append({key: value for key, value in entry.items() if value is not None})
    origins = {entry["origin"] for entry in entries}
    result: dict[str, Any] = {
        "origin": "real-mixed" if len(origins) > 1 else (next(iter(origins)) if origins else payload.get("origin")),
        "scope": payload.get("scope"),
        "parameter": payload.get("parameter"),
        "results": entries,
        "note": payload.get("note"),
        "definition": _INCREASE_DEFINITION,
        "approximation_notice": ENGLISH["approximation_notice"],
        "interpretation_notice": ENGLISH["interpretation_notice"],
    }
    return {key: value for key, value in result.items() if value is not None}


def _compare_periods(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    scope = _text_argument(raw, "scope", required=True)
    if scope not in ("site", "country"):
        raise ToolError("Argument scope must be site or country.")
    identifier = _text_argument(raw, "id_or_country", required=True)
    parameter = _text_argument(raw, "parameter", required=True)
    known = {name.lower(): name for name in [*parameter_names(), *waterbase_parameter_names()]}
    if parameter is None or parameter.lower() not in known:
        raise ToolError(f"Unknown parameter; known parameters: {', '.join(sorted(known.values()))}.")
    period_a, period_b = _parse_periods(raw)
    if scope == "site":
        if identifier is None or not _LOCATION_ID.match(identifier):
            raise ToolError("Argument id_or_country must be a bare site id (letters, digits, dot, dash, underscore) for scope site.")
        if ctx.compare_site is None:
            raise ToolError("Period comparison is not available in this deployment.")
        _check_site_country(ctx, identifier)
        return compact_site_change(ctx.compare_site(identifier, known[parameter.lower()], period_a, period_b))
    if identifier is None or not _COUNTRY_CODE.match(identifier):
        raise ToolError("Argument id_or_country must be a two-letter country code for scope country.")
    country = normalise_country(identifier)
    if ctx.country is not None and country != ctx.country:
        raise ToolError(f"The selected country is {ctx.country}; other countries are not mixed into this answer.")
    if ctx.compare_country is None:
        raise ToolError("Period comparison is not available in this deployment.")
    return compact_country_change(ctx.compare_country(country, known[parameter.lower()], period_a, period_b))
