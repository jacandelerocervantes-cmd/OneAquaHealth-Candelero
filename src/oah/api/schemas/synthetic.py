"""Models of the synthetic demo routes: the reliability campaign, the review queue and decisions, the risk demo."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from oah.api.schemas.common import Origin


class ReliabilityRequestParams(BaseModel):
    """Bounded parameters for the synthetic reliability demo endpoint.

    Bounds exist to keep a single request fast; they are not a substitute for real rate
    limiting, which is out of scope for this block and is a documented known gap.
    """

    seed: int = Field(..., ge=0, le=2_000_000_000)
    observer_count: int = Field(default=8, ge=2, le=30)
    specimens_per_site: int = Field(default=15, ge=1, le=200)
    annotators_per_specimen: int = Field(default=3, ge=2, le=10)


class ReviewDecisionRequest(BaseModel):
    """A reviewer's decision. Both fields land in the append-only audit trail, so they are bounded and limited to
    word characters, spaces and a few separators (no control characters, markup or newlines)."""

    final_label: str = Field(..., min_length=1, max_length=128, pattern=r"^[\w .\-]+$")
    # A pseudonymous handle, not an e-mail address or a name: the audit trail is append-only and cannot
    # honour an erasure request, so personal identifiers must never enter it.
    reviewer_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


class ReliabilityCampaignResponse(BaseModel):
    origin: Origin
    seed: int
    recommended_method: str
    recommendation_diagnostics: dict[str, Any]
    parameters: dict[str, int]
    majority_vote_accuracy: float
    dawid_skene_accuracy: float
    majority_vote_macro_f1: float
    dawid_skene_macro_f1: float
    dawid_skene_log_loss: float


class ReviewQueueItem(BaseModel):
    specimen_id: str
    prediction_set: list[str]
    probabilities: dict[str, float]
    status: str
    tag: str


class ReviewQueueResponse(BaseModel):
    origin: Origin
    count: int
    items: list[ReviewQueueItem]


class ReviewDecisionResponse(BaseModel):
    origin: Origin
    specimen_id: str
    status: str
    final_label: str | None
    reviewer_id: str | None
    decision_time: str | None


class RiskResponse(BaseModel):
    origin: Origin
    note: str
    source_site: str
    site_id: str
    risk: float
