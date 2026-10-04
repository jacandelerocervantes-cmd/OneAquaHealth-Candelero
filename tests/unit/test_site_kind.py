"""Deterministic site kind: water body, air-quality station, city or other."""

import pytest

from oah.indices.site_kind import site_kind

RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
CITY = [{"coding": [{"system": "http://snomed.info/sct", "code": "288520005"}]}]


@pytest.mark.parametrize(
    ("location", "kind"),
    [
        ({"id": "Loc-Almyros", "type": RIVER}, "water-body"),
        ({"id": "Loc-Almyros-Estuary"}, "water-body"),
        ({"id": "Loc-Giofyros-LowerReach"}, "water-body"),
        ({"id": "Loc-X", "description": "Coastal stream segment"}, "water-body"),
        ({"id": "Loc-BN-01", "name": "Air quality station Benevento 1", "type": CITY}, "air-quality-station"),
        ({"id": "Loc-Benevento", "description": "City of Benevento (Campania, IT)", "type": CITY}, "city"),
        ({"id": "Loc-Nordre-Aker"}, "other"),
        ({}, "other"),
    ],
)
def test_site_kind_rules(location, kind):
    assert site_kind(location) == kind


def test_the_river_type_code_wins_over_a_station_word():
    assert site_kind({"id": "Loc-1", "name": "River station", "type": RIVER}) == "water-body"


def test_a_keyword_must_be_a_whole_word():
    assert site_kind({"id": "Loc-Creekside-Mall"}) == "other"
    assert site_kind({"id": "Loc-Stationary"}) == "other"
