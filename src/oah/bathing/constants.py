"""Labels, filters and fixed wording of the bathing-water slice. Pure module: no I/O.

Nothing is invented: the column names, the sheet name and the country scope come from the file verified on
2026-10-02 (``docs/bathing_water_store.md``); the README sentences below are quoted exactly from the archive's
``README.md``. The file holds the per-season CLASSIFICATION only, not E. coli or intestinal enterococci concentrations.
"""

from __future__ import annotations

import re

SOURCE_ID = "real-eea-bathing-water"  # the ``origin`` label of every record read from the store
SOURCE_LABEL = "EEA Bathing Water Directive - Status of bathing water, 2025 v.1.0"
EDITION = "Bathing Water Directive - Status of bathing water, 2025 v.1.0 (seasons 1990-2025), v01_r00"
SOURCE_URL = "https://www.eea.europa.eu/data-and-maps/data/bathing-water-directive-status-of-bathing-water-12"
LICENCE = "EEA CC BY 4.0 (EEA legal notice; dataset page does not restate it)"
ATTRIBUTION = "EEA Bathing Water Directive - Status of bathing water, 2025 v.1.0 (EEA CC BY 4.0)"

SHEET_NAME = "bw_assessment_datahub_1990_2025"
XLSX_NAME = "bw_assessment_eea_datahub_1990_2025.xlsx"
EXPECTED_COLUMNS = (
    "countryCode", "bathingWaterIdentifier", "groupIdentifier", "bathingWaterName", "bathingWaterType",
    "geographicalConstraint", "lon", "lat", "bwProfile", "season", "quality", "monitoringCalendar", "management",
)

# Country codes of the file -> project code. Greece is checked in the real file (docs/bathing_water_store.md); the
# project treats EL as an alias of GR everywhere, so both spellings are accepted and stored as GR.
COUNTRY_CODES: dict[str, str] = {"EL": "GR", "GR": "GR", "IT": "IT", "NO": "NO"}

# ``quality`` values observed in the 2025 v1.0 file (all countries; verified 2026-10-02, counts in
# docs/bathing_water_store.md). The README names four categories (excellent, good, sufficient, poor); the file also
# holds "Not classified" and "Good or Sufficient", which the README does not explain: they are kept as written and
# never interpreted. A value outside this set is kept as it is and reported in the provenance
# (``unknown_quality_values``).
KNOWN_QUALITY_VALUES: frozenset[str] = frozenset(
    {"0 - Not classified", "1 - Excellent", "2 - Good", "3 - Good or Sufficient", "3 - Sufficient", "4 - Poor"}
)
PLACEHOLDER_NAME = "UNKNOWN"  # the file's placeholder for a missing bathing water name; stored as null
_QUALITY_PATTERN = re.compile(r"^\s*(?P<code>\d+)\s*-\s*(?P<label>.+?)\s*$")

README_CLASSES_SENTENCE = (
    "Based on the monitoring results for these bacteria, bathing waters are classified into four quality categories: "
    "excellent, good, sufficient, or poor."
)
README_BACTERIA_SENTENCE = (
    "Member States are also requested to monitor the concentration in water of E. coli and intestinal enterococci."
)
README_SAMPLES_SENTENCE = "At least four water samples per bathing water need to be collected and analysed"

NOTICE = (
    "This is the per-season CLASSIFICATION of each bathing water under Directive 2006/7/EC as published by the EEA, "
    "not a concentration: E. coli and intestinal enterococci results are not in this data. It is not a statement of "
    "legal compliance and not a health or safety determination."
)
# The season comparison notice as the chat model reads it (English; short enough to survive the 200-character cut of the
# tool-result sanitiser). The full, localised wording is the fixed string ``bathing_change_notice`` of ``oah.i18n.strings``.
COMPARISON_NOTICE_SHORT = (
    "Compared only by the order excellent, good, sufficient, poor. Not classified and good or sufficient are not "
    "comparable and are counted apart. No concentration or threshold is used."
)
PROFILE_NOTE = "bw_profile_url is plain text from the file; it is never fetched or followed by this project."

MAX_PAGE = 500
DEFAULT_PAGE = 200
MAX_HISTORY = 200  # seasons of one bathing water (the file spans 36 seasons)
MAX_QUERY_CHARS = 64
MAX_ID_CHARS = 128


def quality_class(quality: str | None) -> str | None:
    """The label after the code of a ``quality`` value (``1 - Excellent`` -> ``Excellent``), or None when it has no such shape.

    A convenience for readers; the raw string is always kept next to it.
    """
    if quality is None:
        return None
    match = _QUALITY_PATTERN.match(quality)
    return match.group("label") if match else None


def safe_profile_url(value: str | None) -> str | None:
    """The ``bwProfile`` text when it is an http(s) URL, else None (never a ``javascript:`` or other scheme)."""
    if value is None:
        return None
    text = value.strip()
    return text if re.match(r"^https?://\S+$", text, re.IGNORECASE) else None
