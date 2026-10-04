"""Chat tools over sites: countries, site lists, the CCME index, per-parameter measurements and the QC summary."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from oah.chat.errors import ToolError
from oah.chat.tools.approximate import measurements_block, record_block
from oah.chat.tools.context import ToolContext
from oah.chat.tools.results import MAX_TOOL_RESULT_CHARS, _amount, _shrink_list
from oah.chat.tools.validation import (
    _date_argument,
    _parse_country,
    _parse_location,
    _parse_query,
    _text_argument,
)
from oah.indices.site_measurements import parameter_names
from oah.waterbase.mapping import ATTRIBUTION as WATERBASE_ATTRIBUTION
from oah.waterbase.mapping import SOURCE_ID as WATERBASE_SOURCE
from oah.waterbase.mapping import parameter_names as waterbase_parameter_names


DEFAULT_MEASUREMENT_LIMIT = 50
MAX_LISTED_STORE_SITES = 60  # Waterbase sites fetched for one list_sites call (the result is cut again by size)


def compact_record(record: Mapping[str, Any]) -> dict[str, Any]:
    unit = record.get("unit")
    compact: dict[str, Any] = {
        "observation_id": record.get("observation_id"),
        "parameter": record.get("parameter"),
        "statistic": record.get("statistic"),
        "value": _amount(record.get("value"), unit, comparator=record.get("comparator")),
        "min": _amount(record.get("min"), unit),
        "max": _amount(record.get("max"), unit),
        "period_start": record.get("period_start"),
        "period_end": record.get("period_end"),
        "limit": _amount(
            record.get("limit"), record.get("limit_unit"), type=record.get("limit_type"), range=record.get("limit_range")
        ),
        "limit_basis": record.get("limit_basis"),
        "status": record.get("status"),
        "data_quality_flags": list(record.get("data_quality_flags") or []),
        "year": record.get("year"),
        "n": record.get("n"),
        "n_below_loq": record.get("n_below_loq"),
        "matrix": record.get("matrix"),
        "group": record.get("group"),
    }
    return {key: value for key, value in compact.items() if value is not None}


_INDEX_KEYS = (
    "status", "reason", "total_observations", "evaluable_measurements", "failed_measurements", "ccme_wqi",
    "limit_regime", "limit_country", "limit_basis", "confidence", "confidence_note", "distinct_parameters_count",
    "excluded_data_quality_observations", "objective_limits_source",
)


def _site_summary(site: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "id", "name", "kind", "status", "ccme_wqi", "ccme_class", "limit_regime", "limit_country", "confidence", "reason",
        "source", "water_category", "location_status", "first_year", "last_year",
    )
    summary = {key: site[key] for key in keys if site.get(key) is not None}
    if site.get("source") == WATERBASE_SOURCE:
        summary.pop("reason", None)  # the same fixed sentence for every Waterbase site: said once in the result
    return summary


def _stored_site(ctx: ToolContext, location_id: str) -> dict[str, Any] | None:
    return ctx.waterbase_site(location_id) if ctx.waterbase_site is not None else None


def _check_site_country(ctx: ToolContext, location_id: str) -> None:
    if ctx.country is None:
        return
    site = _stored_site(ctx, location_id) or next((item for item in ctx.sites() if item.get("id") == location_id), None)
    site_country = site.get("limit_country") if site else None
    if site_country != ctx.country:
        raise ToolError(
            f"That site belongs to country {site_country or 'unknown'}, not the selected country {ctx.country}. "
            "Limits of different countries are never mixed; tell the user to change the country selector."
        )


def _list_countries(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    overview, without_country = ctx.countries()
    keys = (
        "code", "status", "regime", "has_national_limits", "limit_sources", "evaluated_sites", "skipped_sites",
        "total_sites", "measurement_only_sites", "latest_year", "sources", "parameter_groups", "bathing_water",
    )
    held = any(item.get("measurement_only_sites") for item in overview)
    return {
        "origin": "real-mixed" if held else "real-sandbox",
        "selected_country": ctx.country,
        "countries": [{key: item.get(key) for key in keys} for item in overview],
        "sites_without_country": without_country,
    }


def _list_sites(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    requested = _parse_country(raw)
    query = _parse_query(raw)
    if requested is not None and ctx.country is not None and requested != ctx.country:
        raise ToolError(f"The selected country is {ctx.country}; other countries are not mixed into this answer.")
    country = requested or ctx.country
    if requested is not None and requested not in {item["code"] for item in ctx.countries()[0]}:
        raise ToolError("Unknown country code; list_countries shows the known ones.")
    needle = query.lower() if query else None
    selected = [
        site
        for site in ctx.sites()
        if (country is None or site.get("limit_country") == country)
        and (needle is None or needle in str(site.get("name", "")).lower() or needle in str(site.get("id", "")).lower())
    ]
    stored_total, stored = (
        ctx.waterbase_sites(country, query, MAX_LISTED_STORE_SITES) if ctx.waterbase_sites is not None else (0, [])
    )
    listed = [*(_site_summary(site) for site in selected), *(_site_summary(site) for site in stored)]
    sources = ([] if not selected else ["real-sandbox"]) + ([WATERBASE_SOURCE] if stored else [])
    result: dict[str, Any] = {
        "origin": "real-mixed" if len(sources) == 2 else (sources[0] if sources else "real-sandbox"),
        "country": country,
        "query": query,
        "total_sites": len(selected) + stored_total,
        "returned": len(listed),
        "truncated": len(selected) + stored_total > len(listed),
        "sites": listed,
    }
    if stored:
        result["waterbase_note"] = "real-eea-waterbase sites have annual aggregates and no CCME index; no-location means no coordinates."
        result["attribution"] = WATERBASE_ATTRIBUTION
    _shrink_list(result, "sites", MAX_TOOL_RESULT_CHARS)
    return result


def _get_site_index(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    location_id = _parse_location(raw)
    _check_site_country(ctx, location_id)
    if _stored_site(ctx, location_id) is not None:
        raise ToolError(
            "That is an EEA Waterbase site: no index is computed for it (annual measurements only); "
            "use get_site_measurements."
        )
    payload = ctx.index(location_id)
    if payload is None:
        raise ToolError("Unknown site: no water-quality data for that id.")
    return {"location_id": location_id, **{key: payload[key] for key in _INDEX_KEYS if key in payload}}


def _get_site_measurements(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    location_id = _parse_location(raw)
    parameter = _text_argument(raw, "parameter", required=False)
    if parameter is not None:
        known = {name.lower(): name for name in [*parameter_names(), *waterbase_parameter_names()]}
        if parameter.lower() not in known:
            raise ToolError(f"Unknown parameter; known parameters: {', '.join(sorted(known.values()))}.")
        parameter = known[parameter.lower()]
    date_from, date_to = _date_argument(raw, "date_from"), _date_argument(raw, "date_to")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ToolError("date_from must not be after date_to.")
    limit = raw.get("limit", DEFAULT_MEASUREMENT_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ToolError("Argument limit must be an integer from 1 to 500.")
    _check_site_country(ctx, location_id)
    records = ctx.measurements(location_id, parameter, date_from, date_to)
    if records is None:
        raise ToolError("Unknown site.")
    from_store = records[0].get("origin") == WATERBASE_SOURCE if records else _stored_site(ctx, location_id) is not None
    shown = [compact_record(record) for record in records[:limit]]
    for record in shown:
        record["approximate"] = record_block(record, annual_aggregate_without_count=not from_store)  # see oah.chat.precision
        if record["approximate"] is None:
            del record["approximate"]
    result: dict[str, Any] = {
        "origin": WATERBASE_SOURCE if from_store else "real-sandbox",
        "location_id": location_id,
        "parameter": parameter,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "limit": limit,
        "total_matching": len(records),
        "returned": len(shown),
        "truncated": len(records) > limit,
        "limit_regime": records[0].get("limit_regime") if records else None,
        "limit_country": records[0].get("limit_country") if records else None,
        "records": shown,
    }
    if shown:
        result["approximate"] = measurements_block(shown)  # the basis, and whether any shown record is low precision
    if from_store:
        result["data_freshness"] = {"status": "snapshot", "as_of": None}  # a published edition, not a live feed
        result["attribution"] = WATERBASE_ATTRIBUTION
        result["note"] = "Annual means of quantified samples; values below the quantification limit are counted in n_below_loq, not in the mean."
    _shrink_list(result, "records", MAX_TOOL_RESULT_CHARS)
    return result


def _get_qc_summary(ctx: ToolContext, raw: Mapping[str, Any]) -> dict[str, Any]:
    report = ctx.qc()
    keys = ("total_observations", "findings", "excluded_observations", "excluded_observations_total")
    return {key: report[key] for key in keys if key in report}
