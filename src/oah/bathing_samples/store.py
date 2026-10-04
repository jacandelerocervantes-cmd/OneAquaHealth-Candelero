"""Read-only access to the bathing-water SAMPLES SQLite store (built by ``oah.bathing_samples.build``).

Every query is parameterised and bounded (a page of at most ``MAX_LIMIT`` samples, an identifier of at most
``MAX_ID_CHARS`` characters, a country-scope read of at most ``MAX_COUNTRY_ROWS`` rows), the connection is opened
read-only, and a store that is missing or unreadable is an explicit state (``store_status``): nothing here raises for a
missing file. Column names that reach SQL come from a closed mapping, never from a caller.

A value is a CONCENTRATION only when its kind is ``Q`` or ``C`` (``oah.bathing_samples.constants``); every statistic below
uses those kinds and nothing else, and counts the other kinds apart.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from oah.bathing_samples.constants import (
    COUNTRY_ALIASES,
    DEFAULT_LIMIT,
    INDEX_KINDS,
    INDEX_QUANTIFIED,
    INDICATORS,
    KIND_CONFIRMED,
    KIND_DETECTION,
    KIND_INVALID,
    KIND_MISSING,
    KIND_UNKNOWN,
    MAX_COUNTRY_ROWS,
    MAX_ID_CHARS,
    MAX_LIMIT,
)
from oah.bathing_samples import country_scan
from oah.indices.sqlite_aggregates import PROGRESS_STEPS, ReadGuard
from oah.paths import bathing_samples_store_path

SUPPORTED_SCHEMA = "2"  # 2: covering and partial indexes of the country comparison (a store of schema 1 must be rebuilt)
COUNTRY_READ_SECONDS = 240.0  # wall-clock cap of the aggregate read of one country (a whole country takes about 5 s per pass on a laptop)
NOT_BUILT_DETAIL = (
    "The bathing-water samples store has not been built. Run scripts/build_bathing_samples_store.py "
    "(docs/bathing_samples_store.md); until then no E. coli or intestinal enterococci sample is served."
)
StoreState = Literal["ready", "not-built", "unreadable"]
_QUANTIFIED = "('Q','C')"


class RowCapExceeded(Exception):
    """A country-scope read would exceed ``MAX_COUNTRY_ROWS``; the caller narrows the periods."""


@dataclass(frozen=True)
class StoreStatus:
    state: StoreState
    detail: str

    @property
    def ready(self) -> bool:
        return self.state == "ready"


@dataclass(frozen=True)
class SiteSamples:
    bw_id: str
    country: str
    n_samples: int
    first_date: str
    last_date: str
    first_season: int
    last_season: int


@dataclass(frozen=True)
class CountrySamples:
    country: str
    bathing_waters: int
    n_samples: int
    first_date: str
    last_date: str
    first_season: int
    last_season: int
    n_quantified_ec: int
    n_quantified_ie: int


@dataclass(frozen=True)
class SampleRecord:
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
    has_remarks: bool


@dataclass(frozen=True)
class IndicatorStats:
    """Counts by kind and the statistics of the quantified values (kinds Q and C) of one indicator over a set of samples."""

    n_rows: int
    n_quantified: int
    n_confirmed_high: int  # included in n_quantified
    n_detection_limit: int
    n_missing: int
    n_unknown_status: int
    n_invalid: int
    low: int | None
    high: int | None
    total: int | None
    median: float | None

    @property
    def mean(self) -> float | None:
        return self.total / self.n_quantified if self.n_quantified and self.total is not None else None


@dataclass(frozen=True)
class MonthCell:
    """Quantified values of one bathing water in one calendar month (the unit of the period comparison)."""

    bw_id: str
    year: int
    month: int
    n: int
    total: int
    low: int
    high: int


def _open(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


@contextmanager
def _connection(path: Path | None = None) -> Iterator[sqlite3.Connection | None]:
    """A read-only connection, or None when the store is missing, unreadable or of another schema version."""
    target = path if path is not None else bathing_samples_store_path()
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
    target = path if path is not None else bathing_samples_store_path()
    if not target.is_file():
        return StoreStatus("not-built", NOT_BUILT_DETAIL)
    with _connection(target) as connection:
        if connection is None:
            return StoreStatus("unreadable", "The bathing-water samples store exists but cannot be read or has another schema version; rebuild it.")
    return StoreStatus("ready", "ready")


def provenance(path: Path | None = None) -> dict[str, str]:
    """The provenance table (source, query texts, build date, counts, observed limits, licence); {} when absent."""
    with _connection(path) as connection:
        if connection is None:
            return {}
        return {str(key): str(value) for key, value in connection.execute("SELECT key, value FROM provenance ORDER BY key")}


def normalise_country(code: str) -> str:
    """Upper-case code with the EL alias read as GR (the way the whole project treats Greece)."""
    upper = code.strip().upper()
    return COUNTRY_ALIASES.get(upper, upper)


def _valid_id(bw_id: str) -> bool:
    return bool(bw_id) and len(bw_id) <= MAX_ID_CHARS


def _prefix(indicator: str) -> str:
    return INDICATORS[indicator][0]  # KeyError for an unknown indicator: a programming error, never user input


def _filter(
    bw_id: str, date_from: str | None, date_to: str | None, season: int | None
) -> tuple[str, list[object]]:
    clauses: list[str] = ["bw_id = ?"]
    params: list[object] = [bw_id]
    if date_from is not None:
        clauses.append("sample_date >= ?")
        params.append(date_from)
    if date_to is not None:
        clauses.append("sample_date <= ?")
        params.append(date_to)
    if season is not None:
        clauses.append("season = ?")
        params.append(int(season))
    return " AND ".join(clauses), params


_RECORD_COLUMNS = (
    "uid, bw_id, country, season, sample_date, ec_value, ec_status, ec_kind, ie_value, ie_status, ie_kind, "
    "sample_status, obs_status, has_remarks"
)


def _record(row: tuple[Any, ...]) -> SampleRecord:
    return SampleRecord(
        int(row[0]), str(row[1]), str(row[2]), int(row[3]), str(row[4]), row[5], row[6], str(row[7]), row[8], row[9],
        str(row[10]), row[11], row[12], bool(row[13]),
    )


def site_samples(bw_id: str, path: Path | None = None) -> SiteSamples | None:
    """The sample range of one bathing water (None when it has no sample or the store is absent)."""
    if not _valid_id(bw_id):
        return None
    with _connection(path) as connection:
        if connection is None:
            return None
        row = connection.execute(
            "SELECT bw_id, country, n_samples, first_date, last_date, first_season, last_season FROM sites WHERE bw_id = ?", [bw_id]
        ).fetchone()
    return SiteSamples(*row) if row else None


def list_samples(
    bw_id: str,
    date_from: str | None = None,
    date_to: str | None = None,
    season: int | None = None,
    limit: int = DEFAULT_LIMIT,
    descending: bool = False,
    path: Path | None = None,
) -> tuple[int, list[SampleRecord]]:
    """``(total matching, one page)`` of the samples of one bathing water, by date then UID; ``(0, [])`` when absent."""
    if not _valid_id(bw_id):
        return 0, []
    page = max(1, min(int(limit), MAX_LIMIT))
    where, params = _filter(bw_id, date_from, date_to, season)
    direction = "DESC" if descending else "ASC"
    with _connection(path) as connection:
        if connection is None:
            return 0, []
        total = connection.execute(f"SELECT COUNT(*) FROM samples WHERE {where}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT {_RECORD_COLUMNS} FROM samples WHERE {where} ORDER BY sample_date {direction}, uid {direction} LIMIT ?",
            [*params, page],
        ).fetchall()
    return int(total), [_record(row) for row in rows]


def _median(connection: sqlite3.Connection, where: str, params: Sequence[object], column: str, kind: str, n: int) -> float | None:
    if n <= 0:
        return None
    rows = connection.execute(
        f"SELECT {column} FROM samples WHERE {where} AND {kind} IN {_QUANTIFIED} ORDER BY {column} LIMIT ? OFFSET ?",
        [*params, 2 - n % 2, (n - 1) // 2],
    ).fetchall()
    values = [int(row[0]) for row in rows]
    return sum(values) / len(values) if values else None


def indicator_stats(
    bw_id: str,
    indicator: str,
    date_from: str | None = None,
    date_to: str | None = None,
    season: int | None = None,
    path: Path | None = None,
) -> IndicatorStats | None:
    """Counts by kind, minimum, maximum, mean and the exact median of the quantified values of one bathing water."""
    if not _valid_id(bw_id):
        return None
    where, params = _filter(bw_id, date_from, date_to, season)
    return _stats(where, params, indicator, path)


def _stats(where: str, params: Sequence[object], indicator: str, path: Path | None) -> IndicatorStats | None:
    prefix = _prefix(indicator)
    value, kind = f"{prefix}_value", f"{prefix}_kind"
    with _connection(path) as connection:
        if connection is None:
            return None
        row = connection.execute(
            f"SELECT COUNT(*), "
            f"SUM(CASE WHEN {kind} IN {_QUANTIFIED} THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN {kind} = '{KIND_CONFIRMED}' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN {kind} = '{KIND_DETECTION}' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN {kind} = '{KIND_MISSING}' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN {kind} = '{KIND_UNKNOWN}' THEN 1 ELSE 0 END), "
            f"SUM(CASE WHEN {kind} = '{KIND_INVALID}' THEN 1 ELSE 0 END), "
            f"MIN(CASE WHEN {kind} IN {_QUANTIFIED} THEN {value} END), "
            f"MAX(CASE WHEN {kind} IN {_QUANTIFIED} THEN {value} END), "
            f"SUM(CASE WHEN {kind} IN {_QUANTIFIED} THEN {value} END) "
            f"FROM samples WHERE {where}",
            list(params),
        ).fetchone()
        n_rows, n_q = int(row[0]), int(row[1] or 0)
        median = _median(connection, where, params, value, kind, n_q)
    return IndicatorStats(
        n_rows, n_q, int(row[2] or 0), int(row[3] or 0), int(row[4] or 0), int(row[5] or 0), int(row[6] or 0),
        None if row[7] is None else int(row[7]), None if row[8] is None else int(row[8]),
        None if row[9] is None else int(row[9]), median,
    )


def countries_summary(path: Path | None = None) -> list[CountrySamples]:
    """One summary per country: bathing waters with samples, samples, the date and season range, quantified counts."""
    with _connection(path) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            "SELECT country, bathing_waters, n_samples, first_date, last_date, first_season, last_season, "
            "n_quantified_ec, n_quantified_ie FROM country_summary ORDER BY country"
        ).fetchall()
    return [CountrySamples(*row) for row in rows]


# --- period comparison reads --------------------------------------------------------------------------------------------


_month_start = country_scan.month_start
_month_end = country_scan.month_end


def _windows(windows: Sequence[tuple[int, int]]) -> tuple[str, list[object]]:
    """``(a clause, params)`` selecting the samples dated inside any of the month ranges (month positions, inclusive)."""
    if not 1 <= len(windows) <= 2:
        raise ValueError("one or two windows")
    clause = " OR ".join("(sample_date >= ? AND sample_date <= ?)" for _ in windows)
    params: list[object] = []
    for first, last in windows:
        params.extend([_month_start(first), _month_end(last)])
    return f"({clause})", params


def quantified_range(scope: Literal["site", "country"], key: str, indicator: str, path: Path | None = None) -> tuple[str, str] | None:
    """First and last sample date (all time) with a quantified value of ``indicator`` for a bathing water or a country."""
    prefix = _prefix(indicator)
    with _connection(path) as connection:
        if connection is None:
            return None
        if scope == "country":  # precomputed at build time: a scan of a whole country takes seconds
            row = connection.execute(
                f"SELECT first_quantified_{prefix}, last_quantified_{prefix} FROM country_summary WHERE country = ?", [key]
            ).fetchone()
        else:
            row = connection.execute(
                f"SELECT MIN(sample_date), MAX(sample_date) FROM samples WHERE bw_id = ? AND {prefix}_kind IN {_QUANTIFIED}", [key]
            ).fetchone()
    return (row[0], row[1]) if row and row[0] is not None else None


def month_cells(
    scope: Literal["site", "country"], key: str, indicator: str, windows: Sequence[tuple[int, int]], path: Path | None = None
) -> list[MonthCell]:
    """Per bathing water and calendar month: n, sum, min and max of the quantified values dated inside the windows."""
    column = "bw_id" if scope == "site" else "country"
    prefix = _prefix(indicator)
    value, kind = f"{prefix}_value", f"{prefix}_kind"
    clause, params = _windows(windows)
    with _connection(path) as connection:
        if connection is None:
            return []
        rows = connection.execute(
            f"SELECT bw_id, CAST(substr(sample_date, 1, 4) AS INTEGER), CAST(substr(sample_date, 6, 2) AS INTEGER), "
            f"COUNT(*), SUM({value}), MIN({value}), MAX({value}) FROM samples "
            f"WHERE {column} = ? AND {kind} IN {_QUANTIFIED} AND {clause} GROUP BY bw_id, 2, 3 ORDER BY bw_id, 2, 3",
            [key, *params],
        ).fetchall()
    return [MonthCell(*row) for row in rows]


def kind_counts(
    scope: Literal["site", "country"], key: str, indicator: str, window: tuple[int, int], path: Path | None = None
) -> dict[str, int]:
    """Samples inside one window by value kind (Q, C, D, M, U, I) for a bathing water or a whole country."""
    column = "bw_id" if scope == "site" else "country"
    kind = f"{_prefix(indicator)}_kind"
    clause, params = _windows([window])
    with _connection(path) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            f"SELECT {kind}, COUNT(*) FROM samples WHERE {column} = ? AND {clause} GROUP BY {kind}", [key, *params]
        ).fetchall()
    return {str(name): int(count) for name, count in rows}


def window_values(
    scope: Literal["site", "country"], key: str, indicator: str, window: tuple[int, int], path: Path | None = None
) -> dict[str, list[int]]:
    """The quantified values inside one window, grouped by bathing water and sorted (for exact medians).

    A country read is bounded by ``MAX_COUNTRY_ROWS`` (``RowCapExceeded`` beyond it).
    """
    column = "bw_id" if scope == "site" else "country"
    prefix = _prefix(indicator)
    value, kind = f"{prefix}_value", f"{prefix}_kind"
    clause, params = _windows([window])
    with _connection(path) as connection:
        if connection is None:
            return {}
        rows = connection.execute(
            f"SELECT bw_id, {value} FROM samples WHERE {column} = ? AND {kind} IN {_QUANTIFIED} AND {clause} "
            f"ORDER BY bw_id, {value} LIMIT ?",
            [key, *params, MAX_COUNTRY_ROWS + 1],
        ).fetchall()
    if len(rows) > MAX_COUNTRY_ROWS:
        raise RowCapExceeded
    grouped: dict[str, list[int]] = {}
    for bw_id, number in rows:
        grouped.setdefault(str(bw_id), []).append(int(number))
    return grouped


@dataclass(frozen=True)
class SampleWindow:
    """The quantified values of one bathing water inside one window: integers, so every number is exact."""

    n: int
    total: int
    low: int
    high: int
    months: int  # bit (month position - window first) set for every month with a quantified value
    median: float  # the middle value, or the mean of the two middle ones


def _guarded(connection: sqlite3.Connection, guard: ReadGuard) -> None:
    connection.set_progress_handler(guard.progress, PROGRESS_STEPS)


def country_window_aggregates(
    country: str, indicator: str, windows: Sequence[tuple[int, int]], path: Path | None = None
) -> dict[str, tuple[SampleWindow | None, ...]]:
    """Per bathing water of ``country`` and per window: n, sum, minimum, maximum, the months with a quantified value and the median.

    ONE sequential pass over the partial index of the indicator (``country_scan``): the bathing waters come one after the other
    with their values, so only one small record per bathing water and window reaches the caller, however many samples the
    country has. The numbers are those of ``month_cells`` summed over the months and of ``window_values`` taken as a median.
    A bathing water without a quantified value inside a window has ``None`` for it. The rows read are bounded by
    ``MAX_COUNTRY_ROWS`` (``RowCapExceeded`` beyond it) and the read by a wall-clock cap (``RowCapExceeded`` too).
    """
    prefix = _prefix(indicator)
    wanted = [(int(first), int(last)) for first, last in windows]
    if not 1 <= len(wanted) <= 2:
        raise ValueError("one or two windows")
    guard = ReadGuard(MAX_COUNTRY_ROWS, COUNTRY_READ_SECONDS)
    first_day, last_day = country_scan.span(wanted)
    with _connection(path) as connection:
        if connection is None:
            return {}
        country_scan.register(connection, guard, wanted)
        try:
            rows = connection.execute(
                f"SELECT bw_id, oah_window_scan({prefix}_value, sample_date) FROM samples INDEXED BY {INDEX_QUANTIFIED[prefix]} "
                f"WHERE country = ? AND {prefix}_kind IN {_QUANTIFIED} AND sample_date >= ? AND sample_date <= ? GROUP BY bw_id "
                "ORDER BY bw_id",
                [country, first_day, last_day],
            ).fetchall()
        except sqlite3.OperationalError as error:
            if guard.reason:
                raise RowCapExceeded from None
            raise error
    found: dict[str, tuple[SampleWindow | None, ...]] = {}
    for bw_id, text in rows:
        entries = country_scan.parse(text)
        found[str(bw_id)] = tuple(
            None if entry is None else SampleWindow(int(entry[0]), int(entry[1]), int(entry[2]), int(entry[3]), int(entry[4]), float(entry[5]))
            for entry in entries
        )
    return found


def country_kind_counts(
    country: str, windows: Sequence[tuple[int, int]], path: Path | None = None
) -> dict[str, tuple[dict[str, int], ...]]:
    """Samples of a whole country by value kind (Q, C, D, M, U, I), for BOTH indicators and every window, in one pass.

    Read from the covering index ``idx_samples_kinds`` alone. The result maps each indicator name to one dictionary per window
    (the same numbers as ``kind_counts`` for the country scope, window by window).
    """
    wanted = [(int(first), int(last)) for first, last in windows]
    if not 1 <= len(wanted) <= 2:
        raise ValueError("one or two windows")
    guard = ReadGuard(MAX_COUNTRY_ROWS, COUNTRY_READ_SECONDS)
    first_day, last_day = country_scan.span(wanted)
    inside = ", ".join("SUM(sample_date >= ? AND sample_date <= ?)" for _ in wanted)
    params: list[object] = []
    for first, last in wanted:
        params.extend([country_scan.month_start(first), country_scan.month_end(last)])
    with _connection(path) as connection:
        if connection is None:
            return {}
        _guarded(connection, guard)
        try:
            rows = connection.execute(
                f"SELECT ec_kind, ie_kind, {inside} FROM samples INDEXED BY {INDEX_KINDS} "
                "WHERE country = ? AND sample_date >= ? AND sample_date <= ? GROUP BY ec_kind, ie_kind",
                [*params, country, first_day, last_day],
            ).fetchall()
        except sqlite3.OperationalError as error:
            if guard.reason:
                raise RowCapExceeded from None
            raise error
    result: dict[str, tuple[dict[str, int], ...]] = {name: tuple({} for _ in wanted) for name in INDICATORS}
    for ec_kind, ie_kind, *counts in rows:
        for name, kind in (("escherichia_coli", ec_kind), ("intestinal_enterococci", ie_kind)):
            for index, count in enumerate(counts):
                if count:
                    result[name][index][str(kind)] = result[name][index].get(str(kind), 0) + int(count)
    return result
