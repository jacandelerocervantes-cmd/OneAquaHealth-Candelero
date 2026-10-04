"""The three EXTERNAL-context chat tools: weather, river discharge, species records near a site.

They are wrappers over ``oah.external.service.ExternalContext`` (the same function the REST routes call; no HTTP
self-call) and follow the rules of the other tools (docs/chat_agent.md): validated arguments, a bare site id (never a raw
coordinate), the selected country enforced here, a bounded result, every number written as ``{amount, unit}``.

What the model is told, in every result (fixed English notices, not model output):

* this is EXTERNAL context from a public provider, MODELLED (weather reanalysis, river discharge) or OPPORTUNISTIC (species
  records), never the site's own measurements and never monitoring;
* the provider and its attribution and licence;
* no causation: ``external_no_causation_notice``; the prompt (``CHAT_DATA_FACTS``) allows at most "rainfall may be relevant",
  and only when the tool returned both series;
* when the provider is unavailable or the period is outside its data, the result says so (``status``, ``reason``, flags).

No import of ``oah.chat.tools`` here: that module imports this one (the tool names and the handlers), so the shared helpers
are small local ones.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import date
from typing import TYPE_CHECKING, Any

from oah.chat.errors import ToolError
from oah.external.envelope import ExternalInputError
from oah.external.service import notice_keys
from oah.external.sites import LocatedSite, SiteLookupError
from oah.i18n.strings import ENGLISH

if TYPE_CHECKING:  # pragma: no cover
    from oah.chat.tools import ToolContext

CHAT_SPECIES_LIMIT = 10  # records one chat result carries; the counts per group cover the whole search
WEATHER_TOOL = "get_weather_context"
DISCHARGE_TOOL = "get_river_discharge_context"
SPECIES_TOOL = "get_species_nearby"
EXTERNAL_TOOL_NAMES = (WEATHER_TOOL, DISCHARGE_TOOL, SPECIES_TOOL)

_SITE_ID = re.compile(r"^[\w.\-]{1,128}$")
_GROUP = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,30}$")
_UNAVAILABLE_HINT = (
    "If status is external-unavailable or no-data, say so plainly with the reason; nothing may be estimated in its place."
)

_SITE_PROPERTY = {"type": "string", "description": "Bare site id as returned by list_sites, for example IT01001065."}
_DATE_FROM = {"type": "string", "description": "ISO date YYYY-MM-DD, first day, inclusive."}
_DATE_TO = {"type": "string", "description": "ISO date YYYY-MM-DD, last day, inclusive. The period is at most about three years."}

DEFINITIONS: dict[str, dict[str, Any]] = {
    WEATHER_TOOL: {
        "name": WEATHER_TOOL,
        "description": (
            "EXTERNAL context, not the site's own data: monthly precipitation sum and mean air temperature around a site or "
            "bathing water from the ERA5 reanalysis (a MODELLED value for a coarse grid cell, from Open-Meteo, licence CC BY 4.0), "
            "with the number of days and the coverage per month. The latest days may be missing (flag era5-delay). Use it only to "
            "give weather context for a period; it never explains or causes a water-quality value. " + _UNAVAILABLE_HINT
        ),
        "input_schema": {
            "type": "object",
            "properties": {"site_id": _SITE_PROPERTY, "date_from": _DATE_FROM, "date_to": _DATE_TO},
            "required": ["site_id", "date_from", "date_to"],
            "additionalProperties": False,
        },
    },
    DISCHARGE_TOOL: {
        "name": DISCHARGE_TOOL,
        "description": (
            "EXTERNAL context, not the site's own data: monthly mean river discharge in m3/s of the river cell nearest to a "
            "site from GloFAS (a MODELLED value, not a gauge reading, from Open-Meteo). The cell may be another river than the "
            "site's (flag nearest-cell-may-not-be-the-river, and the distance is given). The data end before today: read "
            "data_range and the flags period-outside-data and beyond-documented-history. Water-quality sites only. " + _UNAVAILABLE_HINT
        ),
        "input_schema": {
            "type": "object",
            "properties": {"site_id": _SITE_PROPERTY, "date_from": _DATE_FROM, "date_to": _DATE_TO},
            "required": ["site_id", "date_from", "date_to"],
            "additionalProperties": False,
        },
    },
    SPECIES_TOOL: {
        "name": SPECIES_TOOL,
        "description": (
            "EXTERNAL context, not monitoring: freshwater macroinvertebrate occurrence records published to GBIF within a 5 km "
            "half-side square around a site, with counts per group and the licence of each record. Opportunistic observations "
            "only: no record never means the species is absent. Groups: ephemeroptera, plecoptera, trichoptera, ept (those "
            "three), odonata, chironomidae, gammaridae, unionida; leave group out for all. Optional ISO date window on the "
            "event date. Water-quality sites only. " + _UNAVAILABLE_HINT
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "site_id": _SITE_PROPERTY,
                "group": {"type": "string", "description": "One of the groups above (optional)."},
                "date_from": {"type": "string", "description": "ISO date YYYY-MM-DD, earliest event date (optional)."},
                "date_to": {"type": "string", "description": "ISO date YYYY-MM-DD, latest event date (optional)."},
            },
            "required": ["site_id"],
            "additionalProperties": False,
        },
    },
}


# --- argument parsing ----------------------------------------------------------------------------------------------


def _site_id(raw: Mapping[str, Any]) -> str:
    value = raw.get("site_id")
    if not isinstance(value, str) or not _SITE_ID.match(value.strip()):
        raise ToolError("Argument site_id must be a bare site id (letters, digits, dot, dash, underscore).")
    return value.strip()


def _date(raw: Mapping[str, Any], name: str, *, required: bool) -> date | None:
    value = raw.get(name)
    if value is None:
        if required:
            raise ToolError(f"Missing required argument {name}.")
        return None
    if not isinstance(value, str):
        raise ToolError(f"Argument {name} must be an ISO date YYYY-MM-DD.")
    try:
        return date.fromisoformat(value.strip())
    except ValueError as error:
        raise ToolError(f"Argument {name} must be an ISO date YYYY-MM-DD.") from error


def _group(raw: Mapping[str, Any]) -> str | None:
    value = raw.get("group")
    if value is None:
        return None
    if not isinstance(value, str) or not _GROUP.match(value.strip()):
        raise ToolError("Argument group must be one of the group names in the tool description.")
    return value.strip()


def _located(ctx: ToolContext, site_id: str, *, allow_bathing: bool) -> LocatedSite:
    """The site, refused when it is unknown, unusable or of another country than the selected one."""
    if ctx.external is None:
        raise ToolError("External context is not available in this deployment.")
    try:
        site = ctx.external.locate(site_id, allow_bathing=allow_bathing)
    except SiteLookupError as error:
        raise ToolError(error.detail) from error
    if ctx.country is not None and site.country != ctx.country:
        raise ToolError(
            f"That site belongs to country {site.country or 'unknown'}, not the selected country {ctx.country}. "
            "Limits and context of different countries are never mixed; tell the user to change the country selector."
        )
    return site


# --- compaction -----------------------------------------------------------------------------------------------------


def _amount(value: Any, unit: str, **extra: Any) -> dict[str, Any] | None:
    """A number together with ITS unit, so the grounding check pairs each figure with the right unit."""
    if value is None:
        return None
    return {"amount": value, "unit": unit, **{key: item for key, item in extra.items() if item is not None}}


def _percent(coverage: Any) -> float | None:
    return round(float(coverage) * 100, 1) if isinstance(coverage, (int, float)) and not isinstance(coverage, bool) else None


def _frame(result: Mapping[str, Any]) -> dict[str, Any]:
    site = result.get("site") or {}
    return {
        "origin": result["origin"],
        "data_kind": result["data_kind"],
        "provider": result["provider"],
        "status": result["status"],
        "reason": result.get("reason"),
        # not the sandbox freshness that run_tool would add by default: the context comes from a provider, not from the data
        "data_freshness": {"status": "external-context", "as_of": None},
        "attribution": result["attribution"],
        "licence": result["licence"],
        "data_note": result["data_note"],
        "site": {key: site.get(key) for key in ("id", "name", "kind", "country", "water_category") if site.get(key)},
        "flags": list(result.get("flags") or []),
        "notices": [ENGLISH[key] for key in notice_keys(dict(result))],
    }


def _dropped(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if value is not None}


def compact_weather(result: Mapping[str, Any]) -> dict[str, Any]:
    grid = result.get("grid") or {}
    limits = result.get("data_limits") or {}
    months = [
        _dropped(
            {
                "month": month["month"],
                "precipitation_sum": _amount(
                    month.get("precipitation_sum_mm"), "mm", n_days=month["precipitation_n_days"],
                    coverage_percent=_percent(month["precipitation_coverage"]),
                ),
                "temperature_mean": _amount(
                    month.get("temperature_mean_c"), "degC", n_days=month["temperature_n_days"],
                    coverage_percent=_percent(month["temperature_coverage"]),
                ),
                "flags": list(month.get("flags") or []),
            }
        )
        for month in result.get("months", [])
    ]
    return _dropped(
        {
            **_frame(result),
            "dataset": result.get("dataset"),
            "period": result.get("period"),
            "months": months,
            "returned": len(months),
            "grid_distance": _amount(grid.get("distance_km"), "km"),
            "data_limits": {
                "first_day": limits.get("first_day"), "latest_day_expected_final": limits.get("latest_day_expected_final"),
                "era5_delay_days": limits.get("era5_delay_days"),
            } if limits else None,
            "definition": (
                "Per month: sum of the daily precipitation and mean of the daily mean temperature over the days with a value; "
                "n_days counts them. Quote only these numbers."
            ),
        }
    )


def compact_discharge(result: Mapping[str, Any]) -> dict[str, Any]:
    grid = result.get("grid") or {}
    months = [
        _dropped(
            {
                "month": month["month"],
                "discharge_mean": _amount(
                    month.get("river_discharge_mean_m3s"), "m3/s", n_days=month["n_days"],
                    coverage_percent=_percent(month["coverage"]),
                ),
                "flags": list(month.get("flags") or []),
            }
        )
        for month in result.get("months", [])
    ]
    return _dropped(
        {
            **_frame(result),
            "dataset": result.get("dataset"),
            "period": result.get("period"),
            "data_range": result.get("data_range"),
            "months": months,
            "returned": len(months),
            "grid_distance": _amount(grid.get("distance_km"), "km"),
            "documented_history_end": (result.get("data_limits") or {}).get("documented_history_end"),
            "definition": (
                "Per month: mean of the daily modelled discharge of the nearest river cell, over the days with a value. Quote "
                "only these numbers."
            ),
        }
    )


def compact_species(result: Mapping[str, Any]) -> dict[str, Any]:
    records = [
        _dropped(
            {
                "scientific_name": record["scientific_name"],
                "group": record.get("group"),
                "event_date": record.get("event_date"),
                "distance": _amount(record.get("distance_km"), "km"),
                "licence": record["licence"],
                "non_commercial_only": record["non_commercial_only"] or None,
                "basis_of_record": record.get("basis_of_record"),
                "dataset_name": record.get("dataset_name"),
            }
        )
        for record in result.get("records", [])[:CHAT_SPECIES_LIMIT]
    ]
    datasets = [
        _dropped({"title": item.get("title"), "citation": item.get("citation"), "licence": item["licence"]})
        for item in result.get("datasets", [])
    ]
    counts = [
        {"group": item["group"], "name": item["name"], "records": item["count"]}
        for item in result.get("group_counts", [])
        if item["count"] > 0
    ]
    search = result.get("search") or {}
    total = result.get("total_records", 0)
    return _dropped(
        {
            **_frame(result),
            "filters": result.get("filters"),
            "search_half_side": _amount(search.get("half_side_km"), "km"),
            "total_records": total,
            "returned": len(records),
            "truncated": total > len(records),
            "records_per_group": counts,
            "records": records,
            "datasets": datasets,
            "licence_summary": result.get("licence_summary"),
            "definition": (
                "Opportunistic records in a square around the site. records_per_group are GBIF's counts for the whole search; "
                "records shows only some. Not monitoring."
            ),
        }
    )


# --- handlers ---------------------------------------------------------------------------------------------------------


def _weather(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    site_id, date_from, date_to = _site_id(raw), _date(raw, "date_from", required=True), _date(raw, "date_to", required=True)
    assert date_from is not None and date_to is not None
    site = _located(ctx, site_id, allow_bathing=True)
    assert ctx.external is not None
    try:
        return compact_weather(ctx.external.weather(site, date_from, date_to))
    except ExternalInputError as error:
        raise ToolError(str(error)) from error


def _discharge(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    site_id, date_from, date_to = _site_id(raw), _date(raw, "date_from", required=True), _date(raw, "date_to", required=True)
    assert date_from is not None and date_to is not None
    site = _located(ctx, site_id, allow_bathing=False)
    assert ctx.external is not None
    try:
        return compact_discharge(ctx.external.discharge(site, date_from, date_to))
    except ExternalInputError as error:
        raise ToolError(str(error)) from error


def _species(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    site_id, group = _site_id(raw), _group(raw)
    date_from, date_to = _date(raw, "date_from", required=False), _date(raw, "date_to", required=False)
    site = _located(ctx, site_id, allow_bathing=False)
    assert ctx.external is not None
    try:
        return compact_species(ctx.external.species(site, group, date_from, date_to, CHAT_SPECIES_LIMIT))
    except ExternalInputError as error:
        raise ToolError(str(error)) from error


HANDLERS: dict[str, Callable[[ToolContext, Mapping[str, Any]], dict[str, Any]]] = {
    WEATHER_TOOL: _weather,
    DISCHARGE_TOOL: _discharge,
    SPECIES_TOOL: _species,
}


# --- summary and citations (used by oah.chat.tools) --------------------------------------------------------------------------


def summary(name: str, result: Mapping[str, Any]) -> str:
    status = result.get("status")
    if status == "external-unavailable":
        return f"external provider unavailable ({result.get('reason')})"
    if name == SPECIES_TOOL:
        return f"{result.get('total_records', 0)} records, status {status}"
    return f"{result.get('returned', 0)} months, status {status}"


def citations(name: str, result: Mapping[str, Any], entry: Callable[..., dict[str, Any]]) -> list[dict[str, Any]]:
    """One citation per result: the site, the provider, the period, and the external origin as the source."""
    site_id = (result.get("site") or {}).get("id")
    period = result.get("period") or {}
    label = {
        WEATHER_TOOL: "Weather context (ERA5 reanalysis, modelled)",
        DISCHARGE_TOOL: "River discharge context (GloFAS, modelled)",
        SPECIES_TOOL: "Species records (GBIF, opportunistic)",
    }[name]
    return [
        entry(
            site_id=site_id, parameter=label, period_start=period.get("date_from"), period_end=period.get("date_to"),
            source=result.get("origin"),
        )
    ]
