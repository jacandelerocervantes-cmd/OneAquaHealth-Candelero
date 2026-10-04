"""Solids-turbidity and organic-matter groups of the Waterbase store: build rules, records, the group filter, /countries.

All rows are SYNTHETIC (invented values in tmp dirs, see ``waterbase_fixtures``); nothing here is a measurement.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from waterbase_fixtures import NITRATE, build_fixture_store, obs

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.chat.tools import ALL_TOOLS, run_tool
from oah.waterbase import service, store
from oah.waterbase.build import DDL
from oah.waterbase.measurements import annual_record

TURBIDITY = ("EEA_3112-01-4", "Turbidity", "{NTU}")
TSS = ("EEA_31-02-7", "Total suspended solids", "mg/L")
SECCHI = ("EEA_3111-01-1", "Secchi depth", "m")
TOC = ("EEA_3133-06-0", "Total organic carbon (TOC)", "mg{C}/L")
DOC = ("EEA_3133-05-9", "Dissolved organic carbon (DOC)", "mg{C}/L")
CHLA = ("EEA_3164-01-0", "Chlorophyll a", "ug/L")
BOD5 = ("EEA_3133-01-5", "BOD5", "mg{O2}/L")
COD = ("EEA_3133-03-7", "CODCr", "mg{O2}/L")

SITE = "IT01-001025"


def _rows() -> list[list[str]]:
    return [
        obs(TURBIDITY, "4.0"),
        obs(TURBIDITY, "8.0", date="20150601"),
        obs(TURBIDITY, "50.0", matrix="W-DIS"),  # not the W rule: dropped
        obs(TSS, "10.0"),
        obs(TSS, "99.0", matrix="W-DIS"),  # W-DIS variant: dropped
        obs(SECCHI, "2.5"),
        obs(TOC, "3.0"),
        obs(TOC, "33.0", matrix="S", uom="%"),  # sediment: not a kept matrix
        obs(DOC, "2.0", matrix="W-DIS"),
        obs(DOC, "7.0", matrix="W"),  # DOC is W-DIS only: dropped
        obs(CHLA, "5.0", category="LW", site="IT02-LAKE1"),
        obs(BOD5, "1.5"),
        obs(COD, "6.0"),
        obs(COD, "0.5", below="1", date="20150701"),
        obs(TURBIDITY, "3.0", uom="mg/L", date="20160101"),  # a unit label that is not the expected one
        obs(NITRATE, "1.0"),
        # Greek rows: only chlorophyll a (W) qualifies; the rest are in a matrix other than the rule's
        obs(BOD5, "2.0", country="EL", site="EL000123", matrix="W-DIS"),
        obs(CHLA, "9.0", country="EL", site="EL000123", category="LW"),
    ]


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path, rows=_rows())
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    return path


def _series(site: str = SITE) -> list[Any]:
    return store.site_series(site)[1]


def test_the_matrix_rule_of_each_code_decides_what_is_stored(built):
    held = {(row.determinand, row.matrix) for row in _series()}
    assert ("EEA_3112-01-4", "W") in held and ("EEA_3112-01-4", "W-DIS") not in held
    assert ("EEA_31-02-7", "W") in held and ("EEA_31-02-7", "W-DIS") not in held
    assert ("EEA_3133-05-9", "W-DIS") in held and ("EEA_3133-05-9", "W") not in held
    assert ("EEA_3133-06-0", "W") in held and ("EEA_3133-06-0", "S") not in held
    assert {code for code, _ in held} >= {"EEA_3111-01-1", "EEA_3133-01-5", "EEA_3133-03-7", "CAS_14797-55-8"}
    greek = {(row.determinand, row.matrix) for row in _series("EL000123")}
    assert greek == {("EEA_3164-01-0", "W")}  # BOD5 in W-DIS is outside the BOD5 rule
    provenance = store.provenance()
    assert provenance["schema_version"] == "3" and "determinand_groups" in provenance["filters"]


def test_measurement_only_records_have_no_limit_and_say_why(built):
    site = store.get_site(SITE)
    assert site is not None
    records = {(r["determinand_code"], r["year"]): r for r in (annual_record(site, row) for row in _series())}
    turbidity = records[("EEA_3112-01-4", 2015)]
    assert (turbidity["parameter"], turbidity["group"], turbidity["value"], turbidity["unit"]) == ("Turbidity", "solids-turbidity", 6.0, "{NTU}")
    assert (turbidity["min"], turbidity["max"], turbidity["n"], turbidity["statistic"]) == (4.0, 8.0, 2, "mean")
    assert turbidity["limit"] is None and turbidity["limit_type"] is None and turbidity["limit_range"] is None
    assert turbidity["limit_regime"] == "no-limit-regime" and turbidity["status"] == "not-scored"
    assert turbidity["scored_value"] is None and "measurement only" in turbidity["limit_basis"]
    assert {"no-limit-regime", "measurement-only"} <= set(turbidity["data_quality_flags"])
    assert turbidity["origin"] == turbidity["source"] == "real-eea-waterbase" and turbidity["matrix"] == "W"
    assert records[("EEA_3133-05-9", 2015)]["matrix"] == "W-DIS" and records[("EEA_3133-05-9", 2015)]["group"] == "organic-matter"
    assert records[("CAS_14797-55-8", 2015)]["group"] == "water-chemistry"
    assert records[("CAS_14797-55-8", 2015)]["limit"] is not None  # the chemistry is untouched


def test_a_river_is_never_given_a_surface_limit_for_a_measurement_only_determinand(built):
    site = store.get_site(SITE)
    assert site is not None and site.category == "RW"
    for row in _series():
        if row.determinand in {"EEA_3112-01-4", "EEA_31-02-7", "EEA_3133-01-5", "EEA_3133-03-7", "EEA_3133-06-0"}:
            record = annual_record(site, row)
            assert record["limit_regime"] == "no-limit-regime" and record["limit"] is None, record["parameter"]


def test_an_unexpected_unit_is_refused_not_converted(built):
    site = store.get_site(SITE)
    assert site is not None
    mismatched = [annual_record(site, row) for row in _series() if row.determinand == "EEA_3112-01-4" and row.year == 2016]
    assert len(mismatched) == 1
    assert mismatched[0]["status"] == "excluded" and "unit-mismatch" in mismatched[0]["data_quality_flags"]
    assert mismatched[0]["limit"] is None and mismatched[0]["original_unit"] == "mg/L" and mismatched[0]["group"] == "solids-turbidity"


def test_below_loq_values_are_counted_not_used_for_the_new_groups(built):
    site = store.get_site(SITE)
    assert site is not None
    cod = [annual_record(site, row) for row in _series() if row.determinand == "EEA_3133-03-7"]
    assert len(cod) == 1 and cod[0]["n"] == 1 and cod[0]["n_below_loq"] == 1 and cod[0]["value"] == 6.0
    assert "below-loq-excluded-from-mean" in cod[0]["data_quality_flags"]


# --- the group filter -----------------------------------------------------------------------------------------------


def test_the_group_filter_keeps_only_the_codes_of_that_group(built):
    site = store.get_site(SITE)
    assert site is not None
    total, records = service.measurement_page(site, None, None, None, 200, "solids-turbidity")
    assert total == len(records) > 0 and {r["group"] for r in records} == {"solids-turbidity"}
    assert {r["parameter"] for r in records} == {"Turbidity", "Total suspended solids", "Secchi depth"}
    _, chemistry = service.measurement_page(site, None, None, None, 200, "water-chemistry")
    assert {r["group"] for r in chemistry} == {"water-chemistry"} and {r["parameter"] for r in chemistry} == {"Nitrate"}
    assert service.measurement_page(site, "Nitrate", None, None, 200, "organic-matter") == (0, [])  # parameter outside the group
    assert service.measurement_page(site, "Turbidity", None, None, 200, "solids-turbidity")[0] == 2  # 2015 and 2016
    assert service.measurement_page(site, None, None, None, 200, "not-a-group") == (0, [])


def test_an_empty_determinand_list_matches_nothing_and_the_list_is_bounded(built):
    assert store.site_series(SITE, determinands=[]) == (0, [])
    many = [f"CODE-{i}" for i in range(500)] + ["EEA_3112-01-4"]
    assert store.site_series(SITE, determinands=many)[0] == 0  # only the first 40 codes are used: bounded SQL
    total, rows = store.site_series(SITE, determinands=["EEA_3112-01-4", "EEA_31-02-7"])
    assert total == len(rows) and {r.determinand for r in rows} == {"EEA_3112-01-4", "EEA_31-02-7"}


def test_the_injection_style_group_value_is_inert(built):
    site = store.get_site(SITE)
    assert site is not None
    assert service.measurement_page(site, None, None, None, 200, "'; DROP TABLE measurements; --") == (0, [])
    assert store.site_series(SITE, determinands=["x' OR '1'='1"])[0] == 0
    assert store.site_series(SITE)[0] > 0


# --- countries ---------------------------------------------------------------------------------------------------------


def test_each_country_lists_the_groups_it_holds(built):
    summaries = {s.country: s for s in store.countries_summary()}
    assert summaries["IT"].parameter_groups == ("organic-matter", "solids-turbidity", "water-chemistry")
    assert summaries["GR"].parameter_groups == ("organic-matter",)  # only chlorophyll a qualifies in this synthetic slice


# --- old stores --------------------------------------------------------------------------------------------------------


def test_a_version_1_store_is_reported_as_rebuild_required_and_not_served(tmp_path: Path, monkeypatch):
    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.executemany("INSERT INTO provenance VALUES (?,?)", [("schema_version", "1"), ("build_date_utc", "2026-10-02T00:00:00Z")])
    connection.execute("INSERT INTO sites VALUES ('S1','NO','RW','Elva',NULL,NULL,60.0,10.0,'F',2015,2015,1)")
    connection.commit()
    connection.close()
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    status = store.store_status()
    assert status.state == "rebuild-required" and not status.ready and "build_waterbase_store.py" in status.detail
    assert store.list_sites() == (0, []) and store.countries_summary() == []  # an old layout is never read
    payload = service.status_payload()
    assert payload["state"] == "rebuild-required" and payload["edition"] is None


# --- API and chat -------------------------------------------------------------------------------------------------------


@pytest.fixture()
def http(monkeypatch) -> TestClient:
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: [])
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [])
    return TestClient(app_module.app)


def test_the_route_returns_the_new_parameters_with_their_group_and_filters_by_group(http, built):
    body = http.get(f"/sites/{SITE}/measurements?group=solids-turbidity").json()
    assert body["group"] == "solids-turbidity" and body["origin"] == "real-eea-waterbase"
    assert {r["parameter"] for r in body["records"]} == {"Turbidity", "Total suspended solids", "Secchi depth"}
    assert all(r["group"] == "solids-turbidity" and r["limit"] is None and r["status"] in {"not-scored", "excluded"} for r in body["records"])
    everything = http.get(f"/sites/{SITE}/measurements").json()
    assert everything["group"] is None
    assert {r["group"] for r in everything["records"]} == {"water-chemistry", "solids-turbidity", "organic-matter"}
    one = http.get(f"/sites/{SITE}/measurements?parameter=Turbidity").json()
    assert {r["parameter"] for r in one["records"]} == {"Turbidity"}
    assert http.get(f"/sites/{SITE}/measurements?parameter=Dissolved organic carbon (DOC)").json()["records"][0]["matrix"] == "W-DIS"
    assert http.get(f"/sites/{SITE}/measurements?parameter=Nitrate&group=organic-matter").json()["records"] == []


def test_an_unknown_group_is_a_422(http, built):
    assert http.get(f"/sites/{SITE}/measurements?group=colloids").status_code == 422


def test_the_group_filter_on_a_sandbox_site_uses_the_chemistry_label(http, monkeypatch):
    profile = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
    observation = {
        "id": "a", "resourceType": "Observation", "meta": {"profile": [profile]},
        "subject": {"reference": "Location/Loc-A"}, "code": {"coding": [{"code": "nitrate"}]},
        "effectivePeriod": {"start": "2018-01-01", "end": "2018-12-31"},
        "component": [{"code": {"coding": [{"code": "median"}]}, "valueQuantity": {"value": 3.0, "code": "mg/L", "system": "http://unitsofmeasure.org"}}],
    }
    location = {"resourceType": "Location", "id": "Loc-A", "name": "A", "position": {"latitude": 35.3, "longitude": 25.0}}
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: [observation])
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [location])
    chemistry = http.get("/sites/Loc-A/measurements?group=water-chemistry").json()
    assert [r["group"] for r in chemistry["records"]] == ["water-chemistry"] and chemistry["group"] == "water-chemistry"
    assert http.get("/sites/Loc-A/measurements?group=organic-matter").json()["records"] == []
    assert http.get("/sites/Loc-A/measurements").json()["records"][0]["group"] == "water-chemistry"


def test_countries_carry_the_group_list(http, built):
    body = http.get("/countries").json()
    by_code = {c["code"]: c for c in body["countries"]}
    assert by_code["IT"]["parameter_groups"] == ["organic-matter", "solids-turbidity", "water-chemistry"]
    waterbase_part = {s["source"]: s for s in by_code["IT"]["sources"]}["real-eea-waterbase"]
    assert waterbase_part["parameter_groups"] == ["organic-matter", "solids-turbidity", "water-chemistry"]
    assert by_code["GR"]["parameter_groups"] == ["organic-matter"]


def test_an_old_store_does_not_break_the_routes(http, tmp_path: Path, monkeypatch):
    path = tmp_path / "old.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', '1')")
    connection.commit()
    connection.close()
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    assert http.get("/sites").json()["waterbase"]["state"] == "rebuild-required"
    assert http.get("/countries").json()["waterbase"]["state"] == "rebuild-required"
    assert http.get(f"/sites/{SITE}/measurements").status_code == 404


def test_the_chat_tool_returns_the_new_parameters_with_their_group(built):
    ctx = app_module._chat_tool_context(None)
    outcome = run_tool(ctx, "get_site_measurements", {"location_id": SITE, "parameter": "Turbidity"}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None
    first = outcome.result["records"][0]
    assert first["group"] == "solids-turbidity" and first["value"]["unit"] == "{NTU}" and "limit" not in first
    assert first["year"] == 2015 and first["status"] == "not-scored" and "measurement only" in first["limit_basis"]
    countries = run_tool(ctx, "list_countries", {}, ALL_TOOLS).result
    assert countries is not None
    assert {c["code"]: c["parameter_groups"] for c in countries["countries"]}["IT"] == ["organic-matter", "solids-turbidity", "water-chemistry"]
