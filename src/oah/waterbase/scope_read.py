"""Country-scope reads of the monthly store, aggregated INSIDE SQLite (``docs/period_change.md`` section 11).

The earlier path (``store.scope_monthly_rows``) turned every monthly row of a country into a Python object, up to 2 million
rows per request. This module asks SQLite for one aggregate per site and window instead, so memory grows with the number
of sites (a few thousand), not with the rows scanned, and the result is the same number for number:

* ``n``, the below-LOQ and lower-reliability counts are SQL ``SUM``s of integers (exact);
* the minimum and maximum are SQL ``MIN`` and ``MAX`` of the value multiplied by the unit factor (multiplication by a
  positive factor is monotone, and it is the same IEEE product the row path computes);
* the sum of the quantified values is NOT SQLite's ``SUM`` (its rounding depends on the SQLite version and differs from
  ``math.fsum``): a small user-defined aggregate keeps Shewchuk's exact partial sums, so the total is the correctly rounded
  exact sum, which is what ``math.fsum`` of the row values gives (the row path used it);
* the months with a quantified value are a bit mask (``bit = month - window.first``), so the union over sites is an OR.

Everything is parameterised and read-only. A last-resort guard stops a read that would scan more than ``MAX_SCOPE_ROWS`` rows
or run longer than ``SCOPE_QUERY_SECONDS`` with ``ScopeTooLarge`` (a clear error, never memory exhaustion).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from oah.indices.scope_guard import ScopeTooLarge
from oah.indices.sqlite_aggregates import ReadGuard, mask_value, register
from oah.waterbase import store

__all__ = ["SCOPE_QUERY_SECONDS", "CountryScope", "ScopeTooLarge", "SiteScope", "SiteWindow", "scope_country_aggregates"]

SCOPE_QUERY_SECONDS = 120.0  # wall-clock cap of one country-scope read


@dataclass(frozen=True)
class SiteWindow:
    """One site inside one window, summed by SQLite. ``total`` is the exactly rounded sum of the converted quantified sums."""

    n: int
    n_below_loq: int
    n_lower_reliability: int
    low: float | None
    high: float | None
    total: float
    months: int  # bit (month - window first) set for each month with a quantified value


@dataclass(frozen=True)
class SiteScope:
    site_id: str
    country: str
    category: str  # of the first row of the site in primary-key order (unit, year, month), as the row path took it
    windows: tuple[SiteWindow | None, ...]  # one per requested window; None when the site has no row in it


@dataclass(frozen=True)
class CountryScope:
    sites: dict[str, SiteScope]
    data_range: tuple[int, int] | None  # first and last month position of the scope for this determinand and matrix, all time
    unit_weights: dict[str, tuple[int, int]]  # unit -> (rows, quantified + below-LOQ samples) inside the windows, kept or not


def _bounds(windows: Sequence[tuple[int, int]]) -> tuple[str, list[object]]:
    clause = " OR ".join("(year * 12 + month - 1 BETWEEN ? AND ?)" for _ in windows)
    params: list[object] = [value for first, last in windows for value in (int(first), int(last))]
    return "(" + clause + ")", params


def _unit_filter(units: Sequence[str]) -> str:
    return "unit IN (" + ",".join("?" for _ in units) + ")"


def _factor_case(units: Sequence[str], factors: Mapping[str, float]) -> tuple[str, list[object]]:
    """``CASE unit WHEN ? THEN ? ... END`` and its parameters: the unit factor as a bound double (exact)."""
    clause = "CASE unit " + " ".join("WHEN ? THEN ?" for _ in units) + " END"
    params: list[object] = [value for unit in units for value in (unit, float(factors[unit]))]
    return clause, params


def scope_country_aggregates(
    determinand: str,
    matrix: str,
    windows: Sequence[tuple[int, int]],
    country: str,
    factors_for: Callable[[dict[str, tuple[int, int]]], Mapping[str, float | None]],
    path: Path | None = None,
) -> CountryScope | None:
    """The per-site aggregates of ONE determinand in ONE matrix for every site of ``country``, inside each window.

    ``factors_for`` receives the units found inside the windows with their ``(rows, samples)`` weight and returns the factor
    of every unit to convert to the parameter's unit (None: leave that unit out). Returns None when the store is absent
    or of another schema. Raises ``ScopeTooLarge`` past the row or time cap.
    """
    wanted = list(windows)[: store.MAX_WINDOWS]
    if not wanted:
        return CountryScope({}, None, {})
    country_code = (country or "").strip().upper()
    base = "determinand = ? AND matrix = ? AND site_id IN (SELECT site_id FROM sites WHERE country = ?)"
    base_params: list[object] = [determinand, matrix, country_code]
    guard = ReadGuard(store.MAX_SCOPE_ROWS, SCOPE_QUERY_SECONDS)
    with store._connection(path) as connection:
        if connection is None:
            return None
        register(connection, guard)
        try:
            return _read(connection, guard, base, base_params, wanted, factors_for)
        except (sqlite3.OperationalError, RuntimeError) as error:
            if guard.reason:
                raise ScopeTooLarge(f"This comparison is too large to run: {guard.reason}. Narrow the periods.") from None
            raise error


def _read(
    connection: sqlite3.Connection, guard: ReadGuard, base: str, base_params: list[object], windows: list[tuple[int, int]],
    factors_for: Callable[[dict[str, tuple[int, int]]], Mapping[str, float | None]],
) -> CountryScope:
    span = connection.execute(
        f"SELECT MIN(year * 12 + month - 1), MAX(year * 12 + month - 1) FROM measurements WHERE {base}", base_params
    ).fetchone()
    data_range = (int(span[0]), int(span[1])) if span and span[0] is not None else None
    bounds, bound_params = _bounds(windows)
    weights = {
        str(unit): (int(rows), int(samples))
        for unit, rows, samples in connection.execute(
            f"SELECT unit, COUNT(*), SUM(n + n_below_loq) FROM measurements WHERE {base} AND {bounds} GROUP BY unit",
            [*base_params, *bound_params],
        )
    }
    chosen = factors_for(dict(weights))
    factors = {unit: float(factor) for unit, factor in chosen.items() if factor is not None}
    units = sorted(unit for unit in weights if unit in factors)
    if not units:
        return CountryScope({}, data_range, weights)
    rank_case = "CASE unit " + " ".join("WHEN ? THEN ?" for _ in units) + " END"
    rank_params: list[object] = [value for index, unit in enumerate(units) for value in (unit, index)]
    unit_clause = _unit_filter(units)
    # One row per site: country and category of its first row in primary-key order (unit, year, month) inside the windows.
    # SQLite documents that with MIN() as the only aggregate, the bare columns come from the row holding the minimum.
    identity = connection.execute(
        f"SELECT site_id, country, category, MIN(({rank_case}) * 100000 + year * 12 + month - 1) FROM measurements "
        f"WHERE {base} AND {unit_clause} AND {bounds} GROUP BY site_id",
        [*rank_params, *base_params, *units, *bound_params],
    ).fetchall()
    per_window: dict[tuple[int, int], dict[str, SiteWindow]] = {}
    for window in windows:
        if window not in per_window:
            per_window[window] = _window(connection, base, base_params, window, units, factors, unit_clause)
    sites = {
        str(site): SiteScope(str(site), str(code), str(category), tuple(per_window[window].get(str(site)) for window in windows))
        for site, code, category, _key in identity
    }
    return CountryScope(sites, data_range, weights)


def _window(
    connection: sqlite3.Connection, base: str, base_params: list[object], window: tuple[int, int], units: list[str],
    factors: Mapping[str, float], unit_clause: str,
) -> dict[str, SiteWindow]:
    factor_case, factor_params = _factor_case(units, factors)
    first, last = window
    rows = connection.execute(
        "SELECT site_id, SUM(n), SUM(n_below_loq), SUM(n_lower_reliability), "
        "MIN(CASE WHEN n > 0 THEN min * f END), MAX(CASE WHEN n > 0 THEN max * f END), "
        "oah_fsum(CASE WHEN n > 0 THEN sum_value * f END), oah_months(CASE WHEN n > 0 THEN pos - ? END) "
        "FROM (SELECT site_id, n, n_below_loq, n_lower_reliability, min, max, sum_value, "
        f"year * 12 + month - 1 AS pos, {factor_case} AS f FROM measurements "
        f"WHERE {base} AND {unit_clause} AND (year * 12 + month - 1 BETWEEN ? AND ?)) GROUP BY site_id",
        [int(first), *factor_params, *base_params, *units, int(first), int(last)],
    ).fetchall()
    return {
        str(site): SiteWindow(
            int(n), int(below), int(unreliable), None if low is None else float(low), None if high is None else float(high),
            float(total) if total is not None else 0.0, mask_value(mask),
        )
        for site, n, below, unreliable, low, high, total, mask in rows
    }
