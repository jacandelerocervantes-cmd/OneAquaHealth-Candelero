"""The read-only Waterbase reader: states, filters, bounds, parameterised SQL."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from waterbase_fixtures import NITRATE, build_fixture_store

from oah.waterbase import store
from oah.waterbase.build import DDL


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    return path


def test_a_store_that_was_not_built_is_a_clear_state_and_nothing_crashes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(tmp_path / "absent.sqlite"))
    status = store.store_status()
    assert status.state == "not-built" and "build_waterbase_store.py" in status.detail and not status.ready
    assert store.list_sites() == (0, [])
    assert store.get_site("IT01-001025") is None
    assert store.site_series("IT01-001025") == (0, [])
    assert store.countries_summary() == [] and store.provenance() == {}


def test_a_corrupt_or_foreign_file_is_reported_as_unreadable(tmp_path: Path, monkeypatch):
    path = tmp_path / "broken.sqlite"
    path.write_bytes(b"this is not a sqlite database" * 40)
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    assert store.store_status().state == "unreadable"
    assert store.list_sites() == (0, [])
    other = tmp_path / "other.sqlite"
    connection = sqlite3.connect(other)
    connection.execute("CREATE TABLE unrelated (x)")
    connection.commit()
    connection.close()
    assert store.store_status(other).state == "unreadable"


def test_a_store_of_another_schema_version_is_not_read(tmp_path: Path):
    path = tmp_path / "future.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', '99')")
    connection.commit()
    connection.close()
    assert store.store_status(path).state == "unreadable"


def test_a_ready_store_lists_its_provenance(built: Path):
    assert store.store_status().ready
    info = store.provenance()
    assert info["source"] == "EEA Waterbase - Water Quality ICM 2026" and info["licence"].startswith("CC BY 4.0")


def test_sites_are_filtered_by_country_category_and_text(built: Path):
    total, everything = store.list_sites()
    assert total == 5
    assert [s.site_id for s in everything] == ["EL000123", "IT01-001025", "IT02-LAKE1", "IT99-NOSPATIAL", "NO0001"]
    assert store.list_sites("it")[0] == 3
    assert store.list_sites("GR")[0] == 1
    assert [s.site_id for s in store.list_sites(category="lake")[1]] == ["IT02-LAKE1"]
    assert [s.site_id for s in store.list_sites(q="revello")[1]] == ["IT01-001025"]  # a name, case-insensitive
    assert [s.site_id for s in store.list_sites(q="Testelva nedre")[1]] == ["NO0001"]  # a water body name
    assert [s.site_id for s in store.list_sites("IT", q="nospatial")[1]] == ["IT99-NOSPATIAL"]
    assert store.list_sites("DE") == (0, [])


def test_sites_without_coordinates_are_listed_and_know_it(built: Path):
    sites = {s.site_id: s for s in store.list_sites()[1]}
    assert sites["EL000123"].has_location is False and sites["EL000123"].confidentiality == "N"
    assert sites["IT01-001025"].has_location is True
    assert sites["IT02-LAKE1"].water_category == "lake" and sites["IT01-001025"].water_category == "river"


def test_like_wildcards_in_the_text_filter_are_literal(built: Path):
    assert store.list_sites(q="%")[0] == 0 and store.list_sites(q="_")[0] == 0
    assert store.list_sites(q="IT0_-LAKE1")[0] == 0  # an underscore is not "any character" (nor is the dash special)


def test_sql_injection_in_the_filters_is_inert(built: Path):
    for text in ("'; DROP TABLE sites; --", "x' OR '1'='1", 'a" OR 1=1 --'):
        assert store.list_sites(q=text)[0] == 0
        assert store.list_sites(country=text)[0] == 0
        assert store.get_site(text) is None
        assert store.site_series("IT01-001025", determinand=text) == (0, [])
    assert store.list_sites()[0] == 5  # the table is intact


def test_pages_are_bounded_and_ordered(tmp_path: Path, monkeypatch):
    path = tmp_path / "many.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', ?)", [store.SUPPORTED_SCHEMA])
    connection.executemany(
        "INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(f"S{i:04d}", "IT", "RW", None, None, None, None, None, None, 2015, 2015, 1) for i in range(700)],
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    total, page = store.list_sites(limit=100_000)
    assert total == 700 and len(page) == store.MAX_PAGE == 500
    assert len(store.list_sites(limit=0)[1]) == 1 and len(store.list_sites(limit=-5)[1]) == 1
    second = store.list_sites(limit=500, offset=500)[1]
    assert [s.site_id for s in second] == [f"S{i:04d}" for i in range(500, 700)]
    assert store.list_sites(offset=-3)[1][0].site_id == "S0000"
    assert len(store.list_sites(q="S" * 500)[1]) == 0  # an over-long text is cut, not an error


def test_the_connection_is_read_only(built: Path):
    connection = store._open(built)
    try:
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM sites")
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE x (y)")
    finally:
        connection.close()


def test_a_site_series_is_filtered_by_determinand_matrix_and_years(built: Path):
    total, rows = store.site_series("IT01-001025")
    assert total == len(rows) == 12
    assert [r.year for r in rows] == sorted(r.year for r in rows)
    total, nitrate = store.site_series("IT01-001025", NITRATE[0])
    assert [(r.year, r.n, r.mean, r.min, r.max, r.n_lower_reliability) for r in nitrate] == [
        (2015, 2, 2.0, 1.0, 3.0, 1), (2016, 1, 2.0, 2.0, 2.0, 0),
    ]
    assert store.site_series("IT01-001025", NITRATE[0], year_from=2016)[0] == 1
    assert store.site_series("IT01-001025", NITRATE[0], year_to=2015)[0] == 1
    assert store.site_series("IT01-001025", "CAS_7439-92-1", matrix="W")[0] == 1
    assert store.site_series("IT01-001025", "CAS_7439-92-1", matrix="W-DIS")[0] == 1
    assert len(store.site_series("IT01-001025", limit=3)[1]) == 3
    assert store.site_series("IT01-001025", limit=3)[0] == 12  # the total is not cut


def test_the_countries_summary(built: Path):
    summary = {s.country: s for s in store.countries_summary()}
    assert set(summary) == {"GR", "IT", "NO"}
    italy = summary["IT"]
    assert (italy.sites, italy.river_sites, italy.lake_sites, italy.sites_without_location) == (3, 2, 1, 1)
    assert (italy.first_year, italy.last_year) == (2015, 2016)
    assert summary["GR"].sites_without_location == 1 and summary["GR"].last_year == 2017


def test_the_store_path_defaults_to_the_data_directory_and_can_be_overridden(tmp_path: Path, monkeypatch):
    from oah.paths import waterbase_store_path

    monkeypatch.delenv("OAH_WATERBASE_STORE", raising=False)
    assert waterbase_store_path().parent.name == "waterbase" and waterbase_store_path().suffix == ".sqlite"
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(tmp_path / "x.sqlite"))
    assert waterbase_store_path() == tmp_path / "x.sqlite"
    monkeypatch.setenv("OAH_WATERBASE_STORE", "relative/store.sqlite")
    with pytest.raises(RuntimeError, match="OAH_WATERBASE_STORE"):
        waterbase_store_path()


def test_the_seven_zip_location_follows_the_setting_then_the_path(tmp_path: Path, monkeypatch):
    from oah import paths

    fake = tmp_path / "7z.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv("OAH_SEVENZIP_PATH", str(fake))
    assert paths.sevenzip_executable() == fake
    monkeypatch.setenv("OAH_SEVENZIP_PATH", str(tmp_path / "missing.exe"))
    assert paths.sevenzip_executable() is None  # a wrong setting is not silently replaced
    monkeypatch.delenv("OAH_SEVENZIP_PATH")
    monkeypatch.setattr("shutil.which", lambda name: str(fake) if name == "7z" else None)
    assert paths.sevenzip_executable() == fake
    monkeypatch.setenv("OAH_SEVENZIP_PATH", "7z.exe")
    with pytest.raises(RuntimeError, match="OAH_SEVENZIP_PATH"):
        paths.sevenzip_executable()
