"""Writing the Waterbase SQLite store: the tables, and an atomic, deterministic write (rows in key order)."""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from oah.waterbase.aggregate import Aggregates
from oah.waterbase.mapping import location_publishable
from oah.waterbase.spatial import SpatialSite


DDL = """
CREATE TABLE provenance (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE sites (
    site_id TEXT PRIMARY KEY,
    country TEXT NOT NULL,
    category TEXT NOT NULL,
    name TEXT,
    water_body_id TEXT,
    water_body_name TEXT,
    lat REAL,
    lon REAL,
    confidentiality TEXT,
    first_year INTEGER NOT NULL,
    last_year INTEGER NOT NULL,
    n_records INTEGER NOT NULL
);
CREATE TABLE measurements (
    country TEXT NOT NULL,
    site_id TEXT NOT NULL,
    category TEXT NOT NULL,
    determinand TEXT NOT NULL,
    matrix TEXT NOT NULL,
    unit TEXT NOT NULL,
    year INTEGER NOT NULL,
    month INTEGER NOT NULL,
    n INTEGER NOT NULL,
    sum_value REAL NOT NULL,
    min REAL,
    max REAL,
    n_below_loq INTEGER NOT NULL,
    n_lower_reliability INTEGER NOT NULL,
    PRIMARY KEY (site_id, determinand, matrix, unit, year, month)
) WITHOUT ROWID;
CREATE TABLE country_determinands (
    country TEXT NOT NULL,
    determinand TEXT NOT NULL,
    n_sites INTEGER NOT NULL,
    n_records INTEGER NOT NULL,
    PRIMARY KEY (country, determinand)
) WITHOUT ROWID;
CREATE TABLE country_ranges (
    country TEXT PRIMARY KEY,
    first_month TEXT NOT NULL,
    last_month TEXT NOT NULL
) WITHOUT ROWID;
"""
# The measurements table has NO secondary index: the primary key leads with the site, a country-wide read goes through
# the sites of the country (one seek per site), and an extra index would roughly double the file (docs/waterbase_store.md).
INDEXES = """
CREATE INDEX idx_sites_country ON sites (country, category, site_id);
"""


def _month_text(position: int) -> str:
    """``YYYY-MM`` of a month position (``year * 12 + month - 1``)."""
    return f"{position // 12:04d}-{position % 12 + 1:02d}"


# --- writing the store ------------------------------------------------------------------------------------------


def write_store(
    target: Path,
    aggregates: Aggregates,
    spatial: dict[tuple[str, str], SpatialSite],
    provenance: dict[str, str],
    counters: Counter[str],
) -> None:
    """Write the SQLite store atomically (temporary file next to ``target``, then rename)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    temporary.unlink(missing_ok=True)
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("PRAGMA journal_mode=OFF")
        connection.execute("PRAGMA synchronous=OFF")
        connection.executescript(DDL)
        # A site id that appears under two countries keeps the first country in alphabetical order (counted; none in
        # the real build); decided before the rows are written, because they are written in primary-key order.
        site_country: dict[str, str] = {}
        for country, site, *_rest in aggregates:
            known = site_country.get(site)
            if known is None or country < known:
                site_country[site] = country
        categories: dict[str, Counter[str]] = {}
        years: dict[str, list[int]] = {}
        records: Counter[str] = Counter()
        held_sites: dict[tuple[str, str], set[str]] = {}
        held_records: Counter[tuple[str, str]] = Counter()
        ranges: dict[str, list[int]] = {}
        written = 0
        batch: list[tuple[Any, ...]] = []
        # Primary-key order (site, determinand, matrix, unit, year, month): sequential inserts, a compact file, and the
        # same input always gives the same store.
        for key in sorted(aggregates, key=lambda k: (k[1], k[3], k[4], k[5], k[6], k[7], k[0], k[2])):
            country, site, category, code, matrix, unit, year, month = key
            if site_country[site] != country:
                counters["rows_skipped_site_id_in_two_countries"] += 1
                continue
            n, total, low, high, below, unreliable = aggregates[key]
            batch.append((
                country, site, category, code, matrix, unit, year, month, int(n),
                total, low if n else None, high if n else None, int(below), int(unreliable),
            ))
            if len(batch) >= 50_000:
                connection.executemany("INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
                written += len(batch)
                batch = []
            categories.setdefault(site, Counter())[category] += int(n + below)
            span = years.setdefault(site, [year, year])
            span[0], span[1] = min(span[0], year), max(span[1], year)
            records[site] += int(n + below)
            held_sites.setdefault((country, code), set()).add(site)
            held_records[(country, code)] += int(n + below)
            position = year * 12 + month - 1
            span_ym = ranges.setdefault(country, [position, position])
            span_ym[0], span_ym[1] = min(span_ym[0], position), max(span_ym[1], position)
        connection.executemany("INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        written += len(batch)
        connection.executemany(
            "INSERT INTO country_determinands VALUES (?,?,?,?)",
            [(c, d, len(held_sites[(c, d)]), held_records[(c, d)]) for c, d in sorted(held_sites)],
        )
        connection.executemany(
            "INSERT INTO country_ranges VALUES (?,?,?)",
            [(c, _month_text(low), _month_text(high)) for c, (low, high) in sorted(ranges.items())],
        )
        site_rows = []
        confidential = dropped = 0
        for site in sorted(site_country):
            country = site_country[site]
            counts = categories[site]
            if len(counts) > 1:
                counters["sites_with_two_categories"] += 1
            category = sorted(counts, key=lambda name: (-counts[name], name))[0]  # most records, then alphabetical
            place = spatial.get((country, site))
            if place is None:
                counters["sites_without_spatial_row"] += 1
            # Privacy, enforced here as well as in the spatial reader: coordinates are stored only for a site that is
            # free for publication (status F); any other status stores NULL, whatever the source supplied.
            lat, lon = (place.lat, place.lon) if place is not None and location_publishable(place.confidentiality) else (None, None)
            if place is not None and not location_publishable(place.confidentiality):
                confidential += 1
                dropped += int(place.coordinates_withheld or place.lat is not None or place.lon is not None)
            site_rows.append((
                site, country, category,
                place.name if place else None, place.water_body_id if place else None,
                place.water_body_name if place else None, lat, lon,
                place.confidentiality if place else None, years[site][0], years[site][1], records[site],
            ))
            if lat is None or lon is None:
                counters["sites_without_location"] += 1
        connection.executemany("INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", site_rows)
        counters["sites"] = len(site_rows)
        counters["sites_confidential"] = confidential  # held sites whose confidentiality status is not F
        counters["sites_confidential_with_coordinates_dropped"] = dropped  # of those, how many had coordinates in the source
        counters["measurement_rows"] = written
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
