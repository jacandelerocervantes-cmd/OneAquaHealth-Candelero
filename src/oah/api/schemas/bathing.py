"""Response models of the EEA bathing-water routes (classification and samples links) and the store-state blocks."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from oah.api.schemas.common import DataFreshnessModel


class BathingSamplesStatus(BaseModel):
    """State of the optional EEA bathing-water samples store; a store that is not built is a clear status, never an error."""

    state: Literal["ready", "not-built", "unreadable"]
    detail: str
    edition: str | None = None
    attribution: str | None = None
    build_date_utc: str | None = None


class CountryBathingSamples(BaseModel):
    """The individual bathing-water samples held for a country (E. coli and intestinal enterococci; no thresholds)."""

    origin: Literal["real-eea-bathing-samples"]
    bathing_waters_with_samples: int
    n_samples: int
    n_quantified: dict[str, int]  # indicator -> samples with a quantified value
    first_sample_date: str
    last_sample_date: str
    first_season: int
    last_season: int
    unit: str
    attribution: str
    content: Literal["individual-samples-no-thresholds"]


class BathingSamplesLink(BaseModel):
    """Whether individual samples exist for one bathing water, and the last sample date."""

    state: Literal["ready", "not-built", "unreadable"]
    available: bool
    n_samples: int
    first_sample_date: str | None = None
    last_sample_date: str | None = None
    first_season: int | None = None
    last_season: int | None = None
    path: str | None = None  # the route that serves them, relative to the API root


class CountryBathingWater(BaseModel):
    """Bathing-water CLASSIFICATION held for a country (never concentrations); ``samples`` says what individual samples exist."""

    origin: Literal["real-eea-bathing-water"]
    bathing_waters: int
    classification_rows: int
    first_season: int
    latest_season: int
    latest_season_counts: dict[str, int]  # the file's own quality strings -> bathing waters in the latest season
    attribution: str
    content: Literal["classification-only"]
    samples: CountryBathingSamples | None = None  # null when the samples store is not built or holds none for the country


class BathingWaterStatus(BaseModel):
    """State of the optional EEA bathing-water store; a store that is not built is a clear status, never an error."""

    state: Literal["ready", "not-built", "unreadable"]
    detail: str
    edition: str | None = None
    attribution: str | None = None
    build_date_utc: str | None = None


class BathingWaterEntry(BaseModel):
    """One bathing water with the classification of its latest season. A classification, not a concentration."""

    id: str
    country: str
    name: str
    type: str | None = None  # as written in the file, e.g. coastalBathingWater
    geographical_constraint: str | None = None
    group_identifier: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_status: Literal["located", "no-location"]
    bw_profile_url: str | None = None  # plain text from the file; render as text, never fetched by this API
    first_season: int
    latest_season: int
    n_seasons: int
    latest_quality: str | None = None  # the file's own string, e.g. "1 - Excellent"
    latest_quality_class: str | None = None  # its label, e.g. "Excellent"
    origin: Literal["real-eea-bathing-water"]
    source: Literal["real-eea-bathing-water"]


class BathingWatersResponse(BaseModel):
    origin: Literal["real-eea-bathing-water"]
    data_freshness: DataFreshnessModel
    attribution: str
    notice: str  # a classification, not a concentration, not legal compliance
    bathing_water: BathingWaterStatus
    bathing_waters: list[BathingWaterEntry]
    total_matching: int
    returned: int
    limit: int
    offset: int
    truncated: bool


class SeasonClassification(BaseModel):
    season: int
    quality: str | None = None  # the file's own string; values outside the known set are kept as written
    quality_class: str | None = None
    monitoring_calendar: str | None = None
    management: str | None = None


class BathingWaterHistoryResponse(BaseModel):
    """The classification of one bathing water by season. A classification, not a concentration."""

    origin: Literal["real-eea-bathing-water"]
    data_freshness: DataFreshnessModel
    attribution: str
    notice: str
    profile_note: str
    bathing_water: BathingWaterEntry
    history: list[SeasonClassification]
    samples: BathingSamplesLink  # whether individual E. coli and enterococci samples exist, and the last sample date
