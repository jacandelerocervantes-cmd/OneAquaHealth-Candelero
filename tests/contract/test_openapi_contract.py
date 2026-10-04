"""The OpenAPI document is a real contract: every protected route is typed and declares its shared errors."""
import pytest

from oah.api.app import app

SPEC = app.openapi()
PUBLIC = {"/health"}
OPERATIONS = [
    (path, method, operation)
    for path, item in SPEC["paths"].items()
    if path not in PUBLIC
    for method, operation in item.items()
]


def test_the_spec_lists_the_protected_routes():
    assert len(OPERATIONS) >= 11


@pytest.mark.parametrize(("path", "method", "operation"), OPERATIONS, ids=lambda v: v if isinstance(v, str) else "")
def test_every_protected_route_returns_a_named_schema_not_a_free_form_object(path, method, operation):
    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert "$ref" in schema, f"{method.upper()} {path} has no typed response model"


@pytest.mark.parametrize(("path", "method", "operation"), OPERATIONS, ids=lambda v: v if isinstance(v, str) else "")
def test_every_protected_route_declares_the_shared_errors(path, method, operation):
    for status in ("401", "429", "503"):
        assert status in operation["responses"], f"{method.upper()} {path} does not declare {status}"


def test_real_data_responses_carry_freshness_and_an_origin():
    for name in ("SitesResponse", "QcReportResponse", "IndexResponse"):
        properties = SPEC["components"]["schemas"][name]["properties"]
        assert "data_freshness" in properties and "origin" in properties, name
    freshness = SPEC["components"]["schemas"]["DataFreshnessModel"]["properties"]["status"]
    assert set(freshness["enum"]) == {"live", "snapshot", "snapshot-stale", "unknown"}


def test_the_origin_is_a_closed_set_never_a_free_string():
    origin = SPEC["components"]["schemas"]["SitesResponse"]["properties"]["origin"]
    # real-eea-waterbase (EEA Waterbase slice) and real-mixed (both real sources in one list) were added with the
    # Waterbase store (docs/waterbase_store.md); real-eea-bathing-water (the EEA bathing-water CLASSIFICATION, never a
    # concentration) was added with docs/bathing_water_store.md; real-eea-bathing-samples (the individual E. coli and
    # intestinal enterococci results, no threshold) with docs/bathing_samples_store.md. The set stays closed.
    assert set(origin["enum"]) == {
        "real-sandbox", "real-eea-waterbase", "real-eea-bathing-water", "real-eea-bathing-samples", "real-mixed", "synthetic",
    }


def test_explanations_are_marked_unsafe_or_safe_and_carry_the_disclaimer():
    properties = SPEC["components"]["schemas"]["ExplanationResponse"]["properties"]
    assert {"unsafe", "disclaimer", "output_flags", "grounded"} <= set(properties)
