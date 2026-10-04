"""Abuse resistance of the API: LLM spend limits, the response cache, security headers and bounded inputs (mocked)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
import oah.api.payloads as payloads_module
from oah.api.llm_guard import LLMSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.explain import LLMNotConfiguredError
from oah.review.queue import submit_to_queue
from oah.store.review_store import ReviewStore
from oah.uncertainty.conformal import ConformalPredictionSet

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
client = TestClient(app_module.app)


class _Model:
    def __init__(self):
        self.calls = 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls += 1
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="Concern level: low\nThe index is 100.")], usage=None)


@pytest.fixture()
def model(monkeypatch, tmp_path):
    monkeypatch.setenv("OAH_ENABLE_WRITE_ROUTES", "1")  # the review decision route is off by default (tests/unit/test_write_routes.py)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    observations = [
        {
            "id": f"o-{code}", "resourceType": "Observation", "meta": {"profile": [PROFILE]},
            "subject": {"reference": "Location/Loc-Test-01"}, "code": {"coding": [{"code": code}]},
            "valueQuantity": {"value": value, "system": "http://unitsofmeasure.org", "code": "mg/L"},
        }
        for code, value in (("nitrate", 12.0), ("ammonium", 0.1), ("nitrite", 0.1), ("sulphate", 90.0))
    ]
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: observations)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [])
    fake = _Model()
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: fake)
    store = ReviewStore(tmp_path / "abuse.db")
    submit_to_queue(store, ConformalPredictionSet("SPEC-1", ("A", "B"), {"A": 0.55, "B": 0.45}, 0.5, "one-coin"))
    monkeypatch.setattr(deps_module, "get_review_store", lambda: store)
    return fake


def _use_guard(monkeypatch, **kwargs):
    settings = {"per_minute": 100, "daily_cap": 100, "cache_ttl_seconds": 600.0} | kwargs
    guard = LLMSpendGuard(**settings)
    monkeypatch.setattr(deps_module, "get_llm_guard", lambda: guard)
    return guard


PATH = "/explain/indices/Loc-Test-01"


# --- /explain budget ------------------------------------------------------------------------------------


def test_explain_has_its_own_tight_per_minute_budget_with_retry_after(monkeypatch, model):
    _use_guard(monkeypatch, per_minute=2)
    assert client.get(PATH).status_code == 200 and client.get(PATH).status_code == 200
    blocked = client.get(PATH)
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "60"
    assert "Explanation rate limit" in blocked.json()["detail"]


def test_the_explain_budget_applies_to_cached_answers_too_so_a_loop_is_stopped(monkeypatch, model):
    _use_guard(monkeypatch, per_minute=3)
    codes = [client.get(PATH).status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429] and model.calls == 1


def test_an_identical_request_is_answered_from_the_cache_without_a_model_call(monkeypatch, model):
    _use_guard(monkeypatch)
    first, second = client.get(PATH).json(), client.get(PATH).json()
    assert (first["cached"], second["cached"]) == (False, True) and model.calls == 1
    assert first["explanation"] == second["explanation"]


def test_a_different_mode_or_evidence_is_a_different_cache_entry(monkeypatch, model):
    _use_guard(monkeypatch)
    client.get(PATH)
    other_mode = client.get(PATH, params={"mode": "assess"}).json()
    other_target = client.get("/explain/review/SPEC-1").json()
    assert other_mode["cached"] is False and other_target["cached"] is False and model.calls == 3


def test_the_daily_cap_bounds_real_model_calls_but_cached_answers_stay_available(monkeypatch, model):
    guard = _use_guard(monkeypatch, daily_cap=1)
    assert client.get(PATH).status_code == 200
    blocked = client.get(PATH, params={"mode": "assess"})
    assert blocked.status_code == 429 and "Daily budget of 1" in blocked.json()["detail"]
    assert blocked.headers["Retry-After"] == "3600"
    assert client.get(PATH).json()["cached"] is True  # a cache hit costs nothing, so it is still served
    assert model.calls == 1 and guard.calls_in_last_day() == 1


def test_a_request_that_cannot_reach_the_model_does_not_consume_the_daily_cap(monkeypatch, model):
    guard = _use_guard(monkeypatch, daily_cap=1)

    def unconfigured():
        raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set")

    monkeypatch.setattr(deps_module, "get_llm_client", unconfigured)
    assert client.get(PATH).status_code == 503 and guard.calls_in_last_day() == 0


def test_oversized_evidence_is_a_422_and_never_reaches_the_model(monkeypatch, model):
    _use_guard(monkeypatch)
    monkeypatch.setattr(payloads_module, "_indices_payload", lambda location_id: {"origin": "real-sandbox", "items": ["x"] * 1000})
    response = client.get(PATH)
    assert response.status_code == 422 and model.calls == 0


def test_the_explain_response_reports_flags_and_sanitisation(monkeypatch, model):
    _use_guard(monkeypatch)
    body = client.get(PATH).json()
    assert body["output_flags"] == [] and body["evidence_sanitized"] == [] and body["cached"] is False


def test_explain_review_uses_the_same_budget(monkeypatch, model):
    _use_guard(monkeypatch, per_minute=1)
    assert client.get("/explain/review/SPEC-1").status_code == 200
    assert client.get("/explain/review/SPEC-1").status_code == 429


# --- guard unit behaviour -----------------------------------------------------------------------------------


def test_guard_rejects_non_positive_settings():
    for kwargs in ({"daily_cap": 0}, {"cache_size": 0}, {"cache_ttl_seconds": 0.0}):
        with pytest.raises(ValueError):
            LLMSpendGuard(**({"per_minute": 5, "daily_cap": 5, "cache_ttl_seconds": 5.0} | kwargs))


def test_guard_cache_expires_evicts_the_oldest_and_keys_depend_on_everything():
    now = [0.0]
    guard = LLMSpendGuard(5, 5, cache_ttl_seconds=10.0, cache_size=2, clock=lambda: now[0])
    guard.store("a", 1)
    guard.store("b", 2)
    guard.store("c", 3)
    assert guard.cached("a") is None and guard.cached("b") == 2 and guard.cached("c") == 3
    now[0] = 10.0  # inclusive boundary
    assert guard.cached("b") is None
    base = guard.key("k", "describe", "m", {"x": 1})
    assert base == guard.key("k", "describe", "m", {"x": 1})
    assert len({base, guard.key("k2", "describe", "m", {"x": 1}), guard.key("k", "assess", "m", {"x": 1}),
                guard.key("k", "describe", "m2", {"x": 1}), guard.key("k", "describe", "m", {"x": 2})}) == 5


def test_guard_daily_window_rolls_over():
    now = [0.0]
    guard = LLMSpendGuard(5, daily_cap=2, cache_ttl_seconds=5.0, clock=lambda: now[0])
    guard.reserve_call()
    now[0] = 100.0
    guard.reserve_call()
    with pytest.raises(Exception) as blocked:
        guard.reserve_call()
    assert blocked.value.status_code == 429
    now[0] = 86_400.0 + 1.0  # the first call aged out
    guard.reserve_call()
    assert guard.calls_in_last_day() == 2


# --- headers, general limiter, bounded inputs ------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/health", "/qc/report", "/risk/Loc-Almyros"])
def test_every_response_carries_the_defensive_headers(model, path):
    headers = client.get(path).headers
    assert headers["X-Content-Type-Options"] == "nosniff" and headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "no-referrer" and headers["Cache-Control"] == "no-store"
    assert headers["Content-Security-Policy"] == "default-src 'none'; frame-ancestors 'none'"


def test_error_responses_carry_the_headers_too_and_the_docs_page_has_no_csp(model):
    assert client.get("/indices/Nope").headers["X-Content-Type-Options"] == "nosniff"
    assert "Content-Security-Policy" not in client.get("/docs").headers


def test_the_general_rate_limit_also_sends_retry_after(monkeypatch, model):
    limiter = RateLimiter(1, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: limiter)
    assert client.get("/qc/report").status_code == 200
    blocked = client.get("/qc/report")
    assert blocked.status_code == 429 and blocked.headers["Retry-After"] == "60"


@pytest.mark.parametrize(
    ("body", "ok"),
    [
        ({"final_label": "A", "reviewer_id": "reviewer-1"}, True),
        ({"final_label": "Baetidae sp. 2", "reviewer_id": "ana.perez@agency.test"}, False),  # e-mail: personal data
        ({"final_label": "A", "reviewer_id": "ana perez"}, False),  # a name with a space
        ({"final_label": "A", "reviewer_id": "ana.perez_01"}, True),  # a pseudonymous handle
        ({"final_label": "A", "reviewer_id": "x" * 64}, True),
        ({"final_label": "A", "reviewer_id": "x" * 65}, False),
        ({"final_label": "A", "reviewer_id": "a\nb"}, False),
        ({"final_label": "A", "reviewer_id": "x" * 129}, False),
        ({"final_label": "<script>alert(1)</script>", "reviewer_id": "reviewer-1"}, False),
        ({"final_label": "Baetidae\r\nX-Injected: 1", "reviewer_id": "reviewer-1"}, False),
        ({"final_label": "", "reviewer_id": "reviewer-1"}, False),
        ({"final_label": "A", "reviewer_id": "'; DROP TABLE review_items;--"}, False),
    ],
)
def test_review_decision_fields_are_bounded_and_free_of_markup_and_control_characters(model, body, ok):
    response = client.post("/review/SPEC-1/decide", json=body)
    assert (response.status_code == 200) is ok, response.text
    if not ok:
        assert response.status_code == 422
