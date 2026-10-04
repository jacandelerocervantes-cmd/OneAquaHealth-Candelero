"""Response models of ``GET /catalog``: the sidebar families and indices of one country, with what applies and why not."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from oah.api.schemas.bathing import BathingSamplesStatus, BathingWaterStatus
from oah.api.schemas.chat import ChatIndex
from oah.api.schemas.common import DataFreshnessModel, Origin
from oah.api.schemas.sites import WaterbaseStatus

CatalogFamilyId = Literal["water", "microbiology", "context", "data", "synthetic-labs"]
CatalogIndexId = Literal[
    "water-quality", "water-parameters", "solids-turbidity", "organic-matter", "bathing-classes", "bathing-samples",
    "weather", "river-discharge", "species-nearby", "data-quality", "citizen-science", "review-queue", "river-risk",
]
CatalogOriginKind = Literal["real", "external", "synthetic"]
CatalogReasonCode = Literal[
    "no-data-for-country", "data-not-loaded", "provider-off", "no-located-site", "no-located-river-site"
]


class CatalogIndex(BaseModel):
    """One index of the sidebar. ``applies`` false means the service holds nothing for the country (the web app hides it)."""

    id: CatalogIndexId
    family_id: CatalogFamilyId
    family_title: str
    title: str
    origin_kind: CatalogOriginKind
    origins: list[str]  # the origin labels of the data behind it (``real-sandbox``, ``external-gbif``, ``synthetic``, ...)
    applies: bool
    reason_code: CatalogReasonCode | None = None  # set when ``applies`` is false
    reason: str | None = None  # the same reason as a fixed string in ``language``
    routes: list[str]  # the route paths behind the index (docs/api_routes.md)
    chat_index: ChatIndex | None = None  # the ``index`` of POST /chat that fits it, null when the chat has none


class CatalogFamily(BaseModel):
    id: CatalogFamilyId
    title: str
    indices: list[CatalogIndex]  # ALL the indices of the family, in a stable order


class CatalogExternal(BaseModel):
    """Which external providers are switched on (the master switch and each provider's own)."""

    enabled: bool
    weather: bool
    discharge: bool
    species: bool


class CatalogStores(BaseModel):
    """The state of every source the applicability rules read, so a client can show a notice for a store that is not built."""

    sandbox: Literal["available", "unavailable"]
    waterbase: WaterbaseStatus
    bathing_water: BathingWaterStatus
    bathing_samples: BathingSamplesStatus
    external: CatalogExternal


class CatalogResponse(BaseModel):
    origin: Origin
    data_freshness: DataFreshnessModel
    interpretation_notice: str
    language: str
    country: str
    country_name: str | None = None  # only where the project already carries a name for the code
    families: list[CatalogFamily]
    applicable_count: int  # for tests and tools; the web app does not show numbers
    stores: CatalogStores
