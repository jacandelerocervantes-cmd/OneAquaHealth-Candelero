"""GET /sites/{id}/fhir: the measurements of one site as a FHIR R4 collection Bundle (structure, rules, determinism)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from waterbase_fixtures import build_fixture_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.fhir.output.measurements import NoValuesError, measurements_bundle
from oah.fhir.validate import validate_resource

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
LOCATIONS = [{"resourceType": "Location", "id": "Loc-Almyros", "name": "Almyros", "type": RIVER, "position": {"latitude": 35.3, "longitude": 25.0}}]
OBSERVATIONS = [
    {
        "id": "a-nitrate", "resourceType": "Observation", "meta": {"profile": [PROFILE]},
        "subject": {"reference": "Location/Loc-Almyros"}, "code": {"coding": [{"code": "nitrate"}]},
        "effectivePeriod": {"start": "2018-01-01", "end": "2018-12-31"},
        "component": [{"code": {"coding": [{"code": "median"}]}, "valueQuantity": {"value": 3.0, "code": "mg/L", "system": "http://unitsofmeasure.org"}}],
    }
]
RETRIEVED = "2026-10-04T12:00:00Z"


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    return path


def _by_type(body: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for entry in body["entry"]:
        out.setdefault(entry["resource"]["resourceType"], []).append(entry["resource"])
    return out


def _assert_valid(body: dict[str, Any]) -> None:
    assert validate_resource(body).findings == ()
    for entry in body["entry"]:
        assert validate_resource(entry["resource"]).findings == (), entry["resource"]["resourceType"]


def test_a_sandbox_site_gives_a_valid_bundle_with_location_observations_device_and_provenance(http):
    response = http.get("/sites/Loc-Almyros/fhir")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")  # FHIR JSON, typed as FhirBundleResponse in the contract
    body = response.json()
    assert body["resourceType"] == "Bundle" and body["type"] == "collection"
    _assert_valid(body)
    parts = _by_type(body)
    assert len(parts["Location"]) == 1 and len(parts["Device"]) == 1 and len(parts["Provenance"]) == 1
    assert parts["Location"][0]["name"] == "Loc-Almyros" and parts["Location"][0]["mode"] == "instance"
    records = http.get("/sites/Loc-Almyros/measurements").json()["records"]
    assert len(parts["Observation"]) == len([r for r in records if isinstance(r["value"], (int, float))]) >= 1
    for observation in parts["Observation"]:
        assert observation["status"] == "final" and observation["subject"]["reference"] == f"urn:uuid:{parts['Location'][0]['id']}"
        assert {"system": "https://oneaquahealth-hackathon.example/CodeSystem/data-origin", "code": "real-sandbox"} in observation["meta"]["tag"]
    provenance = parts["Provenance"][0]
    assert {t["reference"] for t in provenance["target"]} == {f"urn:uuid:{o['id']}" for o in parts["Observation"]}
    assert provenance["agent"][0]["who"]["reference"] == f"urn:uuid:{parts['Device'][0]['id']}"


def test_no_code_is_invented_the_parameter_is_text_only(http):
    body = http.get("/sites/Loc-Almyros/fhir").json()
    for observation in _by_type(body)["Observation"]:
        assert set(observation["code"]) == {"text"}
    assert '"coding"' not in json.dumps(body)


def test_a_waterbase_site_carries_position_origin_attribution_and_ucum_units(http, built):
    body = http.get("/sites/IT01-001025/fhir").json()
    _assert_valid(body)
    parts = _by_type(body)
    location = parts["Location"][0]
    assert location["name"] and "position" in location and location["identifier"][0]["value"] == "IT01-001025"
    units = {o["valueQuantity"]["unit"]: o["valueQuantity"] for o in parts["Observation"]}
    assert units, "the fixture site has measurements"
    for unit, quantity in units.items():
        if unit in {"mg/L", "ug/L", "mg{NO3}/L", "mg{P}/L", "mg{NH4}/L", "mg{NO2}/L", "Cel", "%"}:
            assert quantity["system"] == "http://unitsofmeasure.org" and quantity["code"] == unit
        else:
            assert "system" not in quantity and "code" not in quantity
    origins = {t["code"] for o in parts["Observation"] for t in o["meta"]["tag"]}
    assert origins == {"real-eea-waterbase"}
    assert "Waterbase" in parts["Provenance"][0]["entity"][0]["what"]["display"]
    assert all("screening aids, not legal limits" in o["note"][0]["text"] for o in parts["Observation"])


def test_the_bundle_is_deterministic_except_for_the_retrieval_time(http, built):
    first = http.get("/sites/IT01-001025/fhir").json()
    second = http.get("/sites/IT01-001025/fhir").json()
    ids = lambda b: [e["resource"]["id"] for e in b["entry"] if e["resource"]["resourceType"] in {"Location", "Observation", "Device"}]  # noqa: E731
    assert ids(first) == ids(second)


def test_the_selection_of_the_measurements_route_applies(http, built):
    everything = http.get("/sites/IT01-001025/fhir").json()
    one_parameter = http.get("/sites/IT01-001025/fhir", params={"parameter": "Nitrate"}).json()
    count = lambda b: len(_by_type(b)["Observation"])  # noqa: E731
    assert 1 <= count(one_parameter) <= count(everything)
    assert {o["code"]["text"] for o in _by_type(one_parameter)["Observation"]} == {"Nitrate"}


def test_errors_are_the_ones_of_the_measurements_route_and_an_empty_selection_is_404(http, built):
    assert http.get("/sites/Nope/fhir").status_code == 404
    assert http.get("/sites/Loc-Almyros/fhir", params={"parameter": "Plutonium"}).status_code == 422
    assert http.get("/sites/Loc-Almyros/fhir", params={"limit": 501}).status_code == 422
    empty = http.get("/sites/IT01-001025/fhir", params={"date_from": "2100-01-01"})
    assert empty.status_code == 404 and "numeric value" in empty.json()["detail"]


def test_the_builder_skips_records_without_a_value_keeps_comparators_and_refuses_an_empty_bundle():
    payload = {
        "location_id": "X1", "origin": "real-eea-waterbase", "attribution": "EEA Waterbase (CC BY 4.0)", "site": {"name": "Lake X", "latitude": 41.0, "longitude": 12.0},
        "records": [
            {"parameter": "Nitrate", "value": 2.5, "unit": "mg/L", "comparator": "<", "year": 2020, "statistic": "mean", "n": 4, "status": "within-limit", "origin": "real-eea-waterbase"},
            {"parameter": "pH", "value": 7.4, "unit": "[pH]", "period_start": "2020-01-01", "period_end": "2020-12-31", "status": "not-scored", "origin": "real-eea-waterbase"},
            {"parameter": "Turbidity", "value": None, "unit": "NTU", "year": 2020, "status": "not-scored", "origin": "real-eea-waterbase"},
            {"parameter": "Odd", "value": 1, "unit": "mg/L", "comparator": "~", "year": 2020, "month": 3, "status": "within-limit", "origin": "real-eea-waterbase"},
        ],
    }
    body = measurements_bundle(payload, RETRIEVED)
    _assert_valid(body)
    observations = {o["code"]["text"]: o for o in _by_type(body)["Observation"]}
    assert set(observations) == {"Nitrate", "pH", "Odd"}  # no value: left out, never filled in
    assert observations["Nitrate"]["valueQuantity"]["comparator"] == "<" and observations["Nitrate"]["effectiveDateTime"] == "2020"
    assert "comparator" not in observations["Odd"]["valueQuantity"] and observations["Odd"]["effectiveDateTime"] == "2020-03"
    assert observations["pH"]["effectivePeriod"] == {"start": "2020-01-01", "end": "2020-12-31"}
    assert "system" not in observations["pH"]["valueQuantity"]  # "[pH]" is not on the list of units written the UCUM way here
    assert _by_type(body)["Location"][0]["position"] == {"longitude": 12.0, "latitude": 41.0}
    assert _by_type(body)["Provenance"][0]["recorded"] == RETRIEVED
    with pytest.raises(NoValuesError):
        measurements_bundle({**payload, "records": payload["records"][2:3]}, RETRIEVED)
