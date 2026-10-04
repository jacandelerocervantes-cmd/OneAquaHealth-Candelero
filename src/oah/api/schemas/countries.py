"""Response models of ``GET /countries``: regime, limit sources and the per-source breakdown."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from oah.api.schemas.bathing import BathingSamplesStatus, BathingWaterStatus, CountryBathingWater
from oah.api.schemas.common import DataFreshnessModel, Origin, ParameterGroup, SiteSource
from oah.api.schemas.sites import WaterbaseStatus


CountryStatus = Literal["national-limits", "eu-values-only", "measurements-only", "no-evaluable-water-data"]


class DataRange(BaseModel):
    """First and last month (YYYY-MM) a source holds data for a country (null when it holds none)."""

    first: str | None = None
    last: str | None = None


class CountrySourceBreakdown(BaseModel):
    """The sites of one country that come from one source."""

    source: SiteSource
    total_sites: int
    evaluated_sites: int | None = None  # sandbox only
    skipped_sites: int | None = None  # sandbox only
    river_sites: int | None = None  # Waterbase only
    lake_sites: int | None = None
    sites_without_location: int | None = None
    first_year: int | None = None
    last_year: int | None = None
    attribution: str | None = None
    parameter_groups: list[ParameterGroup] | None = None  # Waterbase only: groups of the determinands held for the country
    data_range: DataRange | None = None  # first and last month with data in this source for the country (null when none)


class Country(BaseModel):
    code: str
    status: CountryStatus
    regime: str | None = None  # of the country's water-body sites; "mixed" when they differ; null when it has none
    has_national_limits: bool
    limit_sources: list[str]
    evaluated_sites: int
    skipped_sites: int
    skipped_non_water_sites: int
    total_sites: int  # all sources
    measurement_only_sites: int = 0  # Waterbase sites (annual measurements, no index)
    latest_year: int | None = None  # latest year of Waterbase data for the country
    sources: list[CountrySourceBreakdown] = Field(default_factory=list)
    # Groups of parameters present for the country: the Waterbase groups, plus water-chemistry when a sandbox site was evaluated.
    parameter_groups: list[ParameterGroup] = Field(default_factory=list)
    bathing_water: CountryBathingWater | None = None  # null when the store is not built or the file has no row for the country


class CountriesResponse(BaseModel):
    origin: Origin
    data_freshness: DataFreshnessModel
    interpretation_notice: str
    countries: list[Country]
    sites_without_country: int
    waterbase: WaterbaseStatus
    bathing_water: BathingWaterStatus
    bathing_samples: BathingSamplesStatus
