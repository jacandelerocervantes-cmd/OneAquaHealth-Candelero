"""The samples store reader: states, bounds, exact statistics, flagged values counted apart, injection, read-only.

The store is built from SYNTHETIC rows (``samples_fixtures``); every expected number is computed by hand in the test.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from samples_fixtures import build_fixture_store, dataset, raw_row

from oah.bathing_samples import store
from oah.indices.period_change import month_position

A = (month_position(2020, 5), month_position(2020, 8))
B = (month_position(2022, 5), month_position(2022, 8))


@pytest.fixture()
def built(tmp_path: Path) -> Path:
    return build_fixture_store(tmp_path)


# --- states ---------------------------------------------------------------------------------------------------------------


def test_a_missing_store_is_not_built_and_nothing_raises(tmp_path: Path):
    path = tmp_path / "absent.sqlite"
    assert store.store_status(path).state == "not-built" and "build_bathing_samples_store.py" in store.store_status(path).detail
    assert store.list_samples("ITSYN001", path=path) == (0, [])
    assert store.site_samples("ITSYN001", path) is None and store.countries_summary(path) == [] and store.provenance(path) == {}
    assert store.indicator_stats("ITSYN001", "escherichia_coli", path=path) is None
    assert store.month_cells("site", "ITSYN001", "escherichia_coli", [A], path) == [] and store.quantified_range("site", "x", "escherichia_coli", path) is None
    assert store.kind_counts("site", "x", "escherichia_coli", A, path) == {} and store.window_values("site", "x", "escherichia_coli", A, path) == {}


def test_a_corrupt_store_or_another_schema_is_unreadable(tmp_path: Path):
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"garbage" * 200)
    assert store.store_status(broken).state == "unreadable" and store.list_samples("ITSYN001", path=broken) == (0, [])
    other = tmp_path / "other.sqlite"
    with sqlite3.connect(other) as connection:
        connection.execute("CREATE TABLE provenance (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO provenance VALUES ('schema_version', '99')")
    assert store.store_status(other).state == "unreadable" and store.countries_summary(other) == []
    empty = tmp_path / "empty.sqlite"
    sqlite3.connect(empty).close()
    assert store.store_status(empty).state == "unreadable"


def test_a_store_of_schema_one_must_be_rebuilt(built: Path, tmp_path: Path):
    """Schema 1 had one index on country and date; the country scan names the schema 2 indexes, so the old store is refused."""
    assert store.SUPPORTED_SCHEMA == "2"
    old = tmp_path / "schema1.sqlite"
    old.write_bytes(built.read_bytes())
    with sqlite3.connect(old) as connection:
        for name in (store.INDEX_KINDS, *store.INDEX_QUANTIFIED.values()):
            connection.execute(f"DROP INDEX {name}")
        connection.execute("CREATE INDEX idx_samples_country_date ON samples (country, sample_date)")
        connection.execute("UPDATE provenance SET value = '1' WHERE key = 'schema_version'")
    status = store.store_status(old)
    assert status.state == "unreadable" and "rebuild" in status.detail
    assert store.country_window_aggregates("IT", "escherichia_coli", [A], old) == {}
    assert store.country_kind_counts("IT", [A], old) == {}


def test_the_built_store_has_the_three_country_indexes_and_the_scan_uses_them(built: Path):
    with sqlite3.connect(built) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert {store.INDEX_KINDS, *store.INDEX_QUANTIFIED.values()} <= names
        for prefix, index in store.INDEX_QUANTIFIED.items():
            plan = connection.execute(
                f"EXPLAIN QUERY PLAN SELECT bw_id, {prefix}_value, sample_date FROM samples INDEXED BY {index} "
                f"WHERE country = ? AND {prefix}_kind IN ('Q','C') AND sample_date >= ? AND sample_date <= ? ORDER BY bw_id, {prefix}_value",
                ["IT", "2020-01-01", "2020-12-31"],
            ).fetchall()
            text = " ".join(str(row[-1]) for row in plan)
            assert index in text and "TEMP B-TREE" not in text  # read in index order: no sort
        plan = connection.execute(
            f"EXPLAIN QUERY PLAN SELECT ec_kind, ie_kind, COUNT(*) FROM samples INDEXED BY {store.INDEX_KINDS} "
            "WHERE country = ? AND sample_date >= ? AND sample_date <= ? GROUP BY ec_kind, ie_kind",
            ["IT", "2020-01-01", "2020-12-31"],
        ).fetchall()
        assert "COVERING INDEX" in " ".join(str(row[-1]) for row in plan)


def test_the_window_scan_ignores_a_row_without_a_value_or_a_date_and_a_row_outside_every_window():
    from oah.bathing_samples import country_scan
    from oah.indices.sqlite_aggregates import ReadGuard

    connection = sqlite3.connect(":memory:")
    country_scan.register(connection, ReadGuard(10, 60.0), [(2020 * 12 + 4, 2020 * 12 + 5)])
    connection.execute("CREATE TABLE t (b TEXT, v INTEGER, d TEXT)")
    connection.executemany(
        "INSERT INTO t VALUES (?,?,?)",
        [("x", 5, "2020-05-01"), ("x", None, "2020-05-02"), ("x", 7, None), ("x", 9, "2021-05-01"), ("y", 9, "2021-05-01"),
         ("x", 3, "2020-06-30"), ("x", 4, "2020-05-31")],
    )
    rows = dict(connection.execute("SELECT b, oah_window_scan(v, d) FROM t GROUP BY b"))
    assert country_scan.parse(rows["x"]) == [[3, 12, 3, 5, 3, 4.0]]  # n, sum, min, max, months May and June, median
    assert country_scan.parse(rows["y"]) == [None]


def test_a_ready_store_exposes_its_provenance(built: Path):
    assert store.store_status(built).ready and store.provenance(built)["unit"] == "cfu/100ml"


def test_the_connection_is_read_only(built: Path):
    with store._connection(built) as connection:
        assert connection is not None
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM samples")


# --- listing --------------------------------------------------------------------------------------------------------------


def test_samples_are_listed_by_date_then_uid_and_can_be_reversed(built: Path):
    total, rows = store.list_samples("ITSYN001", path=built)
    assert total == 11 and [row.sample_date for row in rows] == sorted(row.sample_date for row in rows)
    assert rows[0].sample_date == "2020-05-10" and rows[0].ec_value == 10 and rows[0].ec_kind == "Q" and rows[0].country == "IT"
    _, newest = store.list_samples("ITSYN001", descending=True, path=built)
    assert [row.sample_date for row in newest] == [row.sample_date for row in reversed(rows)]


def test_the_filters_narrow_by_date_and_season(built: Path):
    total, rows = store.list_samples("ITSYN001", "2022-06-01", "2022-08-10", path=built)
    assert total == 3 and [row.sample_date for row in rows] == ["2022-06-10", "2022-07-10", "2022-08-10"]  # both ends included
    assert store.list_samples("ITSYN001", season=2021, path=built)[0] == 1
    assert store.list_samples("ITSYN001", "2023-01-01", path=built) == (0, [])
    assert store.list_samples("ITSYN001", "2022-12-31", "2020-01-01", path=built) == (0, [])  # an inverted window matches nothing


def test_the_page_is_bounded_and_the_total_still_counts_everything(built: Path):
    total, rows = store.list_samples("ITSYN001", limit=2, path=built)
    assert total == 11 and len(rows) == 2
    assert len(store.list_samples("ITSYN001", limit=10_000, path=built)[1]) == 11  # clamped to 500, then the 11 rows there are
    assert len(store.list_samples("ITSYN001", limit=0, path=built)[1]) == 1  # at least one


def test_a_row_carries_both_values_both_statuses_and_the_sample_status(built: Path):
    _, rows = store.list_samples("ITSYN001", "2022-08-20", "2022-08-25", path=built)
    missing, confirmed = rows
    assert (missing.ec_value, missing.ec_status, missing.ec_kind, missing.ie_kind, missing.sample_status) == (0, "missingValue", "M", "M", "missingSample")
    assert (confirmed.ec_value, confirmed.ec_status, confirmed.ec_kind, confirmed.ie_value, confirmed.sample_status) == (900, "confirmedValue", "C", 9, "confirmationSample")
    assert confirmed.has_remarks is True and missing.has_remarks is False and confirmed.obs_status == "A" and confirmed.season == 2022


@pytest.mark.parametrize("bw_id", ["", "x" * 129, "'; DROP TABLE samples; --", "ITSYN001' OR '1'='1", "%", "ITSYN001%", "..\\..\\x"])
def test_an_identifier_is_a_value_never_sql(built: Path, bw_id: str):
    assert store.list_samples(bw_id, path=built) == (0, [])
    assert store.site_samples(bw_id, built) is None
    stats = store.indicator_stats(bw_id, "escherichia_coli", path=built)
    assert stats is None or stats.n_rows == 0
    assert store.list_samples("ITSYN001", path=built)[0] == 11  # nothing was dropped or matched by a wildcard


def test_the_filters_are_values_never_sql(built: Path):
    for text in ("2020-01-01' OR '1'='1", "'; DROP TABLE samples; --"):
        assert store.list_samples("ITSYN001", text, None, path=built)[0] == 11  # compared as plain text, never executed
        assert store.list_samples("ITSYN001", None, text, path=built)[0] == 0
    with sqlite3.connect(built) as connection:
        assert connection.execute("SELECT COUNT(*) FROM samples").fetchone()[0] == len(dataset())


def test_the_site_and_country_ranges_are_precomputed(built: Path):
    site = store.site_samples("ITSYN001", built)
    assert site is not None and (site.n_samples, site.first_date, site.last_date, site.first_season, site.last_season, site.country) == (
        11, "2020-05-10", "2022-08-25", 2020, 2022, "IT",
    )
    greek = store.site_samples("ELSYN001", built)
    assert greek is not None and greek.country == "GR"
    countries = {item.country: item for item in store.countries_summary(built)}
    assert set(countries) == {"GR", "IT"} and countries["GR"].n_samples == 6 and countries["IT"].bathing_waters == 4
    assert (countries["IT"].first_date, countries["IT"].last_date) == ("2020-05-10", "2022-08-25")
    assert countries["GR"].n_quantified_ec == 4 and countries["GR"].n_quantified_ie == 3  # flagged, missing and unknown values are not counted
    assert store.normalise_country("el") == "GR" and store.normalise_country(" it ") == "IT" and store.normalise_country("no") == "NO"


# --- exact statistics -------------------------------------------------------------------------------------------------------


def test_the_statistics_are_exact_and_use_only_quantified_values(built: Path):
    stats = store.indicator_stats("ITSYN001", "escherichia_coli", path=built)
    assert stats is not None
    # quantified: 10 20 30 40 7 100 200 300 and the confirmed 900; flagged apart: one detection limit, one missing
    assert (stats.n_rows, stats.n_quantified, stats.n_confirmed_high, stats.n_detection_limit, stats.n_missing) == (11, 9, 1, 1, 1)
    assert (stats.low, stats.high, stats.total) == (7, 900, 10 + 20 + 30 + 40 + 7 + 100 + 200 + 300 + 900)
    assert stats.mean == 1607 / 9
    assert stats.median == 40.0  # the 5th of 9 sorted values: 7 10 20 30 40 100 200 300 900


def test_the_median_of_an_even_count_is_the_mean_of_the_two_middle_values(built: Path):
    stats = store.indicator_stats("ITSYN001", "escherichia_coli", "2020-05-01", "2020-08-31", path=built)
    assert stats is not None and stats.n_quantified == 4 and stats.mean == 25.0 and stats.median == 25.0 and (stats.low, stats.high) == (10, 40)
    odd = store.indicator_stats("ITSYN001", "intestinal_enterococci", "2022-01-01", "2022-12-31", path=built)
    assert odd is not None and odd.n_quantified == 5 and odd.median == 7.0 and odd.mean == 7.0  # 5 6 7 8 9


def test_a_flagged_value_is_never_in_a_statistic(built: Path):
    greek = store.indicator_stats("ELSYN001", "escherichia_coli", path=built)
    assert greek is not None and (greek.n_rows, greek.n_quantified, greek.n_detection_limit) == (4, 3, 1)
    assert greek.low == 20 and greek.high == 24 and greek.mean == 22.0 and greek.median == 22.0  # the detection-limit 9 is not in them
    odd = store.indicator_stats("ELSYN002", "escherichia_coli", path=built)
    assert odd is not None and (odd.n_rows, odd.n_quantified, odd.n_invalid, odd.low) == (2, 1, 1, 31)  # the negative number is invalid
    other = store.indicator_stats("ELSYN002", "intestinal_enterococci", path=built)
    assert other is not None and (other.n_missing, other.n_unknown_status, other.n_quantified, other.mean, other.median, other.low) == (1, 1, 0, None, None, None)


def test_no_sample_means_no_statistics_but_counts_of_zero(built: Path):
    empty = store.indicator_stats("ITSYN001", "escherichia_coli", "2030-01-01", path=built)
    assert empty is not None and empty.n_rows == 0 and empty.mean is None and empty.median is None and empty.low is None


# --- reads for the period comparison -----------------------------------------------------------------------------------------


def test_the_month_cells_hold_n_sum_min_and_max_of_the_quantified_values(built: Path):
    cells = store.month_cells("site", "ITSYN001", "escherichia_coli", [A, B], built)
    by_month = {(cell.year, cell.month): (cell.n, cell.total, cell.low, cell.high) for cell in cells}
    assert by_month[(2020, 5)] == (1, 10, 10, 10) and by_month[(2020, 8)] == (1, 40, 40, 40)
    assert by_month[(2022, 8)] == (1, 900, 900, 900)  # the detection-limit and missing rows of August are not in the cell
    assert (2021, 5) not in by_month  # outside both windows


def test_a_country_read_covers_every_bathing_water_of_the_country_only(built: Path):
    cells = store.month_cells("country", "IT", "escherichia_coli", [A], built)
    assert {cell.bw_id for cell in cells} == {"ITSYN001", "ITSYN002", "ITSYN003", "ITSYN004"}
    assert store.month_cells("country", "GR", "escherichia_coli", [A], built) == []


def test_the_kind_counts_and_values_of_a_window(built: Path):
    assert store.kind_counts("site", "ITSYN001", "escherichia_coli", B, built) == {"Q": 3, "D": 1, "M": 1, "C": 1}
    assert store.kind_counts("country", "GR", "escherichia_coli", (month_position(2023, 5), month_position(2023, 8)), built) == {"Q": 4, "D": 1, "I": 1}
    assert store.window_values("site", "ITSYN001", "escherichia_coli", B, built) == {"ITSYN001": [100, 200, 300, 900]}
    assert store.window_values("site", "ITSYN001", "escherichia_coli", (month_position(2019, 1), month_position(2019, 12)), built) == {}


def test_the_quantified_range_is_per_indicator(built: Path):
    assert store.quantified_range("site", "ITSYN001", "escherichia_coli", built) == ("2020-05-10", "2022-08-25")
    assert store.quantified_range("country", "IT", "escherichia_coli", built) == ("2020-05-10", "2022-08-25")
    assert store.quantified_range("country", "GR", "escherichia_coli", built) == ("2023-05-05", "2023-07-05")  # the 08-05 value is a detection limit
    assert store.quantified_range("country", "NO", "escherichia_coli", built) is None
    assert store.quantified_range("site", "nobody", "escherichia_coli", built) is None


def test_windows_are_validated_and_a_country_read_has_a_row_cap(built: Path, monkeypatch):
    with pytest.raises(ValueError):
        store.month_cells("site", "ITSYN001", "escherichia_coli", [], built)
    with pytest.raises(ValueError):
        store.month_cells("site", "ITSYN001", "escherichia_coli", [A, B, A], built)
    monkeypatch.setattr(store, "MAX_COUNTRY_ROWS", 3)
    with pytest.raises(store.RowCapExceeded):
        store.window_values("country", "IT", "escherichia_coli", A, built)


def test_an_unknown_indicator_is_a_programming_error_not_sql(built: Path):
    with pytest.raises(KeyError):
        store.indicator_stats("ITSYN001", "escherichia_coli; DROP TABLE samples", path=built)


def test_a_store_built_from_other_rows_reads_the_same_way(tmp_path: Path):
    rows = [raw_row(1, "ITONE", "2021-06-01", (5, None), (6, None)), raw_row(2, "ITONE", "2021-06-02", (15, None), (16, None))]
    path = build_fixture_store(tmp_path, rows=rows)
    stats = store.indicator_stats("ITONE", "escherichia_coli", path=path)
    assert stats is not None and stats.median == 10.0 and stats.mean == 10.0


# --- paths and settings ----------------------------------------------------------------------------------------------------


def test_the_default_store_and_work_paths_come_from_the_paths_module_under_the_data_dir(tmp_path: Path, monkeypatch):
    from oah.config import data_dir
    from oah.paths import bathing_samples_store_path, bathing_samples_work_dir

    monkeypatch.delenv("OAH_BATHING_SAMPLES_STORE", raising=False)
    assert bathing_samples_store_path() == data_dir() / "bathing_samples" / "bathing_samples_discodata.sqlite"
    assert bathing_samples_work_dir() == data_dir() / "bathing_samples" / "work"
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(tmp_path / "elsewhere.sqlite"))
    assert bathing_samples_store_path() == tmp_path / "elsewhere.sqlite"
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", "   ")
    assert bathing_samples_store_path() == data_dir() / "bathing_samples" / "bathing_samples_discodata.sqlite"  # blank means unset


def test_the_store_setting_must_be_an_absolute_path(monkeypatch):
    from oah.paths import bathing_samples_store_path

    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", "relative/samples.sqlite")
    with pytest.raises(RuntimeError, match="OAH_BATHING_SAMPLES_STORE must be an absolute external path"):
        bathing_samples_store_path()
