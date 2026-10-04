"""What the API and the chat tools call: bathing-water classification as plain dictionaries, with a clear state when the
store is absent. Pure apart from the read-only store."""

from __future__ import annotations

from typing import Any

from oah.bathing import store
from oah.bathing.constants import ATTRIBUTION, NOTICE, PROFILE_NOTE, SOURCE_ID
from oah.bathing.store import BathingWater, Classification


def status_payload() -> dict[str, Any]:
    """The ``bathing_water`` status block: the store state and, when built, its edition and build date."""
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
    """A published edition: ``snapshot`` dated by the store build (the edition itself is in ``status_payload``)."""
    return {"status": "snapshot", "as_of": store.provenance().get("build_date_utc"), "age_seconds": None}


def entry(item: BathingWater) -> dict[str, Any]:
    """One bathing water as listed (never a concentration: the classification of its latest season)."""
    return {
        "id": item.bw_id,
        "country": item.country,
        "name": item.name or item.bw_id,
        "type": item.type,
        "geographical_constraint": item.geographical_constraint,
        "group_identifier": item.group_id,
        "latitude": item.lat,
        "longitude": item.lon,
        "location_status": "located" if item.lat is not None and item.lon is not None else "no-location",
        "bw_profile_url": item.profile_url,
        "first_season": item.first_season,
        "latest_season": item.last_season,
        "n_seasons": item.n_seasons,
        "latest_quality": item.latest_quality,
        "latest_quality_class": item.latest_quality_class,
        "origin": SOURCE_ID,
        "source": SOURCE_ID,
    }


def history_entry(item: Classification) -> dict[str, Any]:
    return {
        "season": item.season,
        "quality": item.quality,
        "quality_class": item.quality_class,
        "monitoring_calendar": item.monitoring_calendar,
        "management": item.management,
    }


def list_page(
    country: str | None, q: str | None, water_type: str | None, quality: str | None, limit: int, offset: int
) -> tuple[int, list[dict[str, Any]]]:
    """``(total matching, one page of entries)``; ``(0, [])`` when the store is absent."""
    total, items = store.list_bathing_waters(country, q, water_type, quality, limit, offset)
    return total, [entry(item) for item in items]


def find(bw_id: str) -> dict[str, Any] | None:
    """The bathing water and its season history, or None when the id is unknown (or the store is absent)."""
    item = store.get_bathing_water(bw_id)
    if item is None:
        return None
    return {**entry(item), "history": [history_entry(row) for row in store.history(bw_id)]}


def located_counts() -> dict[str, int]:
    """Per country the bathing waters with coordinates (for the catalogue); ``{}`` when the store is absent."""
    return store.located_counts()


def country_blocks() -> dict[str, dict[str, Any]]:
    """The ``bathing_water`` block of each country in the store, keyed by project country code."""
    return {
        summary.country: {
            "origin": SOURCE_ID,
            "bathing_waters": summary.bathing_waters,
            "classification_rows": summary.classification_rows,
            "first_season": summary.first_season,
            "latest_season": summary.latest_season,
            "latest_season_counts": summary.latest_season_counts,
            "attribution": ATTRIBUTION,
            "content": "classification-only",
        }
        for summary in store.countries_summary()
    }


__all__ = [
    "ATTRIBUTION", "NOTICE", "PROFILE_NOTE", "SOURCE_ID", "country_blocks", "entry", "find", "freshness",
    "history_entry", "list_page", "located_counts", "status_payload",
]
