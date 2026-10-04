"""Build the bathing-water SQLite store from the EEA archive (``scripts/build_bathing_water_store.py`` is the command line).

Streams the assessment sheet of the xlsx inside the archive (``oah.bathing.xlsx``, standard library only), keeps the
rows of Greece (EL in some files, GR in others: both stored as GR), Italy and Norway for ALL seasons, and writes two
tables: ``sites`` (one row per bathing water, attributes of its latest season) and ``classifications`` (one row per
bathing water and season). The file holds the per-season CLASSIFICATION only: no E. coli or intestinal enterococci
concentration exists in it, so none is stored. Unknown ``quality`` values are kept as they are and reported.

The write is atomic (temporary file, then rename) and deterministic: rows are written in key order, so the same input
gives the same tables (only the provenance build date differs).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from oah.bathing.constants import (
    ATTRIBUTION,
    COUNTRY_CODES,
    EDITION,
    EXPECTED_COLUMNS,
    KNOWN_QUALITY_VALUES,
    LICENCE,
    PLACEHOLDER_NAME,
    README_BACTERIA_SENTENCE,
    README_CLASSES_SENTENCE,
    README_SAMPLES_SENTENCE,
    SHEET_NAME,
    SOURCE_LABEL,
    SOURCE_URL,
    XLSX_NAME,
    quality_class,
    safe_profile_url,
)
from oah.bathing.xlsx import XlsxError, iter_sheet_rows, open_workbook_in_archive, read_shared_strings
from oah.timeutil import format_utc, utc_now

SCHEMA_VERSION = "1"
MIN_SEASON, MAX_SEASON = 1900, 2100

DDL = """
CREATE TABLE provenance (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sites (
    bw_id TEXT PRIMARY KEY,
    country TEXT NOT NULL,
    group_id TEXT,
    name TEXT,
    type TEXT,
    geographical_constraint TEXT,
    lat REAL,
    lon REAL,
    profile_url TEXT,
    first_season INTEGER NOT NULL,
    last_season INTEGER NOT NULL,
    n_seasons INTEGER NOT NULL,
    latest_quality TEXT,
    latest_quality_class TEXT
);
CREATE TABLE classifications (
    bw_id TEXT NOT NULL,
    season INTEGER NOT NULL,
    quality TEXT,
    quality_class TEXT,
    monitoring_calendar TEXT,
    management TEXT,
    PRIMARY KEY (bw_id, season)
) WITHOUT ROWID;
"""
INDEXES = """
CREATE INDEX idx_sites_country ON sites (country, bw_id);
CREATE INDEX idx_sites_type ON sites (country, type);
CREATE INDEX idx_sites_quality ON sites (country, latest_quality);
"""


@dataclass(frozen=True)
class Row:
    """One kept data row of the sheet (one bathing water in one season)."""

    country: str
    bw_id: str
    season: int
    quality: str | None
    calendar: str | None
    management: str | None
    group_id: str | None
    name: str | None
    type: str | None
    constraint: str | None
    lat: float | None
    lon: float | None
    profile_url: str | None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _name(value: Any) -> str | None:
    text = _text(value)
    return None if text is None or text.upper() == PLACEHOLDER_NAME else text


def _float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _coordinate(value: Any, limit: float) -> float | None:
    number = _float(value)
    return number if number is not None and -limit <= number <= limit else None


def _season(value: Any) -> int | None:
    number = _float(value)
    if number is None or number != int(number):
        return None
    season = int(number)
    return season if MIN_SEASON <= season <= MAX_SEASON else None


def _header_positions(row: dict[int, Any]) -> dict[str, int]:
    found = {str(value).strip(): index for index, value in row.items() if value is not None}
    missing = [name for name in EXPECTED_COLUMNS if name not in found]
    if missing:
        raise XlsxError(f"The assessment sheet lacks the column(s) {missing}; the layout changed.")
    return {name: found[name] for name in EXPECTED_COLUMNS}


def read_records(rows: Iterable[tuple[int, dict[int, Any]]], counters: Counter[str]) -> list[Row]:
    """Filter the streamed sheet rows (header first) into kept ``Row`` records; every drop is counted."""
    iterator = iter(rows)
    header = next(iterator, None)
    if header is None:
        raise XlsxError("The assessment sheet is empty.")
    position = _header_positions(header[1])
    kept: list[Row] = []
    for _number, cells in iterator:
        counters["rows_scanned"] += 1
        country = COUNTRY_CODES.get((_text(cells.get(position["countryCode"])) or "").upper())
        if country is None:
            counters["rows_other_countries"] += 1
            continue
        counters["rows_country_kept"] += 1
        bw_id = _text(cells.get(position["bathingWaterIdentifier"]))
        if bw_id is None:
            counters["dropped_no_identifier"] += 1
            continue
        season = _season(cells.get(position["season"]))
        if season is None:
            counters["dropped_bad_season"] += 1
            continue
        raw_profile = _text(cells.get(position["bwProfile"]))
        profile = safe_profile_url(raw_profile)
        if raw_profile is not None and profile is None:
            counters["profile_url_not_http"] += 1
        lat = _coordinate(cells.get(position["lat"]), 90.0)
        lon = _coordinate(cells.get(position["lon"]), 180.0)
        if lat is None or lon is None:
            if cells.get(position["lat"]) is not None or cells.get(position["lon"]) is not None:
                counters["rows_coordinates_invalid_or_partial"] += 1
            lat = lon = None
        quality = _text(cells.get(position["quality"]))
        if quality is None:
            counters["rows_without_quality"] += 1
        kept.append(
            Row(
                country=country, bw_id=bw_id, season=season, quality=quality,
                calendar=_text(cells.get(position["monitoringCalendar"])),
                management=_text(cells.get(position["management"])),
                group_id=_text(cells.get(position["groupIdentifier"])),
                name=_name(cells.get(position["bathingWaterName"])),
                type=_text(cells.get(position["bathingWaterType"])),
                constraint=_text(cells.get(position["geographicalConstraint"])),
                lat=lat, lon=lon, profile_url=profile,
            )
        )
    return kept


def _tally(rows: Iterable[Row]) -> dict[str, dict[str, int]]:
    tallies: dict[str, Counter[str]] = {
        "quality": Counter(), "type": Counter(), "monitoring_calendar": Counter(), "management": Counter(),
    }
    for row in rows:
        tallies["quality"][row.quality or "(blank)"] += 1
        tallies["type"][row.type or "(blank)"] += 1
        tallies["monitoring_calendar"][row.calendar or "(blank)"] += 1
        tallies["management"][row.management or "(blank)"] += 1
    return {name: dict(sorted(counter.items())) for name, counter in tallies.items()}


def write_store(target: Path, records: list[Row], provenance: dict[str, str], counters: Counter[str]) -> None:
    """Write the SQLite store atomically (temporary file next to ``target``, then rename)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(DDL)

        by_site: dict[str, list[Row]] = {}
        # The full value tuple is part of the key, so which of two conflicting duplicate rows wins never depends on the
        # order of the input (the real 2025 v1.0 file has none).
        for row in sorted(records, key=lambda r: (r.bw_id, r.season, r.country, r.quality or "", r.calendar or "", r.management or "")):
            by_site.setdefault(row.bw_id, []).append(row)

        site_rows: list[tuple[Any, ...]] = []
        class_rows: list[tuple[Any, ...]] = []
        for bw_id in sorted(by_site):
            history = by_site[bw_id]
            if len({row.country for row in history}) > 1:
                counters["bathing_waters_in_two_countries"] += 1
            country = history[0].country
            seen: dict[int, Row] = {}
            for row in history:
                if row.country != country:
                    continue  # a conflicting country keeps the first one (counted above; none expected)
                earlier = seen.get(row.season)
                if earlier is None:
                    seen[row.season] = row
                    continue
                counters["duplicate_site_season_rows"] += 1
                if (earlier.quality, earlier.calendar, earlier.management) != (row.quality, row.calendar, row.management):
                    counters["duplicate_site_season_rows_conflicting"] += 1
            seasons = [seen[season] for season in sorted(seen)]
            latest = seasons[-1]
            located = next((row for row in reversed(seasons) if row.lat is not None), None)
            if located is None:
                counters["bathing_waters_without_coordinates"] += 1
            for row in seasons:
                class_rows.append(
                    (bw_id, row.season, row.quality, quality_class(row.quality), row.calendar, row.management)
                )
            site_rows.append((
                bw_id, country, latest.group_id, latest.name, latest.type, latest.constraint,
                located.lat if located else None, located.lon if located else None, latest.profile_url,
                seasons[0].season, latest.season, len(seasons), latest.quality, quality_class(latest.quality),
            ))
        connection.executemany("INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", site_rows)
        connection.executemany("INSERT INTO classifications VALUES (?,?,?,?,?,?)", class_rows)
        counters["bathing_waters"] = len(site_rows)
        counters["classification_rows"] = len(class_rows)
        provenance = {**provenance, "row_counts": json.dumps(dict(sorted(counters.items())), sort_keys=True)}
        connection.executemany("INSERT INTO provenance VALUES (?,?)", sorted(provenance.items()))
        connection.executescript(INDEXES)
        connection.commit()
    except BaseException:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    os.replace(temporary, target)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 24), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_store(
    archive: Path, target: Path, work_dir: Path, *, build_date: str | None = None, sheet_name: str = SHEET_NAME
) -> dict[str, Any]:
    """Build the store from the archive and return the counters and value tallies (also kept in the provenance)."""
    if not archive.is_file():
        raise FileNotFoundError(f"Bathing-water archive not found: {archive.name}. See docs/bathing_water_store.md.")
    counters: Counter[str] = Counter()
    with open_workbook_in_archive(archive, XLSX_NAME, work_dir) as workbook:
        strings = read_shared_strings(workbook)
        records = read_records(iter_sheet_rows(workbook, sheet_name, strings), counters)
    if not records:
        raise RuntimeError("No row survived the country filter; refusing to write an empty store.")
    tallies = _tally(records)
    unknown = sorted(value for value in tallies["quality"] if value != "(blank)" and value not in KNOWN_QUALITY_VALUES)
    countries_in_file = sorted({row.country for row in records})
    provenance = {
        "schema_version": SCHEMA_VERSION,
        "source": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "edition": EDITION,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "archive_name": archive.name,
        "archive_bytes": str(archive.stat().st_size),
        "archive_sha256": compute_sha256(archive),
        "archive_sha256_source": "computed",
        "workbook": XLSX_NAME,
        "sheet": sheet_name,
        "build_date_utc": build_date or format_utc(utc_now()),
        "filters": json.dumps(
            {
                "countries": sorted(COUNTRY_CODES),
                "countries_stored": countries_in_file,
                "seasons": "all",
                "note": "EL and GR are both stored as GR",
            },
            sort_keys=True,
        ),
        "content": "per-season classification only; no E. coli or intestinal enterococci concentration is in the file",
        "readme_statements": json.dumps(
            [README_BACTERIA_SENTENCE, README_CLASSES_SENTENCE, README_SAMPLES_SENTENCE], sort_keys=False
        ),
        "value_counts": json.dumps(tallies, sort_keys=True),
        "unknown_quality_values": json.dumps(unknown),
    }
    write_store(target, records, provenance, counters)
    result: dict[str, Any] = dict(counters)
    result["unknown_quality_values"] = unknown
    result["value_counts"] = tallies
    return result
