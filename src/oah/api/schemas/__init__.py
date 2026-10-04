"""Pydantic request/response models for the API layer.

Every response model that can describe synthetic or real-sandbox data carries an explicit
`origin` field; callers must never have to guess which kind of data they received.

Every protected route declares a response model, so the OpenAPI document is a real contract a client can generate types
from. Shapes that carry evolving nested detail (the QC report, a per-location index, the evidence sent to the model) type
their stable core and allow extra keys; the closed shapes are typed completely.

The models live in one module per domain (``common``, ``sites``, ``bathing``, ``countries``, ``catalog``, ``language``, ``explain``,
``chat``, ``exports``, ``synthetic``) and are all re-exported here, so ``from oah.api.schemas import SitesResponse`` keeps
working. The period-comparison, samples and external-context models stay in ``oah.api.change_schemas``,
``oah.api.samples_schemas`` and ``oah.api.external_schemas``.
"""
from __future__ import annotations

from oah.api.schemas.common import (
    ChatOrigin,
    DataFreshnessModel,
    ErrorResponse,
    FreshnessStatus,
    HealthResponse,
    Origin,
    ParameterGroup,
    SiteSource,
    UiStatus,
)
from oah.api.schemas.sites import (
    IndexResponse,
    MeasurementRecord,
    MeasurementResolution,
    MeasurementStatus,
    QcReportResponse,
    Site,
    SiteKind,
    SiteMeasurementsResponse,
    SitesResponse,
    StoreState,
    WaterbaseSiteInfo,
    WaterbaseStatus,
)
from oah.api.schemas.bathing import (
    BathingSamplesLink,
    BathingSamplesStatus,
    BathingWaterEntry,
    BathingWaterHistoryResponse,
    BathingWaterStatus,
    BathingWatersResponse,
    CountryBathingSamples,
    CountryBathingWater,
    SeasonClassification,
)
from oah.api.schemas.countries import (
    CountriesResponse,
    Country,
    CountrySourceBreakdown,
    CountryStatus,
    DataRange,
)
from oah.api.schemas.catalog import (
    CatalogExternal,
    CatalogFamily,
    CatalogFamilyId,
    CatalogIndex,
    CatalogIndexId,
    CatalogOriginKind,
    CatalogReasonCode,
    CatalogResponse,
    CatalogStores,
)
from oah.api.schemas.language import (
    LanguageEntry,
    LanguageFields,
    LanguagesResponse,
    TranslationStatus,
)
from oah.api.schemas.explain import (
    ExplanationResponse,
)
from oah.api.schemas.chat import (
    ChatCitation,
    ChatEvidenceItem,
    ChatEvidenceScope,
    ChatEvidenceSummary,
    ChatEvidenceValue,
    ChatIndex,
    ChatRequest,
    ChatResponse,
    ChatStatus,
    ChatStep,
    ChatTurn,
    ChatUsage,
)
from oah.api.schemas.exports import (
    FindingsExportResponse,
    IndicatorsExportResponse,
)
from oah.api.schemas.synthetic import (
    ReliabilityCampaignResponse,
    ReliabilityRequestParams,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueueItem,
    ReviewQueueResponse,
    RiskResponse,
)

__all__ = [
    "BathingSamplesLink",
    "BathingSamplesStatus",
    "BathingWaterEntry",
    "BathingWaterHistoryResponse",
    "BathingWaterStatus",
    "BathingWatersResponse",
    "CatalogExternal",
    "CatalogFamily",
    "CatalogFamilyId",
    "CatalogIndex",
    "CatalogIndexId",
    "CatalogOriginKind",
    "CatalogReasonCode",
    "CatalogResponse",
    "CatalogStores",
    "ChatCitation",
    "ChatEvidenceItem",
    "ChatEvidenceScope",
    "ChatEvidenceSummary",
    "ChatEvidenceValue",
    "ChatIndex",
    "ChatOrigin",
    "ChatRequest",
    "ChatResponse",
    "ChatStatus",
    "ChatStep",
    "ChatTurn",
    "ChatUsage",
    "CountriesResponse",
    "Country",
    "CountryBathingSamples",
    "CountryBathingWater",
    "CountrySourceBreakdown",
    "CountryStatus",
    "DataFreshnessModel",
    "DataRange",
    "ErrorResponse",
    "ExplanationResponse",
    "FindingsExportResponse",
    "FreshnessStatus",
    "HealthResponse",
    "IndexResponse",
    "IndicatorsExportResponse",
    "LanguageEntry",
    "LanguageFields",
    "LanguagesResponse",
    "MeasurementRecord",
    "MeasurementResolution",
    "MeasurementStatus",
    "Origin",
    "ParameterGroup",
    "QcReportResponse",
    "ReliabilityCampaignResponse",
    "ReliabilityRequestParams",
    "ReviewDecisionRequest",
    "ReviewDecisionResponse",
    "ReviewQueueItem",
    "ReviewQueueResponse",
    "RiskResponse",
    "SeasonClassification",
    "Site",
    "SiteKind",
    "SiteMeasurementsResponse",
    "SiteSource",
    "SitesResponse",
    "StoreState",
    "TranslationStatus",
    "UiStatus",
    "WaterbaseSiteInfo",
    "WaterbaseStatus",
]
