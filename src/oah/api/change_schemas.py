"""Response models of the period-comparison and season-comparison routes (docs/period_change.md, docs/api_routes.md).

Every response carries its origin, source, attribution and data freshness, the interpretation notice and, for the
period comparison, the approximation notice (fixed strings, localised when ``language`` is given). Nothing here is a
compliance assessment: a period mean compared with a limit is a screening aid.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

from oah.api.schemas import (
    BathingWaterStatus,
    DataFreshnessModel,
    MeasurementStatus,
    Origin,
    ParameterGroup,
    SiteSource,
    WaterbaseStatus,
)

ChangeStatus = Literal["ok", "insufficient-data"]
Crossing = Literal["within-to-exceeds", "exceeds-to-within", "none"]
LimitType = Literal["maximum", "minimum"]
Resolution = Literal["monthly", "annual-only"]
NUnit = Literal["samples", "aggregate-records"]


class ChangeAssessment(BaseModel):
    """The limit that applies to a period mean (the project's existing limit machinery) and the comparison with it."""

    limit: float | None = None
    limit_unit: str | None = None
    limit_type: LimitType | None = None
    limit_range: list[float] | None = None
    limit_basis: str | None = None
    limit_regime: str
    status: MeasurementStatus
    scored_value: float | None = None
    flags: list[str]


class ChangePeriod(BaseModel):
    """Statistics of one period at one site. ``mean`` is sum / n over the quantified values; below-LOQ values are not in it."""

    start: str
    end: str
    months_in_period: int
    n_samples: int
    n_unit: NUnit
    n_months_with_data: int
    mean: float | None = None
    min: float | None = None
    max: float | None = None
    n_below_loq: int
    below_loq_share: float | None = None
    n_lower_reliability: int
    n_records_excluded_crossing_period_edge: int
    meets_minimum_samples: bool
    flags: list[str]
    assessment: ChangeAssessment


class ChangePair(BaseModel):
    a: ChangePeriod
    b: ChangePeriod


class ChangeValues(BaseModel):
    """``absolute`` is mean_B minus mean_A; ``relative_percent`` is null (with a note) when mean_A is zero or missing."""

    absolute: float | None = None
    relative_percent: float | None = None
    relative_percent_note: str | None = None
    direction: Literal["increased", "decreased", "no-change"] | None = None


class ChangeDataRange(BaseModel):
    """First and last month (YYYY-MM) the scope holds for this parameter, over all time (null when it holds none)."""

    first: str | None = None
    last: str | None = None


class ChangeSiteScope(BaseModel):
    type: Literal["site"] = "site"
    id: str
    name: str
    country: str | None = None
    water_category: Literal["river", "lake"] | None = None
    regime: str | None = None


class SiteChangeResponse(BaseModel):
    """How one parameter changed at one site between two periods. A screening aid, not a compliance assessment."""

    origin: Origin
    source: SiteSource
    data_freshness: DataFreshnessModel
    attribution: str | None = None
    language: str
    interpretation_notice: str
    approximation_notice: str
    scope: ChangeSiteScope
    parameter: str
    unit: str
    group: ParameterGroup
    resolution: Resolution
    status: ChangeStatus
    min_samples_per_period: int
    periods: ChangePair
    change: ChangeValues
    crossed_limit: Crossing | None = None  # null when either period is not judged against a limit or has too few samples
    data_range: ChangeDataRange
    flags: list[str]
    rows_excluded_unit: int | None = None  # Waterbase rows left out because their unit label could not be used
    record_notes: dict[str, Any] | None = None  # sandbox: records left out and the statistics used


class ChangeRiverLimit(BaseModel):
    limit: float | None = None
    limit_unit: str | None = None
    limit_type: LimitType | None = None
    limit_range: list[float] | None = None
    limit_basis: str | None = None
    limit_regime: str
    flags: list[str]


class ChangeRiverLimits(BaseModel):
    a: ChangeRiverLimit
    b: ChangeRiverLimit


class CountryChangePeriod(BaseModel):
    """One period over the PAIRED sites of a country."""

    start: str
    end: str
    months_in_period: int
    n_sites: int
    n_samples: int
    n_unit: NUnit
    n_months_with_data: int
    mean_of_site_means: float | None = None
    n_below_loq: int
    below_loq_share: float | None = None
    river_sites_judged: int
    river_sites_over_limit: int
    flags: list[str]


class CountryChangePair(BaseModel):
    a: CountryChangePeriod
    b: CountryChangePeriod


class CountrySourceChange(BaseModel):
    """The comparison for one source of one country, over paired sites only. Sources are never combined."""

    origin: Origin
    source: SiteSource
    data_freshness: DataFreshnessModel
    attribution: str | None = None
    parameter: str
    unit: str
    group: ParameterGroup
    resolution: Resolution
    status: ChangeStatus
    min_samples_per_period: int
    few_sites_threshold: int
    n_sites_considered: int
    n_sites_paired: int
    n_sites_excluded: int
    exclusion_reasons: dict[str, int]
    periods: CountryChangePair
    change_of_site_means: ChangeValues
    median_site_relative_change_percent: float | None = None
    n_sites_relative_change_undefined: int
    sites_increased: int
    sites_decreased: int
    sites_unchanged: int
    river_limit: ChangeRiverLimits
    data_range: ChangeDataRange
    flags: list[str]
    rows_excluded_unit: int | None = None
    truncated: bool | None = None
    record_notes: dict[str, Any] | None = None


class ChangeCountryScope(BaseModel):
    type: Literal["country"] = "country"
    code: str


class CountryChangeResponse(BaseModel):
    """How one parameter changed across the sites of one country between two periods, one result per source."""

    origin: Origin
    data_freshness: DataFreshnessModel
    language: str
    interpretation_notice: str
    approximation_notice: str
    scope: ChangeCountryScope
    parameter: str
    results: list[CountrySourceChange]
    waterbase: WaterbaseStatus
    note: str | None = None  # said when no source holds the parameter for the country


class SeasonTotals(BaseModel):
    season: int
    bathing_waters: int
    classes: dict[str, int]  # the file's own quality strings -> bathing waters in that season


class SeasonTransition(BaseModel):
    from_class: str
    to_class: str
    count: int


class SeasonNotComparablePair(BaseModel):
    quality_a: str
    quality_b: str
    count: int


class SeasonNotComparable(BaseModel):
    count: int
    pairs: list[SeasonNotComparablePair]


class BathingChangeResponse(BaseModel):
    """Counts of classification transitions between two seasons, in the README's order of four classes. No concentration."""

    origin: Literal["real-eea-bathing-water"]
    data_freshness: DataFreshnessModel
    attribution: str
    language: str
    notice: str
    comparison_notice: str
    bathing_water: BathingWaterStatus
    country: str
    type: str | None = None
    season_a: int
    season_b: int
    order: list[str]
    data_range: dict[str, int | None]
    totals: dict[str, SeasonTotals]
    paired_bathing_waters: int
    comparable: int
    moved_up: int
    moved_down: int
    unchanged: int
    transitions: list[SeasonTransition]
    not_comparable: SeasonNotComparable
    only_in_season_a: int
    only_in_season_b: int
    flags: list[str]
