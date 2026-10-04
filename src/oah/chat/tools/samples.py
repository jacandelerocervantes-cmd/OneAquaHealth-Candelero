"""Chat tools over the EEA bathing-water SAMPLES store: individual E. coli and enterococci results and their comparison.

Measurements only: no threshold, limit or classification is applied. A detection-limit, missing or unrecognised value is
passed on as its kind alone, never as a number.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from oah.bathing_samples.constants import (
    ATTRIBUTION as SAMPLES_ATTRIBUTION,
    CHANGE_NOTICE_SHORT as SAMPLES_CHANGE_NOTICE,
    FLAGGED_VALUES_NOTE_SHORT as SAMPLES_FLAGGED_NOTE,
    NO_THRESHOLD_NOTICE_SHORT as SAMPLES_NO_THRESHOLD_NOTICE,
    SAMPLES_NOTICE_SHORT,
    SOURCE_ID as SAMPLES_SOURCE,
    UNIT as SAMPLES_UNIT,
)
from oah.chat.errors import ToolError
from oah.chat.tools.approximate import samples_comparison_block, samples_summary_block
from oah.chat.tools.comparison import _INCREASE_DEFINITION, _compact_change, _percent
from oah.chat.tools.context import ToolContext
from oah.chat.tools.results import _BATHING_SNAPSHOT, MAX_TOOL_RESULT_CHARS, _amount, _shrink_list
from oah.chat.tools.validation import (
    _COUNTRY_CODE,
    _LOCATION_ID,
    _date_argument,
    _parse_periods,
    _text_argument,
    normalise_country,
)


DEFAULT_SAMPLES_LIMIT = 20
MAX_SAMPLES_LIMIT = 100
_SAMPLE_INDICATORS = ("escherichia_coli", "intestinal_enterococci")


def _samples_notes(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        "data_freshness": _BATHING_SNAPSHOT,
        "attribution": SAMPLES_ATTRIBUTION,
        "notice": SAMPLES_NOTICE_SHORT,
        "no_threshold_notice": SAMPLES_NO_THRESHOLD_NOTICE,
        "flagged_values_note": SAMPLES_FLAGGED_NOTE,
    }


def _sample_indicator(entry: Mapping[str, Any]) -> dict[str, Any]:
    """One indicator of one sample for the model: the number with its unit only for a quantified value, else just the kind.

    The number reported with a detection-limit flag is deliberately not passed on: it is a limit of detection, and the
    model could mistake it for a result.
    """
    out: dict[str, Any] = {"kind": entry.get("kind")}
    if entry.get("value") is not None:
        out["value"] = _amount(entry["value"], SAMPLES_UNIT)
    return out


def _sample_row(sample: Mapping[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {"date": sample.get("sample_date"), "season": sample.get("season")}
    if sample.get("sample_status"):
        row["sample_status"] = sample["sample_status"]
    for name in _SAMPLE_INDICATORS:
        row[name] = _sample_indicator(sample.get(name) or {})
    return row


def _samples_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for name in _SAMPLE_INDICATORS:
        entry = summary.get(name)
        if not entry:
            continue
        counts = {
            key: entry.get(key)
            for key in ("n_samples_in_range", "n_quantified", "n_confirmed_high", "n_detection_limit", "n_missing", "n_unrecognised")
        }
        numbers = {key: _amount(entry.get(key), SAMPLES_UNIT) for key in ("min", "max", "mean", "median")}
        compact[name] = {key: value for key, value in {**counts, **numbers}.items() if value is not None}
    return compact


def _get_bathing_samples(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    if ctx.samples_get is None:
        raise ToolError("Bathing-water sample data is not available in this deployment.")
    value = _text_argument(raw, "bathing_water_id", required=True)
    if value is None or not _LOCATION_ID.match(value):
        raise ToolError("Argument bathing_water_id must be a bare identifier (letters, digits, dot, dash, underscore).")
    date_from, date_to = _date_argument(raw, "date_from"), _date_argument(raw, "date_to")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ToolError("date_from must not be after date_to.")
    season = raw.get("season")
    if season is not None and (isinstance(season, bool) or not isinstance(season, int) or not 1900 <= season <= 2100):
        raise ToolError("Argument season must be a season year from 1900 to 2100.")
    limit = raw.get("limit", DEFAULT_SAMPLES_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_SAMPLES_LIMIT:
        raise ToolError(f"Argument limit must be an integer from 1 to {MAX_SAMPLES_LIMIT}.")
    found = ctx.samples_get(value, date_from, date_to, season, limit)
    if found is None:
        raise ToolError("Unknown bathing water: no sample data for that identifier.")
    site = found.get("bathing_water") or {}
    if ctx.country is not None and site.get("country") != ctx.country:
        raise ToolError(
            f"That bathing water belongs to country {site.get('country') or 'unknown'}, not the selected country "
            f"{ctx.country}. Tell the user to change the country selector."
        )
    result: dict[str, Any] = {
        "origin": SAMPLES_SOURCE,
        "bathing_water": {key: site.get(key) for key in ("id", "country", "name", "type") if site.get(key) is not None},
        "unit": SAMPLES_UNIT,
        "filters": {key: item for key, item in (found.get("filters") or {}).items() if item is not None},
        "data_range": found.get("data_range"),
        "total_matching": found.get("total_matching"),
        "returned": found.get("returned"),
        "truncated": bool(found.get("truncated")),
        "order": "newest first",
        "summary": _samples_summary(found.get("summary") or {}),
        "flags": list(found.get("flags") or []),
        "samples": [_sample_row(sample) for sample in found.get("samples", [])],
    }
    result["approximate"] = samples_summary_block(result["summary"], result["flags"])  # presentation rounding, see oah.chat.precision
    full = _samples_notes({key: item for key, item in result.items() if item is not None})
    _shrink_list(full, "samples", MAX_TOOL_RESULT_CHARS)  # after the notes are added, so the whole result fits
    return full


def _compact_samples_period(view: Mapping[str, Any]) -> dict[str, Any]:
    out = {
        "start": view.get("start"), "end": view.get("end"), "months_in_period": view.get("months_in_period"),
        "n_samples": view.get("n_samples"), "n_months_with_data": view.get("n_months_with_data"),
        "mean": _amount(view.get("mean"), SAMPLES_UNIT), "median": _amount(view.get("median"), SAMPLES_UNIT),
        "min": _amount(view.get("min"), SAMPLES_UNIT), "max": _amount(view.get("max"), SAMPLES_UNIT),
        "n_detection_limit": view.get("n_detection_limit"), "n_missing": view.get("n_missing"),
        "n_unrecognised": view.get("n_unrecognised"), "n_confirmed_high": view.get("n_confirmed_high"),
        "meets_minimum_samples": view.get("meets_minimum_samples"), "flags": list(view.get("flags") or []),
    }
    return {key: item for key, item in out.items() if item is not None}


def _compact_samples_country_period(view: Mapping[str, Any]) -> dict[str, Any]:
    out = {
        "start": view.get("start"), "end": view.get("end"), "months_in_period": view.get("months_in_period"),
        "n_sites": view.get("n_sites"), "n_samples": view.get("n_samples"), "n_months_with_data": view.get("n_months_with_data"),
        "mean_of_site_means": _amount(view.get("mean_of_site_means"), SAMPLES_UNIT),
        "median_of_site_medians": _amount(view.get("median_of_site_medians"), SAMPLES_UNIT),
        "n_detection_limit_all_sites": view.get("n_detection_limit_all_sites"), "n_missing_all_sites": view.get("n_missing_all_sites"),
        "flags": list(view.get("flags") or []),
    }
    return {key: item for key, item in out.items() if item is not None}


def compact_samples_change(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The samples comparison as the model sees it: every number with its unit, the flags, no limit and no significance."""
    indicators: dict[str, Any] = {}
    country_scope = (payload.get("scope") or {}).get("type") == "country"
    for name in _SAMPLE_INDICATORS:
        item = (payload.get("indicators") or {}).get(name)
        if not item:
            continue
        periods = item.get("periods") or {}
        if country_scope:
            entry: dict[str, Any] = {
                "status": item.get("status"), "min_samples_per_period": item.get("min_samples_per_period"),
                "few_sites_threshold": item.get("few_sites_threshold"), "n_sites_considered": item.get("n_sites_considered"),
                "n_sites_paired": item.get("n_sites_paired"), "n_sites_excluded": item.get("n_sites_excluded"),
                "exclusion_reasons": item.get("exclusion_reasons"),
                "period_a": _compact_samples_country_period(periods.get("a") or {}),
                "period_b": _compact_samples_country_period(periods.get("b") or {}),
                "change_of_site_means": _compact_change(item.get("change_of_site_means") or {}, SAMPLES_UNIT),
                "change_of_site_medians": _compact_change(item.get("change_of_site_medians") or {}, SAMPLES_UNIT),
                "median_site_relative_change": _percent(item.get("median_site_relative_change_percent")),
                "sites_increased": item.get("sites_increased"), "sites_decreased": item.get("sites_decreased"),
                "sites_unchanged": item.get("sites_unchanged"),
            }
        else:
            entry = {
                "status": item.get("status"), "min_samples_per_period": item.get("min_samples_per_period"),
                "period_a": _compact_samples_period(periods.get("a") or {}),
                "period_b": _compact_samples_period(periods.get("b") or {}),
                "change_of_mean": _compact_change(item.get("change") or {}, SAMPLES_UNIT),
                "change_of_median": _compact_change(item.get("change_of_median") or {}, SAMPLES_UNIT),
            }
        entry["data_range"] = item.get("data_range")
        entry["flags"] = list(item.get("flags") or [])
        entry["approximate"] = samples_comparison_block(entry, country_scope=country_scope)
        indicators[name] = {key: value for key, value in entry.items() if value is not None}
    scope = payload.get("scope") or {}
    result: dict[str, Any] = {
        "origin": SAMPLES_SOURCE,
        "scope": {key: scope.get(key) for key in ("type", "id", "code", "name", "country") if scope.get(key) is not None},
        "unit": SAMPLES_UNIT,
        "indicators": indicators,
        "flags": list(payload.get("flags") or []),
        "definition": _INCREASE_DEFINITION,
        "change_notice": SAMPLES_CHANGE_NOTICE,
    }
    return _samples_notes({key: item for key, item in result.items() if item not in (None, [])})


def _compare_bathing_concentrations(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    scope = _text_argument(raw, "scope", required=True)
    if scope not in ("bathing_water", "country"):
        raise ToolError("Argument scope must be bathing_water or country.")
    identifier = _text_argument(raw, "id_or_country", required=True)
    period_a, period_b = _parse_periods(raw)
    if scope == "bathing_water":
        if identifier is None or not _LOCATION_ID.match(identifier):
            raise ToolError("Argument id_or_country must be a bare bathing water identifier for scope bathing_water.")
        if ctx.samples_compare_site is None:
            raise ToolError("Bathing-water sample data is not available in this deployment.")
        payload = ctx.samples_compare_site(identifier, period_a, period_b)
        site_country = (payload.get("scope") or {}).get("country")
        if ctx.country is not None and site_country != ctx.country:
            raise ToolError(
                f"That bathing water belongs to country {site_country or 'unknown'}, not the selected country "
                f"{ctx.country}. Tell the user to change the country selector."
            )
        return compact_samples_change(payload)
    if identifier is None or not _COUNTRY_CODE.match(identifier):
        raise ToolError("Argument id_or_country must be a two-letter country code for scope country.")
    country = normalise_country(identifier)
    if ctx.country is not None and country != ctx.country:
        raise ToolError(f"The selected country is {ctx.country}; other countries are not mixed into this answer.")
    if ctx.samples_compare_country is None:
        raise ToolError("Bathing-water sample data is not available in this deployment.")
    return compact_samples_change(ctx.samples_compare_country(country, period_a, period_b))
