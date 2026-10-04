"""Tests for the grounded LLM explanation layer. No real network is used: the Anthropic
client is always a fake double shaped like the SDK's response (a `.content` list of
`.type`/`.text` blocks), matching this project's existing mocking convention (see
test_sandbox_client.py, test_api.py).
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from oah import config
from oah.config import DEFAULT_LLM_MODEL, load_settings
from oah.explain.client import LLMNotConfiguredError, build_client
from oah.explain.errors import LLMRequestError, wrap_anthropic_error
from oah.explain.explainer import explain
from oah.explain.grounding import check_grounding
from oah.explain.prompts import (
    ASSESS_SYSTEM_PROMPT,
    DESCRIBE_SYSTEM_PROMPT,
    build_user_prompt,
    system_prompt_for_mode,
)

_FAKE_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _api_status_error(cls: type[anthropic.APIStatusError], status_code: int, message: str) -> anthropic.APIStatusError:
    body = {"type": "error", "error": {"type": "invalid_request_error", "message": message}}
    response = httpx2.Response(status_code, request=_FAKE_REQUEST, json=body)
    return cls(message, response=response, body=body)


@pytest.fixture(autouse=True)
def _hermetic_dotenv(monkeypatch):
    """No test in this file should be affected by a real local .env file, if one exists."""
    monkeypatch.setattr(config, "_dotenv_values", lambda: {})


# --- grounding ------------------------------------------------------------------------------


def test_grounded_explanation_using_only_evidence_numbers():
    evidence = {"ccme_wqi": 19.928374, "parameters_evaluated": 19}
    text = "The water quality index is 19.93, based on 19 parameters."
    result = check_grounding(text, evidence)
    assert result.grounded
    assert result.ungrounded_numbers == ()


def test_ungrounded_explanation_flags_invented_number():
    evidence = {"ccme_wqi": 19.93}
    text = "The water quality index is 87.5, a very high score."
    result = check_grounding(text, evidence)
    assert not result.grounded
    assert "87.5" in result.ungrounded_numbers


def test_universally_safe_numbers_never_flagged():
    evidence = {"note": "no numbers here at all"}
    text = "There is 1 finding out of 100 possible, and 0 are critical."
    result = check_grounding(text, evidence)
    assert result.grounded


def test_evidence_numbers_nested_inside_lists_and_dicts_are_found():
    evidence = {"probabilities": {"Baetidae": 0.55, "Heptageniidae": 0.45}}
    text = "Baetidae is more likely at 0.55 than Heptageniidae at 0.45."
    assert check_grounding(text, evidence).grounded


# --- client -----------------------------------------------------------------------------------


def test_build_client_raises_when_no_api_key_configured():
    settings = load_settings({})
    with pytest.raises(LLMNotConfiguredError):
        build_client(settings)


def test_build_client_succeeds_when_api_key_present():
    settings = load_settings({"ANTHROPIC_API_KEY": "sk-ant-test-not-real"})
    client = build_client(settings)
    assert client is not None


# --- explainer --------------------------------------------------------------------------------


@dataclass
class _FakeTextBlock:
    text: str
    type: str = "text"


class _FakeMessages:
    def __init__(self, reply_text: str):
        self._reply_text = reply_text
        self.last_call: dict | None = None

    def create(self, **kwargs):
        self.last_call = kwargs
        return SimpleNamespace(content=[_FakeTextBlock(self._reply_text)])


class _FakeClient:
    def __init__(self, reply_text: str):
        self.messages = _FakeMessages(reply_text)


def test_explain_returns_grounded_result_for_faithful_reply():
    evidence = {"ccme_wqi": 19.93, "confidence": "low_confidence"}
    client = _FakeClient("The CCME water quality index for this site is 19.93, a low score.")

    result = explain("ccme-wqi-location", evidence, client=client, model="claude-opus-5")

    assert result.grounded
    assert result.ungrounded_numbers == ()
    assert result.model == "claude-opus-5"
    assert "19.93" in result.text


def test_explain_flags_ungrounded_reply_without_raising():
    evidence = {"ccme_wqi": 19.93}
    client = _FakeClient("This site scores 99.9, an excellent result.")

    result = explain("ccme-wqi-location", evidence, client=client, model="claude-opus-5")

    assert not result.grounded
    assert "99.9" in result.ungrounded_numbers


def test_explain_sends_system_prompt_and_evidence_as_user_message():
    evidence = {"ccme_wqi": 19.93}
    client = _FakeClient("19.93.")

    explain("ccme-wqi-location", evidence, client=client, model="claude-opus-5")

    call = client.messages.last_call
    assert call["model"] == "claude-opus-5"
    assert "EVIDENCE" in call["messages"][0]["content"]
    assert "19.93" in call["messages"][0]["content"]
    assert call["system"]


def test_explain_defaults_to_configured_model_when_none_given(monkeypatch):
    monkeypatch.delenv("OAH_LLM_MODEL", raising=False)
    client = _FakeClient("no numbers here")
    result = explain("ccme-wqi-location", {}, client=client)
    assert result.model == DEFAULT_LLM_MODEL


def test_explain_respects_configured_model_override(monkeypatch):
    monkeypatch.setenv("OAH_LLM_MODEL", "claude-sonnet-5")
    client = _FakeClient("no numbers here")
    result = explain("ccme-wqi-location", {}, client=client)
    assert result.model == "claude-sonnet-5"


# --- modes (describe vs. assess) -----------------------------------------------------------------


def test_system_prompt_for_mode_selects_the_right_prompt():
    assert system_prompt_for_mode("describe") == DESCRIBE_SYSTEM_PROMPT
    assert system_prompt_for_mode("assess") == ASSESS_SYSTEM_PROMPT


def test_system_prompt_for_mode_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        system_prompt_for_mode("opinionated")


def test_build_user_prompt_wording_differs_by_mode():
    describe_prompt = build_user_prompt("ccme-wqi-location", {"ccme_wqi": 19.93}, "describe")
    assess_prompt = build_user_prompt("ccme-wqi-location", {"ccme_wqi": 19.93}, "assess")
    assert "Explain this" in describe_prompt
    assert "Assess this" in assess_prompt


def test_explain_defaults_to_describe_mode():
    client = _FakeClient("19.93.")
    result = explain("ccme-wqi-location", {"ccme_wqi": 19.93}, client=client, model="claude-opus-5")
    assert result.mode == "describe"
    assert client.messages.last_call["system"] == DESCRIBE_SYSTEM_PROMPT


def test_explain_assess_mode_uses_the_assess_system_prompt_and_records_the_mode():
    client = _FakeClient("Concern level: low\nNo action needed right now.")
    result = explain("ccme-wqi-location", {"ccme_wqi": 19.93}, client=client, model="claude-opus-5", mode="assess")
    assert result.mode == "assess"
    assert client.messages.last_call["system"] == ASSESS_SYSTEM_PROMPT
    assert "Concern level" in result.text


def test_explain_assess_mode_is_still_grounding_checked():
    client = _FakeClient("Concern level: critical. This is caused by a reading of 87.5.")
    result = explain("ccme-wqi-location", {"ccme_wqi": 19.93}, client=client, model="claude-opus-5", mode="assess")
    assert not result.grounded
    assert "87.5" in result.ungrounded_numbers


# --- real Anthropic API failures (errors.py) ----------------------------------------------------


class _RaisingFakeMessages:
    def __init__(self, error: Exception):
        self._error = error

    def create(self, **kwargs):
        raise self._error


class _RaisingFakeClient:
    def __init__(self, error: Exception):
        self.messages = _RaisingFakeMessages(error)


def test_wrap_anthropic_error_never_returns_the_upstream_text():
    error = _api_status_error(anthropic.BadRequestError, 400, "Your credit balance is too low.")
    wrapped = wrap_anthropic_error(error)
    assert isinstance(wrapped, LLMRequestError)
    assert wrapped.detail == "The language-model provider could not complete the request."
    assert "credit" not in wrapped.detail.lower()
    assert wrapped.status_code == 502


def test_wrap_anthropic_error_maps_rate_limit_to_429():
    error = _api_status_error(anthropic.RateLimitError, 429, "Rate limited.")
    wrapped = wrap_anthropic_error(error)
    assert wrapped.status_code == 429


def test_wrap_anthropic_error_handles_a_connection_error_with_no_body():
    error = anthropic.APIConnectionError(request=_FAKE_REQUEST)
    wrapped = wrap_anthropic_error(error)
    assert wrapped.status_code == 502
    assert wrapped.detail  # some non-empty, safe-to-show message


def test_explain_raises_llm_request_error_instead_of_the_raw_sdk_exception():
    original = _api_status_error(anthropic.BadRequestError, 400, "Your credit balance is too low.")
    client = _RaisingFakeClient(original)

    with pytest.raises(LLMRequestError) as excinfo:
        explain("ccme-wqi-location", {"ccme_wqi": 19.93}, client=client, model="claude-opus-5")

    assert excinfo.value.status_code == 502
    assert "credit" not in excinfo.value.detail.lower()


def test_the_wqi_prompt_carries_a_glossary_that_defines_excursion_and_warns_about_proxy_limits():
    prompt = build_user_prompt("ccme-wqi-location", {"ccme_wqi": 69.5}, "describe")
    assert "GLOSSARY" in prompt and "times_limit" in prompt and "proxies" in prompt and "never proof" in prompt
    assert prompt.index("GLOSSARY") > prompt.index("EVIDENCE") and prompt.rstrip().endswith("EVIDENCE above.")
    assert "GLOSSARY" not in build_user_prompt("review-queue-item", {"x": 1}, "describe")


def test_explanation_records_token_usage_when_the_client_reports_it_and_none_when_it_does_not():
    class _Usage:
        input_tokens, output_tokens = 321, 87

    with_usage = _FakeClient("The index is 19.93.")
    original = with_usage.messages.create

    def create(**kwargs):
        response = original(**kwargs)
        response.usage = _Usage()
        return response

    with_usage.messages.create = create
    result = explain("ccme-wqi-location", {"ccme_wqi": 19.93}, client=with_usage, model="claude-opus-5")
    assert (result.input_tokens, result.output_tokens) == (321, 87)
    plain = explain("ccme-wqi-location", {"ccme_wqi": 19.93}, client=_FakeClient("19.93."), model="claude-opus-5")
    assert plain.input_tokens is None and plain.output_tokens is None


def test_the_assess_prompt_forbids_stating_general_domain_knowledge_as_fact():
    assert "general domain knowledge" in ASSESS_SYSTEM_PROMPT
    assert "do not state it as fact" in ASSESS_SYSTEM_PROMPT and "check it" in ASSESS_SYSTEM_PROMPT
    assert "general domain knowledge" not in DESCRIBE_SYSTEM_PROMPT  # describe is already strictly factual
