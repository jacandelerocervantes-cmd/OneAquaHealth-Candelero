"""Response models of the bathing-water SAMPLES routes (docs/bathing_samples_store.md, docs/api_routes.md).

Every response carries its origin (``real-eea-bathing-samples``), attribution, data freshness and the fixed notices in the
requested language. The values are individual sample results in cfu/100ml: no threshold, limit or classification rule is
applied, so no field says a value is good, bad, over or under anything.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from oah.api.change_schemas import ChangeDataRange, ChangeStatus, ChangeValues
from oah.api.schemas import BathingSamplesStatus, DataFreshnessModel

SampleKind = Literal["quantified", "confirmed-high", "detection-limit", "missing", "unknown-status", "invalid"]
SamplesOrigin = Literal["real-eea-bathing-samples"]
IndicatorName = Literal["escherichia_coli", "intestinal_enterococci"]


class SampleIndicator(BaseModel):
    """One indicator of one sample. ``value`` is a concentration only for the kinds quantified and confirmed-high."""

    value: int | None = None  # cfu/100ml; null for a detection-limit, missing or unrecognised value
    reported_value: int | None = None  # the number as reported (a limit of detection for kind detection-limit); null when missing
    status: str | None = None  # the EEA status as written (confirmedValue, limitOfDetectionValue, missingValue), null when none
    kind: SampleKind


class SampleEntry(BaseModel):
    uid: int  # the EEA record identifier
    sample_date: str  # YYYY-MM-DD
    season: int
    sample_status: str | None = None  # as written: preSeasonSample, shortTermPollutionSample, ... null for a routine sample
    observation_status: str | None = None  # the EEA record-reliability code as written (A, I, O, U); not interpreted here
    has_remarks: bool  # the source holds a remark for the sample; the text is not served
    escherichia_coli: SampleIndicator
    intestinal_enterococci: SampleIndicator


class IndicatorSummary(BaseModel):
    """Counts by kind and statistics over the QUANTIFIED values (quantified and confirmed-high) of ALL matching samples."""

    n_samples_in_range: int
    n_quantified: int
    n_confirmed_high: int  # included in n_quantified
    n_detection_limit: int  # flagged limit of detection: counted apart, not in min, max, mean or median
    n_missing: int
    n_unrecognised: int
    min: int | None = None
    max: int | None = None
    mean: float | None = None  # arithmetic mean, sum / n_quantified
    median: float | None = None  # exact: the middle value, or the mean of the two middle values


class SamplesSummary(BaseModel):
    escherichia_coli: IndicatorSummary | None = None
    intestinal_enterococci: IndicatorSummary | None = None


class SamplesBathingWater(BaseModel):
    id: str
    country: str
    name: str
    type: str | None = None


class SamplesFilters(BaseModel):
    date_from: str | None = None
    date_to: str | None = None
    season: int | None = None
    order: Literal["asc", "desc"]


class SamplesDataRange(BaseModel):
    first_sample_date: str
    last_sample_date: str
    first_season: int
    last_season: int


class BathingSamplesResponse(BaseModel):
    """Individual E. coli and intestinal enterococci results of one bathing water. A measurement, not a classification."""

    origin: SamplesOrigin
    data_freshness: DataFreshnessModel
    attribution: str
    language: str
    notice: str
    no_threshold_notice: str
    flagged_values_note: str
    unit: str
    unit_statement: str
    bathing_samples: BathingSamplesStatus
    bathing_water: SamplesBathingWater
    filters: SamplesFilters
    data_range: SamplesDataRange | None = None  # all-time range of this bathing water (null when it has no sample)
    limit: int
    total_matching: int
    returned: int
    truncated: bool
    samples: list[SampleEntry]
    summary: SamplesSummary
    flags: list[str]


# --- period comparison ------------------------------------------------------------------------------------------------


class SamplesPeriod(BaseModel):
    """One period at one bathing water. Statistics are over the quantified values only."""

    start: str
    end: str
    months_in_period: int
    n_samples: int  # quantified values
    n_months_with_data: int
    mean: float | None = None
    median: float | None = None
    min: float | None = None
    max: float | None = None
    n_detection_limit: int
    n_missing: int
    n_unrecognised: int
    n_confirmed_high: int
    meets_minimum_samples: bool
    flags: list[str]


class SamplesPeriodPair(BaseModel):
    a: SamplesPeriod
    b: SamplesPeriod


class SamplesIndicatorChange(BaseModel):
    indicator: IndicatorName
    label: str
    unit: str
    status: ChangeStatus
    min_samples_per_period: int
    periods: SamplesPeriodPair
    change: ChangeValues  # of the mean: mean_B minus mean_A
    change_of_median: ChangeValues  # of the median: median_B minus median_A
    data_range: ChangeDataRange  # first and last month with a quantified value, over all time (null when none)
    flags: list[str]


class SamplesIndicatorsChange(BaseModel):
    escherichia_coli: SamplesIndicatorChange
    intestinal_enterococci: SamplesIndicatorChange


class SamplesChangeScope(BaseModel):
    type: Literal["bathing-water", "country"]
    id: str | None = None  # the bathing water identifier (scope bathing-water)
    code: str | None = None  # the country code (scope country)
    name: str | None = None
    country: str | None = None


class BathingSamplesChangeResponse(BaseModel):
    """How the individual samples of one bathing water changed between two periods. No significance claim, no limit."""

    origin: SamplesOrigin
    data_freshness: DataFreshnessModel
    attribution: str
    language: str
    notice: str
    no_threshold_notice: str
    flagged_values_note: str
    change_notice: str
    unit: str
    bathing_samples: BathingSamplesStatus
    scope: SamplesChangeScope
    indicators: SamplesIndicatorsChange


class CountrySamplesPeriod(BaseModel):
    """One period over the PAIRED bathing waters of a country."""

    start: str
    end: str
    months_in_period: int
    n_sites: int
    n_samples: int
    n_months_with_data: int
    mean_of_site_means: float | None = None
    median_of_site_medians: float | None = None
    n_detection_limit_all_sites: int  # all bathing waters of the country in the period, not only the paired ones
    n_missing_all_sites: int
    n_unrecognised_all_sites: int
    n_confirmed_high_all_sites: int
    flags: list[str]


class CountrySamplesPeriodPair(BaseModel):
    a: CountrySamplesPeriod
    b: CountrySamplesPeriod


class CountrySamplesIndicatorChange(BaseModel):
    indicator: IndicatorName
    label: str
    unit: str
    status: ChangeStatus
    min_samples_per_period: int
    few_sites_threshold: int
    n_sites_considered: int
    n_sites_paired: int
    n_sites_excluded: int
    exclusion_reasons: dict[str, int]
    periods: CountrySamplesPeriodPair
    change_of_site_means: ChangeValues
    change_of_site_medians: ChangeValues
    median_site_relative_change_percent: float | None = None
    n_sites_relative_change_undefined: int
    sites_increased: int
    sites_decreased: int
    sites_unchanged: int
    data_range: ChangeDataRange
    flags: list[str]


class CountrySamplesIndicatorsChange(BaseModel):
    escherichia_coli: CountrySamplesIndicatorChange
    intestinal_enterococci: CountrySamplesIndicatorChange


class BathingSamplesCountryChangeResponse(BaseModel):
    """How the individual samples of one country changed between two periods, over paired bathing waters only."""

    origin: SamplesOrigin
    data_freshness: DataFreshnessModel
    attribution: str
    language: str
    notice: str
    no_threshold_notice: str
    flagged_values_note: str
    change_notice: str
    unit: str
    bathing_samples: BathingSamplesStatus
    scope: SamplesChangeScope
    indicators: CountrySamplesIndicatorsChange
    flags: list[str]  # store-not-ready, no-samples-for-country
