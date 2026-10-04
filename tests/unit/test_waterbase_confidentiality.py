"""Privacy of restricted Waterbase sites (``docs/waterbase_store.md``, "Confidentiality").

A site whose ``confidentialityStatus`` is anything other than ``F`` (free for publication) has no location: the build stores
NULL coordinates even when the source CSV supplies them, and every reader treats such a site as ``no-location`` even when a
hand-edited store holds coordinates for it. All data here is SYNTHETIC (invented sites and values in temporary directories).
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from pathlib import Path

import pytest
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
from fastapi.testclient import TestClient
from period_fixtures import LOCATIONS, OBSERVATIONS
from waterbase_fixtures import SPATIAL_HEADER, build_fixture_store, spatial, standard_spatial

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.chat.tools import ALL_TOOLS, run_tool
from oah.external import constants as c
from oah.external import runtime as runtime_module
from oah.external.runtime import set_runtime
from oah.external.sites import SiteLocator, SiteLookupError
from oah.waterbase import service, store
from oah.waterbase.mapping import FREE_FOR_PUBLICATION, location_publishable
from oah.waterbase.spatial import read_spatial

SITE = "IT01-001025"  # a river site of the synthetic archive, given coordinates below
PERIOD = "date_from=2021-03-01&date_to=2021-03-05"


def flagged_spatial(status: str) -> list[list[str]]:
    """The standard synthetic spatial rows, except that ``SITE`` is flagged WITH coordinates in the source."""
    rows = standard_spatial()
    rows[0] = spatial("IT", SITE, "PO - REVELLO", "riverWaterBody", "PO", "44.65", "7.38", status)
    return rows


def raw_site(path: Path, site_id: str) -> tuple[object, ...]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute("SELECT lat, lon, confidentiality FROM sites WHERE site_id = ?", [site_id]).fetchone()
    finally:
        connection.close()


def counts_of(path: Path) -> dict[str, int]:
    connection = sqlite3.connect(path)
    try:
        return json.loads(connection.execute("SELECT value FROM provenance WHERE key = 'row_counts'").fetchone()[0])
    finally:
        connection.close()


def force_coordinates(path: Path, site_id: str, status: str | None) -> None:
    """Hand-build the forbidden state: coordinates AND a restricted status on one site of a built store."""
    connection = sqlite3.connect(path)
    try:
        connection.execute("UPDATE sites SET lat = 45.07, lon = 9.19, confidentiality = ? WHERE site_id = ?", [status, site_id])
        connection.commit()
    finally:
        connection.close()


def spatial_lines(rows: list[list[str]]) -> list[str]:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(SPATIAL_HEADER)
    writer.writerows(rows)
    return buffer.getvalue().splitlines()


# --- the rule ---------------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status, publishable",
    [("F", True), (" F ", True), ("N", False), ("", False), (None, False), ("f", False), ("X", False), ("FN", False), (1, False)],
)
def test_only_the_documented_free_status_is_publishable(status, publishable):
    assert FREE_FOR_PUBLICATION == "F"
    assert location_publishable(status) is publishable


# --- the build drops the coordinates ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", ["N", "X", ""])
def test_the_build_stores_no_coordinates_for_a_flagged_site_whose_source_row_has_them(tmp_path: Path, status: str):
    path = build_fixture_store(tmp_path, spatial_rows=flagged_spatial(status))
    lat, lon, kept_status = raw_site(path, SITE)
    assert (lat, lon) == (None, None)
    assert kept_status == (status or None)  # the raw status is still stored
    counts = counts_of(path)
    assert counts["sites_confidential"] == 2  # SITE and the Greek site, flagged N in the standard rows
    assert counts["sites_confidential_with_coordinates_dropped"] == 1  # only SITE had coordinates in the source
    assert counts["sites_without_location"] == 3  # the Greek site, the site without a spatial row, and SITE
    assert raw_site(path, "IT02-LAKE1")[:2] == (45.9, 8.6) and raw_site(path, "NO0001")[:2] == (60.1, 10.2)  # free sites keep theirs


def test_a_free_site_keeps_its_coordinates_and_the_counters_say_zero_dropped(tmp_path: Path):
    rows = standard_spatial()
    rows[2] = spatial("EL", "EL000123", "ALMYROS WELL FIELD", "riverWaterBody", "TEST BODY", "", "", "F")
    path = build_fixture_store(tmp_path, spatial_rows=rows)
    counts = counts_of(path)
    assert counts["sites_confidential"] == 0 and counts["sites_confidential_with_coordinates_dropped"] == 0
    assert raw_site(path, SITE)[:2] == (44.65, 7.38)


def test_the_spatial_reader_withholds_and_counts_and_a_restricted_row_wins_a_duplicate():
    lines = spatial_lines([
        spatial("IT", "A1", "free", "riverWaterBody", "W1", "44.0", "9.0", "F"),
        spatial("IT", "B1", "flagged", "riverWaterBody", "W2", "45.0", "10.0", "N"),
        spatial("IT", "C1", "no status", "riverWaterBody", "W3", "46.0", "11.0", ""),
        spatial("IT", "D1", "first free", "riverWaterBody", "W4", "47.0", "12.0", "F"),
        spatial("IT", "D1", "second flagged", "riverWaterBody", "W4", "47.1", "12.1", "N"),
        spatial("IT", "E1", "flagged first", "riverWaterBody", "W5", "48.0", "13.0", "N"),
        spatial("IT", "E1", "free second", "riverWaterBody", "W5", "48.1", "13.1", "F"),
        spatial("IT", "F1", "flagged no coordinates", "riverWaterBody", "W6", "", "", "N"),
    ])
    sites = read_spatial(lines)
    assert (sites[("IT", "A1")].lat, sites[("IT", "A1")].lon, sites[("IT", "A1")].coordinates_withheld) == (44.0, 9.0, False)
    for key in ("B1", "C1", "D1", "E1"):
        site = sites[("IT", key)]
        assert (site.lat, site.lon) == (None, None) and site.coordinates_withheld is True, key
        assert site.confidentiality in ("N", None), key
    assert sites[("IT", "C1")].confidentiality is None
    flagged_empty = sites[("IT", "F1")]
    assert (flagged_empty.lat, flagged_empty.lon, flagged_empty.coordinates_withheld) == (None, None, False)
    assert sites[("IT", "D1")].confidentiality == "N" and sites[("IT", "E1")].confidentiality == "N"


# --- the readers refuse even when the stored values contain coordinates -----------------------------------------------------


@pytest.fixture()
def forced(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path)
    force_coordinates(path, SITE, "N")
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    return path


def test_the_store_reader_treats_a_flagged_site_with_stored_coordinates_as_having_no_location(forced: Path):
    assert raw_site(forced, SITE)[:2] == (45.07, 9.19)  # the hand-built forbidden state really is in the file
    site = store.get_site(SITE)
    assert site is not None and (site.lat, site.lon, site.has_location, site.confidentiality) == (None, None, False, "N")
    listed = {item.site_id: item for item in store.list_sites()[1]}
    assert listed[SITE].has_location is False and listed["IT02-LAKE1"].has_location is True
    assert store.located_counts()["IT"] == (0, 1)  # the river site is no longer counted as located; the lake still is
    italy = next(item for item in store.countries_summary() if item.country == "IT")
    assert italy.sites_without_location == 2  # the flagged site and the site without a spatial row


@pytest.mark.parametrize("status", [None, "", "X", "f"])
def test_any_status_other_than_f_is_refused_at_read_time(tmp_path: Path, status):
    path = build_fixture_store(tmp_path)
    force_coordinates(path, SITE, status)
    site = store.get_site(SITE, path)
    assert site is not None and site.has_location is False and (site.lat, site.lon) == (None, None)
    assert store.located_counts(path)["IT"] == (0, 1)


def test_the_service_entries_and_the_measurement_site_block_have_no_location(forced: Path):
    found = service.find_site(SITE)
    assert found is not None
    from oah.waterbase.measurements import site_entry, site_info

    entry, info = site_entry(found), site_info(found)
    for block in (entry, info):
        assert block["latitude"] is None and block["longitude"] is None and block["location_status"] == "no-location"
    assert info["confidentiality"] == "N"


@pytest.fixture()
def world(forced: Path, monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)
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


def test_the_sites_route_lists_the_flagged_site_without_coordinates(http, world):
    body = http.get("/sites?source=real-eea-waterbase&country=IT&limit=500").json()
    entry = next(item for item in body["sites"] if item["id"] == SITE)
    assert entry["latitude"] is None and entry["longitude"] is None and entry["location_status"] == "no-location"
    other = next(item for item in body["sites"] if item["id"] == "IT02-LAKE1")
    assert other["location_status"] == "located"


def test_the_measurements_route_has_no_coordinates_in_its_site_block(http, world):
    body = http.get(f"/sites/{SITE}/measurements").json()
    assert body["site"]["latitude"] is None and body["site"]["longitude"] is None
    assert body["site"]["location_status"] == "no-location" and body["site"]["confidentiality"] == "N"


def test_the_catalogue_and_countries_do_not_count_the_flagged_site_as_located(http, world):
    countries = http.get("/countries").json()["countries"]
    italy = next(item for item in countries if item["code"] == "IT")
    waterbase = next(item for item in italy["sources"] if item["source"] == "real-eea-waterbase")
    assert waterbase["sites_without_location"] == 2


@pytest.mark.parametrize("route", ["weather", "discharge", "species"])
def test_each_external_route_answers_no_location_and_never_calls_a_provider(http, world, route):
    query = PERIOD if route != "species" else ""
    response = http.get(f"/sites/{SITE}/{route}?{query}")
    assert response.status_code == 422 and "no-location" in response.json()["detail"]
    assert world.requests == []


def test_the_chat_tools_refuse_the_flagged_site_without_calling_a_provider(http, world):
    context = app_module._chat_tool_context("IT")
    for tool, arguments in (
        ("get_weather_context", {"site_id": SITE, "date_from": "2021-03-01", "date_to": "2021-03-05"}),
        ("get_river_discharge_context", {"site_id": SITE, "date_from": "2021-03-01", "date_to": "2021-03-05"}),
        ("get_species_nearby", {"site_id": SITE}),
    ):
        outcome = run_tool(context, tool, arguments, ALL_TOOLS)
        assert not outcome.ok and "no-location" in (outcome.error or ""), tool
    assert world.requests == []


def test_the_locator_itself_refuses_an_entry_that_carries_coordinates_but_is_flagged():
    flagged = {"id": "S", "name": "S", "latitude": 45.0, "longitude": 9.0, "confidentiality": "N", "location_status": "located"}
    marked = {"id": "S", "name": "S", "latitude": 45.0, "longitude": 9.0, "location_status": "no-location"}
    free = {"id": "S", "name": "S", "latitude": 45.0, "longitude": 9.0, "confidentiality": "F", "location_status": "located"}
    for entry in (flagged, marked):
        with pytest.raises(SiteLookupError) as caught:
            SiteLocator(waterbase=lambda site_id, entry=entry: entry).locate("S")
        assert caught.value.status_code == 422 and "no-location" in caught.value.detail
    assert SiteLocator(waterbase=lambda site_id: free).locate("S").latitude == 45.0
