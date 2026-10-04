"""Reading the disaggregated Waterbase stream: filtering and aggregating per (site, determinand, matrix, unit, year, month).

No sample value is kept, so the store has no median; values below the limit of quantification are only counted.
"""
from __future__ import annotations

import csv
import math
from collections import Counter
from collections.abc import Iterable, Iterator
from sys import intern

from oah.waterbase.mapping import (
    BELOW_LOQ_TRUE,
    CATEGORIES,
    COUNTRY_CODES,
    DETERMINANDS,
    KEPT_DETERMINAND_CODES,
    LOWER_RELIABILITY_STATUSES,
    MIN_YEAR,
    MISSING_VALUE_STATUSES,
)


REQUIRED_COLUMNS = (
    "countryCode", "monitoringSiteIdentifier", "parameterWaterBodyCategory", "observedPropertyDeterminandCode",
    "procedureAnalysedMatrix", "resultUom", "phenomenonTimeSamplingDate", "resultObservedValue",
    "resultQualityObservedValueBelowLOQ", "resultObservationStatus", "metadata_observationStatus",
)
_COUNTRY_BYTES = {code.encode("ascii"): code for code in COUNTRY_CODES}


# Key: (country, site, category, determinand code, matrix, unit, year, month)
Key = tuple[str, str, str, str, str, str, int, int]
# Value: [n, sum, min, max, n_below_loq, n_lower_reliability]
Aggregates = dict[Key, list[float]]


def _logical_records(lines: Iterable[bytes], counters: Counter[str]) -> Iterator[bytes]:
    """Yield each logical record (a quoted field may span lines) whose country is one of ours; count the rest.

    The country is the first field, so the check needs no CSV parsing. A line with an odd number of quotes opens a
    quoted field and is joined with the following lines until the quotes balance, so a continuation line can never
    be mistaken for a record of its own.
    """
    pending: bytes | None = None
    for line in lines:
        if pending is not None:
            pending += line
            if pending.count(b'"') % 2:
                continue
            record, pending = pending, None
        elif line.count(b'"') % 2:
            pending = line
            continue
        else:
            record = line
        counters["rows_scanned"] += 1
        if record[: record.find(b",")] in _COUNTRY_BYTES:
            counters["rows_country_kept"] += 1
            yield record
    if pending is not None:
        counters["rows_malformed"] += 1  # an unterminated quoted field at the end of the file


def _to_float(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _year_month(text: str) -> tuple[int, int] | None:
    """``(year, month)`` of a sampling date written ``YYYYMMDD`` (the real file) or ``YYYY-MM-DD``; None when unreadable."""
    value = text.strip()
    try:
        year = int(value[:4])
        month = int(value[5:7]) if len(value) > 4 and value[4] == "-" else int(value[4:6])
    except ValueError:
        return None
    return (year, month) if 1 <= month <= 12 else None


def aggregate_disaggregated(lines: Iterable[bytes], min_year: int = MIN_YEAR) -> tuple[Aggregates, Counter[str]]:
    """Filter and aggregate the raw lines of the disaggregated CSV (header first). See the module docstring."""
    counters: Counter[str] = Counter()
    iterator = iter(lines)
    header_line = next(iterator, None)
    if header_line is None:
        raise ValueError("The disaggregated table is empty.")
    header = next(csv.reader([header_line.decode("utf-8-sig")]))  # the file starts with a BOM
    position = {name.strip(): index for index, name in enumerate(header)}
    missing = [name for name in REQUIRED_COLUMNS if name not in position]
    if missing:
        raise ValueError(f"The disaggregated table lacks the column(s) {missing}; the layout changed.")
    c_country, c_site = position["countryCode"], position["monitoringSiteIdentifier"]
    c_category, c_code = position["parameterWaterBodyCategory"], position["observedPropertyDeterminandCode"]
    c_matrix, c_unit = position["procedureAnalysedMatrix"], position["resultUom"]
    c_date, c_value = position["phenomenonTimeSamplingDate"], position["resultObservedValue"]
    c_loq, c_status = position["resultQualityObservedValueBelowLOQ"], position["resultObservationStatus"]
    c_reliability = position["metadata_observationStatus"]
    width = len(header)

    aggregates: Aggregates = {}
    decoded = (record.decode("utf-8", "replace") for record in _logical_records(iterator, counters))
    for row in csv.reader(decoded):
        if len(row) < width:
            counters["rows_malformed"] += 1
            continue
        if row[c_category] not in CATEGORIES:
            counters["dropped_category"] += 1
            continue
        code = row[c_code]
        if code not in KEPT_DETERMINAND_CODES:
            counters["dropped_determinand"] += 1
            continue
        matrix = row[c_matrix]
        if matrix not in DETERMINANDS[code].stored_matrices:  # W and W-DIS for the chemistry; the rule of the code otherwise
            counters["dropped_matrix"] += 1
            continue
        if row[c_status].strip().upper() in MISSING_VALUE_STATUSES:
            counters["dropped_missing_value_status"] += 1
            continue
        parsed_date = _year_month(row[c_date])
        if parsed_date is None:
            counters["dropped_bad_date"] += 1
            continue
        year, month = parsed_date
        if year < min_year:
            counters["dropped_before_min_year"] += 1
            continue
        unit = row[c_unit].strip()
        site = row[c_site].strip()
        if not unit or not site:
            counters["dropped_no_unit_or_site"] += 1
            continue
        below = row[c_loq].strip() in BELOW_LOQ_TRUE
        value = None if below else _to_float(row[c_value].strip())
        if not below and value is None:
            counters["dropped_no_numeric_value"] += 1
            continue
        # Interned strings: the same site, unit and code recur millions of times, so one object each keeps the memory flat.
        key: Key = (
            COUNTRY_CODES[row[c_country]], intern(site), intern(row[c_category]), intern(code), intern(matrix), intern(unit),
            year, month,
        )
        entry = aggregates.get(key)
        if entry is None:
            entry = aggregates[key] = [0.0, 0.0, math.inf, -math.inf, 0.0, 0.0]
        if below or value is None:
            entry[4] += 1
            counters["rows_below_loq"] += 1
        else:
            entry[0] += 1
            entry[1] += value
            entry[2] = min(entry[2], value)
            entry[3] = max(entry[3], value)
            counters["rows_aggregated"] += 1
        if row[c_reliability].strip().upper() in LOWER_RELIABILITY_STATUSES:
            entry[5] += 1
            counters["rows_lower_reliability"] += 1
    counters["groups"] = len(aggregates)
    return aggregates, counters
