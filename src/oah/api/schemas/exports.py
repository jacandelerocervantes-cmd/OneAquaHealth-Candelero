"""Response models of the FHIR export routes."""
from __future__ import annotations

from pydantic import BaseModel

from oah.api.schemas.common import Origin


class FindingsExportResponse(BaseModel):
    origin: Origin
    observations_processed: int
    detected_issue_count: int
    bundle_id: str
    written_to: str


class IndicatorsExportResponse(BaseModel):
    origin: Origin
    interpretation_notice: str
    observations_exported: int
    locations_without_observation: int
    bundle_id: str
    written_to: str
