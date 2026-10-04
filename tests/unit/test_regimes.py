"""Per-location limit regimes (drinking vs surface water), dated lead limit and the corrected copper limit."""

from datetime import UTC, datetime

import pytest

from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.regimes import (
    DRINKING,
    SURFACE,
    observation_instant,
    regime_for_location,
    regimes_by_location_ref,
    resolve_limit,
)
from oah.indices.water_parameter_limits import CLOSED_PARAM_MAPPING

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = {"id": "R1", "type": [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]}
CITY = {"id": "C1", "type": [{"coding": [{"system": "http://snomed.info/sct", "code": "288520005"}]}]}


def _obs(loc, code, value, unit="ug/L", period_end=None):
    obs = {
        "id": f"o-{loc}-{code}",
        "meta": {"profile": [PROFILE]},
        "subject": {"reference": f"Location/{loc}"},
        "code": {"coding": [{"code": code}]},
        "valueQuantity": {"value": value, "unit": unit, "code": unit},
    }
    if period_end:
        obs["effectivePeriod"] = {"start": "2035-01-01", "end": period_end}
    return obs


def test_copper_limit_is_two_milligrams_per_litre():
    assert CLOSED_PARAM_MAPPING["copper-dissolved"][1] == 2000.0
    assert CLOSED_PARAM_MAPPING["copper dissolved"][1] == 2000.0


def test_regime_by_location_type():
    assert regime_for_location(RIVER) == SURFACE
    assert regime_for_location(CITY) == DRINKING
    assert regime_for_location({"id": "X"}) == DRINKING
    assert regimes_by_location_ref([RIVER, CITY, {"type": []}]) == {"Location/R1": SURFACE, "Location/C1": DRINKING}
    assert regimes_by_location_ref(None) == {}


@pytest.mark.parametrize(
    ("parameter", "regime", "expected"),
    [
        ("Mercury dissolved", SURFACE, 0.07),
        ("Lead dissolved", SURFACE, 1.2),
        ("Nickel dissolved", SURFACE, 4.0),
        ("Cadmium dissolved", SURFACE, None),
        ("Nitrate", SURFACE, 50.0),
        ("Mercury dissolved", DRINKING, 1.0),
        ("Cadmium dissolved", DRINKING, 5.0),
    ],
)
def test_resolve_limit_by_regime(parameter, regime, expected):
    base = {"Mercury dissolved": 1.0, "Lead dissolved": 10.0, "Nickel dissolved": 20.0, "Cadmium dissolved": 5.0, "Nitrate": 50.0}[parameter]
    assert resolve_limit(parameter, base, regime, datetime(2026, 1, 1, tzinfo=UTC)) == expected


@pytest.mark.parametrize(
    ("instant", "expected"),
    [
        (datetime(2035, 12, 31, 23, 59, 59, tzinfo=UTC), 10.0),
        (datetime(2036, 1, 12, tzinfo=UTC), 5.0),
        (datetime(2040, 6, 1, tzinfo=UTC), 5.0),
        (datetime(2026, 9, 29, tzinfo=UTC), 10.0),
    ],
)
def test_lead_drinking_limit_changes_on_2036_01_12(instant, expected):
    assert resolve_limit("Lead dissolved", 10.0, DRINKING, instant) == expected


def test_observation_instant_reads_effective_time():
    assert observation_instant({"effectiveDateTime": "2020-05-01T10:00:00Z"}).year == 2020
    period = observation_instant({"effectivePeriod": {"start": "2035-01-01", "end": "2036-01-12"}})
    assert period.year == 2036 and period.day == 12  # end of the period touches the change date
    assert observation_instant({"effectivePeriod": {"start": "2035-01-01", "end": "2035-12-31"}}) < datetime(2036, 1, 12, tzinfo=UTC)
    assert observation_instant({"effectiveDateTime": "not-a-date"}).year >= 2026  # falls back to now


def _score(observations, locations):
    result = apply_ccme_wqi_to_sandbox(observations, locations)
    return result, (result["evaluated_locations"][0] if result["evaluated_locations"] else None)


def test_mercury_passes_in_drinking_regime_but_fails_in_surface_regime():
    # 0.5 ug/L is under the 1.0 drinking limit and over the 0.07 surface EQS.
    _, city = _score([_obs("C1", "mercury-dissolved", 0.5)], [CITY])
    _, river = _score([_obs("R1", "mercury-dissolved", 0.5)], [RIVER])
    assert city["ccme_wqi"] == 100.0 and city["limit_regime"] == DRINKING
    assert river["ccme_wqi"] < 100.0 and river["limit_regime"] == SURFACE


def test_without_locations_every_site_uses_the_drinking_regime():
    _, entry = _score([_obs("R1", "mercury-dissolved", 0.5)], None)
    assert entry["ccme_wqi"] == 100.0 and entry["limit_regime"] == DRINKING


def test_cadmium_on_a_river_is_skipped_and_counted():
    result, entry = _score([_obs("R1", "cadmium-dissolved", 0.1)], [RIVER])
    assert entry is None
    assert result["skipped_surface_limit_needs_hardness_observations"] == 1


def test_copper_between_old_and_new_limit_passes():
    # 500 ug/L exceeded the old wrong 20 ug/L limit; it is within the sourced 2.0 mg/L.
    _, entry = _score([_obs("C1", "copper-dissolved", 500.0)], [CITY])
    assert entry["ccme_wqi"] == 100.0


def test_lead_uses_the_limit_valid_on_the_observation_date():
    # 7 ug/L: passes the 10 ug/L limit before 2036-01-12, fails the 5 ug/L limit after it.
    _, before = _score([_obs("C1", "lead-dissolved", 7.0, period_end="2035-12-31")], [CITY])
    _, after = _score([_obs("C1", "lead-dissolved", 7.0, period_end="2036-06-30")], [CITY])
    assert before["ccme_wqi"] == 100.0
    assert after["ccme_wqi"] < 100.0
