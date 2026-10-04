"""Contract tests: what the API promises in docs/architecture.md and to every consumer of its data.

1. The routes the running app exposes are exactly the routes documented in docs/architecture.md.
2. Every response that carries data declares its origin (``real-sandbox`` or ``synthetic``).
3. Real-derived and synthetic answers are never mixed under the wrong label.
All data is mocked (no network, no API key).
"""
import re

import pytest
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.paths import repo_path
from oah.review.queue import submit_to_queue
from oah.store.review_store import ReviewStore
from oah.uncertainty.conformal import ConformalPredictionSet

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _mocked_world(monkeypatch, tmp_path):
    monkeypatch.setenv("OAH_ENABLE_WRITE_ROUTES", "1")  # the export routes are off by default (tests/unit/test_write_routes.py)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    observations = [
        {
            "id": f"obs-{code}",
            "resourceType": "Observation",
            "meta": {"profile": [PROFILE]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": code}]},
            "valueQuantity": {"value": value, "system": "http://unitsofmeasure.org", "code": unit},
        }
        for code, value, unit in (
            ("nitrate", 12.0, "mg/L"),
            ("ammonium", 0.1, "mg/L"),
            ("nitrite", 0.1, "mg/L"),
            ("sulphate", 90.0, "mg/L"),
        )
    ]
    locations = [
        {"resourceType": "Location", "id": "Loc-Test-01", "name": "Test", "position": {"latitude": 35.3, "longitude": 25.0}}
    ]
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: observations)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: locations)
    monkeypatch.setattr(deps_module, "export_path", lambda name: tmp_path / name)
    store = ReviewStore(tmp_path / "contract.db")
    submit_to_queue(store, ConformalPredictionSet("SPEC-1", ("A", "B"), {"A": 0.55, "B": 0.45}, 0.5, "one-coin"))
    monkeypatch.setattr(deps_module, "get_review_store", lambda: store)


def _documented_routes() -> set[tuple[str, str]]:
    text = repo_path("docs", "architecture.md").read_text(encoding="utf-8")
    table = text[text.index("| Method & path |"):]
    table = table[: table.index("\n\n")]
    return {(method, path.split("?")[0]) for method, path in re.findall(r"`(GET|POST) (/[^`\s]*)`", table)}


def _served_routes() -> set[tuple[str, str]]:
    return {
        (method.upper(), path) for path, item in app_module.app.openapi()["paths"].items() for method in item
    }


def test_served_routes_are_exactly_the_documented_routes():
    assert _served_routes() == _documented_routes()


REAL_GETS = ["/qc/report", "/sites", "/indices/Loc-Test-01"]
SYNTHETIC_GETS = [
    "/reliability/campaign?seed=7&observer_count=4&specimens_per_site=5&annotators_per_specimen=2",
    "/review/queue",
    "/risk/Loc-Almyros",
]


@pytest.mark.parametrize("path", REAL_GETS)
def test_real_sandbox_answers_are_labelled_real(path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("origin", body.get("input_origin")) == "real-sandbox", path


@pytest.mark.parametrize("path", SYNTHETIC_GETS)
def test_synthetic_answers_are_labelled_synthetic(path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    assert response.json()["origin"] == "synthetic", path


@pytest.mark.parametrize("path", ["/fhir/export", "/fhir/export/indicators"])
def test_exports_are_labelled_real_and_never_leak_a_filesystem_path(path):
    body = client.post(path).json()
    assert body["origin"] == "real-sandbox"
    assert "\\" not in body["written_to"] and "/" not in body["written_to"]


def test_sites_carry_the_veto_and_confidence_contract_fields():
    site = client.get("/sites").json()["sites"][0]
    assert {"id", "name", "latitude", "longitude", "status", "ui_status"} <= set(site)
    assert site["status"] == "evaluated"
    assert {"ccme_wqi", "ccme_class", "confidence", "veto_triggered", "eclipsed"} <= set(site)


def test_indices_expose_the_data_quality_accounting_fields():
    body = client.get("/indices/Loc-Test-01").json()["data_quality"]
    assert {
        "skipped_censored_quantities",
        "censored_quantities_counted_as_pass",
        "skipped_qc_inconsistent_observations",
        "skipped_physically_impossible_observations",
        "skipped_unit_mismatch_observations",
    } <= set(body)


def test_health_is_the_only_unlabelled_route_and_needs_no_data():
    assert client.get("/health").json() == {"status": "ok"}


def test_unknown_site_is_a_clean_404_with_a_message_not_a_traceback():
    for path in ("/indices/Nope", "/risk/Nope"):
        response = client.get(path)
        assert response.status_code == 404 and "detail" in response.json()
