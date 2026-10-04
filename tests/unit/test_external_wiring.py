"""The real site locator behind the external routes and tools: Waterbase, bathing-water and sandbox sites from SYNTHETIC stores.

The stores are built from invented archives (``waterbase_fixtures``, ``bathing_fixtures``); the providers are scripted fakes.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from bathing_fixtures import build_fixture_store as build_bathing_store
from external_fakes import (
    FakeClock,
    archive_handler,
    flood_handler,
    gbif_handler,
    json_response,
    make_runtime,
    occurrence,
    search_payload,
)
from fastapi import HTTPException
from fastapi.testclient import TestClient
from period_fixtures import LOCATIONS, OBSERVATIONS
from waterbase_fixtures import build_fixture_store as build_waterbase_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.chat.tools import ALL_TOOLS, run_tool
from oah.external import constants as c
from oah.external import runtime as runtime_module
from oah.external.runtime import set_runtime

PERIOD = "date_from=2021-03-01&date_to=2021-03-05"


@pytest.fixture(autouse=True)
def _world(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(build_waterbase_store(tmp_path)))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(build_bathing_store(tmp_path)))
    runtime, router, _ = make_runtime(clock=FakeClock())
    router.on(c.ARCHIVE_HOST, archive_handler())
    router.on(c.FLOOD_HOST, flood_handler())
    router.on(c.GBIF_HOST, gbif_handler(lambda request: json_response(search_payload([occurrence(1)]))))
    set_runtime(runtime)
    monkeypatch.setattr(runtime_module, "_runtime", runtime)
    yield router
    set_runtime(None)


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


def test_a_waterbase_river_site_is_located_from_the_store(http, _world):
    body = http.get(f"/sites/IT01-001025/weather?{PERIOD}").json()
    assert body["status"] == "ok" and body["site"]["kind"] == "waterbase-site" and body["site"]["country"] == "IT"
    assert body["site"]["water_category"] == "river" and (body["site"]["latitude"], body["site"]["longitude"]) == (44.65, 7.38)
    sent = _world.requests[0].url.params
    assert (sent["latitude"], sent["longitude"]) == ("44.65", "7.38")
    discharge = http.get(f"/sites/IT01-001025/discharge?{PERIOD}").json()
    assert discharge["status"] == "ok" and "site-not-a-river" not in discharge["flags"]


def test_a_waterbase_lake_gets_the_not_a_river_flag(http):
    body = http.get(f"/sites/IT02-LAKE1/discharge?{PERIOD}").json()
    assert body["site"]["water_category"] == "lake" and "site-not-a-river" in body["flags"]


def test_a_waterbase_site_without_coordinates_is_a_422_and_never_reaches_a_provider(http, _world):
    response = http.get(f"/sites/EL000123/weather?{PERIOD}")
    assert response.status_code == 422 and "coordinates" in response.json()["detail"]
    assert _world.requests == []


def test_a_bathing_water_is_located_for_weather_only(http, _world):
    body = http.get(f"/sites/EL001/weather?{PERIOD}").json()
    assert body["site"]["kind"] == "bathing-water" and body["site"]["country"] == "GR"
    assert (body["site"]["latitude"], body["site"]["longitude"]) == (35.1, 25.1)
    refused = http.get(f"/sites/EL001/discharge?{PERIOD}")
    assert refused.status_code == 422 and "bathing water" in refused.json()["detail"]
    assert http.get("/sites/EL001/species").status_code == 422


def test_a_sandbox_site_is_located_from_its_location_resource(http):
    body = http.get(f"/sites/Loc-Almyros/weather?{PERIOD}").json()
    assert body["site"]["kind"] == "sandbox-site" and body["site"]["source"] == "real-sandbox"
    assert (body["site"]["latitude"], body["site"]["longitude"]) == (35.3, 25.0)
    assert http.get("/sites/Loc-Almyros/species").json()["status"] == "ok"


def test_unknown_ids_are_404_and_a_sandbox_outage_is_the_usual_503(http, monkeypatch):
    assert http.get(f"/sites/NOPE/weather?{PERIOD}").status_code == 404

    def unavailable():
        raise HTTPException(status_code=503, detail="Sandbox data is unavailable (no live data and no usable snapshot).")

    monkeypatch.setattr(deps_module, "get_cached_locations", unavailable)
    assert http.get(f"/sites/NOPE/weather?{PERIOD}").status_code == 503
    # a local store answers without touching the sandbox at all
    assert http.get(f"/sites/IT01-001025/weather?{PERIOD}").status_code == 200
    assert http.get(f"/sites/EL001/weather?{PERIOD}").status_code == 200


def test_a_sandbox_location_without_a_position_is_not_a_site_for_context(http, monkeypatch):
    bare = [{"resourceType": "Location", "id": "Loc-Bare", "name": "Bare"}, {"resourceType": "Location", "name": "No id", "position": {}}]
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: bare)
    assert http.get(f"/sites/Loc-Bare/weather?{PERIOD}").status_code == 404
    entries = app_module._sandbox_site_entries()
    assert entries == []
    monkeypatch.setattr(
        deps_module, "get_cached_locations",
        lambda: [{"id": "Loc-Half", "name": "Half", "position": {"latitude": 35.0}}],
    )
    assert http.get(f"/sites/Loc-Half/weather?{PERIOD}").status_code == 422


def test_the_chat_tools_use_the_same_locator_and_enforce_the_country(http):
    context = app_module._chat_tool_context("IT")
    assert context.external is not None
    ok = run_tool(context, "get_weather_context", {"site_id": "IT01-001025", "date_from": "2021-03-01", "date_to": "2021-03-05"}, ALL_TOOLS)
    assert ok.ok and ok.result is not None and ok.result["site"]["country"] == "IT"
    greek = run_tool(app_module._chat_tool_context("GR"), "get_weather_context",
                     {"site_id": "IT01-001025", "date_from": "2021-03-01", "date_to": "2021-03-05"}, ALL_TOOLS)
    assert not greek.ok and "not the selected country GR" in (greek.error or "")
    bathing = run_tool(app_module._chat_tool_context("GR"), "get_weather_context",
                       {"site_id": "EL001", "date_from": "2021-03-01", "date_to": "2021-03-05"}, ALL_TOOLS)
    assert bathing.ok


def test_the_status_route_needs_no_site(http):
    assert http.get("/external/status").status_code == 200
