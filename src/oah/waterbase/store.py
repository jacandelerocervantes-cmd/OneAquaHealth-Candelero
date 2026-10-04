"""Read-only access to the Waterbase SQLite store (built by ``oah.waterbase.build``).

Every query is parameterised and bounded (a page size of at most ``MAX_PAGE`` rows, a text filter of at most
``MAX_QUERY_CHARS`` characters), the connection is opened read-only, and a store that is missing or unreadable is an
explicit state (``store_status``) that callers turn into a clear message: nothing here raises for a missing file.

The store is MONTHLY (schema version 3): per site, determinand, matrix, unit and month it holds ``n``, the sum, the
minimum, the maximum and the below-LOQ and lower-reliability counts. The annual view (``site_series``) is computed from
the months, so an annual mean is the sum of the monthly sums over the sum of the counts (exact).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from oah.paths import waterbase_store_path
from oah.waterbase.mapping import CATEGORIES, FREE_FOR_PUBLICATION, group_of, location_publishable

DEFAULT_PAGE = 200
MAX_PAGE = 500
MAX_SERIES = 2000  # rows of one site's annual or monthly series (a site has a few hundred at most)
MAX_SCOPE_ROWS = 2_000_000  # monthly rows read for one period comparison (the real store holds a few million in all)
MAX_WINDOWS = 8  # month windows of one scope read
MAX_QUERY_CHARS = 64
SUPPORTED_SCHEMA = "3"
LEGACY_SCHEMAS = frozenset({"1", "2"})  # older layouts this code recognises: reported as rebuild-required, never read
MAX_DETERMINAND_FILTER = 40  # codes of one group filter (the store holds about thirty determinands)
NOT_BUILT_DETAIL = (
    "The Waterbase store has not been built. Run scripts/build_waterbase_store.py (docs/waterbase_store.md); "
    "until then only the sandbox sites are served."
)
REBUILD_DETAIL = (
    "The Waterbase store was built with an older layout (before schema version 3, which adds monthly resolution; "
    "version 1 also lacked the solids-turbidity and organic-matter groups). Run scripts/build_waterbase_store.py again "
    "(docs/waterbase_store.md); until then it is not served."
)

StoreState = Literal["ready", "not-built", "unreadable", "rebuild-required"]
CategoryName = Literal["river", "lake"]
_CATEGORY_CODE = {name: code for code, name in CATEGORIES.items()}


@dataclass(frozen=True)
class StoreStatus:
    state: StoreState
    detail: str

    @property
    def ready(self) -> bool:
        return self.state == "ready"


@dataclass(frozen=True)
class WaterbaseSite:
    site_id: str
    country: str
    category: str  # RW or LW
    name: str | None
    water_body_id: str | None
    water_body_name: str | None
    lat: float | None
    lon: float | None
    confidentiality: str | None
    first_year: int
    last_year: int
    n_records: int

    @property
    def has_location(self) -> bool:
        return self.lat is not None and self.lon is not None

    @property
    def water_category(self) -> CategoryName:
        return "river" if self.category == "RW" else "lake"


@dataclass(frozen=True)
class AnnualRow:
    country: str
    site_id: str
    category: str
    determinand: str
    matrix: str
    unit: str
    year: int
    n: int
    mean: float | None
    min: float | None
    max: float | None
    n_below_loq: int
    n_lower_reliability: int


@dataclass(frozen=True)
class MonthlyRow(AnnualRow):
    """One month of one site and determinand: ``n`` quantified samples whose mean is ``mean`` (= sum / n)."""

    month: int = 0
    sum_value: float = 0.0  # the sum of the quantified samples, so any coarser mean is exact (sum of sums / sum of n)


@dataclass(frozen=True)
class CountrySummary:
    country: str
    sites: int
    river_sites: int
    lake_sites: int
    sites_without_location: int
    first_year: int
    last_year: int
    records: int
    parameter_groups: tuple[str, ...] = ()  # groups of the determinands the country holds (oah.waterbase.mapping.GROUPS)
    first_month: str | None = None  # first and last month with any kept record in the country, YYYY-MM
    last_month: str | None = None


def _open(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


@contextmanager
def _connection(path: Path | None = None) -> Iterator[sqlite3.Connection | None]:
    """A read-only connection, or None when the store is missing, unreadable or of another schema version."""
    target = path if path is not None else waterbase_store_path()
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
    target = path if path is not None else waterbase_store_path()
    if not target.is_file():
        return StoreStatus("not-built", NOT_BUILT_DETAIL)
    version = _schema_version(target)
    if version in LEGACY_SCHEMAS:
        return StoreStatus("rebuild-required", REBUILD_DETAIL)
    with _connection(target) as connection:
        if connection is None:
            return StoreStatus("unreadable", "The Waterbase store exists but cannot be read or has another schema version; rebuild it.")
    return StoreStatus("ready", "ready")


def _schema_version(target: Path) -> str | None:
    try:
        connection = _open(target)
    except (sqlite3.Error, OSError):
        return None
    with closing(connection):
        try:
            row = connection.execute("SELECT value FROM provenance WHERE key = 'schema_version'").fetchone()
        except sqlite3.Error:
            return None
    return str(row[0]) if row else None


def provenance(path: Path | None = None) -> dict[str, str]:
    """The provenance table (source, edition, licence, archive hash, build date, filters, row counts); {} when absent."""
    with _connection(path) as connection:
        if connection is None:
            return {}
        return {str(key): str(value) for key, value in connection.execute("SELECT key, value FROM provenance ORDER BY key")}


def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _site(row: tuple[object, ...]) -> WaterbaseSite:
    """A site from its row. Privacy: a site that is not free for publication (status other than ``F``) has NO location,
    whatever the stored values are (the build already stores NULL; this is the second, independent line of defence)."""
    site = WaterbaseSite(*row)  # type: ignore[arg-type]
    if not location_publishable(site.confidentiality) and (site.lat is not None or site.lon is not None):
        return replace(site, lat=None, lon=None)
    return site


# True (1) only for a site free for publication; NULL status gives 0 (restricted by default). Mirrors ``location_publishable``.
_PUBLISHABLE_SQL = f"COALESCE(TRIM(confidentiality) = '{FREE_FOR_PUBLICATION}', 0)"

_SITE_COLUMNS = (
    "site_id, country, category, name, water_body_id, water_body_name, lat, lon, confidentiality, "
    "first_year, last_year, n_records"
)


def _site_filter(country: str | None, category: CategoryName | None, q: str | None) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    if country:
        clauses.append("country = ?")
        params.append(country.strip().upper())
    if category:
        clauses.append("category = ?")
        params.append(_CATEGORY_CODE[category])
    if q and q.strip():
        pattern = _like(q.strip()[:MAX_QUERY_CHARS])
        clauses.append(
            "(site_id LIKE ? ESCAPE '\\' OR name LIKE ? ESCAPE '\\' OR water_body_name LIKE ? ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern])
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def list_sites(
    country: str | None = None,
    category: CategoryName | None = None,
    q: str | None = None,
    limit: int = DEFAULT_PAGE,
    offset: int = 0,
    path: Path | None = None,
) -> tuple[int, list[WaterbaseSite]]:
    """``(total matching, one page of sites)`` ordered by country and site id; ``(0, [])`` when the store is absent."""
    page = max(1, min(int(limit), MAX_PAGE))
    skip = max(0, int(offset))
    where, params = _site_filter(country, category, q)
    with _connection(path) as connection:
        if connection is None:
            return 0, []
        total = connection.execute(f"SELECT COUNT(*) FROM sites{where}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT {_SITE_COLUMNS} FROM sites{where} ORDER BY country, site_id LIMIT ? OFFSET ?",
            [*params, page, skip],
        ).fetchall()
    return int(total), [_site(row) for row in rows]


def get_site(site_id: str, path: Path | None = None) -> WaterbaseSite | None:
    if not site_id or len(site_id) > 128:
        return None
    with _connection(path) as connection:
        if connection is None:
            return None
        row = connection.execute(f"SELECT {_SITE_COLUMNS} FROM sites WHERE site_id = ?", [site_id]).fetchone()
    return _site(row) if row else None


def _series_filter(
    site_id: str, determinand: str | None, matrix: str | None, determinands: Sequence[str] | None
) -> tuple[list[str], list[object]] | None:
    """The WHERE clauses and parameters shared by the annual and the monthly series; None matches nothing."""
    clauses: list[str] = ["site_id = ?"]
    params: list[object] = [site_id]
    if determinand:
        clauses.append("determinand = ?")
        params.append(determinand)
    if determinands is not None:
        codes = list(determinands)[:MAX_DETERMINAND_FILTER]
        if not codes:
            return None
        clauses.append("determinand IN (" + ",".join("?" for _ in codes) + ")")
        params.extend(codes)
    if matrix:
        clauses.append("matrix = ?")
        params.append(matrix)
    return clauses, params


def _annual(row: tuple[object, ...]) -> AnnualRow:
    country, site, category, code, matrix, unit, year, n, total, low, high, below, unreliable = row
    count = int(n)  # type: ignore[call-overload]
    return AnnualRow(
        country, site, category, code, matrix, unit, year,  # type: ignore[arg-type]
        count, (float(total) / count) if count else None, low, high, below, unreliable,  # type: ignore[arg-type]
    )


def site_series(
    site_id: str,
    determinand: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
    limit: int = DEFAULT_PAGE,
    path: Path | None = None,
    matrix: str | None = None,
    determinands: Sequence[str] | None = None,
) -> tuple[int, list[AnnualRow]]:
    """``(total matching, rows)`` of one site's ANNUAL aggregates, by year, determinand code(s) and matrix.

    The store is monthly (schema 3); each annual row is computed from its months: ``n`` and the below-LOQ counts are
    summed, the mean is the sum of the monthly sums over the sum of the counts (exact), min and max are the extremes.

    ``determinands`` (at most ``MAX_DETERMINAND_FILTER`` codes, for a group filter) narrows to those codes; an empty
    list matches nothing.
    """
    page = max(1, min(int(limit), MAX_SERIES))
    base = _series_filter(site_id, determinand, matrix, determinands)
    if base is None:
        return 0, []
    clauses, params = base
    if year_from is not None:
        clauses.append("year >= ?")
        params.append(int(year_from))
    if year_to is not None:
        clauses.append("year <= ?")
        params.append(int(year_to))
    where = " WHERE " + " AND ".join(clauses)
    grouping = " GROUP BY site_id, determinand, matrix, unit, year"
    with _connection(path) as connection:
        if connection is None:
            return 0, []
        total = connection.execute(f"SELECT COUNT(*) FROM (SELECT 1 FROM measurements{where}{grouping})", params).fetchone()[0]
        rows = connection.execute(
            "SELECT MIN(country), site_id, MIN(category), determinand, matrix, unit, year, SUM(n), SUM(sum_value), "
            "MIN(min), MAX(max), SUM(n_below_loq), SUM(n_lower_reliability) "
            f"FROM measurements{where}{grouping} ORDER BY year, determinand, matrix, unit LIMIT ?",
            [*params, page],
        ).fetchall()
    return int(total), [_annual(row) for row in rows]


def month_position(year: int, month: int) -> int:
    """The month as one integer, ``year * 12 + month - 1`` (consecutive months differ by one)."""
    return int(year) * 12 + int(month) - 1


_MONTHLY_COLUMNS = (
    "country, site_id, category, determinand, matrix, unit, year, n, sum_value, min, max, n_below_loq, "
    "n_lower_reliability, month"
)


def _monthly(row: tuple[object, ...]) -> MonthlyRow:
    country, site, category, code, matrix, unit, year, n, total, low, high, below, unreliable, month = row
    count = int(n)  # type: ignore[call-overload]
    return MonthlyRow(
        country, site, category, code, matrix, unit, year,  # type: ignore[arg-type]
        count, (float(total) / count) if count else None, low, high, below, unreliable,  # type: ignore[arg-type]
        month, float(total),  # type: ignore[arg-type]
    )


def site_monthly_series(
    site_id: str,
    determinand: str | None = None,
    from_month: int | None = None,
    to_month: int | None = None,
    limit: int = DEFAULT_PAGE,
    path: Path | None = None,
    matrix: str | None = None,
    determinands: Sequence[str] | None = None,
) -> tuple[int, list[MonthlyRow]]:
    """``(total matching, rows)`` of one site's MONTHLY aggregates, oldest first, at most ``limit`` (and ``MAX_SERIES``) rows.

    ``from_month`` and ``to_month`` are month positions (``month_position``), both included.
    """
    page = max(1, min(int(limit), MAX_SERIES))
    base = _series_filter(site_id, determinand, matrix, determinands)
    if base is None:
        return 0, []
    clauses, params = base
    if from_month is not None:
        clauses.append("year * 12 + month - 1 >= ?")
        params.append(int(from_month))
    if to_month is not None:
        clauses.append("year * 12 + month - 1 <= ?")
        params.append(int(to_month))
    where = " WHERE " + " AND ".join(clauses)
    with _connection(path) as connection:
        if connection is None:
            return 0, []
        total = connection.execute(f"SELECT COUNT(*) FROM measurements{where}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT {_MONTHLY_COLUMNS} FROM measurements{where} ORDER BY year, month, determinand, matrix, unit LIMIT ?",
            [*params, page],
        ).fetchall()
    return int(total), [_monthly(row) for row in rows]


def scope_monthly_rows(
    determinand: str,
    matrix: str,
    windows: Sequence[tuple[int, int]],
    *,
    site_id: str | None = None,
    country: str | None = None,
    path: Path | None = None,
) -> tuple[list[MonthlyRow], tuple[int, int] | None, bool]:
    """``(rows, data range, truncated)`` of ONE determinand in ONE matrix for one site or every site of one country.

    ``rows`` are the monthly aggregates inside any of the ``windows`` (month positions, both ends included); the data
    range is ``(first, last)`` month position over ALL months the scope holds for this determinand and matrix
    (None when it holds none), whatever the windows. Exactly one of ``site_id`` and ``country`` is given. Parameterised,
    read-only; at most ``MAX_SCOPE_ROWS`` rows are returned (``truncated`` says so, and the caller must not trust the
    result then).
    """
    if (site_id is None) == (country is None):
        raise ValueError("give exactly one of site_id and country")
    base = ["determinand = ?", "matrix = ?"]
    params: list[object] = [determinand, matrix]
    if site_id is not None:
        base.append("site_id = ?")
        params.append(site_id)
    else:
        base.append("site_id IN (SELECT site_id FROM sites WHERE country = ?)")
        params.append((country or "").strip().upper())
    bounds: list[str] = []
    window_params: list[object] = []
    for first, last in list(windows)[:MAX_WINDOWS]:
        bounds.append("(year * 12 + month - 1 BETWEEN ? AND ?)")
        window_params.extend([int(first), int(last)])
    if not bounds:
        return [], None, False
    clauses = [*base, "(" + " OR ".join(bounds) + ")"]
    with _connection(path) as connection:
        if connection is None:
            return [], None, False
        span = connection.execute(
            "SELECT MIN(year * 12 + month - 1), MAX(year * 12 + month - 1) FROM measurements WHERE " + " AND ".join(base),
            params,
        ).fetchone()
        rows = connection.execute(
            f"SELECT {_MONTHLY_COLUMNS} FROM measurements WHERE " + " AND ".join(clauses) + " LIMIT ?",
            [*params, *window_params, MAX_SCOPE_ROWS + 1],
        ).fetchall()
    truncated = len(rows) > MAX_SCOPE_ROWS
    data_range = (int(span[0]), int(span[1])) if span and span[0] is not None else None
    return [_monthly(row) for row in rows[:MAX_SCOPE_ROWS]], data_range, truncated


def located_counts(path: Path | None = None) -> dict[str, tuple[int, int]]:
    """Per country ``(river sites, lake sites)`` that have coordinates; ``{}`` when the store is absent."""
    with _connection(path) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            "SELECT country, SUM(category = 'RW'), SUM(category = 'LW') FROM sites "
            f"WHERE lat IS NOT NULL AND lon IS NOT NULL AND {_PUBLISHABLE_SQL} GROUP BY country ORDER BY country"
        ).fetchall()
    return {str(row[0]): (int(row[1] or 0), int(row[2] or 0)) for row in rows}


def countries_summary(path: Path | None = None) -> list[CountrySummary]:
    """One summary per country in the store (sites by category, sites without coordinates, years, months, records)."""
    with _connection(path) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            "SELECT country, COUNT(*), SUM(category = 'RW'), SUM(category = 'LW'), "
            f"SUM(lat IS NULL OR lon IS NULL OR NOT {_PUBLISHABLE_SQL}), MIN(first_year), MAX(last_year), SUM(n_records) "
            "FROM sites GROUP BY country ORDER BY country"
        ).fetchall()
        held = connection.execute("SELECT country, determinand FROM country_determinands ORDER BY country, determinand").fetchall()
        spans = {
            str(row[0]): (str(row[1]), str(row[2]))
            for row in connection.execute("SELECT country, first_month, last_month FROM country_ranges")
        }
    groups: dict[str, set[str]] = {}
    for country, code in held:
        group = group_of(code)
        if group is not None:
            groups.setdefault(country, set()).add(group)
    return [
        CountrySummary(
            country=row[0], sites=row[1], river_sites=row[2], lake_sites=row[3], sites_without_location=row[4],
            first_year=row[5], last_year=row[6], records=row[7], parameter_groups=tuple(sorted(groups.get(row[0], ()))),
            first_month=spans.get(row[0], (None, None))[0], last_month=spans.get(row[0], (None, None))[1],
        )
        for row in rows
    ]
