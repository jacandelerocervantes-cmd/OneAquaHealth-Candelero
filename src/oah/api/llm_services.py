"""LLM orchestration of the API: the explanation budget and cache, the answer-language translation and the chat conversation.

Split out of ``oah.api.services`` (which re-exports every name). No new business logic: each step sequences an
already-tested ``oah.explain``, ``oah.i18n`` or ``oah.chat`` function under the spend guards.

Dependency-injection note: the seams the tests replace (``get_llm_client``, the spend guards) are parameters here,
supplied by the route as ``deps.NAME`` looked up at call time; this module never imports ``oah.api.deps``.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

from fastapi import HTTPException

from oah.api.llm_guard import ChatSpendGuard, LLMSpendGuard
from oah.chat import ChatLimits, ToolContext, run_chat
from oah.chat.prompts import CHAT_LEAK_CHECK_PARTS
from oah.config import load_settings
from oah.explain import LLMNotConfiguredError, LLMRequestError, explain
from oah.explain import audit as llm_audit
from oah.explain.explainer import Explanation
from oah.explain.prompts import Mode
from oah.explain.safety import UNSAFE_OUTPUT_FLAGS
from oah.i18n.languages import SOURCE_LANGUAGE, UnsupportedLanguageError, parse_language
from oah.i18n.localize import Localization, build_localization
from oah.i18n.strings import ENGLISH
from oah.i18n.translator import TranslationResult, translate


# The 503 text when no model client can be built: fixed, naming neither the missing variable nor the settings file.
LLM_UNAVAILABLE_DETAIL = "The language-model service is not available."


def _explain_with_budget(
    kind: str,
    evidence: dict[str, Any],
    mode: Mode,
    llm_guard: LLMSpendGuard,
    get_llm_client: Callable[[], Any],
) -> tuple[Explanation, bool]:
    """Answer from the cache when possible; otherwise reserve one call of the daily cap and call the model.

    ``llm_guard`` and ``get_llm_client`` are supplied by the caller (the route) as ``deps.NAME``
    looked up at call time, so tests that monkeypatch those names on oah.api.deps keep working.
    """
    key = llm_guard.key(kind, mode, load_settings().llm_model, evidence)
    cached = llm_guard.cached(key)
    if cached is not None:
        try:
            llm_audit.record("cache-hit", kind=kind, mode=mode, model=cached.model, evidence_sha256=llm_audit.evidence_digest(evidence))
        except OSError as error:
            raise HTTPException(status_code=503, detail="LLM audit log unavailable; request refused.") from error
        return cached, True
    try:
        client = get_llm_client()
    except LLMNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=LLM_UNAVAILABLE_DETAIL) from error
    llm_guard.reserve_call()
    try:
        result = explain(kind, evidence, client=client, mode=mode)
    except LLMRequestError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except ValueError as error:  # the evidence was refused as oversized or too deeply nested
        raise HTTPException(status_code=422, detail=str(error)) from error
    except OSError as error:  # the audit trail could not be written: nothing was sent
        raise HTTPException(status_code=503, detail="LLM audit log unavailable; request refused.") from error
    llm_guard.store(key, result)
    return result, False


# UNSAFE_OUTPUT_FLAGS (imported above): flags for which the text must not be rendered to a reader; neither the
# explanation routes nor the chat route return the text then (a not grounded answer is withheld the same way).
EXPLANATION_DISCLAIMER = ENGLISH["disclaimer"]  # the English source text; responses carry it localised (oah.i18n)


def resolve_language(value: str | None) -> str:
    """The canonical code of the requested answer language (``OAH_DEFAULT_LANGUAGE`` when none was named).

    An unknown code is a 422 that lists the supported codes; nothing has been reserved or sent at that point.
    """
    if value is None:
        return load_settings().default_language
    try:
        return parse_language(value).code
    except UnsupportedLanguageError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _reserve_one_unit(guard: LLMSpendGuard) -> bool:
    """The translation of an explanation costs one more unit of the explanation cap; False when the cap is reached."""
    try:
        guard.reserve_call()
    except HTTPException:
        return False
    return True


def _translated(
    source_en: str,
    code: str,
    key: str,
    guard: LLMSpendGuard,
    get_llm_client: Callable[[], Any],
    reserve: Callable[[], bool],
    extra_leak_parts: tuple[str, ...] = (),
) -> tuple[TranslationResult, bool]:
    """Translate a validated English answer: from the cache when the same text was translated, else one model call.

    The cache key carries the language (and the translation model). Only an accepted translation is cached. A missing
    key, an exhausted budget, a provider error or a rejected translation all give the English text back with a status.
    """
    cached = guard.cached(key)
    if isinstance(cached, TranslationResult) and cached.source_en == source_en:
        try:
            llm_audit.record("translation-cache-hit", language=code, source_sha256=llm_audit.text_digest(source_en.strip()))
        except OSError as error:
            raise HTTPException(status_code=503, detail="LLM audit log unavailable; request refused.") from error
        return dataclasses.replace(cached, model_calls=0, input_tokens=None, output_tokens=None), True
    settings = load_settings()
    try:
        client = get_llm_client()
    except LLMNotConfiguredError:
        return TranslationResult("failed", code, source_en, source_en, ("llm-not-configured",)), False
    try:
        result = translate(
            source_en,
            code,
            client=client,
            model=settings.translation_model_id,
            reserve_model_call=reserve,
            timeout_seconds=settings.translation_timeout_seconds,
            extra_leak_parts=extra_leak_parts,
        )
    except OSError as error:  # the audit trail could not be written: nothing was sent
        raise HTTPException(status_code=503, detail="LLM audit log unavailable; request refused.") from error
    if result.status == "ok":
        guard.store(key, result)
    return result, False


def _localise_explanation(
    result: Explanation,
    code: str,
    kind: str,
    mode: Mode,
    evidence: dict[str, Any],
    guard: LLMSpendGuard,
    get_llm_client: Callable[[], Any],
) -> tuple[Localization, bool]:
    """The language fields of an explanation, and whether they needed no model call (English, or a cached translation).

    Grounding and unsafe flags describe the English text. An unsafe or not grounded English text is never translated and
    never returned (``explanation`` is null, the fixed notice and the flags say why); the evidence stays in the response.
    """
    unsafe = explanation_unsafe(result)
    ungrounded = not unsafe and not result.grounded
    if code == SOURCE_LANGUAGE or unsafe or ungrounded:
        return (
            build_localization(code, result.text, unsafe=unsafe, grounded=result.grounded, withheld_ungrounded=ungrounded),
            True,
        )
    settings = load_settings()
    key = guard.key(kind, mode, settings.llm_model, evidence, language=f"{code}:{settings.translation_model_id}")
    translation, cached = _translated(result.text, code, key, guard, get_llm_client, lambda: _reserve_one_unit(guard))
    return build_localization(code, result.text, translation, grounded=result.grounded), cached


def explanation_unsafe(result: Explanation) -> bool:
    """True when an unsafe-to-render flag is present (the text is then never returned)."""
    return bool(set(result.output_flags) & UNSAFE_OUTPUT_FLAGS)


def explanation_status(result: Explanation) -> str:
    """``withheld`` (unsafe), ``withheld-ungrounded`` (a number or unit not traceable to the evidence) or ``answered``."""
    if explanation_unsafe(result):
        return "withheld"
    return "answered" if result.grounded else "withheld-ungrounded"


def _explanation_fields(result: Explanation, cached: bool, localization: Localization | None = None) -> dict[str, Any]:
    unsafe = explanation_unsafe(result)
    status = explanation_status(result)
    loc = localization or build_localization(
        SOURCE_LANGUAGE, result.text, unsafe=unsafe, grounded=result.grounded, withheld_ungrounded=status == "withheld-ungrounded"
    )
    return {
        "mode": result.mode,
        "status": status,
        "explanation": None if status != "answered" else loc.text,
        "model": result.model,
        "grounded": result.grounded,
        "ungrounded_numbers": list(result.ungrounded_numbers),
        "unit_mismatches": list(result.unit_mismatches),
        "output_flags": list(result.output_flags),
        "unsafe": unsafe,
        "disclaimer": loc.disclaimer,
        "evidence_sanitized": list(result.evidence_sanitized),
        "cached": cached,
        **_language_fields(loc),
    }


def _language_fields(loc: Localization) -> dict[str, Any]:
    return {
        "language": loc.language,
        "answer_en": loc.answer_en,
        "translation_status": loc.translation_status,
        "translated": loc.translated,
        "translation_reasons": list(loc.translation_reasons),
        "notices": loc.notices,
        "translation_checks": loc.translation_checks,
    }


def _chat_with_budget(
    message: str,
    country: str | None,
    index: str | None,
    history: list[dict[str, str]],
    guard: ChatSpendGuard,
    get_llm_client: Callable[[], Any],
    ctx: ToolContext,
    data_freshness: Callable[[], Any],
    language: str = SOURCE_LANGUAGE,
) -> tuple[dict[str, Any], bool]:
    """Answer one chat question in ``language`` (a canonical registry code, see ``resolve_language``).

    The conversation itself is always English (``_chat_english``: all existing guards, grounding and caps). When another
    language is requested and the English answer was ``answered``, ONE more model call translates it
    (``oah.i18n.translator``): it is counted by ``ChatSpendGuard.try_reserve_model_call`` (the rolling model-call cap)
    and not as a conversation, so a translated conversation can use up to ``max_steps + 1`` model calls. The budget and
    no-answer texts are localised from the fixed strings (no model call); a withheld answer is never translated.
    Returns the response fields and ``cached`` (no model call was made at all).
    """
    stored, used_calls, cached = _chat_english(message, country, index, history, guard, get_llm_client, ctx, data_freshness)
    translation: TranslationResult | None = None
    translation_cached = True
    fixed_key = {"budget-exceeded": "budget_exceeded", "no-answer": "no_answer"}.get(stored["status"])
    if language != SOURCE_LANGUAGE and stored["status"] == "answered" and stored["answer"]:
        settings = load_settings()
        key = guard.chat_key(
            message, country, index, history, settings.llm_model, language=f"{language}:{settings.translation_model_id}"
        )
        translation, translation_cached = _translated(
            stored["answer"], language, key, guard, get_llm_client, guard.try_reserve_model_call, CHAT_LEAK_CHECK_PARTS
        )
    loc = build_localization(
        language,
        stored["answer"],
        translation,
        fixed_key=fixed_key,
        unsafe=bool(stored["unsafe"]),
        grounded=bool(stored["grounded"]),
        withheld_ungrounded=stored["status"] == "withheld-ungrounded",
        with_evidence=bool(stored.get("evidence")),
    )
    calls = used_calls + (translation.model_calls if translation is not None else 0)
    tokens_in = stored.get("input_tokens") if used_calls else None
    tokens_out = stored.get("output_tokens") if used_calls else None
    if translation is not None and translation.model_calls:
        tokens_in = (tokens_in or 0) + (translation.input_tokens or 0)
        tokens_out = (tokens_out or 0) + (translation.output_tokens or 0)
    body = {
        **stored,
        "answer": loc.text,
        "disclaimer": loc.disclaimer,
        **_language_fields(loc),
        "input_tokens": tokens_in,
        "output_tokens": tokens_out,
    }
    return _chat_fields(body, guard, model_calls=calls), cached and translation_cached


def _chat_english(
    message: str,
    country: str | None,
    index: str | None,
    history: list[dict[str, str]],
    guard: ChatSpendGuard,
    get_llm_client: Callable[[], Any],
    ctx: ToolContext,
    data_freshness: Callable[[], Any],
) -> tuple[dict[str, Any], int, bool]:
    """The English conversation: from the cache when identical, otherwise reserve ONE conversation of the chat cap
    and run the agent (whose model calls are counted by the same guard).
    Returns the stored fields, the model calls made now (0 when cached) and ``cached``.

    Order matters: nothing is reserved until the client exists (503 without a key) and the audit log is writable.
    Only an ``answered`` result is cached; a withheld or out-of-budget one is not.
    """
    settings = load_settings()
    key = guard.chat_key(message, country, index, history, settings.llm_model)
    cached = guard.cached(key)
    if cached is not None:
        try:
            llm_audit.record("chat-cache-hit", model=cached["model"], question_sha256=llm_audit.text_digest(message))
        except OSError as error:
            raise HTTPException(status_code=503, detail="LLM audit log unavailable; request refused.") from error
        return {**cached, "data_freshness": data_freshness()}, 0, True
    try:
        client = get_llm_client()
    except LLMNotConfiguredError as error:
        raise HTTPException(status_code=503, detail=LLM_UNAVAILABLE_DETAIL) from error
    guard.reserve_call()
    try:
        result = run_chat(
            message, country, index, history,
            client=client, ctx=ctx, model=settings.llm_model,
            limits=ChatLimits(max_steps=guard.max_steps, timeout_seconds=settings.chat_timeout_seconds),
            reserve_model_call=guard.try_reserve_model_call,
        )
    except LLMRequestError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail) from error
    except OSError as error:  # the audit trail could not be written: nothing further was sent
        raise HTTPException(status_code=503, detail="LLM audit log unavailable; request refused.") from error
    fields = {
        "origin": result.origin,
        "status": result.status,
        "answer": result.answer,
        "country": country,
        "index": index,
        "steps": result.steps,
        "citations": result.citations,
        "data_freshness": data_freshness(),
        "grounded": result.grounded,
        "ungrounded_numbers": list(result.ungrounded_numbers),
        "unit_mismatches": list(result.unit_mismatches),
        "unsafe": result.unsafe,
        "output_flags": list(result.output_flags),
        "input_notes": list(result.input_notes),
        "disclaimer": EXPLANATION_DISCLAIMER,
        "model": result.model,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        # the data consulted, only for a withheld answer (built from the tool results by oah.chat.evidence); null otherwise
        "evidence": result.evidence,
        "evidence_truncated": result.evidence_truncated,
    }
    if result.status == "answered":
        guard.store(key, {**fields, "model_calls": result.model_calls})
    return fields, result.model_calls, False


def _chat_fields(stored: dict[str, Any], guard: ChatSpendGuard, model_calls: int) -> dict[str, Any]:
    """The response body: the stored fields plus what this conversation used.

    The process-wide remaining budget (conversations and model calls left today) is deliberately NOT public: it tells a caller
    how much of the shared allowance is left to exhaust.
    """
    body = {key: value for key, value in stored.items() if key not in ("input_tokens", "output_tokens", "model_calls")}
    body["usage"] = {
        "model_calls": model_calls,
        "max_steps": guard.max_steps,
        "input_tokens": stored.get("input_tokens") if model_calls else None,
        "output_tokens": stored.get("output_tokens") if model_calls else None,
    }
    return body
