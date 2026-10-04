"""The OpenAPI contract of the period-comparison and season-comparison routes (all additive)."""
from oah.api.app import app

SPEC = app.openapi()
SCHEMAS = SPEC["components"]["schemas"]
PERIOD_QUERY = {"a_from", "a_to", "b_from", "b_to"}


def _parameters(path: str) -> dict[str, dict]:
    return {p["name"]: p for p in SPEC["paths"][path]["get"]["parameters"]}


def test_the_new_routes_are_typed_and_declare_their_errors():
    for path in ("/sites/{site_id}/change", "/countries/{country_code}/change", "/bathing-waters/change"):
        operation = SPEC["paths"][path]["get"]
        assert "$ref" in operation["responses"]["200"]["content"]["application/json"]["schema"]
        for status in ("401", "422", "429", "503"):
            assert status in operation["responses"], (path, status)
    assert "404" in SPEC["paths"]["/sites/{site_id}/change"]["get"]["responses"]
    assert "404" in SPEC["paths"]["/countries/{country_code}/change"]["get"]["responses"]


def test_the_period_routes_take_four_months_a_parameter_and_an_optional_language():
    for path in ("/sites/{site_id}/change", "/countries/{country_code}/change"):
        parameters = _parameters(path)
        assert PERIOD_QUERY | {"parameter"} <= set(parameters) and all(parameters[name]["required"] for name in PERIOD_QUERY | {"parameter"})
        assert parameters["language"]["required"] is False
    assert "source" in _parameters("/countries/{country_code}/change") and _parameters("/countries/{country_code}/change")["source"]["required"] is False


def test_the_season_route_takes_a_country_two_seasons_an_optional_type_and_language():
    parameters = _parameters("/bathing-waters/change")
    assert {"country", "season_a", "season_b"} <= set(parameters) and all(parameters[n]["required"] for n in ("country", "season_a", "season_b"))
    assert parameters["type"]["required"] is False and parameters["language"]["required"] is False
    assert parameters["season_a"]["schema"]["minimum"] == 1900 and parameters["season_a"]["schema"]["maximum"] == 2100


def test_every_comparison_response_is_labelled_and_carries_the_fixed_notices():
    site = SCHEMAS["SiteChangeResponse"]
    assert {"origin", "source", "data_freshness", "attribution", "language", "interpretation_notice", "approximation_notice"} <= set(site["properties"])
    assert {"origin", "source", "language", "interpretation_notice", "approximation_notice", "scope", "periods", "change", "data_range", "flags"} <= set(site["required"])
    country = SCHEMAS["CountryChangeResponse"]
    assert {"origin", "data_freshness", "language", "interpretation_notice", "approximation_notice", "results", "waterbase"} <= set(country["required"])
    assert {"origin", "source", "data_freshness", "attribution"} <= set(SCHEMAS["CountrySourceChange"]["properties"])
    bathing = SCHEMAS["BathingChangeResponse"]
    assert {"origin", "data_freshness", "attribution", "language", "notice", "comparison_notice"} <= set(bathing["required"])
    assert bathing["properties"]["origin"]["const"] == "real-eea-bathing-water" or bathing["properties"]["origin"].get("enum") == ["real-eea-bathing-water"]


def test_the_closed_values_of_the_comparison_are_enumerated():
    assert set(SCHEMAS["ChangeValues"]["properties"]["direction"]["anyOf"][0]["enum"]) == {"increased", "decreased", "no-change"}
    assert set(SCHEMAS["ChangeAssessment"]["properties"]["status"]["enum"]) == {"within-limit", "exceeds-limit", "indeterminate", "not-scored", "excluded"}
    crossing = SCHEMAS["SiteChangeResponse"]["properties"]["crossed_limit"]["anyOf"][0]["enum"]
    assert set(crossing) == {"within-to-exceeds", "exceeds-to-within", "none"}
    assert set(SCHEMAS["SiteChangeResponse"]["properties"]["resolution"]["enum"]) == {"monthly", "annual-only"}


def test_the_additive_fields_of_the_existing_routes():
    assert "month" in SCHEMAS["MeasurementRecord"]["properties"]
    assert set(SCHEMAS["SiteMeasurementsResponse"]["properties"]["resolution"]["enum"]) == {"annual", "monthly", "period-summary"}
    resolution = _parameters("/sites/{location_id}/measurements")["resolution"]
    assert resolution["required"] is False and resolution["schema"]["default"] == "annual" and set(resolution["schema"]["enum"]) == {"annual", "monthly"}
    breakdown = SCHEMAS["CountrySourceBreakdown"]["properties"]
    assert "data_range" in breakdown and set(SCHEMAS["DataRange"]["properties"]) == {"first", "last"}
    # month and data_range are optional: no existing client breaks
    assert "month" not in SCHEMAS["MeasurementRecord"]["required"] and "data_range" not in SCHEMAS["CountrySourceBreakdown"].get("required", [])
