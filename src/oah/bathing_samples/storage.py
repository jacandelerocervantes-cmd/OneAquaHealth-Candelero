"""Store stage of the samples build: the saved pages into a temporary raw table, then the final SQLite store written
atomically (temporary file, then rename), rows in key order."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from oah.bathing_samples.constants import INDEX_KINDS, INDEX_QUANTIFIED
from oah.bathing_samples.extract import ExtractionError, PrefixResult, _page_path, _read_json
from oah.bathing_samples.normalise import Tallies, normalise_row


DDL = """
CREATE TABLE provenance (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE samples (
    bw_id TEXT NOT NULL,
    sample_date TEXT NOT NULL,
    uid INTEGER NOT NULL,
    country TEXT NOT NULL,
    season INTEGER NOT NULL,
    ec_value INTEGER,
    ec_status TEXT,
    ec_kind TEXT NOT NULL,
    ie_value INTEGER,
    ie_status TEXT,
    ie_kind TEXT NOT NULL,
    sample_status TEXT,
    obs_status TEXT,
    has_remarks INTEGER NOT NULL,
    PRIMARY KEY (bw_id, sample_date, uid)
) WITHOUT ROWID;
CREATE TABLE sites (
    bw_id TEXT PRIMARY KEY,
    country TEXT NOT NULL,
    n_samples INTEGER NOT NULL,
    first_date TEXT NOT NULL,
    last_date TEXT NOT NULL,
    first_season INTEGER NOT NULL,
    last_season INTEGER NOT NULL
) WITHOUT ROWID;
CREATE TABLE country_summary (
    country TEXT PRIMARY KEY,
    bathing_waters INTEGER NOT NULL,
    n_samples INTEGER NOT NULL,
    first_date TEXT NOT NULL,
    last_date TEXT NOT NULL,
    first_season INTEGER NOT NULL,
    last_season INTEGER NOT NULL,
    n_quantified_ec INTEGER NOT NULL,
    n_quantified_ie INTEGER NOT NULL,
    first_quantified_ec TEXT,
    last_quantified_ec TEXT,
    first_quantified_ie TEXT,
    last_quantified_ie TEXT
) WITHOUT ROWID;
"""
# Schema 2 (country comparison speed-up, docs/bathing_samples_store.md): three covering indexes, none of them needs a lookup in
# the table. ``idx_samples_kinds`` answers the per-kind counts of a country and window from the index alone. The two PARTIAL
# indexes hold only the quantified values (kinds Q and C) of one indicator, in the order (country, bathing water, value), so a
# country is read as one sequential scan, bathing water by bathing water with the values already sorted (the exact medians).
# The reader names them (``INDEXED BY``), so a store without them cannot be read: the schema version says so.
INDEXES = "\n".join(
    [
        f"CREATE INDEX {INDEX_KINDS} ON samples (country, sample_date, ec_kind, ie_kind);",
        *(
            f"CREATE INDEX {name} ON samples (country, bw_id, {prefix}_value, sample_date) WHERE {prefix}_kind IN ('Q','C');"
            for prefix, name in INDEX_QUANTIFIED.items()
        ),
    ]
)
RAW_DDL = """
CREATE TABLE raw (
    uid INTEGER PRIMARY KEY,
    bw_id TEXT NOT NULL, country TEXT NOT NULL, season INTEGER NOT NULL, sample_date TEXT NOT NULL,
    ec_value INTEGER, ec_status TEXT, ec_kind TEXT NOT NULL,
    ie_value INTEGER, ie_status TEXT, ie_kind TEXT NOT NULL,
    sample_status TEXT, obs_status TEXT, has_remarks INTEGER NOT NULL
);
"""


def _load_raw(work_dir: Path, results: list[PrefixResult], tallies: Tallies) -> Path:
    """Normalise the saved pages into a temporary SQLite table in the work directory (flat memory, one page at a time)."""
    raw_path = work_dir / "raw.sqlite"
    raw_path.unlink(missing_ok=True)
    connection = sqlite3.connect(raw_path)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(RAW_DDL)
        for result in results:
            for seq in range(1, result.pages + 1):
                data = _read_json(_page_path(work_dir, result.prefix, seq))
                if data is None or not isinstance(data.get("rows"), list):
                    raise ExtractionError(f"the saved page {result.prefix}-{seq:05d} cannot be read; rebuild with --restart")
                batch = [
                    sample.as_tuple()
                    for row in data["rows"]
                    if isinstance(row, dict) and (sample := normalise_row(row, result.prefix, tallies)) is not None
                ]
                before = connection.total_changes
                connection.executemany("INSERT OR IGNORE INTO raw VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                tallies.counters["duplicate_uid"] += len(batch) - (connection.total_changes - before)
        connection.commit()
    except BaseException:
        connection.close()
        raw_path.unlink(missing_ok=True)
        raise
    connection.close()
    return raw_path


def write_store(target: Path, raw_path: Path, provenance: dict[str, str]) -> dict[str, int]:
    """Write the final store atomically from the raw table; returns the table sizes."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(DDL)
        connection.execute("ATTACH DATABASE ? AS source", (str(raw_path),))
        connection.execute(
            "INSERT INTO samples SELECT bw_id, sample_date, uid, country, season, ec_value, ec_status, ec_kind, ie_value, "
            "ie_status, ie_kind, sample_status, obs_status, has_remarks FROM source.raw ORDER BY bw_id, sample_date, uid"
        )
        connection.commit()  # a database cannot be detached inside a transaction
        connection.execute("DETACH DATABASE source")
        connection.execute(
            "INSERT INTO sites SELECT bw_id, MIN(country), COUNT(*), MIN(sample_date), MAX(sample_date), MIN(season), MAX(season) "
            "FROM samples GROUP BY bw_id ORDER BY bw_id"
        )
        connection.execute(
            "INSERT INTO country_summary SELECT country, COUNT(DISTINCT bw_id), COUNT(*), MIN(sample_date), MAX(sample_date), "
            "MIN(season), MAX(season), SUM(CASE WHEN ec_kind IN ('Q','C') THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN ie_kind IN ('Q','C') THEN 1 ELSE 0 END), "
            "MIN(CASE WHEN ec_kind IN ('Q','C') THEN sample_date END), MAX(CASE WHEN ec_kind IN ('Q','C') THEN sample_date END), "
            "MIN(CASE WHEN ie_kind IN ('Q','C') THEN sample_date END), MAX(CASE WHEN ie_kind IN ('Q','C') THEN sample_date END) "
            "FROM samples GROUP BY country ORDER BY country"
        )
        sizes = {
            "samples": int(connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0]),
            "bathing_waters": int(connection.execute("SELECT COUNT(*) FROM sites").fetchone()[0]),
            "site_dates_with_several_samples": int(
                connection.execute(
                    "SELECT COUNT(*) FROM (SELECT 1 FROM samples GROUP BY bw_id, sample_date HAVING COUNT(*) > 1)"
                ).fetchone()[0]
            ),
        }
        provenance = {**provenance, "table_sizes": json.dumps(sizes, sort_keys=True)}
        connection.executemany("INSERT INTO provenance VALUES (?,?)", sorted(provenance.items()))
        connection.executescript(INDEXES)
        connection.commit()
    except BaseException:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    os.replace(temporary, target)
    return sizes
