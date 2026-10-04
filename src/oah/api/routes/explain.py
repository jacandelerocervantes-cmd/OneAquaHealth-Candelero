"""The LLM explanation routes: one CCME index result or one review-queue item, each in ``describe`` or ``assess`` mode."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from oah.api import deps, payloads
from oah.api.deps import enforce_explain_rate
from oah.api.schemas import ErrorResponse, ExplanationResponse
from oah.api.services import (
    _explain_with_budget,
    _explanation_fields,
    _localise_explanation,
    get_data_freshness,
    resolve_language,
)

router = APIRouter()


@router.get(
    "/explain/indices/{location_id}",
    response_model=ExplanationResponse,
    responses={404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    dependencies=[Depends(enforce_explain_rate)],
)
def explain_indices_for_location(
    location_id: str,
    mode: Literal["describe", "assess"] = "describe",
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """LLM explanation (mode=describe) or interpretive assessment (mode=assess) of the CCME WQI
    result for one real sandbox Location.

    ``language`` (a code of GET /languages, default OAH_DEFAULT_LANGUAGE) asks for the text in another language: the
    explanation is produced and checked in English, then translated by one more constrained model call and verified;
    ``answer_en`` always carries the English original. An unknown code is a 422 listing the supported codes.

    Reuses /indices/{location_id}'s own evaluated-or-skipped result as the sole evidence given
    to the model in either mode; see oah.explain for the grounding check applied to its output.
    "assess" adds a concern level and a recommended next step on top of the same evidence -- an
    interpretive judgment, not a new fact, and still grounding-checked for invented numbers.
    """
    code = resolve_language(language)  # a 422 before anything is fetched, reserved or sent
    freshness = get_data_freshness()
    # The evidence names where the data came from (status and date, not the ever-growing age) so the
    # explanation can say when it rests on a stale snapshot, and the cache key stays stable.
    evidence = {**payloads._indices_payload(location_id), "data_freshness": {"status": freshness["status"], "as_of": freshness["as_of"]}}
    result, cached = _explain_with_budget("ccme-wqi-location", evidence, mode, deps.get_llm_guard(), deps.get_llm_client)
    localization, translation_cached = _localise_explanation(
        result, code, "ccme-wqi-location", mode, evidence, deps.get_llm_guard(), deps.get_llm_client
    )
    return {
        "origin": evidence["origin"],
        "location_id": location_id,
        "evidence": evidence,
        **_explanation_fields(result, cached and translation_cached, localization),
    }


@router.get(
    "/explain/review/{specimen_id}",
    response_model=ExplanationResponse,
    responses={404: {"model": ErrorResponse}, 429: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
    dependencies=[Depends(enforce_explain_rate)],
)
def explain_review_item(
    specimen_id: str,
    mode: Literal["describe", "assess"] = "describe",
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """LLM explanation (mode=describe) or interpretive assessment (mode=assess) of why a
    specimen is in the synthetic human-review queue.

    ``language`` works as for GET /explain/indices/{location_id}: English first, then a verified translation.

    Reuses the review item's own prediction_set and probabilities (already computed by
    conformal prediction over Dawid-Skene or majority-vote posteriors) as the sole evidence
    given to the model in either mode; see oah.explain for the grounding check applied to its
    output. "assess" adds a concern level and a recommended next step for the human reviewer.
    """
    code = resolve_language(language)
    store = deps.get_review_store()
    item = store.get_review_item(specimen_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"No review item found for specimen {specimen_id!r}.")

    evidence = {
        "specimen_id": item.specimen_id,
        "prediction_set": list(item.prediction_set),
        "probabilities": item.probabilities,
        "status": item.status,
        "tag": item.tag,
    }
    result, cached = _explain_with_budget("review-queue-item", evidence, mode, deps.get_llm_guard(), deps.get_llm_client)
    localization, translation_cached = _localise_explanation(
        result, code, "review-queue-item", mode, evidence, deps.get_llm_guard(), deps.get_llm_client
    )
    return {
        "origin": item.tag,
        "specimen_id": specimen_id,
        "evidence": evidence,
        **_explanation_fields(result, cached and translation_cached, localization),
    }
