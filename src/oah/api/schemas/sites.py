"""Response models of the site-level routes: ``/sites``, ``/qc/report``, ``/sites/{id}/measurements``, ``/indices/{id}``."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from oah.api.schemas.common import DataFreshnessModel, Origin, ParameterGroup, SiteSource, UiStatus


SiteKind = Literal["water-body", "air-quality-station", "city", "other"]


class Site(BaseModel):
    """One site on the map: a sandbox Location joined to its CCME result when computable, or a Waterbase site
    (``source`` ``real-eea-waterbase``, status ``measurements-only``, coordinates null when the file has none)."""

    id: str
    name: str
    latitude: float | None  # null only for a Waterbase site without coordinates (location_status "no-location")
    longitude: float | None
    kind: SiteKind
    status: Literal["evaluated", "skipped", "measurements-only"]
    ccme_wqi: float | None = None
    ccme_class: str | None = None
    ui_status: UiStatus
    limit_regime: str | None = None
    limit_country: str | None = None
    confidence: str | None = None
    veto_triggered: bool = False
    eclipsed: bool = False
    reason: str | None = None
    origin: Origin = "real-sandbox"
    source: SiteSource = "real-sandbox"
    water_category: Literal["river", "lake"] | None = None
    location_status: Literal["located", "no-location"] = "located"
    water_body_name: str | None = None
    first_year: int | None = None
    last_year: int | None = None


StoreState = Literal["ready", "not-built", "unreadable", "rebuild-required"]


class WaterbaseStatus(BaseModel):
    """State of the optional EEA Waterbase store; a store that is not built is a clear status, never an error."""

    state: StoreState
    detail: str
    edition: str | None = None
    attribution: str | None = None
    build_date_utc: str | None = None


class SitesResponse(BaseModel):
    origin: Origin
    data_freshness: DataFreshnessModel
    interpretation_notice: str
    sites: list[Site]
    sources: list[SiteSource]  # the sources of the returned sites
    total_matching: int  # sites matching the filters, across both sources
    returned: int
    limit: int
    offset: int
    truncated: bool
    waterbase: WaterbaseStatus


class QcReportResponse(BaseModel, extra="allow"):
    origin: Origin
    generated_at_utc: str
    source: str
    total_observations: int
    findings: dict[str, int]
    # Additive: records left out before counting (demo, simulated and third-party records), by reason.
    excluded_observations: dict[str, int] = Field(default_factory=dict)
    excluded_observations_total: int = 0
    data_freshness: DataFreshnessModel


MeasurementStatus = Literal["within-limit", "exceeds-limit", "indeterminate", "not-scored", "excluded"]


class MeasurementRecord(BaseModel):
    """One Observation of one parameter at one site, with the limit it was judged against."""

    observation_id: str | None = None
    parameter: str
    value: float | None = None  # the value used, in `unit` (converted from original_unit)
    statistic: str | None = None  # median, then average; "value" for a plain Quantity
    comparator: str | None = None
    min: float | None = None
    max: float | None = None
    unit: str
    original_unit: str | None = None
    period_start: str | None = None
    period_end: str | None = None
    scored_value: float | None = None  # the number compared with the limit (the oxygen saturation deviation, in %, for Italy)
    limit: float | None = None
    limit_unit: str | None = None
    limit_type: Literal["maximum", "minimum"] | None = None
    limit_range: list[float] | None = None
    limit_basis: str | None = None
    limit_regime: str
    limit_country: str | None = None
    status: MeasurementStatus
    data_quality_flags: list[str]
    origin: Origin
    # Waterbase annual aggregates only (null for sandbox records):
    source: SiteSource = "real-sandbox"
    year: int | None = None
    n: int | None = None  # quantified samples in the mean
    n_below_loq: int | None = None  # samples below the limit of quantification (not in the mean)
    n_lower_reliability: int | None = None  # samples flagged U or V by Waterbase (in the mean)
    determinand_code: str | None = None
    matrix: str | None = None
    month: int | None = None  # calendar month (1 to 12) of a monthly Waterbase record (resolution=monthly), else null
    # Parameter group (``oah.waterbase.mapping.GROUPS``): ``water-chemistry`` for the closed parameter names of the
    # sandbox and the Waterbase chemistry, ``solids-turbidity`` and ``organic-matter`` for the measurement-only ones.
    group: ParameterGroup | None = None


class WaterbaseSiteInfo(BaseModel):
    id: str
    name: str
    country: str
    water_category: Literal["river", "lake"]
    water_body_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_status: Literal["located", "no-location"]
    confidentiality: str | None = None
    first_year: int
    last_year: int


MeasurementResolution = Literal["annual", "monthly", "period-summary"]


class SiteMeasurementsResponse(BaseModel):
    origin: Origin
    data_freshness: DataFreshnessModel
    interpretation_notice: str
    location_id: str
    parameter: str | None = None
    group: ParameterGroup | None = None  # the group filter, echoed
    # What one record is: a Waterbase annual or monthly aggregate, or a sandbox period-summary (its own period).
    resolution: MeasurementResolution = "annual"
    date_from: str | None = None
    date_to: str | None = None
    limit: int
    total_matching: int
    returned: int
    truncated: bool
    records: list[MeasurementRecord]
    source: SiteSource = "real-sandbox"
    attribution: str | None = None  # credit line of the Waterbase licence (set for Waterbase sites)
    index_status: str | None = None  # "measurements-only" for Waterbase sites: no CCME index
    site: WaterbaseSiteInfo | None = None


class IndexResponse(BaseModel, extra="allow"):
    origin: Origin
    status: Literal["evaluated", "skipped"]
    location_ref: str
    data_quality: dict[str, Any]
    objective_limits_source: str
    data_freshness: DataFreshnessModel
    interpretation_notice: str
