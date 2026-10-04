"""Contract of the external-context routes: closed labels, typed responses, and no way to name a coordinate, URL or host."""
from __future__ import annotations

import pytest

from oah.api.app import app

SPEC = app.openapi()
SCHEMAS = SPEC["components"]["schemas"]
ROUTES = {
    "/sites/{site_id}/weather": ("WeatherResponse", {"site_id", "date_from", "date_to", "language"}),
    "/sites/{site_id}/discharge": ("DischargeResponse", {"site_id", "date_from", "date_to", "language"}),
    "/sites/{site_id}/species": ("SpeciesResponse", {"site_id", "group", "date_from", "date_to", "limit", "language"}),
    "/external/status": ("ExternalStatusResponse", {"language"}),
}


@pytest.mark.parametrize("path", list(ROUTES))
def test_each_route_is_a_typed_get_with_the_shared_errors(path: str) -> None:
    schema_name, _ = ROUTES[path]
    operations = SPEC["paths"][path]
    assert list(operations) == ["get"]
    responses = operations["get"]["responses"]
    assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith(schema_name)
    assert {"401", "429", "503"} <= set(responses)
    if path != "/external/status":
        assert {"404", "422"} <= set(responses)


@pytest.mark.parametrize("path", list(ROUTES))
def test_no_route_accepts_a_coordinate_a_url_or_a_host(path: str) -> None:
    _, allowed = ROUTES[path]
    names = {parameter["name"] for parameter in SPEC["paths"][path]["get"].get("parameters", [])} - {"x-api-key"}  # the shared key header
    assert names == allowed
    assert not names & {"latitude", "longitude", "lat", "lon", "url", "host", "uri", "endpoint"}


def test_origin_labels_are_closed_sets_and_the_shared_origin_is_not_widened() -> None:
    assert SCHEMAS["WeatherResponse"]["properties"]["origin"]["enum"] == ["external-open-meteo", "external-gbif"]
    assert SCHEMAS["SpeciesResponse"]["properties"]["data_kind"]["enum"] == [
        "modelled-reanalysis", "modelled-river-discharge", "opportunistic-occurrence-records",
    ]
    assert not any("external" in value for value in SCHEMAS["SitesResponse"]["properties"]["origin"]["enum"])
    chat_origin = SCHEMAS["ChatResponse"]["properties"]["origin"]["enum"]
    assert {"external-open-meteo", "external-gbif", "real-mixed"} <= set(chat_origin)


@pytest.mark.parametrize("name", ["WeatherResponse", "DischargeResponse", "SpeciesResponse"])
def test_every_external_response_says_what_it_is_and_how_to_credit_it(name: str) -> None:
    properties = SCHEMAS[name]["properties"]
    required = set(SCHEMAS[name]["required"])
    for field in ("status", "provider", "origin", "data_kind", "attribution", "attribution_verified", "licence", "flags", "site",
                  "language", "notices", "cached"):
        assert field in properties and field in required, (name, field)
    assert set(properties["status"]["enum"]) == {"ok", "no-data", "external-unavailable"}
    assert "disabled" in properties["reason"]["anyOf"][0]["enum"]


def test_a_species_record_carries_its_licence_and_attribution_data() -> None:
    record = SCHEMAS["SpeciesRecord"]
    for field in ("licence", "non_commercial_only", "dataset_key", "publishing_organization_key", "institution_code", "rights_holder",
                  "citation", "basis_of_record", "event_date", "coordinate_uncertainty_m"):
        assert field in record["properties"], field
    assert {"licence", "non_commercial_only", "gbif_id", "scientific_name"} <= set(record["required"])
    assert "recorded_by" not in record["properties"]  # the observer's name is never passed on


def test_the_monthly_values_name_their_units_and_coverage() -> None:
    weather = SCHEMAS["WeatherMonth"]["properties"]
    assert {"precipitation_sum_mm", "temperature_mean_c", "precipitation_n_days", "precipitation_coverage",
            "temperature_n_days", "temperature_coverage"} <= set(weather)
    discharge = SCHEMAS["DischargeMonth"]["properties"]
    assert {"river_discharge_mean_m3s", "n_days", "coverage"} <= set(discharge)
