"""Fixed facts about the external providers: hosts, labels, attribution, licences, documented limits.

Every value here was read at the provider's own page on 2026-10-03 (docs/external_context.md section 3 lists the page of
each); a wording that could not be verified is marked ``verified: False`` and shown as unverified. Nothing is a threshold
or a formula of this project.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

# --- origins (the ``origin`` value of every external response) ---------------------------------------------------
ORIGIN_OPEN_METEO = "external-open-meteo"
ORIGIN_GBIF = "external-gbif"
EXTERNAL_ORIGINS = (ORIGIN_OPEN_METEO, ORIGIN_GBIF)

# --- hosts: the only outbound targets. Confirmed from the documentation pages of each provider (2026-10-03) ---------
ARCHIVE_HOST = "archive-api.open-meteo.com"  # GET /v1/archive
FLOOD_HOST = "flood-api.open-meteo.com"  # GET /v1/flood
GBIF_HOST = "api.gbif.org"  # GET /v1/occurrence/search, /v1/dataset/{key}
ALLOWED_HOSTS = frozenset({ARCHIVE_HOST, FLOOD_HOST, GBIF_HOST})

ARCHIVE_PATH = "/v1/archive"
FLOOD_PATH = "/v1/flood"
GBIF_SEARCH_PATH = "/v1/occurrence/search"
GBIF_DATASET_PATH = "/v1/dataset/"  # followed by a UUID checked by ``oah.external.gbif``

# --- provider identifiers (breaker, cache and status keys) ------------------------------------------------------------
PROVIDER_WEATHER = "open-meteo-archive"
PROVIDER_DISCHARGE = "open-meteo-flood"
PROVIDER_GBIF = "gbif"
PROVIDERS = (PROVIDER_WEATHER, PROVIDER_DISCHARGE, PROVIDER_GBIF)
BUDGET_OPEN_METEO = "open-meteo"  # the archive and flood hosts share one published free-tier limit
BUDGET_GBIF = "gbif"

# --- data kinds: what the numbers ARE (shown on every response) ---------------------------------------------------
KIND_REANALYSIS = "modelled-reanalysis"
KIND_DISCHARGE = "modelled-river-discharge"
KIND_OCCURRENCE = "opportunistic-occurrence-records"

# --- status vocabulary of an external response -----------------------------------------------------------------------
STATUS_OK = "ok"
STATUS_NO_DATA = "no-data"  # the provider answered but holds no value for the requested period
STATUS_UNAVAILABLE = "external-unavailable"  # disabled, over budget, failed or timed out

# --- reasons of an ``external-unavailable`` status -----------------------------------------------------------------------
REASON_DISABLED = "disabled"
REASON_BUDGET = "budget-exhausted"
REASON_COOLING_DOWN = "cooling-down"
REASON_TIMEOUT = "timeout"
REASON_RATE_LIMITED = "rate-limited"
REASON_NETWORK = "network-error"
REASON_HTTP = "http-error"
REASON_BAD_RESPONSE = "bad-response"
REASON_TOO_LARGE = "response-too-large"
REASON_REDIRECT = "redirect-refused"
REASON_BLOCKED = "blocked-target"
REASONS = (
    REASON_DISABLED, REASON_BUDGET, REASON_COOLING_DOWN, REASON_TIMEOUT, REASON_RATE_LIMITED, REASON_NETWORK,
    REASON_HTTP, REASON_BAD_RESPONSE, REASON_TOO_LARGE, REASON_REDIRECT, REASON_BLOCKED,
)

# --- flags of a data response ------------------------------------------------------------------------------------------
FLAG_PERIOD_OUTSIDE_DATA = "period-outside-data"
FLAG_ERA5_DELAY = "era5-delay"
FLAG_PERIOD_END_CLIPPED = "period-end-clipped"
FLAG_PERIOD_START_CLIPPED = "period-start-clipped"
FLAG_PARTIAL_MONTH = "partial-month"
FLAG_IMPLAUSIBLE_IGNORED = "implausible-values-ignored"
FLAG_BEYOND_DOCUMENTED_HISTORY = "beyond-documented-history"
FLAG_SITE_NOT_A_RIVER = "site-not-a-river"
FLAG_NEAREST_CELL = "nearest-cell-may-not-be-the-river"
FLAG_TRUNCATED = "truncated"
FLAG_CITATIONS_PARTIAL = "citations-partial"
FLAG_NON_COMMERCIAL_RECORDS = "non-commercial-licence-records"

# --- documented data limits (as read on 2026-10-03; the discharge limit is checked against the API's own behaviour) -----
ARCHIVE_FIRST_DAY = date(1940, 1, 1)  # the API's own error message: "allowed range from 1940-01-01 to <today>"
ERA5_DELAY_DAYS = 5  # "ERA5 ... Daily with 5 days delay" (Historical Weather API page)
FLOOD_FIRST_DAY = date(1984, 1, 1)  # the API's own error message: "allowed range from 1984-01-01"
# The Flood API page documents the GloFAS v4 reanalysis as "1984 - July 2022". The consolidated product was observed on
# 2026-10-03 to return values for later dates too (for example 2024), so this date is NOT used as a cut-off: it only
# marks months as ``beyond-documented-history``. The real end of data is read from the null values of each response.
FLOOD_DOCUMENTED_LAST_DAY = date(2022, 7, 31)
MAX_SPAN_DAYS = 1096  # about three years: the longest period of one weather or discharge request

WEATHER_MODEL = "era5"  # the `models` parameter of the archive API: ERA5 only, so the label is the same on every call
DISCHARGE_MODEL = "consolidated_v4"  # GloFAS v4 consolidated (reanalysis); a name found in the Flood API documentation page
WEATHER_VARIABLES = ("precipitation_sum", "temperature_2m_mean")
DISCHARGE_VARIABLES = ("river_discharge",)
# Physical sanity bounds for a DAILY value, taken from the order of magnitude of recorded world extremes. They only
# reject a corrupt number (a wrong unit, a sentinel such as -999); they are not quality thresholds of this project.
PRECIPITATION_DAILY_MAX_MM = 2000.0
TEMPERATURE_MIN_C = -90.0
TEMPERATURE_MAX_C = 60.0
DISCHARGE_MAX_M3S = 1_000_000.0

# --- coordinates -------------------------------------------------------------------------------------------------------------
COORD_DECIMALS = 2  # about 1.1 km: coarser than every grid in use, finer than a town; also the cache key
GBIF_HALF_SIDE_KM = 5.0  # the search area is a square of this half side (10 km x 10 km) around the rounded point
EARTH_RADIUS_KM = 6371.0088  # mean Earth radius (IUGG), used only for the haversine distance to a grid cell or record


@dataclass(frozen=True)
class ProviderInfo:
    """Static description of a provider, listed by ``GET /external/status`` (no secret, no live value)."""

    provider: str
    name: str
    origin: str
    kind: str
    attribution: str
    attribution_url: str | None
    attribution_verified: bool
    licence: str
    licence_note: str
    limits: str
    data_note: str


OPEN_METEO_ATTRIBUTION = "Weather data by Open-Meteo.com"  # the link text the licence page requires, next to the data
OPEN_METEO_URL = "https://open-meteo.com/"
ERA5_CREDIT = "Generated using Copernicus Climate Change Service information (ERA5 reanalysis, ECMWF)"
ERA5_DOI = "https://doi.org/10.24381/cds.adbb2d47"
# The wording of the CEMS credit for GloFAS could NOT be read (the licence PDF the Open-Meteo page links to returned 404 on
# 2026-10-03): this sentence is the project's own neutral naming of the source, not a verified credit text.
GLOFAS_CREDIT = "River discharge: GloFAS (Copernicus Emergency Management Service), provided through Open-Meteo.com"
GBIF_ATTRIBUTION = "Occurrence records from GBIF.org; each record keeps the licence and publisher of its dataset"
GBIF_URL = "https://www.gbif.org/"

PROVIDER_INFO: dict[str, ProviderInfo] = {
    PROVIDER_WEATHER: ProviderInfo(
        provider=PROVIDER_WEATHER,
        name="Open-Meteo Historical Weather API (ERA5 reanalysis)",
        origin=ORIGIN_OPEN_METEO,
        kind=KIND_REANALYSIS,
        attribution=f"{OPEN_METEO_ATTRIBUTION}. {ERA5_CREDIT}.",
        attribution_url=OPEN_METEO_URL,
        attribution_verified=True,
        licence="CC BY 4.0 (API data); free API for non-commercial use",
        licence_note=(
            "Attribution with a link to the licence and an indication of changes is required; the link text "
            "'Weather data by Open-Meteo.com' must sit next to displayed data. Commercial use needs a paid plan."
        ),
        limits="Free tier: 600 calls per minute, 5,000 per hour, 10,000 per day, 300,000 per month; long requests count as several calls.",
        data_note=(
            "ERA5 reanalysis at 0.25 degrees (about 25 km), 1940 onward, about 5 days behind today. MODELLED values for a "
            "grid cell, not measurements at the site."
        ),
    ),
    PROVIDER_DISCHARGE: ProviderInfo(
        provider=PROVIDER_DISCHARGE,
        name="Open-Meteo Flood API (GloFAS v4 consolidated river discharge)",
        origin=ORIGIN_OPEN_METEO,
        kind=KIND_DISCHARGE,
        attribution=f"{OPEN_METEO_ATTRIBUTION}. {GLOFAS_CREDIT}.",
        attribution_url=OPEN_METEO_URL,
        attribution_verified=False,
        licence="CC BY 4.0 (Open-Meteo API data); GloFAS terms are those of the Copernicus Emergency Management Service",
        licence_note=(
            "The Open-Meteo licence page lists GloFAS with its own licence; the credit wording of that licence was not "
            "read (UNVERIFIED). Check it before public use."
        ),
        limits="Shares the Open-Meteo free-tier limits with the weather provider.",
        data_note=(
            "GloFAS v4, 0.05 degrees (about 5 km), daily from 1984. MODELLED discharge of the nearest river cell, not a "
            "gauge; the cell may not be the river of the site."
        ),
    ),
    PROVIDER_GBIF: ProviderInfo(
        provider=PROVIDER_GBIF,
        name="GBIF occurrence search",
        origin=ORIGIN_GBIF,
        kind=KIND_OCCURRENCE,
        attribution=GBIF_ATTRIBUTION,
        attribution_url=GBIF_URL,
        attribution_verified=False,
        licence="Per record: CC0 1.0, CC BY 4.0 or CC BY-NC 4.0 (shown with every record)",
        licence_note=(
            "Records under CC BY-NC are for non-commercial use only. The GBIF terms pages were not read in full "
            "(UNVERIFIED): the per-record licence and the dataset citation are passed on as the API gives them."
        ),
        limits="No numeric limit verified; this project allows 30 requests per minute and 1,500 per day by default.",
        data_note=(
            "Opportunistic occurrence records (many from citizen-science platforms), not monitoring: an absence of records "
            "says nothing about absence of a species."
        ),
    ),
}
