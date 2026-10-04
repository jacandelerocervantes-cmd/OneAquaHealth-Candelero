"""Waterbase sites in the API and the chat tools: /sites, /countries, /sites/{id}/measurements, tools, prompt facts."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from waterbase_fixtures import build_fixture_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.llm_guard import ChatSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.chat.prompts import CHAT_SYSTEM_PROMPT
from oah.chat.tools import ALL_TOOLS, origin_for, run_tool
from oah.waterbase import store
from oah.waterbase.build import DDL

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
LOCATIONS = [
    {"resourceType": "Location", "id": "Loc-Almyros", "name": "Almyros", "type": RIVER, "position": {"latitude": 35.3, "longitude": 25.0}},
    {"resourceType": "Location", "id": "Loc-Tiber", "name": "Tiber", "type": RIVER, "description": "Tiber river, Italy",
     "position": {"latitude": 41.9, "longitude": 12.5}},
]


def _obs(obs_id: str, code: str, value: float, loc: str) -> dict[str, Any]:
    return {
        "id": obs_id, "resourceType": "Observation", "meta": {"profile": [PROFILE]},
        "subject": {"reference": f"Location/{loc}"}, "code": {"coding": [{"code": code}]},
        "effectivePeriod": {"start": "2018-01-01", "end": "2018-12-31"},
        "component": [{"code": {"coding": [{"code": "median"}]}, "valueQuantity": {"value": value, "code": "mg/L", "system": "http://unitsofmeasure.org"}}],
    }


OBSERVATIONS = [_obs("a-nitrate", "nitrate", 3.0, "Loc-Almyros"), _obs("t-nitrate", "nitrate", 2.0, "Loc-Tiber")]


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


def _many_sites_store(tmp_path: Path, monkeypatch, count: int = 700) -> None:
    path = tmp_path / "many.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.executemany(
        "INSERT INTO provenance VALUES (?,?)", [("schema_version", store.SUPPORTED_SCHEMA), ("build_date_utc", "2026-10-02T00:00:00Z")]
    )
    connection.executemany(
        "INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(f"S{i:04d}", "NO", "RW", f"Elva {i}", None, None, 60.0, 10.0, "F", 2015, 2015, 1) for i in range(count)],
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))


# --- without a store ---------------------------------------------------------------------------------------------


def test_without_a_store_sites_are_the_sandbox_ones_and_the_state_is_stated(http):
    body = http.get("/sites").json()
    assert body["origin"] == "real-sandbox" and body["sources"] == ["real-sandbox"]
    assert [s["id"] for s in body["sites"]] == ["Loc-Almyros", "Loc-Tiber"]
    assert all(s["source"] == "real-sandbox" and s["origin"] == "real-sandbox" for s in body["sites"])
    assert body["waterbase"]["state"] == "not-built" and "build_waterbase_store.py" in body["waterbase"]["detail"]
    assert (body["total_matching"], body["returned"], body["limit"], body["offset"], body["truncated"]) == (2, 2, 200, 0, False)


def test_without_a_store_countries_and_measurements_do_not_break(http):
    body = http.get("/countries").json()
    assert body["origin"] == "real-sandbox" and body["waterbase"]["state"] == "not-built"
    for country in body["countries"]:
        assert country["measurement_only_sites"] == 0 and country["latest_year"] is None
        assert [s["source"] for s in country["sources"]] == ["real-sandbox"]
    assert http.get("/sites/IT01-001025/measurements").status_code == 404
    assert http.get("/sites?source=real-eea-waterbase").json()["sites"] == []
    assert http.get("/sites/Loc-Almyros/measurements").json()["origin"] == "real-sandbox"


def test_a_corrupt_store_is_reported_not_raised(http, tmp_path: Path, monkeypatch):
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"garbage" * 100)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(broken))
    body = http.get("/sites").json()
    assert body["waterbase"]["state"] == "unreadable" and body["origin"] == "real-sandbox"


# --- /sites ----------------------------------------------------------------------------------------------------


def test_sandbox_sites_come_first_and_every_waterbase_site_is_labelled(http, built):
    body = http.get("/sites").json()
    ids = [s["id"] for s in body["sites"]]
    assert ids == ["Loc-Almyros", "Loc-Tiber", "EL000123", "IT01-001025", "IT02-LAKE1", "IT99-NOSPATIAL", "NO0001"]
    assert body["origin"] == "real-mixed" and body["sources"] == ["real-eea-waterbase", "real-sandbox"]
    by_id = {s["id"]: s for s in body["sites"]}
    assert by_id["Loc-Almyros"]["source"] == "real-sandbox" and by_id["Loc-Almyros"]["status"] == "evaluated"
    wb = by_id["IT01-001025"]
    assert wb["source"] == wb["origin"] == "real-eea-waterbase" and wb["kind"] == "water-body"
    assert wb["status"] == "measurements-only" and wb["ccme_wqi"] is None and wb["ui_status"] == "unavailable"
    assert wb["latitude"] == 44.65 and wb["location_status"] == "located" and wb["limit_country"] == "IT"
    assert by_id["EL000123"]["location_status"] == "no-location" and by_id["EL000123"]["latitude"] is None
    assert by_id["IT02-LAKE1"]["water_category"] == "lake" and by_id["IT02-LAKE1"]["limit_regime"] == "no-limit-regime"
    assert body["waterbase"]["state"] == "ready" and body["waterbase"]["attribution"] == "EEA Waterbase - Water Quality ICM 2026 (CC BY 4.0)"
    assert body["total_matching"] == 7 == body["returned"] and body["truncated"] is False


def test_filters_narrow_the_list_and_el_is_read_as_gr(http, built):
    ids = lambda query: [s["id"] for s in http.get(f"/sites?{query}").json()["sites"]]  # noqa: E731
    assert ids("country=IT") == ["Loc-Tiber", "IT01-001025", "IT02-LAKE1", "IT99-NOSPATIAL"]
    assert ids("country=EL") == ["Loc-Almyros", "EL000123"] == ids("country=gr")
    assert ids("q=revello") == ["IT01-001025"]
    assert ids("q=tiber") == ["Loc-Tiber"]
    assert ids("country=NO&q=testelva") == ["NO0001"] and ids("country=NO&q=nothing") == []
    assert ids("source=real-eea-waterbase&country=IT") == ["IT01-001025", "IT02-LAKE1", "IT99-NOSPATIAL"]
    only_sandbox = http.get("/sites?source=real-sandbox").json()
    assert only_sandbox["origin"] == "real-sandbox" and [s["id"] for s in only_sandbox["sites"]] == ["Loc-Almyros", "Loc-Tiber"]
    only_store = http.get("/sites?source=real-eea-waterbase").json()
    assert only_store["origin"] == "real-eea-waterbase" and only_store["data_freshness"]["status"] == "snapshot"
    assert only_store["data_freshness"]["as_of"] == "2026-10-02T00:00:00Z"
    assert http.get("/sites?country=DE").json()["sites"] == []


def test_pagination_runs_across_the_two_sources(http, built):
    first = http.get("/sites?limit=3").json()
    assert [s["id"] for s in first["sites"]] == ["Loc-Almyros", "Loc-Tiber", "EL000123"]
    assert first["truncated"] is True and first["total_matching"] == 7 and first["returned"] == 3
    second = http.get("/sites?limit=3&offset=3").json()
    assert [s["id"] for s in second["sites"]] == ["IT01-001025", "IT02-LAKE1", "IT99-NOSPATIAL"]
    third = http.get("/sites?limit=3&offset=6").json()
    assert [s["id"] for s in third["sites"]] == ["NO0001"] and third["truncated"] is False
    assert http.get("/sites?limit=1&offset=1").json()["sites"][0]["id"] == "Loc-Tiber"
    assert http.get("/sites?limit=1&offset=100").json()["sites"] == []
    assert http.get("/sites?limit=1&offset=1").json()["origin"] == "real-sandbox"


def test_the_list_is_bounded_whatever_the_store_holds(http, tmp_path, monkeypatch):
    _many_sites_store(tmp_path, monkeypatch)
    default = http.get("/sites").json()
    assert default["returned"] == len(default["sites"]) == 200 and default["limit"] == 200
    assert default["total_matching"] == 702 and default["truncated"] is True
    assert [s["id"] for s in default["sites"][:2]] == ["Loc-Almyros", "Loc-Tiber"]  # sandbox first
    biggest = http.get("/sites?limit=500").json()
    assert len(biggest["sites"]) == 500
    assert http.get("/sites?limit=501").status_code == 422
    assert http.get("/sites?limit=0").status_code == 422
    assert http.get("/sites?offset=-1").status_code == 422
    assert http.get("/sites?country=ITA").status_code == 422
    assert http.get("/sites?q=" + "x" * 65).status_code == 422
    tail = http.get("/sites?limit=500&offset=500").json()
    assert tail["returned"] == 202 and tail["truncated"] is False


def test_the_text_filter_is_inert_against_sql(http, built):
    response = http.get("/sites", params={"q": "'; DROP TABLE sites; --"})
    assert response.status_code == 200 and response.json()["sites"] == []
    assert http.get("/sites").json()["total_matching"] == 7


# --- /countries --------------------------------------------------------------------------------------------------


def test_countries_count_both_sources_and_break_them_down(http, built):
    body = http.get("/countries").json()
    assert body["origin"] == "real-mixed" and body["waterbase"]["state"] == "ready"
    by_code = {c["code"]: c for c in body["countries"]}
    greece = by_code["GR"]
    assert greece["total_sites"] == 2 and greece["measurement_only_sites"] == 1 and greece["latest_year"] == 2017
    assert greece["status"] == "national-limits" and greece["evaluated_sites"] == 1  # the sandbox site is still evaluated
    sources = {s["source"]: s for s in greece["sources"]}
    assert sources["real-sandbox"]["total_sites"] == 1 and sources["real-sandbox"]["evaluated_sites"] == 1
    assert sources["real-eea-waterbase"]["total_sites"] == 1 and sources["real-eea-waterbase"]["sites_without_location"] == 1
    assert sources["real-eea-waterbase"]["attribution"].endswith("(CC BY 4.0)")
    norway = by_code["NO"]
    assert norway["status"] == "measurements-only" and norway["total_sites"] == 1 and norway["regime"] == "surface"
    assert norway["has_national_limits"] is False and norway["evaluated_sites"] == 0 and norway["latest_year"] == 2015
    italy = by_code["IT"]
    assert italy["total_sites"] == 4 and italy["regime"] == "mixed"  # rivers (surface) and a lake (no-limit-regime)
    wb = {s["source"]: s for s in italy["sources"]}["real-eea-waterbase"]
    assert (wb["river_sites"], wb["lake_sites"], wb["first_year"], wb["last_year"]) == (2, 1, 2015, 2016)


# --- /sites/{id}/measurements -------------------------------------------------------------------------------------


def test_waterbase_measurements_are_annual_records_with_attribution(http, built):
    body = http.get("/sites/IT01-001025/measurements?parameter=Nitrate").json()
    assert body["origin"] == body["source"] == "real-eea-waterbase"
    assert body["attribution"] == "EEA Waterbase - Water Quality ICM 2026 (CC BY 4.0)"
    assert body["index_status"] == "measurements-only"
    assert body["site"]["name"] == "PO - REVELLO" and body["site"]["water_category"] == "river"
    assert body["data_freshness"]["status"] == "snapshot" and body["interpretation_notice"]
    assert (body["total_matching"], body["returned"], body["truncated"], body["limit"]) == (2, 2, False, 200)
    first, second = body["records"]
    assert (first["year"], first["n"], first["value"], first["min"], first["max"]) == (2015, 2, 2.0, 1.0, 3.0)
    assert first["unit"] == "mg/L" and first["status"] == "within-limit" and first["limit_regime"] == "surface"
    assert first["limit_basis"] and first["source"] == "real-eea-waterbase" and second["period_start"] == "2016-01-01"


def test_every_parameter_of_a_site_is_listed_in_year_order(http, built):
    body = http.get("/sites/IT01-001025/measurements").json()
    parameters = {r["parameter"] for r in body["records"]}
    assert {"Nitrate", "Total phosphates", "pH", "Lead dissolved", "Lead and its compounds", "Chloride", "Oxygen saturation", "Phosphate"} <= parameters
    assert [r["year"] for r in body["records"]] == sorted(r["year"] for r in body["records"])
    unmapped = [r for r in body["records"] if "no-limit-mapping" in r["data_quality_flags"]]
    assert unmapped and all(r["status"] == "not-scored" and r["limit"] is None for r in unmapped)


def test_the_parameter_filter_accepts_closed_names_and_listed_labels(http, built):
    dissolved = http.get("/sites/IT01-001025/measurements?parameter=lead dissolved").json()
    assert [(r["parameter"], r["matrix"]) for r in dissolved["records"]] == [("Lead dissolved", "W-DIS")]
    whole = http.get("/sites/IT01-001025/measurements?parameter=Lead and its compounds").json()
    assert [(r["parameter"], r["matrix"], r["status"]) for r in whole["records"]] == [("Lead and its compounds", "W", "not-scored")]
    assert http.get("/sites/IT01-001025/measurements?parameter=Chloride").json()["records"][0]["parameter"] == "Chloride"
    unknown = http.get("/sites/IT01-001025/measurements?parameter=Mercury%20in%20fish")
    assert unknown.status_code == 422 and "Unknown parameter" in unknown.json()["detail"]
    # a label that only exists in Waterbase is not a sandbox parameter
    assert http.get("/sites/Loc-Almyros/measurements?parameter=Chloride").status_code == 422


def test_the_date_window_keeps_the_years_it_overlaps(http, built):
    in_2016 = http.get("/sites/IT01-001025/measurements?parameter=Nitrate&date_from=2016-03-01").json()
    assert [r["year"] for r in in_2016["records"]] == [2016] and in_2016["date_from"] == "2016-03-01"
    until_2015 = http.get("/sites/IT01-001025/measurements?parameter=Nitrate&date_to=2015-02-01").json()
    assert [r["year"] for r in until_2015["records"]] == [2015]
    assert http.get("/sites/IT01-001025/measurements?date_from=2017-01-01&date_to=2016-01-01").status_code == 422
    assert http.get("/sites/IT01-001025/measurements?parameter=Nitrate&date_from=2030-01-01").json()["records"] == []


def test_the_record_limit_bounds_the_answer_and_says_so(http, built):
    body = http.get("/sites/IT01-001025/measurements?limit=3").json()
    assert body["returned"] == 3 and body["total_matching"] == 12 and body["truncated"] is True
    assert http.get("/sites/IT01-001025/measurements?limit=501").status_code == 422


def test_lakes_and_missing_coordinates_are_visible_in_the_answer(http, built):
    lake = http.get("/sites/IT02-LAKE1/measurements").json()
    assert lake["records"][0]["limit_regime"] == "no-limit-regime" and lake["records"][0]["limit"] is None
    assert lake["site"]["water_category"] == "lake"
    greek = http.get("/sites/EL000123/measurements?parameter=Dissolved Oxygen").json()
    assert greek["site"]["location_status"] == "no-location" and greek["site"]["confidentiality"] == "N"
    assert greek["records"][0]["status"] == "exceeds-limit" and greek["records"][0]["limit_country"] == "GR"


def test_an_unknown_id_is_a_404_and_the_sandbox_route_is_unchanged(http, built):
    assert http.get("/sites/NOPE-1/measurements").status_code == 404
    sandbox = http.get("/sites/Loc-Almyros/measurements").json()
    assert sandbox["origin"] == "real-sandbox" and "source" in sandbox and sandbox["source"] == "real-sandbox"
    assert sandbox["site"] is None and sandbox["attribution"] is None
    assert sandbox["records"][0]["source"] == "real-sandbox" and sandbox["records"][0]["n"] is None


def test_waterbase_sites_have_no_index(http, built):
    assert http.get("/indices/IT01-001025").status_code == 404


def test_the_waterbase_routes_are_protected_like_the_others(http, built, monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "secret")
    assert http.get("/sites/IT01-001025/measurements").status_code == 401
    assert http.get("/sites/IT01-001025/measurements", headers={"X-API-Key": "secret"}).status_code == 200


# --- chat tools --------------------------------------------------------------------------------------------------


def _ctx(country: str | None = None):
    return app_module._chat_tool_context(country)


def test_list_sites_takes_a_country_and_a_name_query_across_both_sources(built):
    result = run_tool(_ctx(), "list_sites", {"country": "IT", "query": "revello"}, ALL_TOOLS).result
    assert result is not None
    assert [s["id"] for s in result["sites"]] == ["IT01-001025"] and result["origin"] == "real-eea-waterbase"
    assert result["sites"][0]["source"] == "real-eea-waterbase" and result["attribution"].endswith("(CC BY 4.0)") and "no CCME index" in result["waterbase_note"]
    mixed = run_tool(_ctx(), "list_sites", {"country": "EL"}, ALL_TOOLS).result
    assert mixed is not None and mixed["country"] == "GR" and mixed["origin"] == "real-mixed"
    assert [s["id"] for s in mixed["sites"]] == ["Loc-Almyros", "EL000123"]
    assert {s["id"]: s.get("location_status") for s in mixed["sites"]}["EL000123"] == "no-location"
    assert mixed["total_sites"] == 2
    named = run_tool(_ctx(), "list_sites", {"query": "tiber"}, ALL_TOOLS).result
    assert named is not None and [s["id"] for s in named["sites"]] == ["Loc-Tiber"] and named["origin"] == "real-sandbox"


def test_list_sites_query_is_validated_and_the_selected_country_is_enforced(built):
    for bad in ({"query": "x" * 65}, {"query": "bad\x00text"}, {"query": 5}, {"query": ""}):
        assert run_tool(_ctx(), "list_sites", bad, ALL_TOOLS).ok is False
    other = run_tool(_ctx("GR"), "list_sites", {"country": "IT"}, ALL_TOOLS)
    assert other.ok is False and "selected country is GR" in (other.error or "")
    injected = run_tool(_ctx(), "list_sites", {"query": "'; DROP TABLE sites; --"}, ALL_TOOLS)
    assert injected.ok and injected.result is not None and injected.result["sites"] == []


def test_list_sites_is_bounded_even_for_a_huge_store(tmp_path, monkeypatch):
    from oah.chat.tools import MAX_LISTED_STORE_SITES, MAX_TOOL_RESULT_CHARS

    _many_sites_store(tmp_path, monkeypatch)
    outcome = run_tool(_ctx(), "list_sites", {"country": "NO"}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None and len(outcome.content) <= MAX_TOOL_RESULT_CHARS
    assert outcome.result["total_sites"] == 700 and outcome.result["truncated"] is True
    assert 0 < outcome.result["returned"] <= MAX_LISTED_STORE_SITES


def test_waterbase_measurements_through_the_tool_carry_source_unit_and_basis(built):
    outcome = run_tool(
        _ctx("IT"), "get_site_measurements",
        {"location_id": "IT01-001025", "parameter": "Nitrate", "date_from": "2015-01-01", "date_to": "2015-12-31"}, ALL_TOOLS,
    )
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["origin"] == "real-eea-waterbase" and result["attribution"].endswith("(CC BY 4.0)")
    assert result["data_freshness"]["status"] == "snapshot" and result["limit_regime"] == "surface"
    record = result["records"][0]
    assert record["value"] == {"amount": 2.0, "unit": "mg/L"} and record["statistic"] == "mean"
    assert (record["year"], record["n"]) == (2015, 2) and record["limit_basis"] and record["status"] == "within-limit"
    assert "<" not in outcome.content and outcome.notes == () and "n_below_loq" in result["note"]  # nothing was cut


def test_tool_parameter_names_include_the_listed_waterbase_ones(built):
    ok = run_tool(_ctx(), "get_site_measurements", {"location_id": "IT01-001025", "parameter": "chloride"}, ALL_TOOLS)
    assert ok.ok and ok.result is not None and ok.result["records"][0]["parameter"] == "Chloride"
    assert run_tool(_ctx(), "get_site_measurements", {"location_id": "IT01-001025", "parameter": "Mercury in fish"}, ALL_TOOLS).ok is False


def test_a_waterbase_site_of_another_country_is_refused_while_a_country_is_selected(built):
    refused = run_tool(_ctx("GR"), "get_site_measurements", {"location_id": "IT01-001025"}, ALL_TOOLS)
    assert refused.ok is False and "belongs to country IT" in (refused.error or "")
    assert run_tool(_ctx("GR"), "get_site_measurements", {"location_id": "EL000123"}, ALL_TOOLS).ok


def test_the_index_tool_explains_that_waterbase_sites_have_no_index(built):
    outcome = run_tool(_ctx(), "get_site_index", {"location_id": "IT01-001025"}, ALL_TOOLS)
    assert outcome.ok is False and "no index is computed" in (outcome.error or "") and "get_site_measurements" in (outcome.error or "")


def test_a_site_unknown_to_both_sources_is_an_unknown_site(built):
    assert run_tool(_ctx(), "get_site_measurements", {"location_id": "NOPE-1"}, ALL_TOOLS).error == "Unknown site."
    empty = run_tool(_ctx(), "get_site_measurements", {"location_id": "IT01-001025", "parameter": "Nitrate", "date_from": "2030-01-01"}, ALL_TOOLS)
    assert empty.ok and empty.result is not None and empty.result["records"] == [] and empty.result["origin"] == "real-eea-waterbase"


def test_list_countries_gives_the_latest_year_and_the_sources(built):
    result = run_tool(_ctx(), "list_countries", {}, ALL_TOOLS).result
    assert result is not None and result["origin"] == "real-mixed"
    by_code = {c["code"]: c for c in result["countries"]}
    assert by_code["NO"]["latest_year"] == 2015 and by_code["GR"]["latest_year"] == 2017
    assert {s["source"] for s in by_code["GR"]["sources"]} == {"real-sandbox", "real-eea-waterbase"}


def test_the_answer_origin_names_the_sources_consulted(built):
    wb = run_tool(_ctx(), "get_site_measurements", {"location_id": "IT01-001025"}, ALL_TOOLS)
    sandbox = run_tool(_ctx(), "get_site_measurements", {"location_id": "Loc-Almyros"}, ALL_TOOLS)
    assert origin_for([wb]) == "real-eea-waterbase" and origin_for([sandbox]) == "real-sandbox"
    assert origin_for([wb, sandbox]) == "real-mixed" and origin_for([]) == "real-sandbox"
    failed = run_tool(_ctx(), "get_site_measurements", {"location_id": "NOPE-1"}, ALL_TOOLS)
    assert origin_for([failed]) == "real-sandbox"


def test_the_system_prompt_states_the_data_facts():
    text = CHAT_SYSTEM_PROMPT
    for needle in (
        "real-sandbox", "real-eea-waterbase", "ANNUAL aggregates", "latest_year", "lakes have NO limit regime",
        "Groundwater and coastal waters are not in the data", "no-location",
        "no median", "CC BY 4.0",
        # added with the solids-turbidity / organic-matter groups and the bathing-water classification
        "MEASUREMENT-ONLY", "NO limit regime for the measurement-only groups", "proxies for particulate or colloidal matter",
        "real-eea-bathing-water", "CLASSIFICATION", "NOT a concentration", "real-eea-bathing-samples",
        "protozoa", "Norway has no bathing water in that file",
    ):
        assert needle in text, needle


# --- the chat route end to end -------------------------------------------------------------------------------------


@dataclass
class _Text:
    text: str
    type: str = "text"


@dataclass
class _ToolUse:
    id: str
    name: str
    input: Any
    type: str = "tool_use"


@dataclass
class _Client:
    replies: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        def _create(**kwargs: Any) -> Any:
            self.calls.append({**kwargs, "messages": json.loads(json.dumps(kwargs["messages"], default=str))})
            return self.replies[len(self.calls) - 1]

        self.messages = SimpleNamespace(create=_create)


def _reply(*blocks: Any) -> Any:
    return SimpleNamespace(content=list(blocks), usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_a_chat_answer_from_waterbase_is_labelled_and_cited(http, built, monkeypatch):
    guard = ChatSpendGuard(per_minute=10_000, daily_cap=100, cache_ttl_seconds=60.0, max_steps=6)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: guard)
    client = _Client([
        _reply(_ToolUse("t1", "list_sites", {"country": "IT", "query": "revello"})),
        _reply(_ToolUse("t2", "get_site_measurements", {"location_id": "IT01-001025", "parameter": "Nitrate", "date_from": "2015-01-01", "date_to": "2015-12-31"})),
        _reply(_Text("EEA Waterbase annual data for PO - REVELLO in 2015: nitrate mean 2.0 mg/L from 2 samples.")),
    ])
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: client)
    response = http.post("/chat", json={"message": "Nitrate at Revello in 2015?", "country": "IT"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered" and body["origin"] == "real-eea-waterbase"
    cited = [c for c in body["citations"] if c["tool"] == "get_site_measurements"]
    assert cited and cited[0]["source"] == "real-eea-waterbase" and cited[0]["site_id"] == "IT01-001025" and cited[0]["unit"] == "mg/L"
    assert body["grounded"] is True
    assert "ANNUAL aggregates" in client.calls[0]["system"]


def test_the_chat_accepts_a_country_that_only_the_store_holds(http, built, monkeypatch):
    guard = ChatSpendGuard(per_minute=10_000, daily_cap=100, cache_ttl_seconds=60.0, max_steps=6)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: guard)
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _Client([_reply(_Text("No data was consulted."))]))
    assert http.post("/chat", json={"message": "Norway?", "country": "NO"}).status_code == 200
    assert http.post("/chat", json={"message": "Germany?", "country": "DE"}).status_code == 422
