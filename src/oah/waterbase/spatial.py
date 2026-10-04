"""The Waterbase spatial table: monitoring sites with their names, water bodies and coordinates.

Privacy (``docs/waterbase_store.md``): a site whose ``confidentialityStatus`` is anything other than ``F`` (free for
publication) never keeps its coordinates, even when the source supplies them; the number of coordinates dropped for that
reason is counted (``coordinates_withheld``).
"""
from __future__ import annotations

import csv
from collections.abc import Iterable
from dataclasses import dataclass, replace

from oah.waterbase.aggregate import _to_float
from oah.waterbase.mapping import COUNTRY_CODES, location_publishable


@dataclass(frozen=True)
class SpatialSite:
    name: str | None
    water_body_id: str | None
    water_body_name: str | None
    lat: float | None
    lon: float | None
    confidentiality: str | None
    coordinates_withheld: bool = False  # the source gave coordinates and they were dropped because the site is restricted


def _coordinate(text: str, limit: float) -> float | None:
    value = _to_float(text.strip())
    return value if value is not None and -limit <= value <= limit else None


def _merge(existing: SpatialSite, candidate: SpatialSite) -> SpatialSite:
    """Two rows of one site: a restricted row wins (its status is kept, coordinates stay dropped); else the row with coordinates."""
    existing_restricted = not location_publishable(existing.confidentiality)
    candidate_restricted = not location_publishable(candidate.confidentiality)
    if existing_restricted or candidate_restricted:
        chosen = existing if existing_restricted else candidate
        return replace(
            chosen, lat=None, lon=None, coordinates_withheld=existing.coordinates_withheld or candidate.coordinates_withheld
        )
    return candidate if existing.lat is None and candidate.lat is not None else existing


def read_spatial(lines: Iterable[str]) -> dict[tuple[str, str], SpatialSite]:
    """Monitoring sites of the spatial table, keyed by (project country code, site id).

    Rows without a site identifier are water bodies, not sites, and are skipped. A site that appears twice keeps the
    row with coordinates (the first one when both or neither have them), unless one of its rows is restricted: then the
    site is restricted. The placeholder name ``UNKNOWN`` becomes null. Coordinates of a site whose confidentiality status
    is not ``F`` are dropped (and ``coordinates_withheld`` records that the source had them).
    """
    sites: dict[tuple[str, str], SpatialSite] = {}
    for row in csv.DictReader(lines):
        country = COUNTRY_CODES.get((row.get("countryCode") or "").strip())
        site_id = (row.get("monitoringSiteIdentifier") or "").strip()
        if country is None or not site_id:
            continue
        name = (row.get("monitoringSiteName") or "").strip()
        lat, lon = _coordinate(row.get("lat") or "", 90.0), _coordinate(row.get("lon") or "", 180.0)
        status = (row.get("confidentialityStatus") or "").strip() or None
        has_coordinates = lat is not None and lon is not None
        publishable = location_publishable(status)
        candidate = SpatialSite(
            name=None if not name or name.upper() == "UNKNOWN" else name,
            water_body_id=(row.get("waterBodyIdentifier") or "").strip() or None,
            water_body_name=(row.get("waterBodyName") or "").strip() or None,
            lat=lat if has_coordinates and publishable else None,
            lon=lon if has_coordinates and publishable else None,
            confidentiality=status,
            coordinates_withheld=has_coordinates and not publishable,
        )
        existing = sites.get((country, site_id))
        sites[(country, site_id)] = candidate if existing is None else _merge(existing, candidate)
    return sites
