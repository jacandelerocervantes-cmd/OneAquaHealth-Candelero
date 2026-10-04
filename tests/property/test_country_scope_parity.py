"""Parity of the SQL-aggregated country comparison with the row-materialising reference path (``docs/period_change.md`` s. 11).

``oah.waterbase.change.country_change`` asks SQLite for one aggregate per site and period; ``country_change_rows`` turns every
monthly row into an object, as the code did before. The two must agree number for number on every store: the whole result
dictionary, and the per-site statistics BEFORE rounding (the mean must be bit-identical, which is why the sum is an exact
``math.fsum``-equivalent aggregate and not SQLite's ``SUM``). All stores here are SYNTHETIC and random.
"""
from __future__ import annotations

import sqlite3
import statistics
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from oah.bathing_samples import change as samples_change
from oah.bathing_samples import store as samples_store
from oah.bathing_samples.storage import DDL as SAMPLES_DDL
from oah.bathing_samples.storage import INDEXES as SAMPLES_INDEXES
from oah.indices import scope_guard
from oah.indices.period_change import Period, aggregate_stats, period_stats
from oah.waterbase import change, scope_read, store
from oah.waterbase.storage import DDL

CASES = [  # (determinand code, matrix, stored units: some convertible, some not)
    ("CAS_7723-14-0", "W", ["mg{P}/L", "ug{P}/L", "bogus"]),  # total phosphorus -> "Total phosphates" (factor 3.0662)
    ("CAS_16887-00-6", "W", ["mg/L", "ug/L"]),  # chloride: no closed name, the dominant unit is kept
    ("EEA_3112-01-4", "W", ["{NTU}", "other"]),  # turbidity: measurement only, one expected unit
    ("CAS_7439-92-1", "W-DIS", ["ug/L", "mg/L", "weird"]),  # lead dissolved
]
FIRST_MONTH = 2018 * 12  # month positions of the generated rows: 2018-01 to 2021-12
MONTHS = 48

magnitude = st.one_of(st.floats(min_value=0.0, max_value=1e4, allow_nan=False), st.sampled_from([1e-9, 1e12, 0.1, 0.2, 0.3, 7.0]))


@st.composite
def row_strategy(draw, units: list[str]):
    n = draw(st.integers(0, 6))
    low = draw(magnitude)
    spread = draw(st.floats(min_value=0.0, max_value=50.0, allow_nan=False))
    fraction = draw(st.floats(min_value=0.0, max_value=1.0))
    below = draw(st.integers(0, 3))
    return {
        "unit": draw(st.sampled_from(units)), "position": FIRST_MONTH + draw(st.integers(0, MONTHS - 1)), "n": n,
        "low": low if n else None, "high": (low + spread) if n else None,
        "total": (n * low + fraction * n * spread) if n else 0.0, "below": below,
        "unreliable": draw(st.integers(0, n + below)), "category": draw(st.sampled_from(["RW", "LW"])),
    }


@st.composite
def scenario(draw):
    code, matrix, units = draw(st.sampled_from(CASES))
    sites = draw(st.lists(st.sampled_from(["IT", "GR"]), min_size=1, max_size=7))
    rows = {
        (index, row["unit"], row["position"]): row
        for index in range(len(sites))
        for row in draw(st.lists(row_strategy(units), max_size=24))
    }
    first_a, first_b = (FIRST_MONTH + draw(st.integers(0, MONTHS)) for _ in range(2))
    return code, matrix, sites, rows, Period(first_a, first_a + draw(st.integers(0, 30))), Period(first_b, first_b + draw(st.integers(0, 30)))


def build(path: Path, sites: list[str]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', '3')")
    connection.executemany(
        "INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(f"S{i}", country, "RW", None, None, None, None, None, "F", 2018, 2021, 1) for i, country in enumerate(sites)],
    )
    connection.commit()
    connection.close()


def insert(path: Path, code: str, matrix: str, sites: list[str], rows: dict[tuple[int, str, int], dict]) -> None:
    connection = sqlite3.connect(path)
    connection.executemany(
        "INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                sites[index], f"S{index}", row["category"], code, matrix, unit, position // 12, position % 12 + 1, row["n"],
                row["total"], row["low"], row["high"], row["below"], row["unreliable"],
            )
            for (index, unit, position), row in rows.items()
        ],
    )
    connection.commit()
    connection.close()


def site_stats_by_rows(path: Path, series: change.Series, a: Period, b: Period):
    rows, _range, _truncated = store.scope_monthly_rows(
        series.code, series.matrix, [(a.first, a.last), (b.first, b.last)], country="IT", path=path
    )
    cells, kept, _parameter, _excluded = change.to_cells(rows, series)
    by_site: dict[str, list] = {}
    for row, cell in zip(kept, cells, strict=True):
        by_site.setdefault(row.site_id, []).append(cell)
    return {site: (period_stats(cells_, a), period_stats(cells_, b)) for site, cells_ in by_site.items()}


def site_stats_by_sql(path: Path, series: change.Series, a: Period, b: Period):
    scope = scope_read.scope_country_aggregates(
        series.code, series.matrix, [(a.first, a.last), (b.first, b.last)], "IT",
        lambda weights: change.unit_rules(series, {unit: samples for unit, (_rows, samples) in weights.items()})[1], path,
    )
    assert scope is not None
    return {
        site: (
            aggregate_stats(change._aggregate(entry.windows[0]), a), aggregate_stats(change._aggregate(entry.windows[1]), b)
        )
        for site, entry in scope.sites.items()
    }


@pytest.fixture()
def pointed_at(monkeypatch):
    def point(path: Path) -> None:
        monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))

    return point


@given(scenario())
@settings(max_examples=250, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_the_sql_aggregation_equals_the_row_path_on_random_stores(pointed_at, case):
    code, matrix, sites, rows, period_a, period_b = case
    series = change.Series(code, matrix)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "random.sqlite"
        build(path, sites)
        insert(path, code, matrix, sites, rows)
        pointed_at(path)
        by_sql = change._country_change("IT", series, period_a, period_b)
        by_rows = change.country_change_rows("IT", series, period_a, period_b)
        assert by_sql == by_rows
        assert site_stats_by_sql(path, series, period_a, period_b) == site_stats_by_rows(path, series, period_a, period_b)


def test_the_two_paths_agree_on_a_store_with_two_categories_per_site_and_a_mixed_unit_site(tmp_path: Path, pointed_at):
    """The category of a site is that of its first row in primary-key order (unit, year, month); both paths take it."""
    rows = {}
    for position in range(FIRST_MONTH, FIRST_MONTH + 6):
        rows[(0, "ug{P}/L", position)] = {
            "unit": "ug{P}/L", "position": position, "n": 2, "low": 10.0, "high": 30.0, "total": 40.0, "below": 1,
            "unreliable": 1, "category": "LW" if position % 2 else "RW",
        }
        rows[(0, "mg{P}/L", position)] = {
            "unit": "mg{P}/L", "position": position, "n": 3, "low": 0.01, "high": 0.03, "total": 0.06, "below": 0,
            "unreliable": 0, "category": "RW",
        }
    path = tmp_path / "mixed.sqlite"
    build(path, ["IT"])
    insert(path, "CAS_7723-14-0", "W", ["IT"], rows)
    pointed_at(path)
    series = change.Series("CAS_7723-14-0", "W")
    a, b = Period(FIRST_MONTH, FIRST_MONTH + 2), Period(FIRST_MONTH + 3, FIRST_MONTH + 5)
    assert change._country_change("IT", series, a, b) == change.country_change_rows("IT", series, a, b)


# --- bathing-water SAMPLES: the one-pass scan of the partial indexes against the row path --------------------------------------
# (docs/bathing_samples_store.md, "Country comparison read path"). All stores below are SYNTHETIC and random.

SAMPLE_SITES = ["IT001", "IT002", "IT003", "IT004", "IT005", "GR001", "GR002", "GR003", "NO001"]
COUNTRY_OF = {"IT": "IT", "GR": "GR", "NO": "NO"}
INDICATOR_NAMES = ("escherichia_coli", "intestinal_enterococci")

sample_value = st.one_of(st.integers(0, 3000), st.integers(0, 2**40), st.sampled_from([0, 1, 2, 2**53 - 1]))
sample_row_strategy = st.tuples(
    st.sampled_from(SAMPLE_SITES), st.integers(2018, 2021), st.integers(1, 12), st.integers(1, 28),
    sample_value, st.sampled_from("QQQQCDMUI"), sample_value, st.sampled_from("QQQQCDMUI"),
)


def build_samples(path: Path, items: list[tuple]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SAMPLES_DDL + SAMPLES_INDEXES)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', ?)", [samples_store.SUPPORTED_SCHEMA])
    by_country: dict[str, list[tuple]] = {}
    for uid, (bw, year, month, day, ec, ec_kind, ie, ie_kind) in enumerate(items):
        country = COUNTRY_OF[bw[:2]]
        date = f"{year}-{month:02d}-{day:02d}"
        connection.execute(
            "INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [bw, date, uid, country, year, ec, None, ec_kind, ie, None, ie_kind, None, "A", 0],
        )
        by_country.setdefault(country, []).append((bw, date, ec_kind, ie_kind))
    for country, rows in by_country.items():
        days = {
            prefix: [row[1] for row in rows if row[2 if prefix == "ec" else 3] in ("Q", "C")] for prefix in ("ec", "ie")
        }
        bounds = {key: (min(found), max(found)) if found else (None, None) for key, found in days.items()}
        connection.execute(
            "INSERT INTO country_summary VALUES (?, ?, ?, '2018-01-01', '2021-12-28', 2018, 2021, ?, ?, ?, ?, ?, ?)",
            [country, len({row[0] for row in rows}), len(rows), len(days["ec"]), len(days["ie"]), *bounds["ec"], *bounds["ie"]],
        )
    connection.commit()
    connection.close()


@given(
    st.lists(sample_row_strategy, min_size=0, max_size=80), st.integers(-3, 50), st.integers(-3, 50), st.integers(0, 40),
    st.integers(0, 40), st.sampled_from(["IT", "GR", "NO"]),
)
@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_the_samples_scan_equals_the_row_path_on_random_stores(monkeypatch, items, first_a, first_b, length_a, length_b, country):
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "samples.sqlite"
        build_samples(path, items)
        monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(path))
        period_a = Period(2018 * 12 + first_a, 2018 * 12 + first_a + length_a)  # may overlap, swap or fall outside the data
        period_b = Period(2018 * 12 + first_b, 2018 * 12 + first_b + length_b)
        scope_guard.GUARD.clear()
        assert samples_change.country_change(country, period_a, period_b) == samples_change.country_change_rows(
            country, period_a, period_b
        )
        windows = [(period_a.first, period_a.last), (period_b.first, period_b.last)]
        for indicator in INDICATOR_NAMES:
            scanned = samples_store.country_window_aggregates(country, indicator, windows, path)
            for index, window in enumerate(windows):
                cells = samples_store.month_cells("country", country, indicator, [window], path)
                values = samples_store.window_values("country", country, indicator, window, path)
                found = {bw: entry[index] for bw, entry in scanned.items() if entry[index] is not None}
                assert set(found) == set(values) == {cell.bw_id for cell in cells}
                for bw, entry in found.items():
                    mine = [cell for cell in cells if cell.bw_id == bw]
                    assert entry.n == sum(cell.n for cell in mine) == len(values[bw])
                    assert entry.total == sum(cell.total for cell in mine) == sum(values[bw])
                    assert (entry.low, entry.high) == (min(cell.low for cell in mine), max(cell.high for cell in mine))
                    assert entry.median == float(statistics.median(values[bw]))
                    assert entry.months == sum(1 << (cell.year * 12 + cell.month - 1 - window[0]) for cell in mine)
            counted = samples_store.country_kind_counts(country, windows, path).get(indicator)
            if counted is not None:
                assert list(counted) == [samples_store.kind_counts("country", country, indicator, w, path) for w in windows]
