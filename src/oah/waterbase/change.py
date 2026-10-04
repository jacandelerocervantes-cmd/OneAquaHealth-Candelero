"""Period comparison over the Waterbase store: monthly rows in, ``oah.indices.period_change`` results out.

This module only reads the store and turns its rows into the pure module's cells; every statistic, flag and limit
decision is made by ``oah.indices.period_change``. Rules (``docs/period_change.md``):

* one determinand in ONE matrix is compared. A closed project name selects the matrix the mapping holds for; the label
  of an unmapped determinand selects ``W`` when the store holds it, else its only stored matrix (the measurements route
  lists every matrix, a comparison needs exactly one series);
* a unit is never guessed: a mapped determinand is converted with ``to_project_unit`` (basis checked, mass prefixes
  converted, total phosphorus as phosphate), a measurement-only determinand keeps only rows in its expected unit, an
  unmapped one keeps the unit with most records; every other row is left out and counted (``rows_excluded_unit``).

A country comparison is aggregated inside SQLite (``oah.waterbase.scope_read``): per site and period only sums reach
Python, so memory does not grow with the rows scanned. ``country_change_rows`` is the earlier path that materialises every
row (the reference of the parity tests and of ``scripts/check_country_scope_parity.py``; the routes do not use it). Both
give the same numbers.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from oah.indices.period_change import (
    Cell,
    ParameterContext,
    Period,
    PeriodStats,
    SiteContext,
    WindowAggregate,
    aggregate_stats,
    compare_country,
    compare_country_stats,
    compare_site,
    monthly_cell,
)
from oah.indices.scope_guard import GUARD, file_signature
from oah.indices.water_parameter_limits import PARAMETER_UNITS
from oah.paths import waterbase_store_path
from oah.waterbase import scope_read, store
from oah.waterbase.mapping import (
    DETERMINANDS,
    NO_LIMIT_REGIME,
    SOURCE_ID,
    closed_name,
    listed_name,
    parameter_filter,
    to_project_unit,
    unmapped_reason,
)
from oah.waterbase.store import MonthlyRow, WaterbaseSite


@dataclass(frozen=True)
class Series:
    """The one determinand and matrix a parameter name stands for."""

    code: str
    matrix: str


def resolve_series(parameter: str) -> Series | None:
    """The series behind a parameter name (a closed name or a label of ``waterbase_parameter_names``), or None."""
    selected = parameter_filter(parameter)
    if selected is None:
        return None
    code, matrix = selected
    if matrix is None:
        stored = sorted(DETERMINANDS[code].stored_matrices)
        matrix = "W" if "W" in stored else stored[0]
    return Series(code, matrix)


def regime_of(category: str) -> str:
    """``surface`` for a river, ``no-limit-regime`` for a lake (the same rule as the measurement records)."""
    return "surface" if category == "RW" else NO_LIMIT_REGIME


def _dominant_unit(weights: Mapping[str, int]) -> str | None:
    """The stored unit with the most records (quantified plus below-LOQ), ties alphabetical."""
    return sorted(weights, key=lambda unit: (-weights[unit], unit))[0] if weights else None


def unit_rules(series: Series, weights: Mapping[str, int]) -> tuple[str | None, dict[str, float | None]]:
    """``(the parameter's unit, factor per stored unit)``; a factor of None leaves that unit out (counted as excluded).

    ``weights`` is the number of records per stored unit inside the periods (used only to pick the unit of an unmapped
    determinand). The factor is linear, so it converts sums, minima and maxima alike.
    """
    determinand = DETERMINANDS[series.code]
    mapped = closed_name(series.code, series.matrix)
    if determinand.measurement_only:
        unit: str | None = determinand.expected_unit
    elif mapped is not None:
        unit = PARAMETER_UNITS[mapped]
    else:
        unit = _dominant_unit(weights)
    factors: dict[str, float | None] = {}
    for stored in weights:
        if determinand.measurement_only or mapped is None:
            factors[stored] = 1.0 if stored == unit else None
        else:
            factors[stored] = to_project_unit(1.0, stored, determinand)
    return unit, factors


def parameter_context(series: Series, unit: str | None) -> ParameterContext:
    """The parameter as listed to the reader, in ``unit``."""
    determinand = DETERMINANDS[series.code]
    mapped = closed_name(series.code, series.matrix)
    return ParameterContext(
        name=listed_name(series.code, series.matrix),
        unit=unit or "",
        group=determinand.group,
        closed_name=mapped if not determinand.measurement_only else None,
        measurement_only=determinand.measurement_only,
        resolution="monthly",
        source=SOURCE_ID,
        unmapped_reason="" if determinand.measurement_only or mapped is not None else unmapped_reason(series.code, series.matrix),
    )


def to_cells(rows: Sequence[MonthlyRow], series: Series) -> tuple[list[Cell], list[MonthlyRow], ParameterContext, int]:
    """``(cells, the rows they came from, parameter context, rows left out for their unit)`` of one series, in the unit
    of the parameter. ``cells[i]`` comes from ``kept[i]``."""
    weight: Counter[str] = Counter()
    for row in rows:
        weight[row.unit] += row.n + row.n_below_loq
    unit, factors = unit_rules(series, weight)
    cells: list[Cell] = []
    kept: list[MonthlyRow] = []
    excluded = 0
    for row in rows:
        factor = factors[row.unit]
        if factor is None:
            excluded += 1
            continue
        kept.append(row)
        cells.append(
            monthly_cell(
                row.site_id, row.year * 12 + row.month - 1, row.n, row.sum_value * factor,
                None if row.min is None else row.min * factor, None if row.max is None else row.max * factor,
                row.n_below_loq, row.n_lower_reliability,
            )
        )
    return cells, kept, parameter_context(series, unit), excluded


def _context(site: WaterbaseSite) -> SiteContext:
    return SiteContext(site.site_id, site.country, regime_of(site.category), site.name or site.site_id)


def site_change(site: WaterbaseSite, series: Series, period_a: Period, period_b: Period) -> dict[str, Any]:
    """One site's comparison (the pure result, plus ``rows_excluded_unit``)."""
    rows, data_range, _truncated = store.scope_monthly_rows(
        series.code, series.matrix, [(period_a.first, period_a.last), (period_b.first, period_b.last)], site_id=site.site_id
    )
    cells, _kept, parameter, excluded = to_cells(rows, series)
    result = compare_site(cells, parameter, _context(site), period_a, period_b, data_range=data_range)
    return {**result, "rows_excluded_unit": excluded}


def country_change_rows(country: str, series: Series, period_a: Period, period_b: Period) -> dict[str, Any]:
    """One country's comparison through the row path: every monthly row becomes an object (the reference implementation).

    Memory grows with the rows of the country (up to ``store.MAX_SCOPE_ROWS``). Kept for the parity tests and the check
    script; ``country_change`` is the path the routes use.
    """
    rows, data_range, truncated = store.scope_monthly_rows(
        series.code, series.matrix, [(period_a.first, period_a.last), (period_b.first, period_b.last)], country=country
    )
    cells, kept, parameter, excluded = to_cells(rows, series)
    by_site: dict[str, list[Cell]] = {}
    sites: dict[str, SiteContext] = {}
    for row, cell in zip(kept, cells, strict=True):
        by_site.setdefault(cell.site_id, []).append(cell)
        sites.setdefault(cell.site_id, SiteContext(cell.site_id, row.country, regime_of(row.category)))
    result = compare_country(by_site, sites, parameter, country, period_a, period_b, data_range=data_range)
    return {**result, "rows_excluded_unit": excluded, "truncated": truncated}


def _aggregate(window: scope_read.SiteWindow | None) -> WindowAggregate | None:
    if window is None:
        return None
    return WindowAggregate(
        window.n, window.n_below_loq, window.n_lower_reliability, window.low, window.high, window.total, window.months
    )


def country_change(country: str, series: Series, period_a: Period, period_b: Period) -> dict[str, Any]:
    """One country's comparison over paired sites (the pure result, plus ``rows_excluded_unit`` and ``truncated``).

    Aggregated in SQLite: only per-site sums reach Python (``oah.waterbase.scope_read``); the numbers are those of
    ``country_change_rows``. Runs under the process-wide guard (``oah.indices.scope_guard``): at most two at a time, a
    bounded wait then ``ScopeBusy``, and a repeated identical question is answered from a small TTL + LRU cache. Raises
    ``scope_read.ScopeTooLarge`` past the hard row or time cap (the caller turns both into clear answers).
    """
    key = (
        SOURCE_ID, file_signature(waterbase_store_path()), country, series.code, series.matrix,
        (period_a.first, period_a.last), (period_b.first, period_b.last),
    )
    return GUARD.run(key, lambda: _country_change(country, series, period_a, period_b))


def _country_change(country: str, series: Series, period_a: Period, period_b: Period) -> dict[str, Any]:
    windows = [(period_a.first, period_a.last), (period_b.first, period_b.last)]
    scope = scope_read.scope_country_aggregates(
        series.code, series.matrix, windows, country,
        lambda weights: unit_rules(series, {name: samples for name, (_rows, samples) in weights.items()})[1],
    ) or scope_read.CountryScope({}, None, {})
    unit, factors = unit_rules(series, {name: samples for name, (_rows, samples) in scope.unit_weights.items()})
    excluded = sum(rows for name, (rows, _samples) in scope.unit_weights.items() if factors[name] is None)
    stats_by_site: dict[str, tuple[PeriodStats, PeriodStats]] = {}
    sites: dict[str, SiteContext] = {}
    for site_id, entry in scope.sites.items():
        stats_by_site[site_id] = (
            aggregate_stats(_aggregate(entry.windows[0]), period_a), aggregate_stats(_aggregate(entry.windows[1]), period_b)
        )
        sites[site_id] = SiteContext(site_id, entry.country, regime_of(entry.category))
    result = compare_country_stats(
        stats_by_site, sites, parameter_context(series, unit), country, period_a, period_b, data_range=scope.data_range
    )
    return {**result, "rows_excluded_unit": excluded, "truncated": False}
