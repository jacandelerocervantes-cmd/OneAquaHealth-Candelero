"""``GET /catalog``: applicability of the sidebar indices per country, from SYNTHETIC stores and a scripted sandbox.

Every expected value is derived by hand from the fixtures; nothing here is real data and no test opens a network connection.
"""
from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
from bathing_fixtures import HEADER, row
from bathing_fixtures import build_fixture_store as build_classification_store
from external_fakes import make_runtime
from fastapi import HTTPException
from fastapi.testclient import TestClient
from samples_fixtures import build_fixture_store as build_samples_store
from waterbase_fixtures import build_fixture_store as build_waterbase_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.external.runtime import set_runtime
from oah.external.settings import ExternalSettings
from oah.i18n.strings import ENGLISH, load_strings
from oah.indices.catalog import INDEX_IDS, NEVER_RETURNED
from oah.indices.regimes import INTERPRETATION_NOTICE

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
RIVER = [{"coding": [{"system": "http://snomed.info/sct", "code": "420531007"}]}]
POSITION = {"latitude": 35.3, "longitude": 25.0}
LOCATIONS = [
    {"id": "Loc-Almyros", "name": "Almyros", "type": RIVER, "position": POSITION},
    {"id": "Loc-IT-River", "name": "IT river", "type": RIVER, "description": "Stream (Campania, IT)", "position": POSITION},
]
OBSERVATIONS = [
    {
        "id": "o1", "meta": {"profile": [PROFILE]}, "subject": {"reference": "Location/Loc-Almyros"},
        "code": {"coding": [{"code": "nitrate"}]}, "valueQuantity": {"value": 1.0, "code": "mg/L"},
    }
]


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)
    runtime, _, _ = make_runtime()
    set_runtime(runtime)

    def refuse(*_a: Any, **_k: Any):
        raise AssertionError("the catalogue must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    yield
    set_runtime(None)


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture()
def stores(tmp_path: Path, monkeypatch) -> None:
    """Waterbase (GR without coordinates, IT river and lake, NO river), bathing classes (GR, IT), samples (GR, IT)."""
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(build_waterbase_store(tmp_path)))
    monkeypatch.setenv(
        "OAH_BATHING_WATER_STORE",
        str(
            build_classification_store(
                tmp_path,
                rows=[
                    HEADER,
                    row("IT", "ITSYN001", 2022, "1 - Excellent"),
                    row("EL", "ELSYN001", 2023, "1 - Excellent"),
                ],
            )
        ),
    )
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(build_samples_store(tmp_path)))


def _catalog(http: TestClient, country: str = "IT", **params: str) -> dict[str, Any]:
    response = http.get("/catalog", params={"country": country, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _flat(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for family in body["families"] for item in family["indices"]}


def _verdicts(body: dict[str, Any]) -> dict[str, str | None]:
    return {key: item["reason_code"] for key, item in _flat(body).items()}


# --- shape ---------------------------------------------------------------------------------------------------------------


def test_the_response_lists_every_family_and_index_in_a_stable_order(http, stores):
    body = _catalog(http, "IT")
    assert body["country"] == "IT" and body["country_name"] == "Italy" and body["language"] == "en"
    assert [family["id"] for family in body["families"]] == ["water", "microbiology", "context", "data", "synthetic-labs"]
    assert [family["title"] for family in body["families"]] == ["Water", "Microbiology", "Context", "Data", "Synthetic labs"]
    flat = [item["id"] for family in body["families"] for item in family["indices"]]
    assert flat == list(INDEX_IDS) and flat == [item for item in _flat(_catalog(http, "NO"))]  # same order for every country
    for family in body["families"]:
        for item in family["indices"]:
            assert item["family_id"] == family["id"] and item["family_title"] == family["title"]
            assert item["origin_kind"] in {"real", "external", "synthetic"} and item["routes"] and item["origins"]
            assert item["applies"] == (item["reason_code"] is None) == (item["reason"] is None)
    assert body["interpretation_notice"] == INTERPRETATION_NOTICE == ENGLISH["interpretation_notice"]
    assert body["data_freshness"]["status"] in {"live", "snapshot", "snapshot-stale", "unknown"}
    assert body["origin"] == "real-mixed"
    assert body["applicable_count"] == sum(item["applies"] for item in _flat(body).values())


def test_the_unavailable_indices_are_never_returned(http, stores):
    for country in ("GR", "IT", "NO"):
        text = str(_catalog(http, country)).lower()
        for name in (*NEVER_RETURNED, "biotic", "protozoa", "air quality", "population health"):
            assert name not in text


def test_the_stores_block_reports_every_source_state(http, stores):
    body = _catalog(http, "IT")["stores"]
    assert body["sandbox"] == "available"
    assert body["waterbase"]["state"] == body["bathing_water"]["state"] == body["bathing_samples"]["state"] == "ready"
    assert body["external"] == {"enabled": True, "weather": True, "discharge": True, "species": True}


def test_origin_kinds_chat_indices_and_routes_of_the_indices(http, stores):
    flat = _flat(_catalog(http, "IT"))
    assert {key: item["origin_kind"] for key, item in flat.items()} == {
        "water-quality": "real", "water-parameters": "real", "solids-turbidity": "real", "organic-matter": "real",
        "bathing-classes": "real", "bathing-samples": "real", "weather": "external", "river-discharge": "external",
        "species-nearby": "external", "data-quality": "real", "citizen-science": "synthetic", "review-queue": "synthetic",
        "river-risk": "synthetic",
    }
    assert flat["bathing-samples"]["chat_index"] == "microbiology" and flat["weather"]["chat_index"] is None
    assert flat["species-nearby"]["origins"] == ["external-gbif"] and flat["river-risk"]["origins"] == ["synthetic"]


# --- applicability from the data held -------------------------------------------------------------------------------------


def test_italy_with_every_store_ready(http, stores):
    verdicts = _verdicts(_catalog(http, "IT"))
    # the only sandbox site of Italy was skipped (no evaluable record), so no CCME index; the fixture Waterbase has chemistry only
    assert verdicts["water-quality"] == "no-data-for-country"
    assert verdicts["solids-turbidity"] == "no-data-for-country" and verdicts["organic-matter"] == "no-data-for-country"
    assert {key for key, reason in verdicts.items() if reason is not None} == {"water-quality", "solids-turbidity", "organic-matter"}


def test_greece_has_a_ccme_index_through_the_sandbox_site(http, stores):
    body = _catalog(http, "GR")
    assert body["country_name"] == "Greece" and _verdicts(body)["water-quality"] is None
    assert _flat(body)["bathing-classes"]["applies"] and _flat(body)["bathing-samples"]["applies"]


def test_norway_has_measurements_but_no_bathing_water_data(http, stores):
    verdicts = _verdicts(_catalog(http, "NO"))
    assert verdicts["water-parameters"] is None and verdicts["water-quality"] == "no-data-for-country"
    assert verdicts["bathing-classes"] == "no-data-for-country" and verdicts["bathing-samples"] == "no-data-for-country"
    assert verdicts["weather"] is None and verdicts["river-discharge"] is None and verdicts["species-nearby"] is None


def test_without_any_store_the_store_based_indices_say_data_not_loaded(http):
    body = _catalog(http, "IT")
    verdicts = _verdicts(body)
    assert body["stores"]["waterbase"]["state"] == body["stores"]["bathing_water"]["state"] == "not-built"
    assert body["stores"]["bathing_samples"]["state"] == "not-built" and body["origin"] == "real-sandbox"
    assert {key for key, reason in verdicts.items() if reason == "data-not-loaded"} == {
        "water-parameters", "solids-turbidity", "organic-matter", "bathing-classes", "bathing-samples",
    }
    assert _flat(body)["bathing-classes"]["reason"] == ENGLISH["catalog_reason_not_loaded"] == "Data not loaded."
    # the sandbox still answers: the skipped Italian river site is a located water site for the external context
    assert verdicts["water-quality"] == "no-data-for-country" and verdicts["data-quality"] is None
    assert verdicts["weather"] is None and verdicts["river-discharge"] is None and verdicts["species-nearby"] is None
    assert _flat(body)["citizen-science"]["applies"]
    # Norway: no sandbox site, no store: the site-based indices cannot be decided without the stores
    assert _verdicts(_catalog(http, "NO"))["weather"] == "data-not-loaded"


def test_a_country_whose_waterbase_sites_have_no_coordinates_has_no_located_river(http, stores, monkeypatch):
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: [])
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [])
    verdicts = _verdicts(_catalog(http, "GR"))
    # the only Greek Waterbase site has no coordinates: no river, no water-quality site; the bathing water has coordinates
    assert verdicts["river-discharge"] == "no-located-river-site" and verdicts["species-nearby"] == "no-located-site"
    assert verdicts["weather"] is None  # a located bathing water is enough for the weather
    assert verdicts["water-quality"] == "no-data-for-country" and verdicts["water-parameters"] is None


def test_a_sandbox_that_cannot_answer_does_not_fail_the_catalogue(http, stores, monkeypatch):
    def down() -> list[dict[str, Any]]:
        raise HTTPException(status_code=503, detail="Sandbox data is unavailable (no live data and no usable snapshot).")

    monkeypatch.setattr(deps_module, "get_cached_locations", down)
    body = _catalog(http, "IT")
    verdicts = _verdicts(body)
    assert body["stores"]["sandbox"] == "unavailable"
    assert verdicts["water-quality"] == "data-not-loaded" and verdicts["data-quality"] == "data-not-loaded"
    assert verdicts["water-parameters"] is None and verdicts["bathing-classes"] is None  # the stores still answer
    assert _flat(body)["citizen-science"]["applies"] and body["country"] == "IT"
    assert http.get("/catalog", params={"country": "DE"}).status_code == 422  # validation still works


def test_another_failure_of_the_sandbox_is_not_swallowed(http, stores, monkeypatch):
    def broken() -> list[dict[str, Any]]:
        raise HTTPException(status_code=500, detail="boom")

    monkeypatch.setattr(deps_module, "get_cached_locations", broken)
    assert http.get("/catalog", params={"country": "IT"}).status_code == 500


def test_a_provider_that_is_switched_off_hides_its_index(http, stores):
    runtime, _, _ = make_runtime(settings=ExternalSettings(gbif_enabled=False))
    set_runtime(runtime)
    body = _catalog(http, "IT")
    verdicts = _verdicts(body)
    assert verdicts["species-nearby"] == "provider-off" and verdicts["weather"] is None and verdicts["river-discharge"] is None
    assert body["stores"]["external"] == {"enabled": True, "weather": True, "discharge": True, "species": False}
    assert _flat(body)["species-nearby"]["reason"] == ENGLISH["catalog_reason_provider_off"]


def test_the_master_switch_turns_off_all_three_providers(http, stores):
    runtime, _, _ = make_runtime(settings=ExternalSettings(enabled=False))
    set_runtime(runtime)
    body = _catalog(http, "IT")
    assert [_verdicts(body)[key] for key in ("weather", "river-discharge", "species-nearby")] == ["provider-off"] * 3
    assert body["stores"]["external"] == {"enabled": False, "weather": False, "discharge": False, "species": False}


# --- the query -----------------------------------------------------------------------------------------------------------


def test_el_is_an_alias_of_gr_and_the_case_does_not_matter(http, stores):
    greece = _catalog(http, "GR")
    for text in ("EL", "el", "gr", "Gr"):
        alias = _catalog(http, text)
        assert alias["country"] == "GR" and alias["families"] == greece["families"]


def test_an_unknown_country_is_a_422_that_lists_the_known_codes(http, stores):
    response = http.get("/catalog", params={"country": "DE"})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "'DE'" in detail and "['GR', 'IT', 'NO']" in detail


@pytest.mark.parametrize("query", ["", "?country=", "?country=GRC", "?country=G", "?country=1T", "?country=%27%3B--", "?language=en"])
def test_the_country_is_required_and_must_be_two_letters(http, stores, query):
    assert http.get(f"/catalog{query}").status_code == 422


def test_the_reasons_are_localised_while_the_codes_stay_fixed(http, stores):
    english = _flat(_catalog(http, "IT"))["water-quality"]
    italian = _flat(_catalog(http, "IT", language="it"))["water-quality"]
    spanish = _flat(_catalog(http, "IT", language="es"))["water-quality"]
    assert english["reason_code"] == italian["reason_code"] == "no-data-for-country"
    assert english["reason"] == ENGLISH["catalog_reason_no_data"]
    assert italian["reason"] == load_strings("it").strings["catalog_reason_no_data"] != english["reason"]
    assert spanish["reason"] == load_strings("es-MX").strings["catalog_reason_no_data"]
    assert _catalog(http, "IT", language="it")["language"] == "it"
    assert italian["title"] == english["title"]  # titles are the English ones the UI uses


def test_an_unknown_language_is_a_422(http, stores):
    assert http.get("/catalog", params={"country": "IT", "language": "xx"}).status_code == 422
    assert http.get("/catalog", params={"country": "IT", "language": "x"}).status_code == 422


# --- protection and contract ---------------------------------------------------------------------------------------------


def test_the_route_uses_the_shared_rate_limit_and_the_api_key(http, stores, monkeypatch):
    limiter = RateLimiter(1, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: limiter)
    assert http.get("/catalog", params={"country": "IT"}).status_code == 200
    assert http.get("/catalog", params={"country": "IT"}).status_code == 429
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("OAH_API_KEY", "k" * 40)
    assert http.get("/catalog", params={"country": "IT"}).status_code == 401
    assert http.get("/catalog", params={"country": "IT"}, headers={"X-API-Key": "k" * 40}).status_code == 200


def test_every_route_named_by_an_index_exists_in_the_app(http):
    from oah.indices.catalog import INDEX_SPECS

    served = set(app_module.app.openapi()["paths"])
    for spec in INDEX_SPECS:
        assert set(spec.routes) <= served, spec.id


def test_the_openapi_describes_the_catalogue_route(http):
    operation = app_module.app.openapi()["paths"]["/catalog"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("CatalogResponse")
    assert {"401", "422", "429", "503"} <= set(operation["responses"])
    country = next(param for param in operation["parameters"] if param["name"] == "country")
    assert country["required"] is True
