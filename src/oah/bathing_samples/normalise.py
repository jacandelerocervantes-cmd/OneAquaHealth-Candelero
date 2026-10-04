"""Normalisation of one Discodata row into a ``Sample``: every drop counted, every status kept as written, every value
given a KIND (rules in ``oah.bathing_samples.build``). Pure: no I/O."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from oah.bathing_samples.constants import (
    KIND_INVALID,
    KIND_MISSING,
    KIND_QUANTIFIED,
    KIND_UNKNOWN,
    PREFIX_TO_COUNTRY,
    STATUS_KIND,
)


MIN_SEASON, MAX_SEASON = 1900, 2100


MAX_STATUS_CHARS = 64
_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?$")


@dataclass(frozen=True)
class Sample:
    uid: int
    bw_id: str
    country: str
    season: int
    sample_date: str
    ec_value: int | None
    ec_status: str | None
    ec_kind: str
    ie_value: int | None
    ie_status: str | None
    ie_kind: str
    sample_status: str | None
    obs_status: str | None
    has_remarks: int

    def as_tuple(self) -> tuple[Any, ...]:
        return (
            self.uid, self.bw_id, self.country, self.season, self.sample_date, self.ec_value, self.ec_status, self.ec_kind,
            self.ie_value, self.ie_status, self.ie_kind, self.sample_status, self.obs_status, self.has_remarks,
        )


# --- normalisation -----------------------------------------------------------------------------------------------------


def _text(value: Any, limit: int = MAX_STATUS_CHARS) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _count(value: Any) -> tuple[int | None, bool]:
    """``(the value as a whole number, usable)``: ``(None, True)`` when absent, ``(None, False)`` when it is not a
    non-negative whole number (text, boolean, negative, fractional, not finite)."""
    if value is None:
        return None, True
    if isinstance(value, bool):
        return None, False
    if isinstance(value, int):
        return (value, True) if value >= 0 else (None, False)
    if isinstance(value, float) and math.isfinite(value) and value >= 0 and value == int(value):
        return int(value), True
    return None, False


def classify_value(value: Any, status: Any, counters: Counter[str], label: str) -> tuple[int | None, str | None, str]:
    """``(stored value, status as written, kind)`` of one indicator of one sample (the rules are in the module docstring).

    The status is kept as the service wrote it (trimmed); the value is kept as reported for every kind but ``I``, so the
    placeholder 0 of a missing value stays visible in the store, and the kind says it is not a concentration.
    """
    status_text = _text(status)
    number, usable = _count(value)
    if status_text is None:
        if number is None and usable:
            counters[f"{label}_value_null_without_status"] += 1
            return None, None, KIND_MISSING
        if not usable:
            return None, None, KIND_INVALID
        if number == 0:
            counters[f"{label}_zero_without_status"] += 1
        return number, None, KIND_QUANTIFIED
    kind = STATUS_KIND.get(status_text)
    if kind is None:
        return (number if usable else None), status_text, KIND_UNKNOWN
    if kind == KIND_MISSING:
        if number not in (None, 0):
            counters[f"{label}_missing_with_nonzero_value"] += 1
        return (number if usable else None), status_text, KIND_MISSING
    if number is None:  # a confirmed or limit-of-detection status without a usable number
        return None, status_text, KIND_INVALID
    return number, status_text, kind


def _date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = _DATE.match(value.strip())
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def _season(value: Any) -> int | None:
    number, usable = _count(value)
    return number if usable and number is not None and MIN_SEASON <= number <= MAX_SEASON else None


@dataclass
class Tallies:
    """Everything the provenance reports about the values seen (all counted on the kept rows)."""

    counters: Counter[str]
    statuses: dict[str, Counter[str]]
    kinds: dict[str, Counter[str]]
    sample_statuses: Counter[str]
    observation_statuses: Counter[str]
    seasons: dict[str, Counter[int]]
    dates: dict[str, list[str]]  # country -> [first, last]

    @staticmethod
    def new() -> Tallies:
        return Tallies(
            Counter(), {"escherichia_coli": Counter(), "intestinal_enterococci": Counter()},
            {"escherichia_coli": Counter(), "intestinal_enterococci": Counter()}, Counter(), Counter(), {}, {},
        )


def normalise_row(raw: dict[str, Any], prefix: str, tallies: Tallies) -> Sample | None:
    """One service row as a ``Sample``, or None when it is dropped (the reason is counted)."""
    counters = tallies.counters
    counters["rows_scanned"] += 1
    uid = raw.get("UID")
    if isinstance(uid, bool) or not isinstance(uid, int) or uid < 0:
        counters["dropped_bad_uid"] += 1
        return None
    bw_id = _text(raw.get("bathingWaterIdentifier"), 128)
    if bw_id is None:
        counters["dropped_no_identifier"] += 1
        return None
    country = PREFIX_TO_COUNTRY.get(prefix)
    if country is None or bw_id[:2].upper() != prefix:
        counters["dropped_wrong_country_prefix"] += 1
        return None
    day = _date(raw.get("sampleDate"))
    if day is None:
        counters["dropped_bad_date"] += 1
        return None
    season = _season(raw.get("season"))
    if season is None:
        counters["dropped_bad_season"] += 1
        return None
    ec_value, ec_status, ec_kind = classify_value(raw.get("escherichiaColiValue"), raw.get("escherichiaColiStatus"), counters, "ec")
    ie_value, ie_status, ie_kind = classify_value(
        raw.get("intestinalEnterococciValue"), raw.get("intestinalEnterococciStatus"), counters, "ie"
    )
    sample_status = _text(raw.get("sampleStatus"))
    obs_status = _text(raw.get("metadata_observationStatus"))
    remarks = 1 if raw.get("hasRemarks") in (1, True, "1") else 0
    counters["rows_kept"] += 1
    tallies.statuses["escherichia_coli"][ec_status or "(none)"] += 1
    tallies.statuses["intestinal_enterococci"][ie_status or "(none)"] += 1
    tallies.kinds["escherichia_coli"][ec_kind] += 1
    tallies.kinds["intestinal_enterococci"][ie_kind] += 1
    tallies.sample_statuses[sample_status or "(none)"] += 1
    tallies.observation_statuses[obs_status or "(none)"] += 1
    tallies.seasons.setdefault(country, Counter())[season] += 1
    span = tallies.dates.setdefault(country, [day, day])
    span[0], span[1] = min(span[0], day), max(span[1], day)
    if remarks:
        counters["rows_with_remarks"] += 1
    if day.endswith("-01-01"):
        counters["sample_date_is_january_1"] += 1
    if int(day[:4]) != season:
        counters["sample_year_differs_from_season"] += 1
    return Sample(uid, bw_id, country, season, day, ec_value, ec_status, ec_kind, ie_value, ie_status, ie_kind, sample_status, obs_status, remarks)
