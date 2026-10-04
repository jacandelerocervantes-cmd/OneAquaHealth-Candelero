"""The /countries overview: derived from the regime tables and the limits file, never hard-coded in the route."""

import copy

import pytest
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.indices import limit_overrides as lo
from oah.indices.apply_to_sandbox import list_sites_with_status
from oah.indices.countries import countries_overview
from oah.indices.regimes import country_limit_sources, has_national_limits, known_countries

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
CITY = [{"coding": [{"system": "http://snomed.info/sct", "code": "288520005"}]}]
POSITION = {"latitude": 1.0, "longitude": 2.0}
LOCATIONS = [
    {"id": "Loc-Almyros", "name": "Almyros", "type": RIVER, "position": POSITION},
    {"id": "Loc-IT-River", "name": "IT river", "type": RIVER, "description": "Stream (Campania, IT)", "position": POSITION},
    {"id": "Loc-Benevento", "name": "Benevento", "type": CITY, "description": "City of Benevento (Campania, IT)",
     "position": POSITION},
    {"id": "Loc-Unknown", "name": "Somewhere", "position": POSITION},
]
OBSERVATIONS = [
    {
        "id": "o1", "meta": {"profile": [PROFILE]}, "subject": {"reference": "Location/Loc-Almyros"},
        "code": {"coding": [{"code": "nitrate"}]}, "valueQuantity": {"value": 1.0, "code": "mg/L"},
    }
]
client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _restore_tables():
    before = {name: copy.deepcopy(table) for name, table in lo._tables().items()}
    yield
    lo.reset_overrides()
    for name, table in lo._tables().items():
        table.clear()
        table.update(before[name])
    lo._ORIGINALS = None


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)


def _overview():
    return countries_overview(list_sites_with_status(OBSERVATIONS, LOCATIONS), LOCATIONS)


def test_skipped_sites_carry_the_country_when_it_resolves():
    sites = {s["id"]: s for s in list_sites_with_status(OBSERVATIONS, LOCATIONS)}
    assert sites["Loc-IT-River"]["status"] == "skipped" and sites["Loc-IT-River"]["limit_country"] == "IT"
    assert sites["Loc-Almyros"]["limit_country"] == "GR"
    assert sites["Loc-Unknown"]["limit_country"] is None


def test_status_labels_follow_the_evaluated_sites_and_the_national_tables():
    countries, without = _overview()
    by_code = {c["code"]: c for c in countries}
    assert by_code["GR"]["status"] == "national-limits" and by_code["GR"]["evaluated_sites"] == 1
    assert by_code["IT"]["status"] == "no-evaluable-water-data" and by_code["IT"]["has_national_limits"] is True
    assert by_code["IT"]["skipped_sites"] == 2 and by_code["IT"]["skipped_non_water_sites"] == 1
    assert by_code["NO"]["status"] == "no-evaluable-water-data" and by_code["NO"]["total_sites"] == 0
    assert by_code["NO"]["has_national_limits"] is False and by_code["NO"]["regime"] is None
    assert by_code["GR"]["regime"] == "surface"
    assert without == 1


def test_limit_sources_come_from_the_limit_basis_function():
    sources = country_limit_sources("GR")
    assert any(s.startswith("national: HWQI") for s in sources)
    assert any("Directive 2013/39/EU" in s for s in sources)
    assert not any(s.startswith("national") for s in country_limit_sources("NO"))


def test_a_country_added_through_the_limits_file_appears_without_a_code_change():
    assert "MX" not in known_countries()
    document = {
        "schema_version": 1, "note": "test",
        "limits": [{"regime": "surface", "country": "MX", "parameter": "Nitrate", "values": [10.0],
                    "unit": "mg/L", "source": "test source"}],
        "location_countries": {"Loc-Unknown": "MX"},
    }
    lo.apply_overrides(document)
    assert has_national_limits("MX")
    by_code = {c["code"]: c for c in _overview()[0]}
    assert by_code["MX"]["total_sites"] == 1 and by_code["MX"]["status"] == "no-evaluable-water-data"
    assert any(s.startswith("override: test source") for s in by_code["MX"]["limit_sources"])
    assert _overview()[1] == 0


def test_route_lists_the_countries_with_origin_and_freshness():
    body = client.get("/countries").json()
    assert body["origin"] == "real-sandbox" and "data_freshness" in body and "interpretation_notice" in body
    assert [c["code"] for c in body["countries"]] == sorted(c["code"] for c in body["countries"])
    assert {"GR", "IT", "NO"} <= {c["code"] for c in body["countries"]}
    assert body["sites_without_country"] == 1


def test_route_is_protected(monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "secret")
    assert client.get("/countries").status_code == 401
    assert client.get("/countries", headers={"X-API-Key": "secret"}).status_code == 200


def test_sites_carry_a_kind():
    kinds = {s["id"]: s["kind"] for s in client.get("/sites").json()["sites"]}
    assert kinds == {"Loc-Almyros": "water-body", "Loc-IT-River": "water-body", "Loc-Benevento": "city", "Loc-Unknown": "other"}
