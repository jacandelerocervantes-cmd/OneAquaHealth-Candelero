"""Coordinates for the external providers: validation, rounding, the GBIF search square and the haversine distance.

Coordinates come ONLY from the stores' sites (``oah.external.sites``); no route or tool accepts a raw latitude and
longitude from a user. They are rounded to ``COORD_DECIMALS`` decimals (about 1.1 km) before anything is sent or cached.

Derived transformations (docs/external_context.md section 5):

* rounding: ``round(value, COORD_DECIMALS)``;
* search square: half side ``h`` km around the rounded point; ``dlat = h / 111.32`` degrees (one degree of latitude is
  about 111.32 km), ``dlon = dlat / cos(lat)``; the polygon is written counter-clockwise, as GBIF's WKT geometry filter
  expects, with vertices rounded to 4 decimals;
* distance: the haversine great-circle distance on a sphere of radius ``EARTH_RADIUS_KM``.
"""
from __future__ import annotations

import math

from oah.external.constants import COORD_DECIMALS, EARTH_RADIUS_KM, GBIF_HALF_SIDE_KM

KM_PER_DEGREE_LATITUDE = 111.32
MAX_SEARCH_LATITUDE = 80.0  # beyond this the longitude span of a 10 km square is not meaningful; sites are in Europe


class CoordinateError(ValueError):
    """The coordinates are missing, not finite, outside the globe or the (0, 0) placeholder."""


def validate(latitude: object, longitude: object) -> tuple[float, float]:
    """The pair as floats, or ``CoordinateError``. ``(0, 0)`` is refused: it is a missing-value placeholder, not a place."""
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise CoordinateError("coordinates must be numbers")
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        raise CoordinateError("coordinates must be numbers")
    lat, lon = float(latitude), float(longitude)
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise CoordinateError("coordinates must be finite")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise CoordinateError("coordinates are outside the valid range")
    if lat == 0.0 and lon == 0.0:
        raise CoordinateError("coordinates (0, 0) are a placeholder, not a location")
    return lat, lon


def rounded(latitude: float, longitude: float) -> tuple[float, float]:
    """The point at the documented precision (``COORD_DECIMALS``); adding 0.0 turns a negative zero into zero."""
    return round(latitude, COORD_DECIMALS) + 0.0, round(longitude, COORD_DECIMALS) + 0.0


def search_square(latitude: float, longitude: float, half_side_km: float = GBIF_HALF_SIDE_KM) -> tuple[float, float, float, float]:
    """``(west, south, east, north)`` of the square of half side ``half_side_km`` around the (rounded) point."""
    lat, lon = rounded(latitude, longitude)
    if abs(lat) > MAX_SEARCH_LATITUDE:
        raise CoordinateError("latitude is too close to a pole for a search square")
    dlat = half_side_km / KM_PER_DEGREE_LATITUDE
    dlon = dlat / math.cos(math.radians(lat))
    west, east = lon - dlon, lon + dlon
    if west < -180.0 or east > 180.0:
        raise CoordinateError("the search square crosses the antimeridian")
    return round(west, 4), round(lat - dlat, 4), round(east, 4), round(lat + dlat, 4)


def search_wkt(latitude: float, longitude: float, half_side_km: float = GBIF_HALF_SIDE_KM) -> str:
    """The counter-clockwise WKT polygon ``POLYGON((lon lat, ...))`` of ``search_square``."""
    west, south, east, north = search_square(latitude, longitude, half_side_km)
    ring = [(west, south), (east, south), (east, north), (west, north), (west, south)]
    return "POLYGON((" + ", ".join(f"{lon:.4f} {lat:.4f}" for lon, lat in ring) + "))"


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi, dlam = phi2 - phi1, math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))
