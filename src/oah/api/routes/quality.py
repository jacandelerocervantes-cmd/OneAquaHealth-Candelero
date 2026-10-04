"""QC findings over the official sandbox Observations and the FHIR exports built from the same records."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from oah.api import deps
from oah.api.deps import require_write_routes
from oah.api.payloads import _official_observations
from oah.api.schemas import ErrorResponse, FindingsExportResponse, IndicatorsExportResponse, QcReportResponse
from oah.api.services import export_findings_bundle, export_indicators_bundle, get_data_freshness
from oah.config import sandbox_url
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox
from oah.indices.regimes import INTERPRETATION_NOTICE
from oah.ingest.official import split_official
from oah.qc.report import build_report

router = APIRouter()


@router.get("/qc/report", response_model=QcReportResponse)
def qc_report() -> dict[str, Any]:
    """QC findings over the official real sandbox Observations; demo, simulated and third-party records are
    left out and counted by reason in ``excluded_observations``."""
    official, excluded = split_official(deps.get_cached_observations())
    return {
        **build_report(official, default_origin="real-sandbox"),
        "excluded_observations": excluded,
        "excluded_observations_total": sum(excluded.values()),
        "data_freshness": get_data_freshness(),
    }


@router.post(
    "/fhir/export",
    response_model=FindingsExportResponse,
    responses={404: {"model": ErrorResponse, "description": "Write routes are switched off (OAH_ENABLE_WRITE_ROUTES)."}},
    dependencies=[Depends(require_write_routes)],
)
def fhir_export() -> dict[str, Any]:
    """Export real-sandbox QC findings as a deterministic FHIR Bundle with Provenance.

    Writes a file, so it answers 404 unless ``OAH_ENABLE_WRITE_ROUTES`` is on (default off)."""
    observations = _official_observations()
    return export_findings_bundle(observations, sandbox_url(), deps.export_path)


@router.post(
    "/fhir/export/indicators",
    response_model=IndicatorsExportResponse,
    responses={404: {"model": ErrorResponse, "description": "Write routes are switched off (OAH_ENABLE_WRITE_ROUTES)."}},
    dependencies=[Depends(require_write_routes)],
)
def fhir_export_indicators() -> dict[str, Any]:
    """Export real-sandbox CCME WQI results as OAH-indicators Observations with Provenance.

    Writes a file, so it answers 404 unless ``OAH_ENABLE_WRITE_ROUTES`` is on (default off)."""
    result = apply_ccme_wqi_to_sandbox(_official_observations(), deps.get_cached_locations())
    return {**export_indicators_bundle(result, sandbox_url(), deps.export_path), "interpretation_notice": INTERPRETATION_NOTICE}
