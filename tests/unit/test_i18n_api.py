"""Answer languages at the API level: ``language`` on /chat and /explain/*, GET /languages, spend, cache and audit.

No network: a scripted fake model client answers both the English call and the translation call (told apart by the
system prompt). Data is the same tiny synthetic world as the other API tests.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.llm_guard import ChatSpendGuard, LLMSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.explain import audit
from oah.explain.client import LLMNotConfiguredError
from oah.i18n.languages import LANGUAGES
from oah.i18n.strings import ENGLISH, load_strings
from oah.paths import llm_audit_path
from oah.review.queue import submit_to_queue
from oah.store.review_store import ReviewStore
from oah.uncertainty.conformal import ConformalPredictionSet

PROFILE = "http://hl7.eu/fhir/ig/oah/StructureDefinition/observation-with-component-oah"
ENGLISH_ANSWER = "The reference check found no problem in this data."
SPANISH_ANSWER = "La revisión de referencia no encontró ningún problema en estos datos."
FRENCH_ANSWER = "Le contrôle de référence n'a trouvé aucun problème dans ces données."
GERMAN_ANSWER = "Die Prüfung fand kein Problem in diesen Daten."


def _observations() -> list[dict[str, Any]]:
    return [
        {
            "id": "obs-nitrate-1", "resourceType": "Observation", "meta": {"profile": [PROFILE]},
            "subject": {"reference": "Location/Loc-Test-01"}, "code": {"coding": [{"code": "nitrate"}]},
            "valueQuantity": {"value": 12.0, "unit": "mg/L", "system": "http://unitsofmeasure.org", "code": "mg/L"},
        },
        {
            "id": "obs-ph-1", "resourceType": "Observation", "meta": {"profile": [PROFILE]},
            "subject": {"reference": "Location/Loc-Test-01"}, "code": {"coding": [{"code": "ph"}]},
            "valueQuantity": {"value": 7.5, "unit": "pH"},
        },
    ]


def _locations() -> list[dict[str, Any]]:
    return [{"resourceType": "Location", "id": "Loc-Test-01", "name": "Test reach", "position": {"latitude": 35.3, "longitude": 25.0}}]


@dataclass
class Text:
    text: str
    type: str = "text"


@dataclass
class Routing:
    """Answers the English call (``english``) and the translation call (looked up by the language in its system prompt)."""

    english: str = ENGLISH_ANSWER
    translations: dict[str, Any] = field(default_factory=dict)  # language name -> text or exception
    english_calls: list[dict[str, Any]] = field(default_factory=list)
    translation_calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        def _create(**kwargs: Any) -> Any:
            system = str(kwargs.get("system", ""))
            if "translation component" not in system:
                self.english_calls.append(kwargs)
                return SimpleNamespace(content=[Text(self.english)], usage=SimpleNamespace(input_tokens=100, output_tokens=20))
            self.translation_calls.append(kwargs)
            name = next((n for n in self.translations if f"into {n}" in system), None)
            outcome = self.translations.get(name) if name else None
            if isinstance(outcome, BaseException):
                raise outcome
            text = outcome if outcome is not None else self.english
            return SimpleNamespace(
                content=[Text(text)], usage=SimpleNamespace(input_tokens=50, output_tokens=30), stop_reason="end_turn"
            )

        self.messages = SimpleNamespace(create=_create)


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", _observations)
    monkeypatch.setattr(deps_module, "get_cached_locations", _locations)
    explain_guard = LLMSpendGuard(per_minute=10_000, daily_cap=100, cache_ttl_seconds=60.0)
    chat_guard = ChatSpendGuard(per_minute=10_000, daily_cap=100, cache_ttl_seconds=60.0, max_steps=6)
    monkeypatch.setattr(deps_module, "get_llm_guard", lambda: explain_guard)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: chat_guard)
    return SimpleNamespace(explain=explain_guard, chat=chat_guard)


@pytest.fixture()
def guards(_world):
    return _world


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


def use(monkeypatch, client: Any) -> Any:
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: client)
    return client


def explain(http: TestClient, **params: Any):
    return http.get("/explain/indices/Loc-Test-01", params=params)


def chat(http: TestClient, message: str = "How many sites are there?", **extra: Any):
    return http.post("/chat", json={"message": message, **extra})


# --- GET /languages ------------------------------------------------------------------------------------------------


def test_languages_lists_every_registry_entry(http):
    response = http.get("/languages")
    assert response.status_code == 200
    body = response.json()
    assert body["default_language"] == "en" and body["source_language"] == "en"
    codes = [row["code"] for row in body["languages"]]
    assert codes == list(LANGUAGES) and len(codes) == 26 and {"es-MX", "es-ES", "nb", "el"} <= set(codes)
    assert {row["status"] for row in body["languages"]} == {"source", "translated-by-model"}
    by_code = {row["code"]: row for row in body["languages"]}
    assert by_code["en"]["status"] == "source" and by_code["es-MX"]["endonym"] == "Español (México)"
    assert by_code["es-MX"]["fixed_strings_review_status"] == "machine-draft" and by_code["en"]["fixed_strings_review_status"] == "source"
    assert body["note"].startswith("Machine-translated")


def test_languages_is_protected_like_the_other_routes(http, monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "demo-secret")
    assert http.get("/languages").status_code == 401
    assert http.get("/languages", headers={"X-API-Key": "demo-secret"}).status_code == 200


def test_languages_reports_the_configured_default(http, monkeypatch):
    monkeypatch.setenv("OAH_DEFAULT_LANGUAGE", "es_mx")
    assert http.get("/languages").json()["default_language"] == "es-MX"


# --- /explain/indices ----------------------------------------------------------------------------------------------


def test_explain_defaults_to_english_with_the_new_fields(monkeypatch, http):
    fake = use(monkeypatch, Routing())
    body = explain(http).json()
    assert body["language"] == "en" and body["answer_en"] is None and body["translation_status"] == "not-needed"
    assert body["translated"] is False and body["translation_reasons"] == []
    assert body["explanation"] == ENGLISH_ANSWER and body["disclaimer"] == ENGLISH["disclaimer"]
    assert body["notices"] == {"interpretation_notice": ENGLISH["interpretation_notice"]}
    assert body["status"] == "answered" and body["translation_checks"] is None  # nothing is translated into English
    assert len(fake.english_calls) == 1 and fake.translation_calls == []


def test_explain_in_mexican_spanish_translates_the_validated_english_answer(monkeypatch, http):
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    body = explain(http, language="es-MX").json()
    assert body["language"] == "es-MX" and body["translation_status"] == "ok" and body["translated"] is True
    assert body["explanation"] == SPANISH_ANSWER and body["answer_en"] == ENGLISH_ANSWER
    assert body["translation_reasons"] == [] and body["cached"] is False
    assert body["translation_checks"] == "neutral-and-denylist"  # Spanish has a best-effort denylist
    es = load_strings("es-MX")
    assert body["disclaimer"] == es.strings["disclaimer"] and body["disclaimer"] != ENGLISH["disclaimer"]
    assert body["notices"]["machine_translation_notice"] == es.strings["machine_translation_notice"]
    assert body["notices"]["interpretation_notice"] == es.strings["interpretation_notice"]
    assert "translation_fallback_notice" not in body["notices"]
    # the translation call carried nothing but the validated English answer, with Mexican Spanish requested
    call = fake.translation_calls[0]
    assert call["messages"] == [{"role": "user", "content": f"<source_text>\n{ENGLISH_ANSWER}\n</source_text>"}]
    assert "Mexican" in call["system"] and "tools" not in call
    assert len(fake.english_calls) == 1
    assert "evidence" in body and body["evidence"]["origin"] == "real-sandbox"  # the evidence stays as computed, in English


def test_explain_peninsular_spanish_is_a_separate_variant(monkeypatch, http):
    fake = use(monkeypatch, Routing(translations={"Spanish (Spain)": SPANISH_ANSWER}))
    body = explain(http, language="es_ES").json()
    assert body["language"] == "es-ES" and body["translated"] is True
    assert "peninsular" in fake.translation_calls[0]["system"] and "Mexican" not in fake.translation_calls[0]["system"]
    assert body["disclaimer"] == load_strings("es-ES").strings["disclaimer"]


@pytest.mark.parametrize(("given", "canonical"), [("ES", "es-MX"), ("es", "es-MX"), ("Es-mx", "es-MX"), ("EL", "el"), ("no", "nb")])
def test_explain_accepts_case_and_documented_aliases(monkeypatch, http, given, canonical):
    use(monkeypatch, Routing())
    assert explain(http, language=given).json()["language"] == canonical


@pytest.mark.parametrize("bad", ["xx", "pt-BR", "Greek", "e", "x" * 13, "en;fr", "es--MX", "<script>"])
def test_explain_rejects_an_unknown_language_with_the_supported_list_and_sends_nothing(monkeypatch, http, guards, bad):
    fake = use(monkeypatch, Routing())
    response = explain(http, language=bad)
    assert response.status_code == 422
    if len(bad) <= 12 and len(bad) >= 2:
        assert "es-MX" in response.text and "supported" in response.text
    assert fake.english_calls == [] and fake.translation_calls == []
    assert guards.explain.remaining_calls() == 100


def test_an_ungrounded_english_answer_is_withheld_and_never_translated(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing(english="This site scores 87.5, a made-up number.", translations={"Spanish (Mexico)": "Este sitio obtiene 87.5, un número inventado."}))
    body = explain(http, language="es-MX").json()
    assert body["status"] == "withheld-ungrounded" and body["explanation"] is None and body["answer_en"] is None
    assert body["grounded"] is False and body["ungrounded_numbers"] == ["87.5"] and body["unsafe"] is False
    assert body["translated"] is False and body["translation_status"] == "not-needed"
    assert body["translation_reasons"] == ["english-answer-ungrounded"]
    assert fake.translation_calls == [] and guards.explain.remaining_calls() == 99  # no unit spent on a translation
    assert body["notices"]["withheld_ungrounded_notice"] == load_strings("es-MX").strings["withheld_ungrounded_notice"]
    assert "ungrounded_notice" not in body["notices"] and body["evidence"]["origin"] == "real-sandbox"  # the evidence stays
    assert "87.5" not in json.dumps({k: v for k, v in body.items() if k != "ungrounded_numbers"})  # the invented number is not echoed


def test_a_translation_with_an_added_number_is_rejected_and_english_is_returned(monkeypatch, http):
    use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER + " Hay 7 sitios."}))
    body = explain(http, language="es-MX").json()
    assert body["translation_status"] == "rejected" and body["translated"] is False
    assert body["explanation"] == ENGLISH_ANSWER and body["answer_en"] == ENGLISH_ANSWER
    assert body["translation_reasons"] == ["number-added"]
    assert body["notices"]["translation_fallback_notice"] == load_strings("es-MX").get(
        "translation_fallback_notice", language="Español (México)"
    )
    assert "machine_translation_notice" not in body["notices"]


def test_a_provider_error_during_translation_still_answers_in_english(monkeypatch, http):
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    use(monkeypatch, Routing(translations={"Italian": error}))
    response = explain(http, language="it")
    assert response.status_code == 200
    body = response.json()
    assert body["translation_status"] == "failed" and body["translation_reasons"] == ["provider-error"]
    assert body["explanation"] == ENGLISH_ANSWER and body["translated"] is False


def test_an_unsafe_english_answer_is_never_translated(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing(english="The water is potable and fine for everyone."))
    body = explain(http, language="fr").json()
    assert body["unsafe"] is True and "unsupported-health-claim" in body["output_flags"]
    assert fake.translation_calls == [] and guards.explain.remaining_calls() == 99  # only the English call was reserved
    assert body["translation_status"] == "not-needed" and body["translation_reasons"] == ["english-answer-unsafe"]
    assert body["translated"] is False and body["explanation"] is None and body["answer_en"] is None  # no text is returned
    assert body["status"] == "withheld"
    assert "withheld_notice" in body["notices"] and body["notices"]["withheld_notice"] == load_strings("fr").strings["withheld_notice"]


def test_explain_translation_costs_one_more_unit_of_the_cap(monkeypatch, http, guards):
    use(monkeypatch, Routing(translations={"French": FRENCH_ANSWER}))
    explain(http)
    assert guards.explain.remaining_calls() == 99
    other = explain(http, language="fr")
    assert other.json()["translated"] is True
    assert guards.explain.remaining_calls() == 98  # English was cached: one unit for the translation only


def test_explain_cache_is_keyed_by_language(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER, "French": FRENCH_ANSWER}))
    first = explain(http, language="es-MX").json()
    again = explain(http, language="es-MX").json()
    assert first["cached"] is False and again["cached"] is True and again["explanation"] == SPANISH_ANSWER
    assert len(fake.english_calls) == 1 and len(fake.translation_calls) == 1
    french = explain(http, language="fr").json()
    assert french["explanation"] == FRENCH_ANSWER and french["cached"] is False
    assert len(fake.english_calls) == 1 and len(fake.translation_calls) == 2  # English shared, translation per language
    assert explain(http).json()["explanation"] == ENGLISH_ANSWER  # and English is untouched by the translations
    assert guards.explain.remaining_calls() == 100 - 3


def test_a_rejected_translation_is_not_cached(monkeypatch, http):
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER + " 9"}))
    assert explain(http, language="es-MX").json()["translation_status"] == "rejected"
    assert explain(http, language="es-MX").json()["translation_status"] == "rejected"
    assert len(fake.translation_calls) == 2


def test_an_exhausted_daily_cap_makes_the_translation_fail_not_the_route(monkeypatch, http):
    tight = LLMSpendGuard(per_minute=10_000, daily_cap=1, cache_ttl_seconds=60.0)
    monkeypatch.setattr(deps_module, "get_llm_guard", lambda: tight)
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    body = explain(http, language="es-MX").json()
    assert body["translation_status"] == "failed" and body["translation_reasons"] == ["budget"]
    assert body["explanation"] == ENGLISH_ANSWER and fake.translation_calls == []


def test_translation_model_defaults_to_the_explanation_model_and_can_be_set(monkeypatch, http):
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    monkeypatch.setenv("OAH_LLM_MODEL", "model-a")
    explain(http, language="es-MX")
    assert fake.english_calls[0]["model"] == "model-a" and fake.translation_calls[0]["model"] == "model-a"
    monkeypatch.setenv("OAH_TRANSLATION_MODEL", "model-b")
    explain(http, language="fr")
    assert fake.translation_calls[1]["model"] == "model-b" and len(fake.english_calls) == 1


def test_the_translation_timeout_setting_reaches_the_call(monkeypatch, http):
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    monkeypatch.setenv("OAH_TRANSLATION_TIMEOUT_SECONDS", "12")
    explain(http, language="es-MX")
    assert fake.translation_calls[0]["timeout"] == 12.0


def test_an_unconfigured_client_degrades_the_translation_when_english_is_cached(monkeypatch, http):
    use(monkeypatch, Routing())
    explain(http)  # English cached

    def _raise():
        raise LLMNotConfiguredError("not set")

    monkeypatch.setattr(deps_module, "get_llm_client", _raise)
    body = explain(http, language="es-MX").json()
    assert body["translation_status"] == "failed" and body["translation_reasons"] == ["llm-not-configured"]
    assert body["explanation"] == ENGLISH_ANSWER


def test_explain_audit_chain_verifies_and_holds_no_text(monkeypatch, http):
    use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER, "French": FRENCH_ANSWER + " 3"}))
    explain(http, language="es-MX")
    explain(http, language="es-MX")  # translation cache hit
    explain(http, language="fr")  # rejected
    ok, checked, bad = audit.verify_all()
    assert ok and bad is None and checked >= 7
    raw = llm_audit_path().read_text(encoding="utf-8")
    events = [json.loads(line)["event"] for line in raw.splitlines()]
    assert {"translation-dispatch", "translation-result", "translation-rejected", "translation-cache-hit"} <= set(events)
    for fragment in (ENGLISH_ANSWER, SPANISH_ANSWER, FRENCH_ANSWER, "referencia", "reference check"):
        assert fragment not in raw


def test_if_the_audit_log_cannot_be_written_the_translation_is_a_503(monkeypatch, http):
    use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    explain(http)  # English cached
    real_record = audit.record

    def broken(event: str, **fields: Any) -> None:
        if event.startswith("translation"):
            raise OSError("disk full")
        real_record(event, **fields)

    monkeypatch.setattr(audit, "record", broken)
    assert explain(http, language="es-MX").status_code == 503


# --- /explain/review -----------------------------------------------------------------------------------------------


def test_review_explanation_takes_the_language_too(monkeypatch, http, tmp_path):
    store = ReviewStore(tmp_path / "review.db")
    submit_to_queue(store, ConformalPredictionSet("SPEC-1", ("A", "B"), {"A": 0.55, "B": 0.45}, 0.5, "one-coin"))
    monkeypatch.setattr(deps_module, "get_review_store", lambda: store)
    fake = use(monkeypatch, Routing(translations={"German": GERMAN_ANSWER}))
    ok = http.get("/explain/review/SPEC-1", params={"language": "de"}).json()
    assert ok["language"] == "de" and ok["translated"] is True and ok["answer_en"] == ENGLISH_ANSWER
    assert ok["origin"] == "synthetic" and len(fake.english_calls) == 1
    bad = http.get("/explain/review/SPEC-1", params={"language": "xx"})
    assert bad.status_code == 422 and "supported" in bad.text
    assert http.get("/explain/review/NOPE", params={"language": "de"}).status_code == 404


# --- POST /chat ----------------------------------------------------------------------------------------------------


def test_chat_defaults_to_english(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing())
    body = chat(http).json()
    assert body["status"] == "answered" and body["answer"] == ENGLISH_ANSWER
    assert body["language"] == "en" and body["answer_en"] is None and body["translation_status"] == "not-needed"
    assert body["translated"] is False and body["disclaimer"] == ENGLISH["disclaimer"]
    assert body["usage"]["model_calls"] == 1 and len(fake.english_calls) == 1 and fake.translation_calls == []


def test_chat_in_mexican_spanish_translates_and_counts_the_call(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    body = chat(http, language="es-MX").json()
    assert body["status"] == "answered" and body["answer"] == SPANISH_ANSWER and body["answer_en"] == ENGLISH_ANSWER
    assert body["language"] == "es-MX" and body["translation_status"] == "ok" and body["translated"] is True
    assert body["disclaimer"] == load_strings("es-MX").strings["disclaimer"]
    assert "machine_translation_notice" in body["notices"]
    usage = body["usage"]
    assert usage["model_calls"] == 2 and usage["input_tokens"] == 150 and usage["output_tokens"] == 50
    assert "conversations_remaining_today" not in usage and "model_calls_remaining_today" not in usage  # not public (F12)
    assert guards.chat.remaining_calls() == 99  # the translation is not a second conversation
    assert guards.chat.remaining_model_calls() == 100 * 6 - 2  # but it is counted in the model-call cap
    assert len(fake.english_calls) == 1 and len(fake.translation_calls) == 1
    call = fake.translation_calls[0]
    assert call["messages"] == [{"role": "user", "content": f"<source_text>\n{ENGLISH_ANSWER}\n</source_text>"}]
    assert "tools" not in call and "tool_choice" not in call and "How many sites" not in json.dumps(call)


def test_chat_default_language_setting_applies_when_the_request_names_none(monkeypatch, http):
    use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    monkeypatch.setenv("OAH_DEFAULT_LANGUAGE", "es-MX")
    body = chat(http).json()
    assert body["language"] == "es-MX" and body["translated"] is True
    assert chat(http, "Another question?", language="en").json()["language"] == "en"  # an explicit en wins


@pytest.mark.parametrize("bad", ["xx", "pt-BR", "Greek", "en;fr", "es--MX", "<script>"])
def test_chat_rejects_an_unknown_language_before_reserving_anything(monkeypatch, http, guards, bad):
    fake = use(monkeypatch, Routing())
    response = chat(http, language=bad)
    assert response.status_code == 422 and "es-MX" in response.text and "supported" in response.text
    assert fake.english_calls == [] and guards.chat.remaining_calls() == 100 and guards.chat.remaining_model_calls() == 600


@pytest.mark.parametrize("bad", ["", "e", "x" * 13, 5, ["en"]])
def test_chat_rejects_malformed_language_values_with_a_422(monkeypatch, http, bad):
    use(monkeypatch, Routing())
    assert chat(http, language=bad).status_code == 422


def test_chat_translation_rejection_falls_back_to_english(monkeypatch, http):
    use(monkeypatch, Routing(translations={"Spanish (Mexico)": "Hay 4 sitios en estos datos."}))
    body = chat(http, language="es-MX").json()
    assert body["status"] == "answered" and body["answer"] == ENGLISH_ANSWER and body["answer_en"] == ENGLISH_ANSWER
    assert body["translation_status"] == "rejected" and body["translated"] is False
    assert set(body["translation_reasons"]) == {"number-added"}
    assert "translation_fallback_notice" in body["notices"] and body["grounded"] is True


def test_chat_translation_provider_error_falls_back_to_english(monkeypatch, http):
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    use(monkeypatch, Routing(translations={"Greek": error}))
    body = chat(http, language="el").json()
    assert body["translation_status"] == "failed" and body["answer"] == ENGLISH_ANSWER and body["translation_reasons"] == ["provider-error"]


def test_a_withheld_english_answer_is_withheld_in_every_language(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing(english="See https://example.org for the answer."))
    body = chat(http, language="it").json()
    assert body["status"] == "withheld" and body["unsafe"] is True and body["answer"] is None and body["answer_en"] is None
    assert fake.translation_calls == [] and body["usage"]["model_calls"] == 1
    assert body["translation_status"] == "not-needed" and body["translation_reasons"] == ["english-answer-unsafe"]
    assert body["notices"]["withheld_notice"] == load_strings("it").strings["withheld_notice"]


def test_the_budget_exceeded_text_comes_from_the_fixed_strings_without_a_model_call(monkeypatch, http):
    one_step = ChatSpendGuard(per_minute=10_000, daily_cap=100, cache_ttl_seconds=60.0, max_steps=1)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: one_step)

    calls: list[int] = []

    def _create(**_kwargs: Any) -> Any:
        calls.append(1)
        block = SimpleNamespace(type="tool_use", id="t", name="list_countries", input={})
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=10, output_tokens=5))

    use(monkeypatch, SimpleNamespace(messages=SimpleNamespace(create=_create)))
    body = chat(http, language="es-MX").json()
    assert body["status"] == "budget-exceeded" and len(calls) == 1
    assert body["answer"] == load_strings("es-MX").strings["budget_exceeded"]
    assert body["answer_en"] == ENGLISH["budget_exceeded"] and body["translation_status"] == "not-needed"
    assert body["translated"] is False and body["language"] == "es-MX"


def test_chat_cache_is_keyed_by_language_and_english_is_shared(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER, "French": FRENCH_ANSWER}))
    first = chat(http, language="es-MX").json()
    again = chat(http, language="es-MX").json()
    assert first["cached"] is False and again["cached"] is True and again["answer"] == SPANISH_ANSWER
    assert again["usage"]["model_calls"] == 0 and again["usage"]["input_tokens"] is None
    assert len(fake.english_calls) == 1 and len(fake.translation_calls) == 1
    french = chat(http, language="fr").json()
    assert french["answer"] == FRENCH_ANSWER and french["cached"] is False and french["usage"]["model_calls"] == 1
    assert len(fake.english_calls) == 1 and len(fake.translation_calls) == 2
    assert chat(http).json()["answer"] == ENGLISH_ANSWER and len(fake.english_calls) == 1
    assert guards.chat.remaining_calls() == 99  # one real conversation in total
    assert guards.chat.remaining_model_calls() == 600 - 3  # one English call and two translations


def test_the_model_call_cap_also_limits_translations(monkeypatch, http):
    capped = ChatSpendGuard(per_minute=10_000, daily_cap=1, cache_ttl_seconds=60.0, max_steps=1)  # model-call cap: 1
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: capped)
    fake = use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    body = chat(http, language="es-MX").json()
    assert body["status"] == "answered" and body["translation_status"] == "failed" and body["translation_reasons"] == ["budget"]
    assert body["answer"] == ENGLISH_ANSWER and fake.translation_calls == [] and body["usage"]["model_calls"] == 1
    assert capped.remaining_model_calls() == 0


def test_the_translation_call_is_counted_in_the_model_call_cap_exactly(monkeypatch, http):
    exact = ChatSpendGuard(per_minute=10_000, daily_cap=1, cache_ttl_seconds=60.0, max_steps=2)  # model-call cap: 2
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: exact)
    use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER}))
    body = chat(http, language="es-MX").json()
    assert body["translated"] is True and body["usage"]["model_calls"] == 2 and exact.remaining_model_calls() == 0


def test_chat_audit_chain_verifies_after_translations_and_holds_no_text(monkeypatch, http):
    use(monkeypatch, Routing(translations={"Spanish (Mexico)": SPANISH_ANSWER, "French": FRENCH_ANSWER + " 8"}))
    chat(http, language="es-MX")
    chat(http, language="es-MX")
    chat(http, language="fr")
    ok, checked, bad = audit.verify_all()
    assert ok and bad is None and checked >= 8
    raw = llm_audit_path().read_text(encoding="utf-8")
    for fragment in (ENGLISH_ANSWER, SPANISH_ANSWER, FRENCH_ANSWER, "reference check", "referencia"):
        assert fragment not in raw
    translation_events = [json.loads(line) for line in raw.splitlines() if json.loads(line)["event"].startswith("translation")]
    assert {event["language"] for event in translation_events} == {"es-MX", "fr"}
    assert all(set(event) <= {"timestamp", "event", "call_id", "language", "model", "source_sha256", "source_chars",
                              "output_sha256", "output_chars", "reasons", "input_tokens", "output_tokens",
                              "error_type", "reason", "prev_hash", "hash"} for event in translation_events)


def test_every_registry_language_can_be_requested_from_the_chat(monkeypatch, http):
    for code in LANGUAGES:
        guard = ChatSpendGuard(per_minute=10_000, daily_cap=100, cache_ttl_seconds=60.0, max_steps=6)
        monkeypatch.setattr(deps_module, "get_chat_guard", lambda guard=guard: guard)
        use(monkeypatch, Routing())  # the translation call returns the English text unchanged: accepted
        body = chat(http, language=code).json()
        assert body["language"] == code and body["status"] == "answered"
        assert body["translation_status"] == ("not-needed" if code == "en" else "ok")


def test_a_not_grounded_chat_answer_is_withheld_in_every_language_and_never_translated(monkeypatch, http, guards):
    fake = use(monkeypatch, Routing(english="There are 4321 sites in this data.", translations={"Italian": "Ci sono 4321 siti in questi dati."}))
    body = chat(http, language="it").json()
    assert body["status"] == "withheld-ungrounded" and body["answer"] is None and body["answer_en"] is None
    assert body["grounded"] is False and "4321" in body["ungrounded_numbers"] and body["unsafe"] is False
    assert fake.translation_calls == [] and body["usage"]["model_calls"] == 1
    assert body["translation_status"] == "not-needed" and body["translation_reasons"] == ["english-answer-ungrounded"]
    assert body["notices"]["withheld_ungrounded_notice"] == load_strings("it").strings["withheld_ungrounded_notice"]
    assert "withheld_notice" not in body["notices"] and body["translation_checks"] == "neutral-and-denylist"
    assert chat(http, "Another question?").json()["cached"] is False  # a withheld answer is never cached


def test_translation_checks_level_is_reported_for_every_language(monkeypatch, http):
    from oah.i18n.denylist import DENYLIST_FAMILIES

    by_code = {row["code"]: row for row in http.get("/languages").json()["languages"]}
    assert by_code["en"]["translation_checks"] is None
    for code, language in LANGUAGES.items():
        if code == "en":
            continue
        expected = "neutral-and-denylist" if language.family in DENYLIST_FAMILIES else "neutral-only"
        assert by_code[code]["translation_checks"] == expected, code
    levels = {row["translation_checks"] for row in by_code.values()}
    assert levels == {None, "neutral-and-denylist", "neutral-only"}
    assert by_code["fi"]["translation_checks"] == "neutral-only" and by_code["es-ES"]["translation_checks"] == "neutral-and-denylist"
    use(monkeypatch, Routing(translations={"Finnish": "Tarkistus ei löytänyt ongelmaa."}))
    body = chat(http, language="fi").json()
    assert body["translation_checks"] == "neutral-only"  # the response says so: the UI labels it unverified


def test_openapi_documents_the_language_fields(http):
    schema = app_module.app.openapi()
    chat_request = schema["components"]["schemas"]["ChatRequest"]["properties"]
    assert "language" in chat_request
    chat_response = schema["components"]["schemas"]["ChatResponse"]["properties"]
    for name in ("language", "answer_en", "translation_status", "translated", "translation_reasons", "notices", "translation_checks"):
        assert name in chat_response
    assert "withheld-ungrounded" in json.dumps(chat_response["status"])
    parameters = schema["paths"]["/explain/indices/{location_id}"]["get"]["parameters"]
    assert "language" in {parameter["name"] for parameter in parameters}
