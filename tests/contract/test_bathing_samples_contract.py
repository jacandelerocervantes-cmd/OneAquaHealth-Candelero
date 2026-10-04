"""Contract of the bathing-water SAMPLES routes as the committed OpenAPI file states it.

What a client may rely on: the three routes, their query parameters and bounds, the new origin value, closed value kinds, the
presence of the notices and the unit, and the ABSENCE of any limit, threshold, classification or significance field.
"""

from __future__ import annotations

import json
from typing import Any

from oah.paths import openapi_path

SPEC = json.loads(openapi_path().read_text(encoding="utf-8"))
SCHEMAS = SPEC["components"]["schemas"]
SAMPLES_PATH = "/bathing-waters/{bw_id}/samples"
SITE_CHANGE_PATH = "/bathing-waters/{bw_id}/samples/change"
COUNTRY_CHANGE_PATH = "/bathing-waters/samples/change"


def _parameters(path: str) -> dict[str, Any]:
    return {item["name"]: item for item in SPEC["paths"][path]["get"]["parameters"] if item["name"] != "x-api-key"}  # the key header is on every route


def _all_property_names(schema_name: str, seen: set[str] | None = None) -> set[str]:
    """Every property name reachable from a schema (so a forbidden field cannot hide in a nested model)."""
    seen = set() if seen is None else seen
    if schema_name in seen:
        return set()
    seen.add(schema_name)
    names: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "$ref" in node:
                names.update(_all_property_names(node["$ref"].rsplit("/", 1)[1], seen))
            for key, value in node.items():
                if key == "properties" and isinstance(value, dict):
                    names.update(value)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(SCHEMAS[schema_name])
    return names


def test_the_three_routes_are_documented_and_get_only():
    for path in (SAMPLES_PATH, SITE_CHANGE_PATH, COUNTRY_CHANGE_PATH):
        assert set(SPEC["paths"][path]) == {"get"}, path


def test_the_samples_route_parameters_and_bounds():
    parameters = _parameters(SAMPLES_PATH)
    assert set(parameters) == {"bw_id", "date_from", "date_to", "season", "limit", "order", "language"}
    assert parameters["limit"]["schema"]["default"] == 200 and parameters["limit"]["schema"]["maximum"] == 500 and parameters["limit"]["schema"]["minimum"] == 1
    assert parameters["season"]["schema"]["anyOf"][0]["minimum"] == 1900 and parameters["season"]["schema"]["anyOf"][0]["maximum"] == 2100
    assert parameters["order"]["schema"]["enum"] == ["asc", "desc"] and parameters["bw_id"]["in"] == "path"
    assert {"404", "422"} <= set(SPEC["paths"][SAMPLES_PATH]["get"]["responses"])


def test_the_change_routes_take_two_periods_and_a_language():
    for path, extra in ((SITE_CHANGE_PATH, "bw_id"), (COUNTRY_CHANGE_PATH, "country")):
        parameters = _parameters(path)
        assert set(parameters) == {extra, "a_from", "a_to", "b_from", "b_to", "language"}, path
        for name in ("a_from", "a_to", "b_from", "b_to"):
            assert parameters[name]["required"] is True and parameters[name]["schema"]["minLength"] == 7 and parameters[name]["schema"]["maxLength"] == 7
    assert _parameters(COUNTRY_CHANGE_PATH)["country"]["schema"]["pattern"] == "^[A-Za-z]{2}$"


def test_every_samples_response_carries_the_new_origin_the_notices_the_unit_and_freshness():
    for name in ("BathingSamplesResponse", "BathingSamplesChangeResponse", "BathingSamplesCountryChangeResponse"):
        properties = SCHEMAS[name]["properties"]
        assert properties["origin"]["const"] == "real-eea-bathing-samples" or properties["origin"].get("enum") == ["real-eea-bathing-samples"], name
        assert {"data_freshness", "attribution", "language", "notice", "no_threshold_notice", "flagged_values_note", "unit", "bathing_samples"} <= set(properties), name
    assert "change_notice" in SCHEMAS["BathingSamplesChangeResponse"]["properties"] and "change_notice" in SCHEMAS["BathingSamplesCountryChangeResponse"]["properties"]


def test_the_origin_enum_gains_the_samples_value_and_stays_closed():
    origin = SCHEMAS["SitesResponse"]["properties"]["origin"]["enum"]
    assert "real-eea-bathing-samples" in origin and "real-eea-bathing-water" in origin and len(origin) == 6


def test_the_value_kinds_are_a_closed_set():
    kind = SCHEMAS["SampleIndicator"]["properties"]["kind"]["enum"]
    assert kind == ["quantified", "confirmed-high", "detection-limit", "missing", "unknown-status", "invalid"]
    assert set(SCHEMAS["SampleIndicator"]["required"]) == {"kind"}  # value, reported_value and status are nullable


def test_no_samples_model_has_a_limit_a_threshold_a_classification_or_a_significance_field():
    forbidden = {"limit", "limit_basis", "limit_regime", "limit_type", "limit_range", "crossed_limit", "assessment", "threshold", "classification", "quality",
                 "p_value", "significance", "significant", "status_against_limit", "scored_value", "river_limit", "n_below_loq", "below_loq_share"}
    for name in ("BathingSamplesResponse", "BathingSamplesChangeResponse", "BathingSamplesCountryChangeResponse"):
        names = _all_property_names(name)
        # ``limit`` is the page size of the samples route only; it is an integer bound, never a concentration limit
        if name != "BathingSamplesResponse":
            assert not (names & forbidden), (name, names & forbidden)
        else:
            assert not ((names & forbidden) - {"limit"}), (name, (names & forbidden) - {"limit"})
            assert SCHEMAS[name]["properties"]["limit"]["type"] == "integer"


def test_the_history_the_countries_and_the_country_block_gain_the_samples_fields():
    assert "samples" in SCHEMAS["BathingWaterHistoryResponse"]["properties"]
    link = SCHEMAS["BathingSamplesLink"]["properties"]
    assert {"state", "available", "n_samples", "first_sample_date", "last_sample_date", "path"} <= set(link)
    assert "bathing_samples" in SCHEMAS["CountriesResponse"]["properties"] and "bathing_samples" in SCHEMAS["CountriesResponse"]["required"]
    assert "samples" in SCHEMAS["CountryBathingWater"]["properties"]
    assert SCHEMAS["CountryBathingSamples"]["properties"]["content"]["const"] == "individual-samples-no-thresholds"
    assert SCHEMAS["CountryBathingSamples"]["properties"]["origin"]["const"] == "real-eea-bathing-samples"


def test_the_chat_origin_and_citation_source_accept_the_samples_source():
    assert "real-eea-bathing-samples" in SCHEMAS["ChatResponse"]["properties"]["origin"]["enum"]
