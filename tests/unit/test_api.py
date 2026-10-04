"""Tests for the FastAPI application layer. No real network is used: sandbox-backed
endpoints have their data source monkeypatched, and the review store uses a temporary
on-disk SQLite database outside the repository (tmp_path). Reliability and risk endpoints
are self-contained synthetic computations and need no mocking.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
import oah.api.routes.quality as quality_routes_module
from oah.api.llm_guard import LLMSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.explain.client import LLMNotConfiguredError
from oah.review.queue import submit_to_queue
from oah.store.review_store import ReviewStore
from oah.uncertainty.conformal import ConformalPredictionSet

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _generous_rate_limit(monkeypatch):
    """Requests across this file must never trip the real, process-wide rate limiter;
    rate-limiting itself is tested separately below with its own tiny limiter."""
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    guard = LLMSpendGuard(per_minute=10_000, daily_cap=10_000, cache_ttl_seconds=60.0)  # fresh per test: no shared cache
    monkeypatch.setattr(deps_module, "get_llm_guard", lambda: guard)
    # The state-changing routes (review decisions, FHIR exports) are off by default; this file exercises them.
    # Their default-off behaviour is tested in tests/unit/test_write_routes.py.
    monkeypatch.setenv("OAH_ENABLE_WRITE_ROUTES", "1")


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


class _FakeExplainClient:
    """A fake Anthropic client: no real network access, matching this project's convention."""

    def __init__(self, reply_text: str = "This is a grounded, evidence-only explanation."):
        self.last_call: dict | None = None

        def _create(**kwargs):
            self.last_call = kwargs
            return SimpleNamespace(content=[_FakeTextBlock(reply_text)])

        self.messages = SimpleNamespace(create=_create)


class _RaisingExplainClient:
    """A fake Anthropic client whose messages.create raises a real SDK error, no network used."""

    def __init__(self, error: Exception):
        def _raise(**kwargs):
            raise error

        self.messages = SimpleNamespace(create=_raise)


def _credit_error() -> anthropic.BadRequestError:
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": "Your credit balance is too low."}}
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx2.Response(400, request=request, json=body)
    return anthropic.BadRequestError("bad request", response=response, body=body)


def _real_observations():
    """A small set of real-sandbox-shaped Observations (no synthetic tag)."""
    return [
        {
            "id": "obs-nitrate-1",
            "resourceType": "Observation",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": "nitrate"}]},
            "valueQuantity": {"value": 12.0, "unit": "mg/L", "system": "http://unitsofmeasure.org", "code": "mg/L"},
        },
        {
            "id": "obs-ph-1",
            "resourceType": "Observation",
            "meta": {"profile": ["http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"]},
            "subject": {"reference": "Location/Loc-Test-01"},
            "code": {"coding": [{"code": "ph"}]},
            "valueQuantity": {"value": 7.5, "unit": "pH"},
        },
    ]


def _real_locations():
    """A small set of real-sandbox-shaped Location resources with map positions."""
    return [
        {
            "resourceType": "Location",
            "id": "Loc-Test-01",
            "name": "Test reach",
            "position": {"latitude": 35.334, "longitude": 25.048},
        },
    ]


@pytest.fixture(autouse=True)
def _patch_observations(monkeypatch):
    monkeypatch.setattr(deps_module, "get_cached_observations", _real_observations)
    monkeypatch.setattr(deps_module, "get_cached_locations", _real_locations)


@pytest.fixture()
def review_store(monkeypatch, tmp_path):
    store = ReviewStore(tmp_path / "test_review.db")
    monkeypatch.setattr(deps_module, "get_review_store", lambda: store)
    return store


# --- /health ---------------------------------------------------------------------------------


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# --- /qc/report --------------------------------------------------------------------------------


def test_qc_report_happy_path():
    response = client.get("/qc/report")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "real-sandbox"
    assert body["total_observations"] == 2


# --- /sites ----------------------------------------------------------------------------------


def test_sites_happy_path():
    response = client.get("/sites")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "real-sandbox"
    assert len(body["sites"]) == 1
    site = body["sites"][0]
    assert site["id"] == "Loc-Test-01"
    assert site["latitude"] == 35.334
    assert site["longitude"] == 25.048
    assert site["status"] == "evaluated"
    assert site["ui_status"] in ("good", "moderate", "poor")


# --- /indices/{location_id} ---------------------------------------------------------------------


def test_indices_happy_path_evaluated_location():
    response = client.get("/indices/Loc-Test-01")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "real-sandbox"
    assert body["status"] == "evaluated"
    assert 0.0 <= body["ccme_wqi"] <= 100.0


def test_indices_unknown_location_returns_404():
    response = client.get("/indices/Loc-Does-Not-Exist")
    assert response.status_code == 404
    assert "detail" in response.json()


# --- /explain/indices/{location_id} --------------------------------------------------------------


def test_explain_indices_happy_path(monkeypatch):
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _FakeExplainClient())
    response = client.get("/explain/indices/Loc-Test-01")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "real-sandbox"
    assert body["grounded"] is True
    assert body["ungrounded_numbers"] == []
    assert body["unit_mismatches"] == []
    assert "ccme_wqi" in body["evidence"]
    assert body["explanation"]


def test_explain_indices_unknown_location_returns_404(monkeypatch):
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _FakeExplainClient())
    response = client.get("/explain/indices/Loc-Does-Not-Exist")
    assert response.status_code == 404


def test_explain_indices_returns_503_when_llm_not_configured(monkeypatch):
    def _raise():
        raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(deps_module, "get_llm_client", _raise)
    response = client.get("/explain/indices/Loc-Test-01")
    assert response.status_code == 503


def test_explain_indices_returns_502_on_a_real_anthropic_api_failure(monkeypatch):
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _RaisingExplainClient(_credit_error()))
    response = client.get("/explain/indices/Loc-Test-01")
    assert response.status_code == 502
    assert "credit balance" not in response.json()["detail"].lower()  # upstream text stays in the server log
    assert "provider" in response.json()["detail"].lower()


def test_explain_indices_surfaces_an_ungrounded_reply_instead_of_hiding_it(monkeypatch):
    monkeypatch.setattr(
        deps_module, "get_llm_client", lambda: _FakeExplainClient("This site scores 87.5, a made-up number.")
    )
    response = client.get("/explain/indices/Loc-Test-01")
    assert response.status_code == 200
    body = response.json()
    assert body["grounded"] is False
    assert "87.5" in body["ungrounded_numbers"]


def test_explain_indices_defaults_to_describe_mode(monkeypatch):
    fake = _FakeExplainClient()
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: fake)
    body = client.get("/explain/indices/Loc-Test-01").json()
    assert body["mode"] == "describe"
    assert "Explain this" in fake.last_call["messages"][0]["content"]


def test_explain_indices_assess_mode_uses_a_different_prompt(monkeypatch):
    fake = _FakeExplainClient("Concern level: low\nNo action needed.")
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: fake)
    response = client.get("/explain/indices/Loc-Test-01", params={"mode": "assess"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "assess"
    assert "Concern level" in body["explanation"]
    assert "Assess this" in fake.last_call["messages"][0]["content"]


def test_explain_indices_rejects_an_unknown_mode(monkeypatch):
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _FakeExplainClient())
    response = client.get("/explain/indices/Loc-Test-01", params={"mode": "opinionated"})
    assert response.status_code == 422


# --- POST /fhir/export -------------------------------------------------------------------------


def test_fhir_export_happy_path(tmp_path, monkeypatch):
    monkeypatch.setattr(deps_module, "export_path", lambda name: tmp_path / name)
    response = client.post("/fhir/export")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "real-sandbox"
    assert body["observations_processed"] == 2
    assert body["detected_issue_count"] >= 0
    assert body["bundle_id"]


def test_fhir_export_never_leaks_the_absolute_filesystem_path(tmp_path, monkeypatch):
    # Security: the response must not disclose the local username or home-directory layout.
    monkeypatch.setattr(deps_module, "export_path", lambda name: tmp_path / name)
    body = client.post("/fhir/export").json()
    assert body["written_to"] == "findings-bundle.json"
    assert "\\" not in body["written_to"]
    assert "/" not in body["written_to"]
    assert str(tmp_path) not in body["written_to"]


def test_fhir_export_indicators_writes_bundle_without_leaking_path(tmp_path, monkeypatch):
    monkeypatch.setattr(deps_module, "export_path", lambda name: tmp_path / name)
    monkeypatch.setattr(
        quality_routes_module,
        "apply_ccme_wqi_to_sandbox",
        lambda observations, locations=None: {
            "input_origin": "real-sandbox",
            "evaluated_locations_count": 1,
            "skipped_locations_count": 2,
            "evaluated_locations": [
                {
                    "location_ref": "Location/Loc-Test-01",
                    "evaluable_measurements": 5,
                    "distinct_parameters_count": 4,
                    "failed_measurements": 1,
                    "ccme_wqi": 88.0,
                    "confidence": "normal",
                    "confidence_note": "",
                }
            ],
        },
    )
    body = client.post("/fhir/export/indicators").json()
    assert body["origin"] == "real-sandbox"
    assert body["observations_exported"] == 1 and body["locations_without_observation"] == 2
    assert body["written_to"] == "indicators-bundle.json"
    assert (tmp_path / "indicators-bundle.json").is_file()


# --- /reliability/campaign ----------------------------------------------------------------------


def test_reliability_campaign_happy_path():
    response = client.get(
        "/reliability/campaign",
        params={"seed": 42, "observer_count": 4, "specimens_per_site": 5, "annotators_per_specimen": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "synthetic"
    assert body["seed"] == 42
    assert body["recommended_method"] in ("one-coin", "dawid-skene")
    assert 0.0 <= body["dawid_skene_accuracy"] <= 1.0


def test_reliability_campaign_deterministic_for_the_same_seed():
    params = {"seed": 7, "observer_count": 4, "specimens_per_site": 5, "annotators_per_specimen": 2}
    first = client.get("/reliability/campaign", params=params).json()
    second = client.get("/reliability/campaign", params=params).json()
    assert first["dawid_skene_accuracy"] == second["dawid_skene_accuracy"]


def test_reliability_campaign_rejects_out_of_bound_parameters():
    response = client.get("/reliability/campaign", params={"seed": 1, "observer_count": 1})
    assert response.status_code == 422
    response = client.get("/reliability/campaign", params={"seed": -5})
    assert response.status_code == 422


# --- /review/queue and /review/{specimen_id}/decide -----------------------------------------------


def test_review_queue_lists_only_pending_items(review_store):
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-API-01",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.55, "Heptageniidae": 0.45},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    submit_to_queue(review_store, multi_set)

    response = client.get("/review/queue")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "synthetic"
    assert body["count"] == 1
    assert body["items"][0]["specimen_id"] == "SPEC-API-01"
    assert body["items"][0]["tag"] == "synthetic"


def test_explain_review_happy_path(review_store, monkeypatch):
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _FakeExplainClient())
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-EXPLAIN-01",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.55, "Heptageniidae": 0.45},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    submit_to_queue(review_store, multi_set)

    response = client.get("/explain/review/SPEC-EXPLAIN-01")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "synthetic"
    assert body["evidence"]["prediction_set"] == ["Baetidae", "Heptageniidae"]
    assert body["grounded"] is True
    assert body["explanation"]


def test_explain_review_unknown_specimen_returns_404(review_store, monkeypatch):
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _FakeExplainClient())
    response = client.get("/explain/review/SPEC-MISSING")
    assert response.status_code == 404


def test_explain_review_returns_503_when_llm_not_configured(review_store, monkeypatch):
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-EXPLAIN-02",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.6, "Heptageniidae": 0.4},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    submit_to_queue(review_store, multi_set)

    def _raise():
        raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set.")

    monkeypatch.setattr(deps_module, "get_llm_client", _raise)
    response = client.get("/explain/review/SPEC-EXPLAIN-02")
    assert response.status_code == 503


def test_explain_review_assess_mode_uses_a_different_prompt(review_store, monkeypatch):
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-EXPLAIN-03",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.55, "Heptageniidae": 0.45},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    submit_to_queue(review_store, multi_set)

    fake = _FakeExplainClient("Concern level: moderate\nHave a second reviewer confirm.")
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: fake)

    response = client.get("/explain/review/SPEC-EXPLAIN-03", params={"mode": "assess"})
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "assess"
    assert "Concern level" in body["explanation"]
    assert "Assess this" in fake.last_call["messages"][0]["content"]


def test_review_decide_happy_path(review_store):
    multi_set = ConformalPredictionSet(
        specimen_id="SPEC-API-02",
        prediction_set=("Baetidae", "Heptageniidae"),
        probabilities={"Baetidae": 0.55, "Heptageniidae": 0.45},
        quantile_cutoff=0.25,
        probability_provider="dawid-skene",
        tag="synthetic",
    )
    submit_to_queue(review_store, multi_set)

    response = client.post(
        "/review/SPEC-API-02/decide",
        json={"final_label": "Baetidae", "reviewer_id": "rev-test"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "synthetic"
    assert body["status"] == "decided"
    assert body["final_label"] == "Baetidae"

    # The item no longer appears in the pending queue.
    assert client.get("/review/queue").json()["count"] == 0


def test_review_decide_unknown_specimen_returns_404(review_store):
    response = client.post(
        "/review/SPEC-MISSING/decide",
        json={"final_label": "Baetidae", "reviewer_id": "rev-test"},
    )
    assert response.status_code == 404


def test_review_decide_rejects_empty_reviewer_id(review_store):
    response = client.post(
        "/review/SPEC-API-02/decide",
        json={"final_label": "Baetidae", "reviewer_id": ""},
    )
    assert response.status_code == 422


# --- /risk/{site_id} ------------------------------------------------------------------------------


def test_risk_happy_path_known_site():
    response = client.get("/risk/Loc-Almyros-Coast")
    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "synthetic"
    assert 0.0 <= body["risk"] <= 1.0
    assert "not real hydrology" in body["note"].lower()


def test_risk_source_site_has_full_risk():
    response = client.get("/risk/Loc-Almyros")
    assert response.status_code == 200
    assert response.json()["risk"] == 1.0


def test_risk_unknown_site_returns_404():
    response = client.get("/risk/Not-A-Demo-Site")
    assert response.status_code == 404


# --- Auth, rate limiting, CORS ------------------------------------------------------------------


def test_protected_route_open_by_default_when_no_api_key_configured(monkeypatch):
    monkeypatch.delenv("OAH_API_KEY", raising=False)
    response = client.get("/risk/Loc-Almyros")
    assert response.status_code == 200


def test_protected_route_rejects_missing_or_wrong_key_once_configured(monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "demo-secret")
    assert client.get("/risk/Loc-Almyros").status_code == 401
    assert client.get("/risk/Loc-Almyros", headers={"x-api-key": "wrong"}).status_code == 401
    assert client.get("/risk/Loc-Almyros", headers={"x-api-key": "demo-secret"}).status_code == 200


def test_health_never_requires_the_api_key(monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "demo-secret")
    assert client.get("/health").status_code == 200


def test_rate_limiter_returns_429_once_the_window_is_exceeded(monkeypatch):
    tiny_limiter = RateLimiter(1, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: tiny_limiter)
    assert client.get("/risk/Loc-Almyros").status_code == 200
    second = client.get("/risk/Loc-Almyros")
    assert second.status_code == 429
    assert "rate limit" in second.json()["detail"].lower()


def test_health_is_never_rate_limited(monkeypatch):
    tiny_limiter = RateLimiter(1, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: tiny_limiter)
    client.get("/risk/Loc-Almyros")  # consume the tiny protected-route budget
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200


def test_cors_allows_a_configured_dev_origin():
    response = client.get("/risk/Loc-Almyros", headers={"origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_cors_rejects_an_unconfigured_origin():
    response = client.get("/risk/Loc-Almyros", headers={"origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_review_decide_maps_conflicts_and_invalid_labels_to_409_and_422(review_store):
    submit_to_queue(
        review_store,
        ConformalPredictionSet("SPEC-API-CONFLICT", ("Baetidae", "Heptageniidae"), {"Baetidae": 0.55, "Heptageniidae": 0.45}, 0.25, "dawid-skene", "synthetic"),
    )
    url = "/review/SPEC-API-CONFLICT/decide"
    assert client.post(url, json={"final_label": "Perlidae", "reviewer_id": "rev-1"}).status_code == 422
    assert client.post(url, json={"final_label": "Baetidae", "reviewer_id": "rev-1"}).status_code == 200
    assert client.post(url, json={"final_label": "Heptageniidae", "reviewer_id": "rev-2"}).status_code == 409
    assert client.post(url, json={"final_label": "other", "reviewer_id": "rev-2"}).status_code == 409
    assert review_store.get_review_item("SPEC-API-CONFLICT").final_label == "Baetidae"


# --- official-record filter on the real routes --------------------------------------------------------------


def _with_contaminating_records(monkeypatch):
    profile = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
    extra = [
        {"id": "demo-1", "meta": {"profile": [profile], "tag": [{"code": "demo"}]},
         "subject": {"reference": "Location/Loc-Test-01"}, "code": {"coding": [{"code": "nitrate"}]},
         "valueQuantity": {"value": 900.0, "unit": "mg/L", "system": "http://unitsofmeasure.org", "code": "mg/L"}},
        {"id": "third-1", "meta": {"profile": ["https://streampulse.example/StructureDefinition/forecast"]}},
        {"id": "bare-1", "meta": {}},
    ]
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: _real_observations() + extra)


def test_qc_report_excludes_non_official_records_and_counts_them_by_reason(monkeypatch):
    _with_contaminating_records(monkeypatch)
    body = client.get("/qc/report").json()
    assert body["total_observations"] == 2
    assert body["excluded_observations"]["tag-demo"] == 1
    assert body["excluded_observations"]["third-party"] == 1
    assert body["excluded_observations"]["no-profile"] == 1
    assert body["excluded_observations_total"] == 3


def test_a_demo_record_never_reaches_the_index(monkeypatch):
    _with_contaminating_records(monkeypatch)
    body = client.get("/indices/Loc-Test-01").json()
    assert body["total_observations"] == 2  # the demo nitrate of 900 mg/L was not counted
    assert body["evaluable_measurements"] == 2


def test_sites_carry_a_kind():
    site = client.get("/sites").json()["sites"][0]
    assert site["kind"] == "water-body"  # the name "Test reach" contains the water-body word "reach" (provisional rule)
