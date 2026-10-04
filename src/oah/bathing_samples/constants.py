"""Labels, endpoint facts, value kinds and fixed wording of the bathing-water SAMPLES slice. Pure module: no I/O.

Everything here was checked against the live EEA Discodata service on 2026-10-03 (``docs/bathing_samples_store.md``):
the table, its columns, the unit and the status values. Nothing is invented. The unit comes from the table's own
metadata (``https://discodata.eea.europa.eu/md``): "colony forming unit per 100 ml (cfu/100ml)". No threshold, limit or
classification rule exists in this package and none is applied: the values are individual sample results.
"""

from __future__ import annotations

SOURCE_ID = "real-eea-bathing-samples"  # the ``origin`` label of every record read from the samples store
SOURCE_LABEL = "EEA Bathing Water Directive - monitoring results (Discodata, WISE_BWD timeseries_MonitoringResult)"
EDITION = "Discodata WISE_BWD [latest] view of timeseries_MonitoringResult (observed on 2026-10-03 to proxy release v5r1)"
SOURCE_URL = "https://discodata.eea.europa.eu/"
ENDPOINT = "https://discodata.eea.europa.eu/sql"
TABLE = "[WISE_BWD].[latest].[timeseries_MonitoringResult]"
OBSERVED_PROXY = "[WISE_BWD].[v5r1].[timeseries_MonitoringResult]"  # what the metadata said [latest] stands for on 2026-10-03
LICENCE = "EEA CC BY 4.0 (EEA legal notice; dataset page does not restate it)"
ATTRIBUTION = "EEA Bathing Water Directive, monitoring results via Discodata (EEA CC BY 4.0)"
USER_AGENT = "OneAquaHealth-store-build/0.1 (read-only; EEA Discodata; documented in docs/bathing_samples_store.md)"

# The unit, from the table metadata: "colony forming unit per 100 ml (cfu/100ml)" (the Directive convention).
UNIT = "cfu/100ml"
UNIT_STATEMENT = (
    "colony forming unit per 100 ml (cfu/100ml), as stated by the Discodata table metadata read on 2026-10-03"
)

# The country is not a column: it is the first two characters of ``bathingWaterIdentifier``. Greece is written EL
# there; the project treats EL as an alias of GR everywhere, so Greece is stored and served as GR. Norway has no row
# (it is not in the Bathing Water Directive); the build still asks for NO so that every build says so.
PREFIX_TO_COUNTRY: dict[str, str] = {"EL": "GR", "IT": "IT", "NO": "NO"}
COUNTRY_ALIASES: dict[str, str] = {"EL": "GR", "GR": "GR", "IT": "IT", "NO": "NO"}

COLUMNS = (
    "UID", "season", "bathingWaterIdentifier", "sampleDate", "escherichiaColiValue", "intestinalEnterococciValue",
    "escherichiaColiStatus", "intestinalEnterococciStatus", "sampleStatus",
)

# --- value kinds -------------------------------------------------------------------------------------------------------
# One letter per kind in the store. A value is a plain concentration ONLY for Q and C; the others are counted apart and
# never enter a statistic. The statuses are those of the Discodata column description ("missing values, values below the
# limit of detection, or exceptionally high values") as observed on 2026-10-03.
KIND_QUANTIFIED = "Q"  # no status: a measured concentration
KIND_CONFIRMED = "C"  # status confirmedValue: an exceptionally high value, confirmed (a measured concentration, flagged)
KIND_DETECTION = "D"  # status limitOfDetectionValue: the number is a limit of detection, NOT a quantified concentration
KIND_MISSING = "M"  # status missingValue (the number is a placeholder 0) or no value at all
KIND_UNKNOWN = "U"  # a status the project has not seen: the value is kept as written and never used
KIND_INVALID = "I"  # a value that is not a non-negative whole number
QUANTIFIED_KINDS = (KIND_QUANTIFIED, KIND_CONFIRMED)
KIND_NAMES: dict[str, str] = {
    KIND_QUANTIFIED: "quantified",
    KIND_CONFIRMED: "confirmed-high",
    KIND_DETECTION: "detection-limit",
    KIND_MISSING: "missing",
    KIND_UNKNOWN: "unknown-status",
    KIND_INVALID: "invalid",
}
STATUS_KIND: dict[str, str] = {
    "confirmedValue": KIND_CONFIRMED,
    "limitOfDetectionValue": KIND_DETECTION,
    "missingValue": KIND_MISSING,
}
# ``sampleStatus`` values observed (EL and IT, 2026-10-03); anything else is kept as written.
KNOWN_SAMPLE_STATUSES = frozenset(
    {"confirmationSample", "missingSample", "preSeasonSample", "replacementSample", "shortTermPollutionSample"}
)

INDICATORS: dict[str, tuple[str, str]] = {  # API name -> (store column prefix, EEA column prefix)
    "escherichia_coli": ("ec", "escherichiaColi"),
    "intestinal_enterococci": ("ie", "intestinalEnterococci"),
}
INDICATOR_LABELS: dict[str, str] = {
    "escherichia_coli": "Escherichia coli",
    "intestinal_enterococci": "Intestinal enterococci",
}

# --- extraction bounds -------------------------------------------------------------------------------------------------
DEFAULT_PAGE_SIZE = 20_000  # rows per request; the service answered 300,000 in one reply (82 MB) on 2026-10-03, so this is conservative
MAX_PAGE_SIZE = 50_000
HARD_MAX_PAGES = 400  # per country; 754,451 rows are 38 pages of 20,000
HARD_MAX_ROWS_PER_COUNTRY = 3_000_000
MIN_REQUEST_INTERVAL_SECONDS = 0.5  # at most about two requests per second
REQUEST_TIMEOUT_SECONDS = 120.0
MAX_ATTEMPTS = 5
BACKOFF_BASE_SECONDS = 2.0
BACKOFF_CAP_SECONDS = 60.0

# --- reader bounds -----------------------------------------------------------------------------------------------------
DEFAULT_LIMIT = 200
MAX_LIMIT = 500
MAX_ID_CHARS = 128
INDEX_KINDS = "idx_samples_kinds"  # covering index (country, date, both kinds): per-kind counts of a country
INDEX_QUANTIFIED = {"ec": "idx_samples_ec_quantified", "ie": "idx_samples_ie_quantified"}  # partial indexes (kinds Q and C only)
MAX_COUNTRY_ROWS = 1_500_000  # rows a country-scope comparison may read (the real store holds 754,451 in all)

# --- fixed wording for the chat model --------------------------------------------------------------------------------------
# The full notices are fixed strings of ``oah.i18n.strings`` (English source and 25 machine-drafted translations). The chat
# model reads short English wordings because the tool-result sanitiser cuts every string at 200 characters. None of them
# uses a word that calls a value or a bathing water good, bad, safe or unsafe: no such judgement exists in this project.
SAMPLES_NOTICE_SHORT = "Individual sample results in cfu/100ml. Not a classification and not a compliance assessment."
NO_THRESHOLD_NOTICE_SHORT = "No threshold or limit is applied to these values; they carry no good or bad label."
FLAGGED_VALUES_NOTE_SHORT = "Detection-limit, missing and unknown-status values are counted apart, not in the statistics."
CHANGE_NOTICE_SHORT = (
    "Mean and median of individual sample results. No significance is tested and no limit exists, so no limit crossing."
)
