"""What the API and the chat tools call: Waterbase data as plain dictionaries, with a clear state when the store is absent."""

from __future__ import annotations

from typing import Any

from oah.waterbase import store
from oah.waterbase.mapping import ATTRIBUTION, codes_in_group, parameter_filter, parameter_names
from oah.waterbase.measurements import annual_records, site_entry
from oah.waterbase.store import CategoryName, CountrySummary, WaterbaseSite, month_position


def status_payload() -> dict[str, Any]:
    """The ``waterbase`` block of ``/sites`` and ``/countries``: the store state and, when built, its edition."""
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
    """A static published edition: ``snapshot`` dated by the store build (the edition itself is in ``status_payload``)."""
    return {"status": "snapshot", "as_of": store.provenance().get("build_date_utc"), "age_seconds": None}


def country_summaries() -> list[CountrySummary]:
    return store.countries_summary()


def located_counts() -> dict[str, tuple[int, int]]:
    """Per country ``(river sites, lake sites)`` with coordinates (for the catalogue); ``{}`` when the store is absent."""
    return store.located_counts()


def sites_page(
    country: str | None, q: str | None, limit: int, offset: int, category: CategoryName | None = None
) -> tuple[int, list[dict[str, Any]]]:
    """``(total matching, one page of /sites entries)``; ``(0, [])`` when the store is absent."""
    total, sites = store.list_sites(country, category, q, limit, offset)
    return total, [site_entry(site) for site in sites]


def find_site(site_id: str) -> WaterbaseSite | None:
    return store.get_site(site_id)


def known_parameter_names() -> list[str]:
    return parameter_names()


def measurement_page(
    site: WaterbaseSite,
    parameter: str | None,
    year_from: int | None,
    year_to: int | None,
    limit: int,
    group: str | None = None,
    resolution: str = "annual",
) -> tuple[int, list[dict[str, Any]]]:
    """``(total matching, records)`` of one site; an unknown ``parameter`` matches nothing (callers validate first).

    ``group`` (one of ``oah.waterbase.mapping.GROUPS``) keeps only the determinands of that group; a parameter outside
    the group, or an unknown group, matches nothing. ``resolution`` ``annual`` (default) gives one record per year,
    ``monthly`` one per month (``year_from`` and ``year_to`` then bound the years; at most ``limit`` records).
    """
    code: str | None = None
    matrix: str | None = None
    if parameter is not None:
        selected = parameter_filter(parameter)
        if selected is None:
            return 0, []
        code, matrix = selected
    codes = codes_in_group(group) if group is not None else None
    if codes is not None and code is not None and code not in codes:
        return 0, []
    if resolution == "monthly":
        first = month_position(year_from, 1) if year_from is not None else None
        last = month_position(year_to, 12) if year_to is not None else None
        total, monthly = store.site_monthly_series(site.site_id, code, first, last, limit, matrix=matrix, determinands=codes)
        return total, annual_records(site, monthly)
    total, rows = store.site_series(site.site_id, code, year_from, year_to, limit, matrix=matrix, determinands=codes)
    return total, annual_records(site, rows)
