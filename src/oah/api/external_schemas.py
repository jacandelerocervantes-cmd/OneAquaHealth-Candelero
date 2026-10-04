"""Response models of the external-context routes (docs/external_context.md, docs/api_routes.md).

Every response says what the numbers ARE (``origin``, ``data_kind``), who to credit (``attribution``), whether the call
worked (``status``: ``ok``, ``no-data`` or ``external-unavailable`` with a ``reason``) and carries the fixed notices of
the requested language (``notices``). These are EXTERNAL, MODELLED or OPPORTUNISTIC context, never the site's own
measurements, and never evidence of causation.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

ExternalOrigin = Literal["external-open-meteo", "external-gbif"]
ExternalDataKind = Literal["modelled-reanalysis", "modelled-river-discharge", "opportunistic-occurrence-records"]
ExternalStatus = Literal["ok", "no-data", "external-unavailable"]
ExternalProvider = Literal["open-meteo-archive", "open-meteo-flood", "gbif"]
ExternalReason = Literal[
    "disabled", "budget-exhausted", "cooling-down", "timeout", "rate-limited", "network-error", "http-error",
    "bad-response", "response-too-large", "redirect-refused", "blocked-target",
]


class ExternalSite(BaseModel):
    """The site the context is about, with the coordinates at the precision actually sent (never more precise)."""

    id: str
    name: str
    kind: Literal["waterbase-site", "sandbox-site", "bathing-water"]
    source: str
    country: str | None = None
    water_category: str | None = None
    latitude: float
    longitude: float
    coordinate_decimals: int


class ExternalFrame(BaseModel):
    """What every external response shares."""

    status: ExternalStatus
    reason: ExternalReason | None = None  # set when status is external-unavailable
    provider: ExternalProvider
    origin: ExternalOrigin
    data_kind: ExternalDataKind
    attribution: str  # display this next to the data (the link text Open-Meteo requires is included)
    attribution_url: str | None = None
    attribution_verified: bool  # false: the credit wording could not be verified at the provider (docs/external_context.md)
    licence: str
    data_note: str
    flags: list[str]
    cached: bool
    site: ExternalSite
    language: str
    notices: dict[str, str]  # fixed strings in the requested language, never model output


class ExternalPeriod(BaseModel):
    date_from: str
    date_to: str


class ExternalGridCell(BaseModel):
    requested_latitude: float
    requested_longitude: float
    grid_latitude: float | None = None  # the cell the provider used; a few kilometres from the site
    grid_longitude: float | None = None
    distance_km: float | None = None
    resolution_note: str


class WeatherLimits(BaseModel):
    first_day: str
    last_day_requestable: str
    era5_delay_days: int
    latest_day_expected_final: str
    model: str
    day_boundary: str


class WeatherMonth(BaseModel):
    month: str  # YYYY-MM
    days_in_window: int
    precipitation_sum_mm: float | None = None  # sum of the daily values that exist
    precipitation_n_days: int
    precipitation_coverage: float
    temperature_mean_c: float | None = None  # mean of the daily means that exist
    temperature_n_days: int
    temperature_coverage: float
    flags: list[str]


class WeatherResponse(ExternalFrame):
    """MODELLED ERA5 reanalysis for a grid cell, aggregated to months. Not measurements at the site."""

    dataset: str
    period: ExternalPeriod
    data_limits: WeatherLimits
    grid: ExternalGridCell | None = None
    months: list[WeatherMonth]
    n_days_expected: int
    n_days_with_data: int


class DischargeLimits(BaseModel):
    first_day: str
    documented_history_end: str
    documented_history_note: str
    last_day_requestable: str
    model: str
    day_boundary: str


class ExternalDataRange(BaseModel):
    first_day: str
    last_day: str


class DischargeMonth(BaseModel):
    month: str
    days_in_window: int
    river_discharge_mean_m3s: float | None = None
    n_days: int
    coverage: float
    flags: list[str]


class DischargeResponse(ExternalFrame):
    """MODELLED GloFAS river discharge of the nearest river cell, monthly means. Not a gauge reading."""

    dataset: str
    period: ExternalPeriod
    data_limits: DischargeLimits
    site_water_category: str | None = None
    grid: ExternalGridCell | None = None
    data_range: ExternalDataRange | None = None  # first and last day with a value in the answer
    months: list[DischargeMonth]
    n_days_expected: int
    n_days_with_data: int


class SpeciesSearchArea(BaseModel):
    shape: Literal["square"]
    half_side_km: float
    centre_latitude: float
    centre_longitude: float
    bounds: dict[str, float]


class SpeciesFilters(BaseModel):
    group: str | None = None
    groups_searched: list[str]
    date_from: str | None = None
    date_to: str | None = None


class SpeciesGroupCount(BaseModel):
    group: str
    name: str
    common_name: str
    rank: Literal["ORDER", "FAMILY"]
    count: int  # GBIF's own facet count over the same search
    caveat: str


class SpeciesRecord(BaseModel):
    """One occurrence record with the licence and attribution data GBIF gives for it."""

    gbif_id: str
    scientific_name: str
    taxon_rank: str | None = None
    group: str | None = None
    basis_of_record: str | None = None
    event_date: str | None = None
    year: int | None = None
    latitude: float
    longitude: float
    coordinate_uncertainty_m: float | None = None
    distance_km: float
    licence: str  # CC0-1.0, CC-BY-4.0, CC-BY-NC-4.0 or other-or-unspecified
    licence_text: str | None = None  # the raw licence value when it is not one of the three
    non_commercial_only: bool
    dataset_key: str | None = None
    dataset_name: str | None = None
    publishing_organization_key: str | None = None
    institution_code: str | None = None
    rights_holder: str | None = None  # always null: GBIF's rightsHolder can be an individual's name, so it is withheld
    record_url: str | None = None  # only an https URL on gbif.org; any other link is dropped
    coordinate_issues: list[str]
    citation: str | None = None  # the dataset citation text as GBIF provides it, when it could be fetched


class SpeciesDataset(BaseModel):
    dataset_key: str
    title: str | None = None
    citation: str | None = None
    licence: str


class SpeciesTaxaFile(BaseModel):
    discovered_on: str
    selection_note: str


class SpeciesResponse(ExternalFrame):
    """OPPORTUNISTIC GBIF occurrence records in a fixed square around the site. Not monitoring."""

    search: SpeciesSearchArea
    filters: SpeciesFilters
    limit: int
    total_records: int  # GBIF's count for the whole search
    returned: int
    n_records_skipped: int = 0
    group_counts: list[SpeciesGroupCount]
    records: list[SpeciesRecord]
    datasets: list[SpeciesDataset]
    licence_summary: dict[str, int]
    taxa_file: SpeciesTaxaFile


class ExternalProviderStatus(BaseModel):
    provider: ExternalProvider
    name: str
    origin: ExternalOrigin
    data_kind: ExternalDataKind
    enabled: bool
    cooling_down: bool
    attribution: str
    attribution_url: str | None = None
    attribution_verified: bool
    licence: str
    licence_note: str
    limits: str
    data_note: str
    budget_unit: Literal["estimated-call-units", "requests"]
    budget: dict[str, float]


class SpeciesGroupInfo(BaseModel):
    id: str
    name: str
    common_name: str
    rank: Literal["ORDER", "FAMILY"]
    usage_key: int
    match_confidence: int
    caveat: str


class ExternalStatusResponse(BaseModel):
    """The providers, their switches, attribution, licence, limits and the budget left. No secret."""

    enabled: bool
    providers: list[ExternalProviderStatus]
    contact_url_configured: bool
    coordinate_decimals: int
    max_period_days: int
    species_search_half_side_km: float
    species_default_limit: int
    species_max_limit: int
    species_groups: list[SpeciesGroupInfo]
    species_group_aliases: dict[str, list[str]]
    taxa_discovered_on: str
    language: str
    notices: dict[str, str]
