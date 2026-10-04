"""Shared building blocks of the response models: the closed origin sets, the error and health bodies and the
freshness block every real-data response carries."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


# ``real-eea-waterbase`` is the EEA Waterbase slice (docs/waterbase_store.md); ``real-eea-bathing-water`` is the EEA
# bathing-water CLASSIFICATION (docs/bathing_water_store.md, never a concentration); ``real-mixed`` labels a list or an
# answer that holds more than one real source (every entry then carries its own ``origin``). Sources are never mixed silently.
# ``real-eea-bathing-samples`` is the EEA bathing-water SAMPLES store (docs/bathing_samples_store.md): individual E. coli and
# intestinal enterococci results with no threshold; a different dataset from the classification, hence its own label.
Origin = Literal[
    "real-sandbox", "real-eea-waterbase", "real-eea-bathing-water", "real-eea-bathing-samples", "real-mixed", "synthetic"
]
# ``external-open-meteo`` and ``external-gbif`` label EXTERNAL context (docs/external_context.md): MODELLED weather and river
# discharge, and OPPORTUNISTIC species records. They are part of ``ChatOrigin`` only: a chat answer whose tool results were all
# external carries one of them, any mix with another source is ``real-mixed``. The external routes have their own closed
# ``ExternalOrigin`` (``oah.api.external_schemas``); every other response keeps the closed ``Origin`` above.
ChatOrigin = Literal[
    "real-sandbox", "real-eea-waterbase", "real-eea-bathing-water", "real-eea-bathing-samples", "external-open-meteo",
    "external-gbif", "real-mixed", "synthetic"
]
SiteSource = Literal["real-sandbox", "real-eea-waterbase"]
# Parameter groups of the Waterbase measurements (oah.waterbase.mapping.GROUPS; a test keeps the two in step).
ParameterGroup = Literal["water-chemistry", "solids-turbidity", "organic-matter"]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ErrorResponse(BaseModel):
    detail: str


FreshnessStatus = Literal["live", "snapshot", "snapshot-stale", "unknown"]
UiStatus = Literal["good", "moderate", "poor", "unavailable"]


class DataFreshnessModel(BaseModel):
    """Where real-sandbox data came from. A stale snapshot is never reported as live."""

    status: FreshnessStatus
    as_of: str | None = None
    age_seconds: float | None = None
