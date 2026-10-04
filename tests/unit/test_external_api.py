"""The external-context routes: contracts, error codes, localisation, graceful unavailability, protection.

Providers are a scripted fake HTTP layer (``external_fakes``); the sites are a fake locator; nothing reaches the network.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest
from external_fakes import (
    archive_handler,
    fake_locator,
    flood_handler,
    gbif_handler,
    json_response,
    make_runtime,
    occurrence,
    search_payload,
)
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
import oah.api.payloads as payloads_module
from oah.api.rate_limit import RateLimiter
from oah.external import constants as c
from oah.external.service import NOTICE_KEYS, ExternalContext
from oah.external.settings import ExternalSettings
from oah.i18n.strings import ENGLISH, load_strings

TODAY = date(2026, 10, 3)
WEATHER = "/sites/ITRIVER1/weather?date_from=2021-03-01&date_to=2021-03-31"


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))


def install(monkeypatch, settings: ExternalSettings | None = None, search=None):
    runtime, router, clock = make_runtime(settings=settings)
    router.on(c.ARCHIVE_HOST, archive_handler(rain=lambda d: 1.0, temp=lambda d: 10.0))
    router.on(c.FLOOD_HOST, flood_handler())
    router.on(
        c.GBIF_HOST,
        gbif_handler(search or (lambda request: json_response(search_payload([occurrence(1), occurrence(2, license="CC0_1_0")])))),
    )
    context = ExternalContext(fake_locator(), lambda: runtime, lambda: TODAY)
    monkeypatch.setattr(payloads_module, "get_external_context", lambda: context)
    return TestClient(app_module.app), router, runtime


# --- weather -----------------------------------------------------------------------------------------------------------


def test_weather_route_returns_the_labelled_monthly_context(monkeypatch):
    http, router, _ = install(monkeypatch)
    response = http.get(WEATHER)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["reason"] is None and body["origin"] == "external-open-meteo"
    assert body["data_kind"] == "modelled-reanalysis" and body["provider"] == "open-meteo-archive"
    assert body["attribution"].startswith("Weather data by Open-Meteo.com") and body["attribution_url"] == "https://open-meteo.com/"
    assert body["language"] == "en" and set(body["notices"]) == set(NOTICE_KEYS["open-meteo-archive"])
    assert body["notices"]["external_reanalysis_notice"] == ENGLISH["external_reanalysis_notice"]
    assert body["site"]["id"] == "ITRIVER1" and body["site"]["coordinate_decimals"] == 2
    month = body["months"][0]
    assert month["month"] == "2021-03" and month["precipitation_sum_mm"] == 31.0 and month["temperature_mean_c"] == 10.0
    assert body["data_limits"]["era5_delay_days"] == 5 and body["grid"]["grid_latitude"] == 45.0
    assert router.count() == 1 and response.headers["cache-control"] == "no-store"


def test_weather_notices_are_localised_and_a_bad_language_is_422(monkeypatch):
    http, _, _ = install(monkeypatch)
    body = http.get(WEATHER + "&language=it").json()
    assert body["language"] == "it"
    strings = load_strings("it")
    assert body["notices"] == {key: strings.get(key) for key in NOTICE_KEYS["open-meteo-archive"]}
    assert body["notices"]["external_context_notice"] != ENGLISH["external_context_notice"]
    assert http.get(WEATHER + "&language=zz").status_code == 422


def test_weather_accepts_a_bathing_water_and_a_sandbox_site(monkeypatch):
    http, _, _ = install(monkeypatch)
    bathing = http.get("/sites/IT001001050001/weather?date_from=2021-03-01&date_to=2021-03-05")
    assert bathing.status_code == 200 and bathing.json()["site"]["kind"] == "bathing-water"
    sandbox = http.get("/sites/Loc-Almyros/weather?date_from=2021-03-01&date_to=2021-03-05")
    assert sandbox.status_code == 200 and sandbox.json()["site"]["country"] == "GR"


@pytest.mark.parametrize(
    "path, status",
    [
        ("/sites/NOPE/weather?date_from=2021-03-01&date_to=2021-03-31", 404),
        ("/sites/ITNOLOC/weather?date_from=2021-03-01&date_to=2021-03-31", 422),
        ("/sites/ITRIVER1/weather?date_from=2021-03-31&date_to=2021-03-01", 422),
        ("/sites/ITRIVER1/weather?date_from=2015-01-01&date_to=2021-03-01", 422),
        ("/sites/ITRIVER1/weather?date_from=2021-03-01", 422),
        ("/sites/ITRIVER1/weather", 422),
        ("/sites/ITRIVER1/weather?date_from=yesterday&date_to=2021-03-01", 422),
        ("/sites/bad%20id/weather?date_from=2021-03-01&date_to=2021-03-31", 422),
    ],
)
def test_weather_errors_are_404_or_422_and_never_reach_a_provider(monkeypatch, path, status):
    http, router, _ = install(monkeypatch)
    response = http.get(path)
    assert response.status_code == status
    assert router.requests == []
    if status != 422 or "detail" in response.json():
        assert response.json()["detail"]


# --- discharge ----------------------------------------------------------------------------------------------------------


def test_discharge_route_labels_the_modelled_cell(monkeypatch):
    http, router, _ = install(monkeypatch)
    body = http.get("/sites/ITRIVER1/discharge?date_from=2021-03-01&date_to=2021-03-31").json()
    assert body["status"] == "ok" and body["data_kind"] == "modelled-river-discharge" and body["attribution_verified"] is False
    assert body["months"][0]["river_discharge_mean_m3s"] == 50.0 and "nearest-cell-may-not-be-the-river" in body["flags"]
    assert body["data_range"] == {"first_day": "2021-03-01", "last_day": "2021-03-31"}
    assert set(body["notices"]) == set(NOTICE_KEYS["open-meteo-flood"])
    assert router.requests[0].url.host == c.FLOOD_HOST


def test_discharge_and_species_refuse_a_bathing_water(monkeypatch):
    http, router, _ = install(monkeypatch)
    for path in (
        "/sites/IT001001050001/discharge?date_from=2021-03-01&date_to=2021-03-05",
        "/sites/IT001001050001/species",
    ):
        response = http.get(path)
        assert response.status_code == 422 and "bathing water" in response.json()["detail"]
    assert router.requests == []


def test_discharge_beyond_the_data_is_a_200_with_the_flag(monkeypatch):
    http, _, _ = install(monkeypatch)
    body = http.get("/sites/ITRIVER1/discharge?date_from=1981-01-01&date_to=1983-12-31").json()
    assert body["status"] == "no-data" and "period-outside-data" in body["flags"]


# --- species ----------------------------------------------------------------------------------------------------------


def test_species_route_returns_records_with_licence_and_counts(monkeypatch):
    http, router, _ = install(monkeypatch)
    response = http.get("/sites/ITRIVER1/species?group=ept&date_from=2015-01-01&limit=5")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "external-gbif" and body["data_kind"] == "opportunistic-occurrence-records"
    assert body["total_records"] == 2 and body["returned"] == 2 and body["limit"] == 5
    assert [r["licence"] for r in body["records"]] == ["CC-BY-NC-4.0", "CC0-1.0"]
    assert body["records"][0]["non_commercial_only"] is True and body["records"][0]["dataset_key"]
    assert body["filters"] == {"group": "ept", "groups_searched": ["ephemeroptera", "plecoptera", "trichoptera"],
                               "date_from": "2015-01-01", "date_to": None}
    assert {item["group"]: item["count"] for item in body["group_counts"]} == {"ephemeroptera": 0, "plecoptera": 0, "trichoptera": 2}
    assert set(body["notices"]) == set(NOTICE_KEYS["gbif"]) and body["search"]["half_side_km"] == 5.0
    params = router.requests[0].url.params
    assert params["limit"] == "5" and params["eventDate"] == "2015-01-01,*" and sorted(params.get_list("taxonKey")) == ["1003", "1225", "787"]


@pytest.mark.parametrize(
    "query, status",
    [("limit=0", 422), ("limit=201", 422), ("limit=abc", 422), ("group=birds", 422), ("date_from=2020-01-02&date_to=2020-01-01", 422),
     ("date_from=1500-01-01", 422), ("group=ept&limit=200", 200), ("", 200)],
)
def test_species_input_errors(monkeypatch, query, status):
    http, _, _ = install(monkeypatch)
    assert http.get(f"/sites/ITRIVER1/species?{query}").status_code == status


# --- graceful unavailability ------------------------------------------------------------------------------------------------------


def test_a_failing_provider_is_a_200_with_external_unavailable_and_its_notice(monkeypatch):
    http, router, _ = install(monkeypatch)
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(429, headers={"retry-after": "30"}))
    body = http.get(WEATHER).json()
    assert body["status"] == "external-unavailable" and body["reason"] == "rate-limited" and body["months"] == []
    assert "external_unavailable_notice" in body["notices"] and body["site"]["id"] == "ITRIVER1" and body["attribution"]
    again = http.get(WEATHER).json()  # the breaker is open: refused without a request
    assert again["reason"] == "cooling-down" and router.count() == 1
    # the other providers are unaffected
    assert http.get("/sites/ITRIVER1/species").json()["status"] == "ok"


def test_switched_off_and_over_budget_providers_are_graceful(monkeypatch):
    http, router, _ = install(monkeypatch, ExternalSettings(enabled=False))
    for path in (WEATHER, "/sites/ITRIVER1/discharge?date_from=2021-03-01&date_to=2021-03-05", "/sites/ITRIVER1/species"):
        body = http.get(path).json()
        assert body["status"] == "external-unavailable" and body["reason"] == "disabled"
    assert router.requests == []
    http2, router2, _ = install(monkeypatch, ExternalSettings(open_meteo_per_minute=1, max_retries=0))
    body = http2.get("/sites/ITRIVER1/weather?date_from=2019-01-01&date_to=2021-12-31").json()
    assert body["status"] == "external-unavailable" and body["reason"] == "budget-exhausted" and router2.requests == []


def test_a_second_identical_request_is_served_from_the_cache(monkeypatch):
    http, router, _ = install(monkeypatch)
    first, second = http.get(WEATHER).json(), http.get(WEATHER).json()
    assert (first["cached"], second["cached"], router.count()) == (False, True, 1)


# --- status ------------------------------------------------------------------------------------------------------------


def test_external_status_lists_providers_limits_and_groups_without_secrets(monkeypatch):
    http, _, _ = install(monkeypatch, ExternalSettings(gbif_enabled=False, contact_url="https://example.org/contact"))
    response = http.get("/external/status")
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True and body["contact_url_configured"] is True and "example.org" not in response.text
    providers = {item["provider"]: item for item in body["providers"]}
    assert providers["gbif"]["enabled"] is False and providers["open-meteo-archive"]["enabled"] is True
    assert providers["open-meteo-archive"]["attribution_url"] == "https://open-meteo.com/"
    assert providers["open-meteo-flood"]["attribution_verified"] is False
    assert providers["open-meteo-archive"]["budget"]["per_day_limit"] == 3000
    assert [g["id"] for g in body["species_groups"]][:3] == ["ephemeroptera", "plecoptera", "trichoptera"]
    assert body["species_group_aliases"]["ept"] == ["ephemeroptera", "plecoptera", "trichoptera"]
    assert body["notices"]["external_context_notice"] == ENGLISH["external_context_notice"]
    assert http.get("/external/status?language=de").json()["notices"]["external_context_notice"] == load_strings("de").get("external_context_notice")
    assert http.get("/external/status?language=zz").status_code == 422


# --- protection and contract ---------------------------------------------------------------------------------------------------------


def test_the_routes_use_the_shared_rate_limit_and_the_api_key(monkeypatch):
    http, router, _ = install(monkeypatch)
    limiter = RateLimiter(1, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: limiter)
    assert http.get(WEATHER).status_code == 200
    limited = http.get(WEATHER)
    assert limited.status_code == 429 and router.count() == 1
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    monkeypatch.setenv("OAH_API_KEY", "k" * 40)
    assert http.get(WEATHER).status_code == 401
    assert http.get(WEATHER, headers={"X-API-Key": "k" * 40}).status_code == 200


def test_the_openapi_lists_the_new_routes_with_typed_responses_and_errors():
    spec = app_module.app.openapi()
    for path, schema in [
        ("/sites/{site_id}/weather", "WeatherResponse"),
        ("/sites/{site_id}/discharge", "DischargeResponse"),
        ("/sites/{site_id}/species", "SpeciesResponse"),
        ("/external/status", "ExternalStatusResponse"),
    ]:
        operation = spec["paths"][path]["get"]
        assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith(schema)
        assert {"401", "429", "503"} <= set(operation["responses"])
    for path in ("/sites/{site_id}/weather", "/sites/{site_id}/discharge", "/sites/{site_id}/species"):
        assert {"404", "422"} <= set(spec["paths"][path]["get"]["responses"])
    origins = spec["components"]["schemas"]["WeatherResponse"]["properties"]["origin"]
    assert origins["enum"] == ["external-open-meteo", "external-gbif"]
