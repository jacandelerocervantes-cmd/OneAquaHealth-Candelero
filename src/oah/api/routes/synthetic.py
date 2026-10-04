"""The synthetic demo routes: reliability campaign, human-review queue and decisions, and the river-risk demo.

Every response is labelled ``"origin": "synthetic"``; none of it describes real data.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from oah.api import deps
from oah.api.deps import require_write_routes
from oah.api.schemas import (
    ErrorResponse,
    ReliabilityCampaignResponse,
    ReliabilityRequestParams,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueResponse,
    RiskResponse,
)
from oah.api.services import run_reliability_campaign
from oah.review import AlreadyDecidedError, InvalidLabelError, decide_review_item
from oah.risk import DECAY_PER_KM, INITIAL_RISK, SOURCE_SITE, SYNTHETIC_EDGES, build_river_graph, propagate_risk

router = APIRouter()


SITE_LABELS = ("Loc-Almyros", "Loc-Benevento", "Loc-OS")


@router.get("/reliability/campaign", response_model=ReliabilityCampaignResponse)
def reliability_campaign(params: ReliabilityRequestParams = Query()) -> dict[str, Any]:
    """Run a synthetic citizen-science campaign through Dawid-Skene and majority vote.

    Every number in this response measures the simulator, not real ecology.
    """
    return run_reliability_campaign(params, SITE_LABELS)


@router.get("/review/queue", response_model=ReviewQueueResponse)
def review_queue() -> dict[str, Any]:
    """List pending human-review items (all currently synthetic in this demo)."""
    store = deps.get_review_store()
    items = store.list_review_items(status="pending")
    return {
        "origin": "synthetic",
        "count": len(items),
        "items": [
            {
                "specimen_id": item.specimen_id,
                "prediction_set": list(item.prediction_set),
                "probabilities": item.probabilities,
                "status": item.status,
                "tag": item.tag,
            }
            for item in items
        ],
    }


@router.post(
    "/review/{specimen_id}/decide",
    response_model=ReviewDecisionResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
    dependencies=[Depends(require_write_routes)],
)
def review_decide(specimen_id: str, decision: ReviewDecisionRequest) -> dict[str, Any]:
    """Record a human reviewer's decision on a queued specimen.

    State-changing, so it answers 404 (as if the route did not exist) unless ``OAH_ENABLE_WRITE_ROUTES`` is on
    (default off). The review queue itself stays read-only and available."""
    store = deps.get_review_store()
    try:
        updated = decide_review_item(store, specimen_id, decision.final_label, decision.reviewer_id)
    except AlreadyDecidedError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except InvalidLabelError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    return {
        "origin": "synthetic",
        "specimen_id": updated.specimen_id,
        "status": updated.status,
        "final_label": updated.final_label,
        "reviewer_id": updated.reviewer_id,
        "decision_time": updated.decision_time,
    }


@router.get("/risk/{site_id}", response_model=RiskResponse, responses={404: {"model": ErrorResponse}})
def risk_for_site(site_id: str) -> dict[str, Any]:
    """Propagated risk for one site in the documented synthetic river-network demo topology.

    This is NOT real hydrology; see src/oah/risk/demo_topology.py.
    """
    graph = build_river_graph(SYNTHETIC_EDGES)
    if site_id not in graph:
        raise HTTPException(status_code=404, detail=f"Unknown demo topology site: {site_id!r}.")

    risk_by_node = propagate_risk(graph, SOURCE_SITE, INITIAL_RISK, DECAY_PER_KM)
    return {
        "origin": "synthetic",
        "note": "Illustrative synthetic topology, not real hydrology.",
        "source_site": SOURCE_SITE,
        "site_id": site_id,
        "risk": risk_by_node[site_id],
    }
