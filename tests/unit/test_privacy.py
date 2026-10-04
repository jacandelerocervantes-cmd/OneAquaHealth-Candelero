"""Tests for k-anonymity, geographic generalization, and consent validation.

All data here is synthetic and illustrative; no real citizen location data is used.
Written by the auditor (Claude) against code Antigravity left unverified when its
credit window ended; see docs/handoff/LEDGER.md for the corresponding entry.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.privacy.consent import ConsentRecord, is_active
from oah.privacy.geo_generalization import generalize_coordinates
from oah.privacy.k_anonymity import enforce_k_anonymity


# --- k-anonymity -------------------------------------------------------------------------


def test_group_below_k_raises_and_names_the_group():
    records = [
        {"site_id": "Loc-A"},
        {"site_id": "Loc-A"},
        {"site_id": "Loc-B"},
    ]
    with pytest.raises(ValueError) as error:
        enforce_k_anonymity(records, quasi_identifiers=["site_id"], k=3)
    message = str(error.value)
    assert "Loc-A" in message
    assert "Loc-B" in message


def test_all_groups_meeting_k_pass_silently():
    records = [{"site_id": "Loc-A"}] * 5 + [{"site_id": "Loc-B"}] * 5
    result = enforce_k_anonymity(records, quasi_identifiers=["site_id"], k=5)
    assert result == records


def test_k_equal_one_is_a_no_op_even_with_singleton_groups():
    records = [{"site_id": "Loc-A"}, {"site_id": "Loc-B"}]
    result = enforce_k_anonymity(records, quasi_identifiers=["site_id"], k=1)
    assert result == records


def test_empty_records_list_is_a_no_op():
    assert enforce_k_anonymity([], quasi_identifiers=["site_id"], k=5) == []


def test_k_below_one_raises():
    with pytest.raises(ValueError, match="at least 1"):
        enforce_k_anonymity([{"site_id": "Loc-A"}], quasi_identifiers=["site_id"], k=0)


def test_multi_attribute_quasi_identifier_groups_by_the_full_tuple():
    records = [
        {"site_id": "Loc-A", "week": 1},
        {"site_id": "Loc-A", "week": 1},
        {"site_id": "Loc-A", "week": 2},
    ]
    with pytest.raises(ValueError) as error:
        enforce_k_anonymity(records, quasi_identifiers=["site_id", "week"], k=2)
    assert "'week': 2" in str(error.value)


def test_lists_every_violating_group_not_only_the_first():
    records = [{"site_id": "Loc-A"}, {"site_id": "Loc-B"}, {"site_id": "Loc-C"}] * 1
    with pytest.raises(ValueError) as error:
        enforce_k_anonymity(records, quasi_identifiers=["site_id"], k=2)
    message = str(error.value)
    assert "3 equivalence class" in message
    for site in ("Loc-A", "Loc-B", "Loc-C"):
        assert site in message


# --- geographic generalization ------------------------------------------------------------


def test_nearby_points_at_mid_latitude_snap_to_the_same_cell():
    # Two points ~200 m apart, well inside a 5 km cell, at a mid-latitude (Almyros, Crete).
    base_lat, base_lon = 35.33399, 25.04834
    near_lat, near_lon = 35.33580, 25.04900
    assert generalize_coordinates(base_lat, base_lon, precision_km=5.0) == generalize_coordinates(
        near_lat, near_lon, precision_km=5.0
    )


def test_out_of_range_latitude_and_longitude_raise():
    with pytest.raises(ValueError, match="latitude"):
        generalize_coordinates(91.0, 0.0, precision_km=1.0)
    with pytest.raises(ValueError, match="longitude"):
        generalize_coordinates(0.0, 181.0, precision_km=1.0)


def test_non_positive_precision_raises():
    with pytest.raises(ValueError, match="precision_km"):
        generalize_coordinates(35.0, 25.0, precision_km=0.0)
    with pytest.raises(ValueError, match="precision_km"):
        generalize_coordinates(35.0, 25.0, precision_km=-1.0)


def test_near_pole_does_not_raise_or_divide_by_zero():
    # Longitude generalization near the pole is intentionally coarse (documented limitation);
    # this only asserts the function stays defined and returns valid coordinates.
    lat, lon = generalize_coordinates(89.95, 10.0, precision_km=5.0)
    assert -90.0 <= lat <= 90.0
    assert -180.0 <= lon <= 180.0


@given(
    lat=st.floats(min_value=-85.0, max_value=85.0, allow_nan=False, allow_infinity=False),
    lon=st.floats(min_value=-179.0, max_value=179.0, allow_nan=False, allow_infinity=False),
    precision_km=st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=200)
def test_generalized_point_stays_within_half_a_cell_of_the_original(lat, lon, precision_km):
    gen_lat, gen_lon = generalize_coordinates(lat, lon, precision_km)
    km_per_lat_deg = 111.32
    delta_lat = precision_km / km_per_lat_deg
    assert abs(gen_lat - lat) <= delta_lat / 2 + 1e-6


def test_known_limitation_points_straddling_a_latitude_cell_boundary_can_diverge():
    """Documents a real, inherent limitation of any fixed-grid generalization: the longitude
    step is derived from the GENERALIZED latitude (fixed by the auditor so points sharing a
    latitude cell always share a longitude grid; see git history / LEDGER for the before/after).
    Two points that are close together but fall on opposite sides of a latitude cell boundary
    can still round to different latitude cells and therefore use different longitude grids,
    landing in different generalized coordinates even though they are within precision_km of
    each other. This is a boundary (fencepost) effect common to all fixed-grid methods and is
    not fixed by this module; a caller anonymizing points near a cell boundary should not
    assume they always collapse together. See docs/math_registry.md for this note.
    """
    km_per_lat_deg = 111.32
    precision_km = 5.0
    delta_lat = precision_km / km_per_lat_deg
    # Place two points a few metres apart, straddling a latitude grid line at gen_lat = 0.
    boundary_lat = delta_lat / 2.0
    just_below, just_above = boundary_lat - 0.0001, boundary_lat + 0.0001
    gen_below = generalize_coordinates(just_below, 25.0, precision_km)
    gen_above = generalize_coordinates(just_above, 25.0, precision_km)
    assert gen_below[0] != gen_above[0]  # they fall in different latitude cells, as documented


# --- consent -------------------------------------------------------------------------------


def _consent(granted_offset_hours=0, revoked_offset_hours=None):
    base = datetime(2026, 1, 1, tzinfo=UTC)
    granted = base + timedelta(hours=granted_offset_hours)
    revoked = base + timedelta(hours=revoked_offset_hours) if revoked_offset_hours is not None else None
    return ConsentRecord("subj-pseudo-1", "water_quality_citizen_science", granted, revoked)


def test_active_before_revocation():
    consent = _consent(granted_offset_hours=0, revoked_offset_hours=10)
    at_time = datetime(2026, 1, 1, 5, tzinfo=UTC)
    assert is_active(consent, at_time) is True


def test_inactive_after_revocation():
    consent = _consent(granted_offset_hours=0, revoked_offset_hours=10)
    at_time = datetime(2026, 1, 1, 11, tzinfo=UTC)
    assert is_active(consent, at_time) is False


def test_inactive_exactly_at_revocation_instant():
    consent = _consent(granted_offset_hours=0, revoked_offset_hours=10)
    at_time = datetime(2026, 1, 1, 10, tzinfo=UTC)
    assert is_active(consent, at_time) is False


def test_inactive_before_granted_at():
    consent = _consent(granted_offset_hours=5)
    at_time = datetime(2026, 1, 1, 2, tzinfo=UTC)
    assert is_active(consent, at_time) is False


def test_active_exactly_at_granted_instant_with_no_revocation():
    consent = _consent(granted_offset_hours=5, revoked_offset_hours=None)
    at_time = datetime(2026, 1, 1, 5, tzinfo=UTC)
    assert is_active(consent, at_time) is True


def test_revoked_before_granted_raises_at_construction():
    base = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="cannot be prior to"):
        ConsentRecord("subj-pseudo-1", "scope", base, base - timedelta(hours=1))
