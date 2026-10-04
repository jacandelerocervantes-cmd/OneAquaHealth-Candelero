"""Chat tools over the EEA bathing-water CLASSIFICATION store: list, history and season comparison.

A classification, never a concentration (the individual samples are in ``oah.chat.tools.samples``).
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from oah.bathing.constants import ATTRIBUTION as BATHING_ATTRIBUTION
from oah.bathing.constants import COMPARISON_NOTICE_SHORT as BATHING_COMPARISON_NOTICE
from oah.bathing.constants import NOTICE as BATHING_NOTICE
from oah.bathing.constants import SOURCE_ID as BATHING_SOURCE
from oah.chat.errors import ToolError
from oah.chat.tools.context import ToolContext
from oah.chat.tools.results import _BATHING_SNAPSHOT, MAX_TOOL_RESULT_CHARS, _shrink_list
from oah.chat.tools.validation import _LOCATION_ID, _parse_country, _text_argument, _text_filter


DEFAULT_BATHING_LIMIT = 20
MAX_BATHING_LIMIT = 50


def _bathing_summary(item: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("id", "country", "name", "type", "first_season", "latest_season", "n_seasons", "latest_quality", "location_status")
    return {key: item[key] for key in keys if item.get(key) is not None}


def _bathing_notes(result: dict[str, Any]) -> dict[str, Any]:
    return {**result, "data_freshness": _BATHING_SNAPSHOT, "attribution": BATHING_ATTRIBUTION, "notice": BATHING_NOTICE}


def _list_bathing_waters(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    if ctx.bathing_list is None:
        raise ToolError("Bathing-water data is not available in this deployment.")
    requested = _parse_country(raw)
    query, quality, water_type = _text_filter(raw, "query"), _text_filter(raw, "quality"), _text_filter(raw, "type")
    limit = raw.get("limit", DEFAULT_BATHING_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_BATHING_LIMIT:
        raise ToolError(f"Argument limit must be an integer from 1 to {MAX_BATHING_LIMIT}.")
    if requested is not None and ctx.country is not None and requested != ctx.country:
        raise ToolError(f"The selected country is {ctx.country}; other countries are not mixed into this answer.")
    overview = ctx.countries()[0]
    if requested is not None and requested not in {item["code"] for item in overview}:
        raise ToolError("Unknown country code; list_countries shows the known ones.")
    country = requested or ctx.country
    total, items = ctx.bathing_list(country, query, quality, water_type, limit)
    result: dict[str, Any] = {
        "origin": BATHING_SOURCE,
        "country": country,
        "query": query,
        "quality": quality,
        "type": water_type,
        "total_bathing_waters": total,
        "returned": len(items),
        "truncated": total > len(items),
        "bathing_waters": [_bathing_summary(item) for item in items],
    }
    if total == 0:
        covered = sorted(str(item["code"]) for item in overview if item.get("bathing_water"))
        result["note"] = (
            "No bathing water matched. Bathing-water classification is held for: "
            f"{', '.join(covered) if covered else 'no country (the store is not built)'}."
        )
    _shrink_list(result, "bathing_waters", MAX_TOOL_RESULT_CHARS)
    return _bathing_notes(result)


def _get_bathing_water_history(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    if ctx.bathing_get is None:
        raise ToolError("Bathing-water data is not available in this deployment.")
    value = _text_argument(raw, "bathing_water_id", required=True)
    if value is None or not _LOCATION_ID.match(value):
        raise ToolError("Argument bathing_water_id must be a bare identifier (letters, digits, dot, dash, underscore).")
    found = ctx.bathing_get(value)
    if found is None:
        raise ToolError("Unknown bathing water: no classification data for that identifier.")
    if ctx.country is not None and found.get("country") != ctx.country:
        raise ToolError(
            f"That bathing water belongs to country {found.get('country') or 'unknown'}, not the selected country "
            f"{ctx.country}. Tell the user to change the country selector."
        )
    history = [
        {key: row[key] for key in ("season", "quality", "monitoring_calendar", "management") if row.get(key) is not None}
        for row in found.get("history", [])
    ]
    result: dict[str, Any] = {
        "origin": BATHING_SOURCE,
        "bathing_water": _bathing_summary(found),
        "total_seasons": len(history),
        "returned": len(history),
        "truncated": False,
        "history": history,
    }
    _shrink_list(result, "history", MAX_TOOL_RESULT_CHARS)
    return _bathing_notes(result)


def _season(raw: Mapping[str, Any], name: str) -> int:
    value = raw.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or not 1900 <= value <= 2100:
        raise ToolError(f"Argument {name} must be a season year from 1900 to 2100.")
    return value


def _compare_bathing_seasons(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    if ctx.bathing_compare is None:
        raise ToolError("Bathing-water data is not available in this deployment.")
    country = _parse_country(raw)
    if country is None:
        raise ToolError("Missing required argument country.")
    season_a, season_b = _season(raw, "season_a"), _season(raw, "season_b")
    if ctx.country is not None and country != ctx.country:
        raise ToolError(f"The selected country is {ctx.country}; other countries are not mixed into this answer.")
    payload = ctx.bathing_compare(country, season_a, season_b)
    keep = (
        "country", "type", "season_a", "season_b", "order", "data_range", "totals", "paired_bathing_waters", "comparable",
        "moved_up", "moved_down", "unchanged", "transitions", "not_comparable", "only_in_season_a", "only_in_season_b", "flags",
    )
    result = {"origin": BATHING_SOURCE, **{key: payload[key] for key in keep if payload.get(key) is not None}}
    return {**_bathing_notes(result), "comparison_notice": BATHING_COMPARISON_NOTICE}
