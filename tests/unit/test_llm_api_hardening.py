"""Access-key strength (F11), fixed 503 text and no public budget numbers (F12), no hidden SDK retries (F15), and the
explanation routes withholding unsafe or not grounded text (F6)."""
import json
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

import oah.api.deps as deps_module
from oah import config
from oah.api import app as app_module
from oah.api.llm_guard import ChatSpendGuard, LLMSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.explain import client as client_module
from oah.explain.client import LLMNotConfiguredError

STRONG = "s" * 32
SHORT = "short-key"


# --- F11: access-key strength ---------------------------------------------------------------------------------------
def test_cloud_run_is_detected_from_the_service_variable():
    assert config.load_settings({}).on_cloud_run is False
    assert config.load_settings({"K_SERVICE": "oah-backend"}).on_cloud_run is True
    assert config.load_settings({"K_SERVICE": "   "}).on_cloud_run is False


def test_a_strong_key_on_cloud_run_starts_without_a_warning():
    settings = config.load_settings({"K_SERVICE": "svc", "OAH_API_KEY": STRONG})
    assert config.check_auth_policy(settings) == []


@pytest.mark.parametrize("key", [SHORT, "x" * 31, "q9Z"])
def test_a_short_key_on_cloud_run_refuses_to_start_without_naming_the_key_or_its_length(key):
    settings = config.load_settings({"K_SERVICE": "svc", "OAH_API_KEY": key})
    with pytest.raises(ValueError) as refused:
        config.check_auth_policy(settings)
    message = str(refused.value)
    assert key not in message and str(len(key)) not in message.replace("32", "")
    assert "OAH_API_KEY" in message and "32" in message


def test_no_key_on_cloud_run_refuses_to_start():
    with pytest.raises(ValueError, match="OAH_API_KEY is required"):
        config.check_auth_policy(config.load_settings({"K_SERVICE": "svc"}))


@pytest.mark.parametrize("flag", ["1", "true", "yes"])
def test_the_no_authentication_flag_on_cloud_run_refuses_to_start_even_with_a_strong_key(flag):
    settings = config.load_settings({"K_SERVICE": "svc", "OAH_API_KEY": STRONG, "OAH_INSECURE_NO_AUTH": flag})
    with pytest.raises(ValueError, match="OAH_INSECURE_NO_AUTH"):
        config.check_auth_policy(settings)


def test_elsewhere_a_short_key_only_warns_and_keeps_working():
    settings = config.load_settings({"OAH_API_KEY": SHORT})
    [warning] = config.check_auth_policy(settings)
    assert "too short" in warning and SHORT not in warning and str(len(SHORT)) not in warning
    assert config.check_auth_policy(config.load_settings({"OAH_API_KEY": STRONG})) == []
    assert config.check_auth_policy(config.load_settings({})) == []  # no key, no flag: the routes answer 503, nothing to warn
    assert config.check_auth_policy(config.load_settings({"OAH_INSECURE_NO_AUTH": "1"})) == []  # local demo


def test_a_short_key_still_authenticates_locally(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setenv("OAH_API_KEY", SHORT)
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    client = TestClient(app_module.app)
    assert client.get("/risk/Loc-Almyros", headers={"X-API-Key": SHORT}).status_code == 200
    assert client.get("/risk/Loc-Almyros", headers={"X-API-Key": "other"}).status_code == 401


def test_the_start_up_check_is_run_when_the_app_module_is_imported():
    import inspect

    source = inspect.getsource(app_module)
    assert "check_auth_policy(deps.settings)" in source


def test_the_settings_repr_never_shows_the_key_or_cloud_run_state_secrets():
    text = repr(config.load_settings({"K_SERVICE": "svc", "OAH_API_KEY": STRONG}))
    assert STRONG not in text


# --- F15: no hidden retries -------------------------------------------------------------------------------------------
def test_the_client_makes_no_hidden_retries(monkeypatch):
    seen: dict[str, Any] = {}

    class _Anthropic:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(client_module.anthropic, "Anthropic", _Anthropic)
    client_module.build_client(config.load_settings({"ANTHROPIC_API_KEY": "sk-ant-test"}))
    assert seen["max_retries"] == 0 and client_module.MAX_RETRIES == 0
    assert seen["timeout"] == client_module.REQUEST_TIMEOUT_SECONDS


def test_the_real_sdk_client_is_built_without_retries():
    real = client_module.build_client(config.load_settings({"ANTHROPIC_API_KEY": "sk-ant-test"}))
    assert real.max_retries == 0


# --- F12: fixed 503 text and no public budget ----------------------------------------------------------------------------
@pytest.fixture()
def http(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: [])
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [])
    monkeypatch.setattr(deps_module, "get_llm_guard", lambda: LLMSpendGuard(10_000, 100, 60.0))
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: ChatSpendGuard(10_000, 100, 60.0, 6))
    return TestClient(app_module.app)


def test_a_missing_model_key_is_a_generic_503_that_names_no_variable_or_file(http, monkeypatch):
    _location_world(monkeypatch)

    def _raise():
        raise LLMNotConfiguredError("ANTHROPIC_API_KEY is not set (checked the settings file and the process environment).")

    monkeypatch.setattr(deps_module, "get_llm_client", _raise)
    for response in (
        http.post("/chat", json={"message": "hello"}),
        http.get("/explain/indices/Loc-Test-01"),
    ):
        assert response.status_code == 503, response.text
        detail = response.json()["detail"]
        assert detail == "The language-model service is not available."
        assert "ANTHROPIC" not in detail and "_KEY" not in detail and ".env" not in detail and "settings" not in detail.lower()


class _Answer:
    """A model that answers one fixed text."""

    def __init__(self, text: str):
        self.text = text
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_kwargs):
        block = SimpleNamespace(type="text", text=self.text)
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def test_the_chat_usage_no_longer_shows_the_global_remaining_budget(http, monkeypatch):
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _Answer("A plain answer."))
    body = http.post("/chat", json={"message": "hello"}).json()
    assert set(body["usage"]) == {"model_calls", "max_steps", "input_tokens", "output_tokens"}
    assert "remaining" not in json.dumps(body["usage"])
    schema = app_module.app.openapi()["components"]["schemas"]["ChatUsage"]["properties"]
    assert set(schema) == {"model_calls", "max_steps", "input_tokens", "output_tokens"}


# --- F6: the explanation routes -------------------------------------------------------------------------------------------
def _location_world(monkeypatch):
    profile = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
    observations = [
        {
            "id": "obs-nitrate", "resourceType": "Observation", "meta": {"profile": [profile]},
            "subject": {"reference": "Location/Loc-Test-01"}, "code": {"coding": [{"code": "nitrate"}]},
            "valueQuantity": {"value": 12.0, "unit": "mg/L", "system": "http://unitsofmeasure.org", "code": "mg/L"},
        }
    ]
    locations = [{"resourceType": "Location", "id": "Loc-Test-01", "name": "Test", "position": {"latitude": 35.3, "longitude": 25.0}}]
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: observations)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: locations)


@pytest.mark.parametrize(
    ("text", "status", "flag"),
    [
        ("The site shows a value of 9876.5 in this data.", "withheld-ungrounded", None),
        ("See https://example.org/more for the data.", "withheld", "contains-url"),
        ("The details are <details>hidden</details> here.", "withheld", "contains-html"),
        ("This water is potable and fine.", "withheld", "unsupported-health-claim"),
    ],
)
def test_the_explain_route_never_returns_text_that_is_unsafe_or_not_grounded(http, monkeypatch, text, status, flag):
    _location_world(monkeypatch)
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _Answer(text))
    body = http.get("/explain/indices/Loc-Test-01").json()
    assert body["status"] == status and body["explanation"] is None and body["answer_en"] is None
    assert body["evidence"] and body["evidence"]["origin"] == "real-sandbox"  # the evidence stays in the response
    assert body["disclaimer"]
    if flag:
        assert flag in body["output_flags"] and body["unsafe"] is True and "withheld_notice" in body["notices"]
    else:
        assert body["unsafe"] is False and body["grounded"] is False and "9876.5" in body["ungrounded_numbers"]
        assert "withheld_ungrounded_notice" in body["notices"]
    assert text not in json.dumps(body)  # the text appears nowhere in the response


def test_the_explain_route_still_answers_a_grounded_safe_text(http, monkeypatch):
    _location_world(monkeypatch)
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _Answer("The data holds one nitrate observation."))
    body = http.get("/explain/indices/Loc-Test-01").json()
    assert body["status"] == "answered" and body["explanation"] == "The data holds one nitrate observation."
    assert body["grounded"] is True and body["unsafe"] is False


def test_the_explain_schema_documents_the_status(http):
    schema = app_module.app.openapi()["components"]["schemas"]["ExplanationResponse"]
    assert "status" in schema["properties"] and "withheld-ungrounded" in json.dumps(schema["properties"]["status"])
    assert "null" in json.dumps(schema["properties"]["explanation"])  # nullable
