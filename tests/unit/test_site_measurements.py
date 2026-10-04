"""Per-site measurement detail: values, limits and statuses agree with the CCME index they explain."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.site_measurements import location_known, parameter_names, site_measurement_records

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
LOCATIONS = [
    {"resourceType": "Location", "id": "Loc-Almyros", "name": "Almyros", "type": RIVER,
     "position": {"latitude": 35.3, "longitude": 25.0}},
    {"resourceType": "Location", "id": "Loc-Empty", "name": "Empty", "position": {"latitude": 1.0, "longitude": 2.0}},
]
client = TestClient(app_module.app)


def _component(code, value, unit):
    return {"code": {"coding": [{"code": code}]}, "valueQuantity": {"value": value, "code": unit, "system": "http://unitsofmeasure.org"}}


def _obs(obs_id, code, stats, unit="mg/L", year="2018", loc="Loc-Almyros", tags=None):
    meta = {"profile": [PROFILE]}
    if tags:
        meta["tag"] = [{"code": t} for t in tags]
    return {
        "id": obs_id,
        "resourceType": "Observation",
        "meta": meta,
        "subject": {"reference": f"Location/{loc}"},
        "code": {"coding": [{"code": code}]},
        "effectivePeriod": {"start": f"{year}-01-01", "end": f"{year}-12-31"},
        "component": [_component(name, value, unit) for name, value in stats.items()],
    }


OBSERVATIONS = [
    _obs("nitrate-median", "nitrate", {"minimum": 0.5, "median": 3.0, "average": 2.0, "maximum": 4.0}),
    _obs("ammonium-ugl", "ammonium", {"median": 100.0}, unit="ug/L", year="2019"),
    _obs("sulphate-average", "sulphate", {"average": 80.0}, year="2020"),
    _obs("temp", "watertemperature", {"median": 18.0}, unit="Cel", year="2018"),
    _obs("do-inconsistent", "dissolved-oxygen", {"minimum": 9.0, "median": 3.0, "maximum": 5.0}, year="2018"),
    _obs("phosphate-demo", "total-phosphates", {"median": 0.01}, tags=["demo"]),
]


def _records(**kwargs):
    return site_measurement_records(OBSERVATIONS, LOCATIONS, "Loc-Almyros", **kwargs)


def test_the_value_used_is_the_median_then_the_average_and_the_statistic_is_named():
    by_id = {r["observation_id"]: r for r in _records()}
    nitrate = by_id["nitrate-median"]
    assert (nitrate["value"], nitrate["statistic"], nitrate["min"], nitrate["max"]) == (3.0, "median", 0.5, 4.0)
    assert by_id["sulphate-average"]["statistic"] == "average" and by_id["sulphate-average"]["value"] == 80.0


def test_limit_basis_regime_country_and_status_are_reported():
    nitrate = {r["observation_id"]: r for r in _records()}["nitrate-median"]
    assert nitrate["limit_regime"] == "surface" and nitrate["limit_country"] == "GR"
    assert nitrate["limit_basis"].startswith("national:")
    assert nitrate["limit"] == pytest.approx(0.60 * 4.4268, rel=1e-3)
    assert nitrate["limit_type"] == "maximum" and nitrate["status"] == "exceeds-limit"
    assert nitrate["origin"] == "real-sandbox" and nitrate["unit"] == "mg/L" and nitrate["original_unit"] == "mg/L"
    assert (nitrate["period_start"], nitrate["period_end"]) == ("2018-01-01", "2018-12-31")


def test_a_value_in_another_unit_is_converted_and_both_units_are_shown():
    record = {r["observation_id"]: r for r in _records()}["ammonium-ugl"]
    assert record["value"] == pytest.approx(0.1) and record["original_unit"] == "ug/L" and record["unit"] == "mg/L"


def test_unscored_and_excluded_records_are_kept_with_the_reason():
    by_id = {r["observation_id"]: r for r in _records()}
    assert by_id["temp"]["status"] == "not-scored" and "interpretive-only" in by_id["temp"]["data_quality_flags"]
    assert by_id["temp"]["value"] == 18.0
    assert by_id["do-inconsistent"]["status"] == "excluded"
    assert by_id["do-inconsistent"]["data_quality_flags"] == ["qc-inconsistent"]


def test_demo_records_are_not_here_when_the_official_filter_is_applied_by_the_route():
    # the module itself does not filter (the API does, before calling it); the filter is tested in test_official_filter
    assert "phosphate-demo" in {r["observation_id"] for r in _records()}


def test_the_records_agree_with_the_ccme_index_they_explain():
    official = [o for o in OBSERVATIONS if "tag" not in o["meta"]]
    entry = apply_ccme_wqi_to_sandbox(official, LOCATIONS)["evaluated_locations"][0]
    records = site_measurement_records(official, LOCATIONS, "Loc-Almyros")
    scored = [r for r in records if r["status"] in ("within-limit", "exceeds-limit")]
    assert len(scored) == entry["evaluable_measurements"]
    assert sum(r["status"] == "exceeds-limit" for r in scored) == entry["failed_measurements"]


def test_filters_by_parameter_and_by_date_overlap():
    assert {r["parameter"] for r in _records(parameter="nitrate")} == {"Nitrate"}
    assert {r["observation_id"] for r in _records(date_from=date(2019, 6, 1), date_to=date(2019, 6, 2))} == {"ammonium-ugl"}
    assert {r["observation_id"] for r in _records(date_from=date(2020, 1, 1))} == {"sulphate-average"}
    assert {r["observation_id"] for r in _records(date_to=date(2018, 1, 1))} >= {"nitrate-median"}
    assert _records(date_from=date(2030, 1, 1)) == []


def test_ph_inside_the_range_reports_the_range():
    ph = [_obs("ph", "ph", {"median": 7.5}, unit="pH")]
    record = site_measurement_records(ph, LOCATIONS, "Loc-Almyros")[0]
    assert record["limit_range"] == [6.5, 9.5] and record["status"] == "within-limit"


def test_location_known_and_parameter_names():
    assert location_known("Loc-Empty", [], LOCATIONS)
    assert location_known("Loc-Ghost", OBSERVATIONS[:0] + [_obs("g", "nitrate", {"median": 1}, loc="Loc-Ghost")], [])
    assert not location_known("Loc-Ghost", OBSERVATIONS, LOCATIONS)
    assert "Nitrate" in parameter_names() and "pH" in parameter_names()


# --- route ---------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)


def test_route_returns_official_records_only_with_the_documented_fields():
    body = client.get("/sites/Loc-Almyros/measurements").json()
    assert body["origin"] == "real-sandbox" and body["data_freshness"]["status"] in ("live", "snapshot", "snapshot-stale", "unknown")
    ids = {r["observation_id"] for r in body["records"]}
    assert "phosphate-demo" not in ids and "nitrate-median" in ids
    assert body["total_matching"] == body["returned"] == len(body["records"]) and body["truncated"] is False
    assert body["limit"] == 200


def test_route_filters_and_bounds():
    body = client.get("/sites/Loc-Almyros/measurements", params={"parameter": "Nitrate", "limit": 1}).json()
    assert [r["parameter"] for r in body["records"]] == ["Nitrate"]
    many = client.get("/sites/Loc-Almyros/measurements", params={"limit": 2}).json()
    assert many["returned"] == 2 and many["truncated"] is True and many["total_matching"] > 2
    assert client.get("/sites/Loc-Almyros/measurements", params={"limit": 501}).status_code == 422
    assert client.get("/sites/Loc-Almyros/measurements", params={"limit": 0}).status_code == 422


def test_route_validates_inputs_and_404s_for_an_unknown_site():
    assert client.get("/sites/Nope/measurements").status_code == 404
    assert client.get("/sites/Loc-Almyros/measurements", params={"parameter": "Plutonium"}).status_code == 422
    assert client.get("/sites/Loc-Almyros/measurements", params={"date_from": "yesterday"}).status_code == 422
    reversed_dates = {"date_from": "2020-02-01", "date_to": "2020-01-01"}
    assert client.get("/sites/Loc-Almyros/measurements", params=reversed_dates).status_code == 422
    assert client.get("/sites/Loc-Empty/measurements").json()["records"] == []


def test_route_is_protected_by_the_api_key(monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "secret")
    assert client.get("/sites/Loc-Almyros/measurements").status_code == 401
    assert client.get("/sites/Loc-Almyros/measurements", headers={"X-API-Key": "secret"}).status_code == 200


def test_route_is_rate_limited(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda limiter=RateLimiter(1, 60.0): limiter)
    assert client.get("/sites/Loc-Almyros/measurements").status_code == 200
    assert client.get("/sites/Loc-Almyros/measurements").status_code == 429
