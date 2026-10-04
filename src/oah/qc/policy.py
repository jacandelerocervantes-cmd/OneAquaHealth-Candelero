"""Shared QC policy constants derived from observed sandbox data."""

# Observed in the sandbox on 2026-09-21; `pH` remains flagged for review, not an error.
ALLOWED_UCUM_CODES = frozenset(
    {"ug/L", "mg/L", "Cel", "mS/cm", "%", "ug/m3", "uS/cm", "pH"}
)
REVIEW_UCUM_CODES = frozenset({"pH"})
