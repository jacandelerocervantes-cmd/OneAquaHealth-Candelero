"""Unit tests for geographic coordinate generalization."""

import pytest

from oah.privacy.geo_generalization import generalize_coordinates


def test_geo_generalization_mid_latitude_snapping():
    lat = 45.12345
    lon = 10.67890
    precision_km = 10.0
    gen_lat, gen_lon = generalize_coordinates(lat, lon, precision_km)

    # 10 km grid latitude step ~ 0.089831 deg
    delta_lat = 10.0 / 111.32
    expected_lat = round(round(lat / delta_lat) * delta_lat, 6)
    assert gen_lat == expected_lat
    assert abs(gen_lat - lat) <= delta_lat


def test_geo_generalization_error_margin_bound():
    lat = 38.0
    lon = 23.7
    precision_km = 5.0
    gen_lat, gen_lon = generalize_coordinates(lat, lon, precision_km)

    lat_diff_km = abs(gen_lat - lat) * 111.32
    assert lat_diff_km <= precision_km


def test_geo_generalization_invalid_inputs():
    with pytest.raises(ValueError):
        generalize_coordinates(95.0, 10.0, 5.0)

    with pytest.raises(ValueError):
        generalize_coordinates(45.0, -190.0, 5.0)

    with pytest.raises(ValueError):
        generalize_coordinates(45.0, 10.0, 0.0)


def test_geo_generalization_polar_clamp():
    lat = 89.95
    lon = 0.0
    gen_lat, gen_lon = generalize_coordinates(lat, lon, 10.0)
    assert -90.0 <= gen_lat <= 90.0
    assert -180.0 <= gen_lon <= 180.0
