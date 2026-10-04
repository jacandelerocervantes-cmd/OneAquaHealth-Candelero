"""Every request to the external LLM provider leaves an audit trail without leaking content."""
import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from oah.explain import audit
from oah.explain.explainer import explain
from oah.paths import llm_audit_path

EVIDENCE = {"ccme_wqi": 19.93, "site": "Loc-Almyros", "note": "SECRET-EVIDENCE-TEXT"}


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Client:
    def __init__(self, text="The index is 19.93.", error=None):
        self.calls = 0
        self._text, self._error = text, error
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_kwargs):
        self.calls += 1
        if self._error:
            raise self._error
        usage = SimpleNamespace(input_tokens=11, output_tokens=7)
        return SimpleNamespace(content=[_Block(self._text)], usage=usage)


def _lines():
    return [json.loads(line) for line in llm_audit_path().read_text(encoding="utf-8").splitlines()]


def test_a_call_writes_dispatch_then_result_without_content_or_text():
    explain("indices", EVIDENCE, client=_Client("The index is 19.93. SECRET-MODEL-TEXT"))
    dispatch, result = _lines()
    assert dispatch["event"] == "dispatch" and result["event"] == "result"
    assert dispatch["call_id"] == result["call_id"]
    assert dispatch["evidence_sha256"] == audit.evidence_digest(EVIDENCE) and len(dispatch["evidence_sha256"]) == 64
    assert (result["input_tokens"], result["output_tokens"]) == (11, 7)
    raw = llm_audit_path().read_text(encoding="utf-8")
    assert "SECRET-EVIDENCE-TEXT" not in raw and "SECRET-MODEL-TEXT" not in raw


def test_the_digest_ignores_key_order():
    assert audit.evidence_digest({"a": 1, "b": 2}) == audit.evidence_digest({"b": 2, "a": 1})
    assert audit.evidence_digest({"a": 1}) != audit.evidence_digest({"a": 2})


def test_a_provider_error_is_recorded():
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    error = anthropic.APIConnectionError(request=request)
    with pytest.raises(Exception):
        explain("indices", EVIDENCE, client=_Client(error=error))
    events = [line["event"] for line in _lines()]
    assert events == ["dispatch", "error"]


def test_when_the_audit_cannot_be_written_nothing_is_sent(monkeypatch):
    def broken(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(audit, "record", broken)
    client = _Client()
    with pytest.raises(OSError):
        explain("indices", EVIDENCE, client=client)
    assert client.calls == 0
