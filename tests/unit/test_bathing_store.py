"""The read-only bathing-water reader: states, filters, bounds, parameterised SQL. Stores are SYNTHETIC (tmp dirs)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from bathing_fixtures import build_fixture_store

from oah.bathing import service, store
from oah.bathing.build import DDL


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path)
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(path))
    return path


def test_a_store_that_was_not_built_is_a_clear_state_and_nothing_crashes(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "absent.sqlite"))
    status = store.store_status()
    assert status.state == "not-built" and "build_bathing_water_store.py" in status.detail and not status.ready
    assert store.list_bathing_waters() == (0, [])
    assert store.get_bathing_water("EL001") is None and store.history("EL001") == []
    assert store.countries_summary() == [] and store.provenance() == {}
    assert service.status_payload()["state"] == "not-built" and service.find("EL001") is None
    assert service.list_page(None, None, None, None, 10, 0) == (0, []) and service.country_blocks() == {}
    assert service.freshness() == {"status": "snapshot", "as_of": None, "age_seconds": None}


def test_a_corrupt_foreign_or_future_file_is_reported_as_unreadable(tmp_path: Path, monkeypatch):
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"this is not a sqlite database" * 40)
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(broken))
    assert store.store_status().state == "unreadable" and store.list_bathing_waters() == (0, [])
    other = tmp_path / "other.sqlite"
    connection = sqlite3.connect(other)
    connection.execute("CREATE TABLE unrelated (x)")
    connection.commit()
    connection.close()
    assert store.store_status(other).state == "unreadable"
    future = tmp_path / "future.sqlite"
    connection = sqlite3.connect(future)
    connection.executescript(DDL)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', '99')")
    connection.commit()
    connection.close()
    assert store.store_status(future).state == "unreadable"
    assert store.list_bathing_waters(path=future) == (0, [])


def test_a_ready_store_lists_its_provenance_and_status_block(built: Path):
    assert store.store_status().ready
    info = store.provenance()
    assert info["source"].startswith("EEA Bathing Water Directive") and info["licence"].startswith("EEA CC BY 4.0")
    status = service.status_payload()
    assert status["state"] == "ready" and status["build_date_utc"] == "2026-10-02T00:00:00Z" and status["attribution"].endswith("(EEA CC BY 4.0)")
    assert service.freshness() == {"status": "snapshot", "as_of": "2026-10-02T00:00:00Z", "age_seconds": None}


def test_bathing_waters_are_filtered_by_country_text_type_and_quality(built: Path):
    ids = lambda **kw: [b.bw_id for b in store.list_bathing_waters(**kw)[1]]  # noqa: E731
    assert ids() == ["EL001", "EL002", "GR003", "IT001", "IT002", "IT003", "IT004", "NO001"]
    assert ids(country="IT") == ["IT001", "IT002", "IT003", "IT004"]
    assert ids(country="el") == ids(country="GR") == ["EL001", "EL002", "GR003"]  # EL is read as GR
    assert ids(country="DK") == []
    assert ids(q="synthetic beach") == ["EL001", "GR003"] and ids(q="it00") == ["IT001", "IT002", "IT003", "IT004"]
    assert ids(water_type="lakeBathingWater") == ["EL002"] and ids(water_type="RIVERBATHINGWATER") == ["IT002"]
    assert ids(quality="1 - Excellent") == ids(quality="excellent") == ["EL002", "IT004", "NO001"]  # the LATEST season's class
    assert ids(quality="2 - Good") == ["EL001"] and ids(quality="nothing") == []
    assert ids(country="IT", quality="Poor", water_type="coastalBathingWater") == ["IT003"]


def test_the_name_placeholder_and_null_fields_come_back_as_null(built: Path):
    item = store.get_bathing_water("IT001")
    assert item is not None and item.name is None and item.type == "coastalBathingWater" and item.latest_quality == "0 - Not classified"
    assert (item.first_season, item.last_season, item.n_seasons) == (2020, 2021, 2)
    entry = service.entry(item)
    assert entry["name"] == "IT001" and entry["latitude"] == 35.0 and entry["location_status"] == "located"
    missing = store.get_bathing_water("IT004")
    assert missing is not None and service.entry(missing)["latitude"] is None and service.entry(missing)["location_status"] == "no-location"


def test_like_wildcards_in_the_text_filter_are_literal(built: Path):
    assert [b.bw_id for b in store.list_bathing_waters(q="100%")[1]] == ["IT004"]
    assert [b.bw_id for b in store.list_bathing_waters(q="_SYNTH_")[1]] == ["IT004"]
    assert store.list_bathing_waters(q="%")[0] == 1 and store.list_bathing_waters(q="_")[0] == 1  # not "everything"
    assert store.list_bathing_waters(q="\\")[0] == 0


def test_sql_injection_in_every_filter_is_inert(built: Path):
    payload = "'; DROP TABLE sites; --"
    assert store.list_bathing_waters(q=payload) == (0, [])
    assert store.list_bathing_waters(country=payload) == (0, [])
    assert store.list_bathing_waters(water_type=payload) == (0, [])
    assert store.list_bathing_waters(quality=payload) == (0, [])
    assert store.get_bathing_water(payload) is None and store.history(payload) == []
    assert store.list_bathing_waters()[0] == 8  # the table is intact
    assert store.list_bathing_waters(q="x' OR '1'='1")[0] == 0


def test_pages_are_bounded_and_ordered(tmp_path: Path, monkeypatch):
    path = tmp_path / "many.sqlite"
    connection = sqlite3.connect(path)
    connection.executescript(DDL)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', ?)", (store.SUPPORTED_SCHEMA,))
    connection.executemany(
        "INSERT INTO sites VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [(f"B{i:04d}", "IT", None, f"Beach {i}", "coastalBathingWater", "FALSE", 40.0, 10.0, None, 2025, 2025, 1, "1 - Excellent", "Excellent") for i in range(700)],
    )
    connection.commit()
    connection.close()
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(path))
    total, page = store.list_bathing_waters()
    assert total == 700 and len(page) == 200 and page[0].bw_id == "B0000"
    total, page = store.list_bathing_waters(limit=10_000)
    assert len(page) == store.MAX_PAGE == 500
    assert [b.bw_id for b in store.list_bathing_waters(limit=0)[1]] == ["B0000"]  # at least one row
    assert [b.bw_id for b in store.list_bathing_waters(limit=2, offset=-5)[1]] == ["B0000", "B0001"]
    assert store.list_bathing_waters(limit=500, offset=500)[1][-1].bw_id == "B0699"
    assert store.list_bathing_waters(offset=10_000)[1] == []
    long_text = "x" * 5000
    assert store.list_bathing_waters(q=long_text, water_type=long_text, quality=long_text)[0] == 0  # cut, not an error
    assert store.get_bathing_water("B" * 129) is None


def test_the_history_is_ordered_by_season_and_bounded(built: Path):
    rows = store.history("EL001")
    assert [r.season for r in rows] == [2024, 2025] and rows[0].quality_class == "Excellent" and rows[0].monitoring_calendar == "1 - Implemented"
    assert store.history("IT001")[1].management == "4 - Monitoring gap"
    assert store.history("NOPE") == [] and store.history("") == []
    found = service.find("EL001")
    assert found is not None and [h["season"] for h in found["history"]] == [2024, 2025] and found["origin"] == "real-eea-bathing-water"


def test_the_connection_is_read_only(built: Path):
    with store._connection() as connection:
        assert connection is not None
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("DELETE FROM sites")


def test_the_countries_summary_counts_and_the_latest_season(built: Path):
    by_country = {s.country: s for s in store.countries_summary()}
    assert set(by_country) == {"GR", "IT", "NO"}
    greece = by_country["GR"]
    assert (greece.bathing_waters, greece.classification_rows, greece.first_season, greece.latest_season) == (3, 4, 2024, 2025)
    assert greece.latest_season_counts == {"1 - Excellent": 1, "2 - Good": 1, "3 - Sufficient": 1}
    italy = by_country["IT"]
    assert italy.latest_season == 2025 and italy.latest_season_counts == {"1 - Excellent": 1, "4 - Poor": 1, "9 - Surprise": 1}
    blocks = service.country_blocks()
    assert blocks["IT"]["content"] == "classification-only" and blocks["IT"]["origin"] == "real-eea-bathing-water"
    assert blocks["GR"]["bathing_waters"] == 3 and blocks["GR"]["attribution"].endswith("(EEA CC BY 4.0)")
