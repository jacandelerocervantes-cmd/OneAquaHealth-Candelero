"""Read-only access to the bathing-water SQLite store (built by ``oah.bathing.build``).

Every query is parameterised and bounded (a page of at most ``MAX_PAGE`` rows, text filters of at most
``MAX_QUERY_CHARS`` characters, a history of at most ``MAX_HISTORY`` seasons), the connection is opened read-only, and a
store that is missing or unreadable is an explicit state (``store_status``): nothing here raises for a missing file.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from oah.bathing.constants import COUNTRY_CODES, DEFAULT_PAGE, MAX_HISTORY, MAX_ID_CHARS, MAX_PAGE, MAX_QUERY_CHARS
from oah.paths import bathing_water_store_path

SUPPORTED_SCHEMA = "1"
NOT_BUILT_DETAIL = (
    "The bathing-water store has not been built. Run scripts/build_bathing_water_store.py "
    "(docs/bathing_water_store.md); until then no bathing-water classification is served."
)
StoreState = Literal["ready", "not-built", "unreadable"]


@dataclass(frozen=True)
class StoreStatus:
    state: StoreState
    detail: str

    @property
    def ready(self) -> bool:
        return self.state == "ready"


@dataclass(frozen=True)
class BathingWater:
    bw_id: str
    country: str
    group_id: str | None
    name: str | None
    type: str | None
    geographical_constraint: str | None
    lat: float | None
    lon: float | None
    profile_url: str | None
    first_season: int
    last_season: int
    n_seasons: int
    latest_quality: str | None
    latest_quality_class: str | None


@dataclass(frozen=True)
class Classification:
    season: int
    quality: str | None
    quality_class: str | None
    monitoring_calendar: str | None
    management: str | None


@dataclass(frozen=True)
class CountrySummary:
    country: str
    bathing_waters: int
    classification_rows: int
    first_season: int
    latest_season: int
    latest_season_counts: dict[str, int] = field(default_factory=dict)  # quality string -> bathing waters, latest season


def _open(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


@contextmanager
def _connection(path: Path | None = None) -> Iterator[sqlite3.Connection | None]:
    """A read-only connection, or None when the store is missing, unreadable or of another schema version."""
    target = path if path is not None else bathing_water_store_path()
    if not target.is_file():
        yield None
        return
    try:
        connection = _open(target)
    except (sqlite3.Error, OSError):
        yield None
        return
    with closing(connection):
        try:
            row = connection.execute("SELECT value FROM provenance WHERE key = 'schema_version'").fetchone()
        except sqlite3.Error:
            yield None
            return
        yield connection if row and row[0] == SUPPORTED_SCHEMA else None


def store_status(path: Path | None = None) -> StoreStatus:
    target = path if path is not None else bathing_water_store_path()
    if not target.is_file():
        return StoreStatus("not-built", NOT_BUILT_DETAIL)
    with _connection(target) as connection:
        if connection is None:
            return StoreStatus("unreadable", "The bathing-water store exists but cannot be read or has another schema version; rebuild it.")
    return StoreStatus("ready", "ready")


def provenance(path: Path | None = None) -> dict[str, str]:
    """The provenance table (source, edition, licence, archive hash, build date, filters, row counts); {} when absent."""
    with _connection(path) as connection:
        if connection is None:
            return {}
        return {str(key): str(value) for key, value in connection.execute("SELECT key, value FROM provenance ORDER BY key")}


def normalise_country(code: str) -> str:
    """Upper-case code with the EL alias read as GR (the way the whole project treats Greece)."""
    upper = code.strip().upper()
    return COUNTRY_CODES.get(upper, upper)


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


_COLUMNS = (
    "bw_id, country, group_id, name, type, geographical_constraint, lat, lon, profile_url, first_season, "
    "last_season, n_seasons, latest_quality, latest_quality_class"
)


def _filter(
    country: str | None, q: str | None, water_type: str | None, quality: str | None
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if country and country.strip():
        clauses.append("country = ?")
        params.append(normalise_country(country[:MAX_QUERY_CHARS]))
    if q and q.strip():
        pattern = _like(q.strip()[:MAX_QUERY_CHARS])
        clauses.append("(bw_id LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\')")
        params.extend([pattern, pattern])
    if water_type and water_type.strip():
        clauses.append("type = ? COLLATE NOCASE")
        params.append(water_type.strip()[:MAX_QUERY_CHARS])
    if quality and quality.strip():
        text = quality.strip()[:MAX_QUERY_CHARS]
        clauses.append("(latest_quality = ? COLLATE NOCASE OR latest_quality_class = ? COLLATE NOCASE)")
        params.extend([text, text])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_bathing_waters(
    country: str | None = None,
    q: str | None = None,
    water_type: str | None = None,
    quality: str | None = None,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
    path: Path | None = None,
) -> tuple[int, list[BathingWater]]:
    """``(total matching, one page)`` ordered by country and identifier; ``(0, [])`` when the store is absent.

    ``quality`` matches the LATEST season's classification, either the whole string (``1 - Excellent``) or its label
    (``Excellent``), case-insensitively.
    """
    page = max(1, min(int(limit), MAX_PAGE))
    skip = max(0, int(offset))
    where, params = _filter(country, q, water_type, quality)
    with _connection(path) as connection:
        if connection is None:
            return 0, []
        total = connection.execute(f"SELECT COUNT(*) FROM sites{where}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT {_COLUMNS} FROM sites{where} ORDER BY country, bw_id LIMIT ? OFFSET ?", [*params, page, skip]
        ).fetchall()
    return int(total), [BathingWater(*row) for row in rows]


def get_bathing_water(bw_id: str, path: Path | None = None) -> BathingWater | None:
    if not bw_id or len(bw_id) > MAX_ID_CHARS:
        return None
    with _connection(path) as connection:
        if connection is None:
            return None
        row = connection.execute(f"SELECT {_COLUMNS} FROM sites WHERE bw_id = ?", [bw_id]).fetchone()
    return BathingWater(*row) if row else None


def history(bw_id: str, path: Path | None = None) -> list[Classification]:
    """The classification of one bathing water by season (oldest first, at most ``MAX_HISTORY`` seasons)."""
    if not bw_id or len(bw_id) > MAX_ID_CHARS:
        return []
    with _connection(path) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            "SELECT season, quality, quality_class, monitoring_calendar, management FROM classifications "
            "WHERE bw_id = ? ORDER BY season LIMIT ?",
            [bw_id, MAX_HISTORY],
        ).fetchall()
    return [Classification(*row) for row in rows]


def located_counts(path: Path | None = None) -> dict[str, int]:
    """Per country the number of bathing waters that have coordinates; ``{}`` when the store is absent."""
    with _connection(path) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            "SELECT country, COUNT(*) FROM sites WHERE lat IS NOT NULL AND lon IS NOT NULL GROUP BY country ORDER BY country"
        ).fetchall()
    return {str(country): int(count) for country, count in rows}


def countries_summary(path: Path | None = None) -> list[CountrySummary]:
    """One summary per country: bathing waters, classification rows, season range and the latest season's class counts."""
    with _connection(path) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            "SELECT s.country, COUNT(DISTINCT s.bw_id), COUNT(*), MIN(c.season), MAX(c.season) "
            "FROM sites s JOIN classifications c ON c.bw_id = s.bw_id GROUP BY s.country ORDER BY s.country"
        ).fetchall()
        latest: dict[str, dict[str, int]] = {}
        for country, last in ((row[0], row[4]) for row in rows):
            counts = connection.execute(
                "SELECT COALESCE(c.quality, '(blank)'), COUNT(*) FROM sites s JOIN classifications c ON c.bw_id = s.bw_id "
                "WHERE s.country = ? AND c.season = ? GROUP BY 1 ORDER BY 1",
                [country, last],
            ).fetchall()
            latest[country] = {str(quality): int(count) for quality, count in counts}
    return [
        CountrySummary(country, int(sites), int(n), int(first), int(last), latest.get(country, {}))
        for country, sites, n, first, last in rows
    ]


def _country_type_clause(country: str, water_type: str | None) -> tuple[str, list[object]]:
    clause = "s.country = ?"
    params: list[object] = [normalise_country(country[:MAX_QUERY_CHARS])]
    if water_type and water_type.strip():
        clause += " AND s.type = ? COLLATE NOCASE"
        params.append(water_type.strip()[:MAX_QUERY_CHARS])
    return clause, params


def season_class_counts(
    country: str, season: int, water_type: str | None = None, path: Path | None = None
) -> dict[str, int]:
    """The file's own quality strings (``(blank)`` for a missing one) -> bathing waters of ``country`` classified in ``season``."""
    clause, params = _country_type_clause(country, water_type)
    with _connection(path) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            "SELECT COALESCE(c.quality, '(blank)'), COUNT(*) FROM sites s JOIN classifications c "
            f"ON c.bw_id = s.bw_id AND c.season = ? WHERE {clause} GROUP BY 1 ORDER BY 1",
            [int(season), *params],
        ).fetchall()
    return {str(quality): int(count) for quality, count in rows}


def season_pair_counts(
    country: str, season_a: int, season_b: int, water_type: str | None = None, path: Path | None = None
) -> dict[tuple[str, str], int]:
    """``(quality in season A, quality in season B) -> bathing waters`` for the bathing waters of ``country`` classified in BOTH seasons."""
    clause, params = _country_type_clause(country, water_type)
    with _connection(path) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            "SELECT COALESCE(a.quality, '(blank)'), COALESCE(b.quality, '(blank)'), COUNT(*) FROM sites s "
            "JOIN classifications a ON a.bw_id = s.bw_id AND a.season = ? "
            "JOIN classifications b ON b.bw_id = s.bw_id AND b.season = ? "
            f"WHERE {clause} GROUP BY 1, 2 ORDER BY 1, 2",
            [int(season_a), int(season_b), *params],
        ).fetchall()
    return {(str(first), str(second)): int(count) for first, second, count in rows}
