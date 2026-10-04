"""What the API and the chat tools call: bathing-water samples as plain dictionaries, with a clear state when the store is
absent. Pure apart from the read-only stores."""

from __future__ import annotations

from datetime import date
from typing import Any

from oah.bathing import store as bathing_store
from oah.bathing_samples import store
from oah.bathing_samples.constants import (
    ATTRIBUTION,
    DEFAULT_LIMIT,
    INDICATOR_LABELS,
    INDICATORS,
    KIND_NAMES,
    KIND_QUANTIFIED,
    QUANTIFIED_KINDS,
    SOURCE_ID,
    UNIT,
    UNIT_STATEMENT,
)
from oah.bathing_samples.store import IndicatorStats, SampleRecord

VALUE_DECIMALS = 6


def _round(value: float | None) -> float | None:
    if value is None:
        return None
    rounded = round(value, VALUE_DECIMALS)
    return 0.0 if rounded == 0 else rounded


def status_payload() -> dict[str, Any]:
    """The ``bathing_samples`` status block: the store state and, when built, its edition and build date."""
    status = store.store_status()
    if not status.ready:
        return {"state": status.state, "detail": status.detail, "edition": None, "attribution": None, "build_date_utc": None}
    info = store.provenance()
    return {
        "state": "ready",
        "detail": "ready",
        "edition": info.get("edition"),
        "attribution": info.get("attribution", ATTRIBUTION),
        "build_date_utc": info.get("build_date_utc"),
    }


def freshness() -> dict[str, Any]:
    """A snapshot of the service dated by the store build."""
    return {"status": "snapshot", "as_of": store.provenance().get("build_date_utc"), "age_seconds": None}


def indicator_entry(value: int | None, status: str | None, kind: str) -> dict[str, Any]:
    """One indicator of one sample. ``value`` is a concentration ONLY for the kinds quantified and confirmed-high; for a
    detection-limit, missing or unrecognised value it is null and the number as reported (a limit of detection, the
    number as reported, for example a limit of detection, is in ``reported_value`` so nothing is hidden and nothing is mistaken
    for a result; the placeholder 0 that the source writes for a missing value is not shown at all."""
    quantified = kind in QUANTIFIED_KINDS
    return {
        "value": value if quantified else None,
        "reported_value": None if kind in ("I", "M") else value,
        "status": status,
        "kind": KIND_NAMES[kind],
    }


def sample_entry(item: SampleRecord) -> dict[str, Any]:
    return {
        "uid": item.uid,
        "sample_date": item.sample_date,
        "season": item.season,
        "sample_status": item.sample_status,
        "observation_status": item.obs_status,
        "has_remarks": item.has_remarks,
        "escherichia_coli": indicator_entry(item.ec_value, item.ec_status, item.ec_kind),
        "intestinal_enterococci": indicator_entry(item.ie_value, item.ie_status, item.ie_kind),
    }


def summary_entry(stats: IndicatorStats | None) -> dict[str, Any] | None:
    if stats is None:
        return None
    return {
        "n_samples_in_range": stats.n_rows,
        "n_quantified": stats.n_quantified,
        "n_confirmed_high": stats.n_confirmed_high,
        "n_detection_limit": stats.n_detection_limit,
        "n_missing": stats.n_missing,
        "n_unrecognised": stats.n_unknown_status + stats.n_invalid,
        "min": stats.low,
        "max": stats.high,
        "mean": _round(stats.mean),
        "median": _round(stats.median),
    }


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def link_for(bw_id: str) -> dict[str, Any]:
    """Whether samples exist for a bathing water and the last sample date (the ``samples`` block of the history response)."""
    status = store.store_status()
    found = store.site_samples(bw_id) if status.ready else None
    return {
        "state": status.state,
        "available": found is not None,
        "n_samples": found.n_samples if found else 0,
        "first_sample_date": found.first_date if found else None,
        "last_sample_date": found.last_date if found else None,
        "first_season": found.first_season if found else None,
        "last_season": found.last_season if found else None,
        "path": f"/bathing-waters/{bw_id}/samples" if found else None,
    }


def known_bathing_water(bw_id: str) -> dict[str, Any] | None:
    """The bathing water as the classification store or the samples store knows it (None when neither does)."""
    item = bathing_store.get_bathing_water(bw_id)
    if item is not None:
        return {"id": item.bw_id, "country": item.country, "name": item.name or item.bw_id, "type": item.type}
    found = store.site_samples(bw_id)
    if found is not None:
        return {"id": found.bw_id, "country": found.country, "name": found.bw_id, "type": None}
    return None


def samples_for(
    bw_id: str, date_from: date | None, date_to: date | None, season: int | None, limit: int = DEFAULT_LIMIT,
    descending: bool = False,
) -> dict[str, Any] | None:
    """The samples of one bathing water with a summary over ALL matching samples; None when the identifier is unknown."""
    site = known_bathing_water(bw_id)
    if site is None:
        return None
    start, end = _iso(date_from), _iso(date_to)
    total, items = store.list_samples(bw_id, start, end, season, limit, descending)
    held = store.site_samples(bw_id)
    summary = {
        name: summary_entry(store.indicator_stats(bw_id, name, start, end, season)) for name in INDICATORS
    }
    flags: list[str] = []
    status = store.store_status()
    if not status.ready:
        flags.append("store-not-ready")
    elif held is None:
        flags.append("no-samples-for-bathing-water")
    elif total == 0:
        flags.append("no-samples-in-range")
        if (date_from is not None and start is not None and start > held.last_date) or (
            date_to is not None and end is not None and end < held.first_date
        ):
            flags.append("range-outside-data")
    if total > len(items):
        flags.append("truncated")
    for name, entry in summary.items():
        if entry is None:
            continue
        if entry["n_detection_limit"]:
            flags.append("detection-limit-values-excluded")
        if entry["n_missing"]:
            flags.append("missing-values-excluded")
        if entry["n_unrecognised"]:
            flags.append("unrecognised-status-values-excluded")
        if entry["n_confirmed_high"]:
            flags.append("confirmed-high-values-included")
    return {
        "origin": SOURCE_ID,
        "unit": UNIT,
        "unit_statement": UNIT_STATEMENT,
        "bathing_samples": status_payload(),
        "bathing_water": site,
        "filters": {"date_from": start, "date_to": end, "season": season, "order": "desc" if descending else "asc"},
        "data_range": (
            {
                "first_sample_date": held.first_date, "last_sample_date": held.last_date,
                "first_season": held.first_season, "last_season": held.last_season,
            }
            if held else None
        ),
        "total_matching": total,
        "returned": len(items),
        "samples": [sample_entry(item) for item in items],
        "summary": summary,
        "flags": sorted(set(flags)),
    }


def country_blocks() -> dict[str, dict[str, Any]]:
    """The ``samples`` block of each country in the store, keyed by project country code."""
    return {
        summary.country: {
            "origin": SOURCE_ID,
            "bathing_waters_with_samples": summary.bathing_waters,
            "n_samples": summary.n_samples,
            "n_quantified": {"escherichia_coli": summary.n_quantified_ec, "intestinal_enterococci": summary.n_quantified_ie},
            "first_sample_date": summary.first_date,
            "last_sample_date": summary.last_date,
            "first_season": summary.first_season,
            "last_season": summary.last_season,
            "unit": UNIT,
            "attribution": ATTRIBUTION,
            "content": "individual-samples-no-thresholds",
        }
        for summary in store.countries_summary()
    }


__all__ = [
    "ATTRIBUTION", "INDICATOR_LABELS", "KIND_QUANTIFIED", "SOURCE_ID", "country_blocks", "freshness", "indicator_entry",
    "known_bathing_water", "link_for", "sample_entry", "samples_for", "status_payload", "summary_entry",
]
