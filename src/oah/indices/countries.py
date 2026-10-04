"""Country overview: which countries the backend knows, with the limits that apply and what data backs them.

The list comes from the live regime tables and the ``OAH_LIMITS_FILE`` overrides
(``oah.indices.regimes.known_countries``) plus the countries the sandbox Locations resolve to; nothing is
hard-coded here. Status labels (documented in ``docs/api_routes.md``):

- ``national-limits``: a national river-limit table exists and at least one site of the country was evaluated.
- ``eu-values-only``: no national table, at least one site evaluated (EU values are used).
- ``measurements-only``: no sandbox site was evaluated but the EEA Waterbase store holds sites of the country, which
  are listed with annual measurements and no index.
- ``no-evaluable-water-data``: no site of the country was evaluated and none is held by the store, whatever limits
  exist (``has_national_limits`` still says whether a national table is ready).
Every country also carries a per-source breakdown (``sources``); the totals add the sandbox and Waterbase sites.
Pure module: no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Sequence

from oah.indices.regimes import (
    country_limit_sources,
    has_national_limits,
    known_countries,
    regimes_by_location_ref,
    countries_by_location_ref,
)
from oah.waterbase.mapping import ATTRIBUTION, GROUP_WATER_CHEMISTRY, NO_LIMIT_REGIME, SOURCE_ID
from oah.waterbase.store import CountrySummary


def countries_overview(
    sites: Sequence[dict[str, Any]],
    locations: Sequence[dict[str, Any]],
    waterbase: Sequence[CountrySummary] = (),
    bathing: Mapping[str, dict[str, Any]] | None = None,
    sandbox_ranges: Mapping[str, tuple[str, str]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """``(countries, sites_without_country)`` from ``list_sites_with_status`` output, the Locations and, when the
    Waterbase store is available, its per-country summaries. ``bathing`` maps a country code to its bathing-water
    classification block (``oah.bathing.service.country_blocks``); it does not change the country's status.
    ``sandbox_ranges`` maps a country code to the first and last month (``YYYY-MM``) of its sandbox records
    (``oah.indices.sandbox_change.country_ranges``); each source entry carries its ``data_range`` so a client can show
    what period the source covers (null when the source holds no data for the country)."""
    regimes = regimes_by_location_ref(locations)
    resolved = countries_by_location_ref(locations)
    stored: Mapping[str, CountrySummary] = {item.country: item for item in waterbase}
    codes = sorted(
        set(known_countries()) | {c for c in resolved.values()} | set(stored)
        | {s["limit_country"] for s in sites if s.get("limit_country")}
    )
    overview: list[dict[str, Any]] = []
    for code in codes:
        own = [site for site in sites if site.get("limit_country") == code]
        evaluated = [site for site in own if site["status"] == "evaluated"]
        skipped = [site for site in own if site["status"] != "evaluated"]
        water_regimes = {regimes.get(f"Location/{site['id']}", "") for site in own if site.get("kind") == "water-body"} - {""}
        held = stored.get(code)
        if held is not None:
            water_regimes |= ({"surface"} if held.river_sites else set()) | ({NO_LIMIT_REGIME} if held.lake_sites else set())
        water_regimes_sorted = sorted(water_regimes)
        national = has_national_limits(code)
        if not evaluated:
            status = "measurements-only" if held is not None else "no-evaluable-water-data"
        else:
            status = "national-limits" if national else "eu-values-only"
        sandbox_span = (sandbox_ranges or {}).get(code)
        sources: list[dict[str, Any]] = [
            {
                "source": "real-sandbox", "total_sites": len(own), "evaluated_sites": len(evaluated), "skipped_sites": len(skipped),
                "data_range": {"first": sandbox_span[0], "last": sandbox_span[1]} if sandbox_span else None,
            }
        ]
        if held is not None:
            sources.append(
                {
                    "source": SOURCE_ID,
                    "total_sites": held.sites,
                    "river_sites": held.river_sites,
                    "lake_sites": held.lake_sites,
                    "sites_without_location": held.sites_without_location,
                    "first_year": held.first_year,
                    "last_year": held.last_year,
                    "attribution": ATTRIBUTION,
                    "parameter_groups": list(held.parameter_groups),
                    "data_range": {"first": held.first_month, "last": held.last_month} if held.first_month else None,
                }
            )
        groups = set(held.parameter_groups) if held is not None else set()
        if evaluated:
            groups.add(GROUP_WATER_CHEMISTRY)  # the sandbox index is computed from the closed (chemistry) parameter names
        overview.append(
            {
                "code": code,
                "status": status,
                "regime": None if not water_regimes_sorted else (water_regimes_sorted[0] if len(water_regimes_sorted) == 1 else "mixed"),
                "has_national_limits": national,
                "limit_sources": country_limit_sources(code),
                "evaluated_sites": len(evaluated),
                "skipped_sites": len(skipped),
                "skipped_non_water_sites": sum(1 for site in skipped if site.get("kind") != "water-body"),
                "total_sites": len(own) + (held.sites if held is not None else 0),
                "measurement_only_sites": held.sites if held is not None else 0,
                "latest_year": held.last_year if held is not None else None,
                "sources": sources,
                "parameter_groups": sorted(groups),
                "bathing_water": (bathing or {}).get(code),
            }
        )
    return overview, sum(1 for site in sites if not site.get("limit_country"))
