"""The bathing-water store build: filters, classification handling, provenance, atomic and deterministic writes.

Every workbook is SYNTHETIC (``bathing_fixtures``); the values are invented for the tests.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

import importlib
import pytest
from bathing_fixtures import HEADER, build_fixture_store, make_archive, row, standard_rows

from oah.bathing import constants
from oah.bathing.build import build_store
from oah.bathing.constants import (
    COUNTRY_CODES,
    KNOWN_QUALITY_VALUES,
    README_BACTERIA_SENTENCE,
    README_CLASSES_SENTENCE,
    README_SAMPLES_SENTENCE,
    quality_class,
    safe_profile_url,
)
from oah.bathing.xlsx import XlsxError
from oah.paths import repo_path


def _query(path: Path, sql: str, *params: Any) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(path)
    try:
        return connection.execute(sql, params).fetchall()
    finally:
        connection.close()


def _provenance(path: Path) -> dict[str, str]:
    return dict(_query(path, "SELECT key, value FROM provenance"))


@pytest.fixture()
def store_path(tmp_path: Path) -> Path:
    return build_fixture_store(tmp_path)


def test_the_country_filter_keeps_greece_as_el_or_gr_italy_and_norway(store_path: Path):
    assert COUNTRY_CODES == {"EL": "GR", "GR": "GR", "IT": "IT", "NO": "NO"}
    countries = dict(_query(store_path, "SELECT country, COUNT(*) FROM sites GROUP BY country"))
    assert countries == {"GR": 3, "IT": 4, "NO": 1}  # EL001, EL002 and GR003 are all GR; DK001 is gone
    assert _query(store_path, "SELECT COUNT(*) FROM sites WHERE bw_id LIKE 'DK%'") == [(0,)]


def test_every_season_of_a_kept_bathing_water_is_kept(store_path: Path):
    seasons = _query(store_path, "SELECT season, quality FROM classifications WHERE bw_id = 'EL001' ORDER BY season")
    assert seasons == [(2024, "1 - Excellent"), (2025, "2 - Good")]
    site = _query(store_path, "SELECT first_season, last_season, n_seasons, latest_quality, latest_quality_class FROM sites WHERE bw_id = 'EL001'")
    assert site == [(2024, 2025, 2, "2 - Good", "Good")]


def test_a_classification_value_outside_the_known_set_is_kept_as_written_and_reported(store_path: Path):
    assert _query(store_path, "SELECT quality, quality_class FROM classifications WHERE bw_id = 'IT002' AND season = 2025") == [("9 - Surprise", "Surprise")]
    info = _provenance(store_path)
    assert json.loads(info["unknown_quality_values"]) == ["9 - Surprise"]
    assert json.loads(info["value_counts"])["quality"]["9 - Surprise"] == 2  # file rows, before the duplicate is resolved
    # the values the real file holds are known and kept as the file writes them (including those the README does not explain)
    assert "3 - Good or Sufficient" in KNOWN_QUALITY_VALUES and "0 - Not classified" in KNOWN_QUALITY_VALUES
    assert _query(store_path, "SELECT quality FROM classifications WHERE bw_id = 'IT001' ORDER BY season") == [("3 - Good or Sufficient",), ("0 - Not classified",)]


def test_a_blank_class_is_stored_as_null_and_counted(store_path: Path):
    assert _query(store_path, "SELECT quality, quality_class FROM classifications WHERE bw_id = 'IT002' AND season = 2024") == [(None, None)]
    counts = json.loads(_provenance(store_path)["row_counts"])
    assert counts["rows_without_quality"] == 1
    assert json.loads(_provenance(store_path)["value_counts"])["quality"]["(blank)"] == 1


def test_missing_or_invalid_coordinates_are_null_and_an_earlier_season_supplies_them(store_path: Path):
    # EL001 has coordinates only in 2024; the latest row has none: the site keeps the last known position
    assert _query(store_path, "SELECT lat, lon FROM sites WHERE bw_id = 'EL001'") == [(35.1, 25.1)]
    # IT004: a non-numeric longitude and a latitude of 95: both dropped, the bathing water is still listed
    assert _query(store_path, "SELECT lat, lon, name FROM sites WHERE bw_id = 'IT004'") == [(None, None, "100% _SYNTH_ BEACH")]
    counts = json.loads(_provenance(store_path)["row_counts"])
    assert counts["bathing_waters_without_coordinates"] == 1 and counts["rows_coordinates_invalid_or_partial"] >= 1


def test_the_placeholder_name_becomes_null(store_path: Path):
    assert _query(store_path, "SELECT name FROM sites WHERE bw_id = 'IT001'") == [(None,)]


def test_a_profile_link_is_kept_only_when_it_is_http_text(store_path: Path):
    assert _query(store_path, "SELECT profile_url FROM sites WHERE bw_id = 'IT003'") == [(None,)]  # javascript: is not kept
    assert _query(store_path, "SELECT profile_url FROM sites WHERE bw_id = 'EL001'")[0][0].startswith("https://example.invalid/")
    assert json.loads(_provenance(store_path)["row_counts"])["profile_url_not_http"] == 1
    assert safe_profile_url(" http://x.example/a ") == "http://x.example/a" and safe_profile_url("ftp://x") is None
    assert safe_profile_url(None) is None and safe_profile_url("https://a b") is None


def test_dropped_rows_are_counted_by_reason(store_path: Path):
    counts = json.loads(_provenance(store_path)["row_counts"])
    assert counts["rows_scanned"] == len(standard_rows()) - 1
    assert counts["rows_other_countries"] == 1 and counts["dropped_no_identifier"] == 1
    assert counts["dropped_bad_season"] == 3  # blank, text and fractional seasons
    assert counts["duplicate_site_season_rows"] == 2 and counts["duplicate_site_season_rows_conflicting"] == 1
    assert counts["rows_country_kept"] + counts["rows_other_countries"] == counts["rows_scanned"]
    assert counts["bathing_waters"] == 8 and counts["classification_rows"] == _query(store_path, "SELECT COUNT(*) FROM classifications")[0][0]
    # of two conflicting rows for the same bathing water and season the smallest value tuple wins, whatever the input order
    assert _query(store_path, "SELECT management FROM classifications WHERE bw_id = 'IT002' AND season = 2025") == [("1 - Continuously monitored",)]


def test_provenance_records_source_licence_edition_hash_and_the_honest_content_statement(tmp_path: Path):
    archive = make_archive(tmp_path / "a.zip")
    target = tmp_path / "s.sqlite"
    build_store(archive, target, tmp_path / "work", build_date="2026-10-02T00:00:00Z")
    info = _provenance(target)
    assert info["licence"] == "EEA CC BY 4.0 (EEA legal notice; dataset page does not restate it)"
    assert info["edition"].startswith("Bathing Water Directive - Status of bathing water, 2025 v.1.0")
    assert info["archive_sha256"] == hashlib.sha256(archive.read_bytes()).hexdigest() and info["archive_sha256_source"] == "computed"
    assert info["archive_bytes"] == str(archive.stat().st_size) and info["archive_name"] == "a.zip"
    assert info["build_date_utc"] == "2026-10-02T00:00:00Z" and info["schema_version"] == "1"
    assert info["sheet"] == "bw_assessment_datahub_1990_2025" and info["workbook"] == "bw_assessment_eea_datahub_1990_2025.xlsx"
    assert "no E. coli or intestinal enterococci concentration" in info["content"]
    assert json.loads(info["readme_statements"]) == [README_BACTERIA_SENTENCE, README_CLASSES_SENTENCE, README_SAMPLES_SENTENCE]
    assert json.loads(info["filters"])["seasons"] == "all"
    assert json.loads(info["filters"])["countries_stored"] == ["GR", "IT", "NO"]
    assert "source_url" in info and info["attribution"].endswith("(EEA CC BY 4.0)")
    values = json.loads(info["value_counts"])
    assert set(values) == {"quality", "type", "monitoring_calendar", "management"}
    assert values["type"]["lakeBathingWater"] == 1 and values["monitoring_calendar"]["0 - Not implemented"] == 1


def test_no_concentration_or_limit_column_exists_in_the_store(store_path: Path):
    for table in ("sites", "classifications"):
        columns = {name.lower() for _, name, *_rest in _query(store_path, f"PRAGMA table_info({table})")}
        assert not any(word in name for name in columns for word in ("coli", "enterococ", "cfu", "concentration", "limit", "threshold"))


def test_the_readme_sentences_are_the_exact_wording_only():
    assert README_CLASSES_SENTENCE == (
        "Based on the monitoring results for these bacteria, bathing waters are classified into four quality categories: "
        "excellent, good, sufficient, or poor."
    )
    assert README_BACTERIA_SENTENCE == "Member States are also requested to monitor the concentration in water of E. coli and intestinal enterococci."
    assert README_SAMPLES_SENTENCE == "At least four water samples per bathing water need to be collected and analysed"
    assert "Directive 2006/7/EC" in constants.NOTICE and "not a concentration" in constants.NOTICE


def test_quality_class_is_the_label_after_the_code():
    assert quality_class("1 - Excellent") == "Excellent" and quality_class("3 - Good or Sufficient") == "Good or Sufficient"
    assert quality_class("Excellent") is None and quality_class("") is None and quality_class(None) is None


def test_the_write_is_atomic_and_leaves_no_temporary_file(tmp_path: Path):
    target = build_fixture_store(tmp_path)
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    before = target.read_bytes()
    broken = make_archive(tmp_path / "broken.zip", [HEADER, row("IT", "IT001", 2025, "1 - Excellent")])
    # a build that fails midway must not touch the existing store: a layout without the sheet fails before any write
    with pytest.raises(XlsxError):
        build_store(broken, target, tmp_path / "work", sheet_name="absent")
    assert target.read_bytes() == before and [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []


def test_a_failure_while_writing_removes_the_temporary_file_and_keeps_the_old_store(tmp_path: Path, monkeypatch):
    target = build_fixture_store(tmp_path)
    before = target.read_bytes()
    import oah.bathing.build as build_module

    monkeypatch.setattr(build_module, "INDEXES", "CREATE INDEX broken ON no_such_table (x);")
    with pytest.raises(sqlite3.OperationalError):
        build_store(make_archive(tmp_path / "again.zip"), target, tmp_path / "work")
    assert target.read_bytes() == before and not target.with_name(target.name + ".tmp").exists()


def test_the_same_input_builds_the_same_tables(tmp_path: Path):
    first, second = tmp_path / "one", tmp_path / "two"
    first.mkdir()
    second.mkdir()
    a = build_fixture_store(first, build_date="2026-10-02T00:00:00Z")
    b = build_fixture_store(second, build_date="2026-10-02T00:00:00Z")
    for table in ("sites", "classifications"):
        assert _query(a, f"SELECT * FROM {table} ORDER BY 1, 2") == _query(b, f"SELECT * FROM {table} ORDER BY 1, 2")
    assert _provenance(a)["row_counts"] == _provenance(b)["row_counts"]
    # input order does not matter either
    shuffled = [standard_rows()[0], *reversed(standard_rows()[1:])]
    c = build_fixture_store(tmp_path, rows=shuffled, name="shuffled.sqlite")
    assert _query(a, "SELECT bw_id, season, quality FROM classifications ORDER BY 1, 2") == _query(
        c, "SELECT bw_id, season, quality FROM classifications ORDER BY 1, 2"
    )


def test_inline_strings_build_the_same_store_as_shared_strings(tmp_path: Path):
    shared = build_fixture_store(tmp_path)
    inline_dir = tmp_path / "inline"
    inline_dir.mkdir()
    inline = build_fixture_store(inline_dir, inline_columns=frozenset(range(13)))
    assert _query(shared, "SELECT * FROM sites ORDER BY 1") == _query(inline, "SELECT * FROM sites ORDER BY 1")


def test_a_compressed_workbook_member_builds_too(tmp_path: Path):
    archive = make_archive(tmp_path / "deflated.zip", stored=False)
    target = tmp_path / "s.sqlite"
    counters = build_store(archive, target, tmp_path / "work")
    assert counters["bathing_waters"] == 8


def test_a_changed_layout_is_refused_with_the_missing_column_named(tmp_path: Path):
    rows: list[list[Any]] = [[name for name in HEADER if name != "quality"], ["IT", "IT001", None, "N", "coastalBathingWater", "FALSE", 1.0, 2.0, None, 2025, None, None]]
    with pytest.raises(XlsxError, match="quality"):
        build_store(make_archive(tmp_path / "a.zip", rows), tmp_path / "s.sqlite", tmp_path / "work")


def test_an_empty_sheet_or_a_slice_with_no_kept_row_does_not_write_a_store(tmp_path: Path):
    with pytest.raises(XlsxError, match="empty"):
        build_store(make_archive(tmp_path / "e.zip", []), tmp_path / "s.sqlite", tmp_path / "work")
    only_other = [HEADER, row("DK", "DK001", 2025, "1 - Excellent")]
    with pytest.raises(RuntimeError, match="refusing to write an empty store"):
        build_store(make_archive(tmp_path / "d.zip", only_other), tmp_path / "s.sqlite", tmp_path / "work")
    assert not (tmp_path / "s.sqlite").exists()


def test_a_missing_archive_is_a_clear_error(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="docs/bathing_water_store.md"):
        build_store(tmp_path / "absent.zip", tmp_path / "s.sqlite", tmp_path / "work")


def test_a_bathing_water_listed_under_two_countries_keeps_the_first_and_is_counted(tmp_path: Path):
    rows = [HEADER, row("IT", "X1", 2024, "1 - Excellent"), row("EL", "X1", 2025, "2 - Good")]
    target = tmp_path / "s.sqlite"
    counters = build_store(make_archive(tmp_path / "a.zip", rows), target, tmp_path / "work")
    assert counters["bathing_waters_in_two_countries"] == 1
    assert _query(target, "SELECT country, n_seasons FROM sites") == [("IT", 1)]  # the row of the other country is not stored


# --- the command line -----------------------------------------------------------------------------------------------


@pytest.fixture()
def script():
    scripts_dir = str(repo_path("scripts"))
    sys.path.insert(0, scripts_dir)
    try:
        yield importlib.import_module("build_bathing_water_store")
    finally:
        sys.path.remove(scripts_dir)
        sys.modules.pop("build_bathing_water_store", None)


def test_the_dry_run_names_files_only(script, tmp_path: Path, capsys):
    assert script.main(["--dry-run"]) == 0
    output = capsys.readouterr().out
    assert "eea_t_bathing-water-status_p_1990-2025_v01_r00.zip (MISSING)" in output and "bathing_water_2025.sqlite (new)" in output
    assert str(tmp_path) not in output


def test_a_missing_archive_is_exit_code_2_and_relative_paths_are_refused(script, tmp_path: Path, capsys):
    assert script.main(["--archive", str(tmp_path / "absent.zip")]) == 2
    assert "archive is missing" in capsys.readouterr().err
    with pytest.raises(RuntimeError, match="absolute"):
        script.main(["--archive", "relative.zip", "--dry-run"])


def test_a_full_run_builds_a_store_the_reader_accepts(script, tmp_path: Path, monkeypatch, capsys):
    archive = make_archive(tmp_path / "archive.zip")
    target = tmp_path / "out" / "store.sqlite"
    assert script.main(["--archive", str(archive), "--output", str(target)]) == 0
    output = capsys.readouterr().out
    assert "store size" in output and "bathing_waters: 8" in output and "9 - Surprise" in output
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(target))
    from oah.bathing import store

    assert store.store_status().ready


def test_the_store_path_defaults_to_the_data_directory_and_can_be_overridden(tmp_path: Path, monkeypatch):
    from oah.paths import bathing_water_archive_path, bathing_water_store_path, bathing_water_work_dir

    data = tmp_path / "data-root"
    monkeypatch.setenv("OAH_DATA_DIR", str(data))
    assert bathing_water_store_path() == data / "bathing_water" / "bathing_water_2025.sqlite"
    assert bathing_water_archive_path() == data / "data" / "bathing_water" / "2025" / "eea_t_bathing-water-status_p_1990-2025_v01_r00.zip"
    assert bathing_water_work_dir() == data / "bathing_water" / "work"
    chosen = tmp_path / "elsewhere" / "b.sqlite"
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(chosen))
    assert bathing_water_store_path() == chosen
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", "relative/b.sqlite")
    with pytest.raises(RuntimeError, match="absolute"):
        bathing_water_store_path()
