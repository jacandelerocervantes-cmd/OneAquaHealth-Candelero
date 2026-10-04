"""``POST /chat``: the bounded tool-use agent over the read-only tools."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from oah.api import deps
from oah.api.chat_context import _chat_tool_context
from oah.api.deps import enforce_chat_rate
from oah.api.payloads import _countries_overview
from oah.api.schemas import ChatRequest, ChatResponse, ErrorResponse
from oah.api.services import _chat_with_budget, get_data_freshness, resolve_language
from oah.chat import normalise_country

router = APIRouter()


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
    dependencies=[Depends(enforce_chat_rate)],
)
def chat(body: ChatRequest) -> dict[str, Any]:
    """Answer a free-text question about the real sandbox data with a bounded agent that chains read-only tool calls.

    Tools are read-only wrappers over the same functions as the REST routes (official records only). The answer is
    checked against the tool results (grounding, units, output safety); an unsafe answer is withheld. The chat has its
    own caps (OAH_CHAT_DAILY_CAP conversations per rolling 24 hours, OAH_CHAT_RATE_LIMIT_PER_MINUTE per host) and
    a step bound (OAH_CHAT_MAX_STEPS); see docs/chat_agent.md.

    ``language`` (a code of GET /languages, default OAH_DEFAULT_LANGUAGE) selects the answer language: the conversation
    stays English and a validated English answer is then translated by one more, verified model call (counted in the
    model-call cap); ``answer_en`` is the English original. See docs/language_support.md.
    """
    code = resolve_language(body.language)  # a 422 before anything is reserved or sent
    country = normalise_country(body.country) if body.country else None
    if country is not None:
        overview, _ = _countries_overview()
        if country not in {item["code"] for item in overview}:
            raise HTTPException(status_code=422, detail=f"Unknown country {country!r}; GET /countries lists the known codes.")
    fields, cached = _chat_with_budget(
        body.message,
        country,
        body.index,
        [turn.model_dump() for turn in body.history],
        deps.get_chat_guard(),
        deps.get_llm_client,
        _chat_tool_context(country),
        get_data_freshness,
        code,
    )
    return {**fields, "cached": cached}
