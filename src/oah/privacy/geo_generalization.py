"""Geographic spatial coordinate generalization to spatial grid cells.

Grid cell spacing formulas:
    - Latitude step: delta_lat = precision_km / 111.32 (degrees)
    - Longitude step: delta_lon = precision_km / (111.32 * cos(radians(lat))) (degrees)

At mid-latitudes (~45 deg N/S), 1 deg lat ~ 111.32 km, 1 deg lon ~ 78.7 km.
The maximum spatial displacement error margin is approximately +/- (precision_km / 2)
along each axis under standard conditions.

Known limitation (fencepost effect at grid boundaries):
    The longitude step is derived from the GENERALIZED latitude (not the raw input latitude),
    so any two points that snap to the same latitude cell are guaranteed to use the same
    longitude grid and generalize consistently. Two points that straddle a latitude cell
    boundary, however, can still fall into different latitude cells and therefore use
    different longitude grids, landing in different generalized coordinates even though they
    are within precision_km of each other. This is inherent to fixed-grid generalization
    methods and is not resolved by this module; see
    tests/unit/test_privacy.py::test_known_limitation_points_straddling_a_latitude_cell_boundary_can_diverge.

Note:
    Spatial generalization alone reduces spatial granularity but does NOT guarantee k-anonymity
    without checking population density across quasi-identifiers (enforce_k_anonymity).
"""

from __future__ import annotations

import math


def generalize_coordinates(
    lat: float,
    lon: float,
    precision_km: float,
) -> tuple[float, float]:
    """Snap geographic coordinates (lat, lon) to a grid of approximate resolution precision_km.

    Args:
        lat: Latitude in degrees in range [-90.0, 90.0].
        lon: Longitude in degrees in range [-180.0, 180.0].
        precision_km: Grid cell resolution in kilometers (> 0.0).

    Returns:
        Tuple of (generalized_lat, generalized_lon) rounded to 6 decimal places.

    Raises:
        ValueError: If lat or lon are out of valid geographic range, or precision_km <= 0.0.
    """
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        raise ValueError("lat and lon must be numerical values.")

    lat_val = float(lat)
    lon_val = float(lon)

    if not (-90.0 <= lat_val <= 90.0):
        raise ValueError(f"latitude out of valid range [-90.0, 90.0]: {lat_val}")

    if not (-180.0 <= lon_val <= 180.0):
        raise ValueError(f"longitude out of valid range [-180.0, 180.0]: {lon_val}")

    if not isinstance(precision_km, (int, float)) or precision_km <= 0.0:
        raise ValueError(f"precision_km must be positive (> 0.0), got {precision_km}")

    km_per_lat_deg = 111.32
    delta_lat = precision_km / km_per_lat_deg
    gen_lat = round(lat_val / delta_lat) * delta_lat

    # Derive the longitude step from the GENERALIZED latitude, not the raw input latitude.
    # Two nearby points that fall in the same latitude band must share the same longitude
    # grid, or they can snap to different longitude cells despite being well inside one
    # precision_km cell (verified: using lat_val here made two points ~200 m apart, at
    # latitudes 0.0018 deg apart, generalize to different longitudes under a 5 km cell).
    # Near poles (|lat| >= 89.9), clamp cos(lat) to avoid zero division or infinite grid steps.
    cos_lat = max(math.cos(math.radians(gen_lat)), math.cos(math.radians(89.9)))
    delta_lon = precision_km / (km_per_lat_deg * cos_lat)
    gen_lon = round(lon_val / delta_lon) * delta_lon

    # Clamp and normalize
    gen_lat = max(-90.0, min(90.0, round(gen_lat, 6)))

    # Wrap longitude to [-180.0, 180.0]
    while gen_lon > 180.0:
        gen_lon -= 360.0
    while gen_lon < -180.0:
        gen_lon += 360.0

    gen_lon = round(gen_lon, 6)

    return (gen_lat, gen_lon)
