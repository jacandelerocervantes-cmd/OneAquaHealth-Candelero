"""The samples store build: value kinds, filters, resume, atomic and deterministic writes, provenance, the command line.

All data is SYNTHETIC and the service is a scripted fake (``samples_fixtures``); no network, no real EEA data.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from samples_fixtures import FakeDiscodata, build_fixture_store, dataset, make_client, raw_row, transient

from oah.bathing_samples import build as build_module
from oah.bathing_samples.build import (
    ExtractionError,
    IncompleteExtraction,
    Tallies,
    build_store,
    classify_value,
    load_resume,
    normalise_row,
)
from oah.bathing_samples.client import DiscodataClient, DiscodataError

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_a: Any, **_k: Any):
        raise AssertionError("a test must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)


def _provenance(path: Path) -> dict[str, str]:
    with sqlite3.connect(path) as connection:
        return dict(connection.execute("SELECT key, value FROM provenance"))


def _table(path: Path, sql: str) -> list[tuple[Any, ...]]:
    with sqlite3.connect(path) as connection:
        return connection.execute(sql).fetchall()


# --- the kind of a value ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "status", "expected"),
    [
        (60, None, (60, None, "Q")),
        (60.0, None, (60, None, "Q")),
        (1, "limitOfDetectionValue", (1, "limitOfDetectionValue", "D")),
        (900, "confirmedValue", (900, "confirmedValue", "C")),
        (0, "missingValue", (0, "missingValue", "M")),
        (None, "missingValue", (None, "missingValue", "M")),
        (None, None, (None, None, "M")),
        (12, "somethingNew", (12, "somethingNew", "U")),
        (-3, None, (None, None, "I")),
        (2.5, None, (None, None, "I")),
        ("17", None, (None, None, "I")),
        (True, None, (None, None, "I")),
        (float("nan"), None, (None, None, "I")),
        (None, "limitOfDetectionValue", (None, "limitOfDetectionValue", "I")),
        (None, "confirmedValue", (None, "confirmedValue", "I")),
        (5, "  limitOfDetectionValue  ", (5, "limitOfDetectionValue", "D")),
        (5, "", (5, None, "Q")),
    ],
)
def test_every_value_gets_a_kind_and_a_flagged_one_never_becomes_a_plain_number(value, status, expected):
    assert classify_value(value, status, Counter(), "ec") == expected


def test_only_status_free_and_confirmed_values_are_concentrations():
    from oah.bathing_samples.constants import KIND_NAMES, QUANTIFIED_KINDS

    assert set(QUANTIFIED_KINDS) == {"Q", "C"}
    assert KIND_NAMES["D"] == "detection-limit" and KIND_NAMES["M"] == "missing" and KIND_NAMES["U"] == "unknown-status"


def test_oddities_are_counted():
    counters: Counter[str] = Counter()
    classify_value(None, None, counters, "ec")
    classify_value(0, None, counters, "ie")
    classify_value(5, "missingValue", counters, "ie")
    assert counters == {"ec_value_null_without_status": 1, "ie_zero_without_status": 1, "ie_missing_with_nonzero_value": 1}


# --- rows ---------------------------------------------------------------------------------------------------------------


def test_a_row_is_normalised_and_the_country_follows_the_prefix_with_el_stored_as_gr():
    tallies = Tallies.new()
    greek = normalise_row(raw_row(1, "elsyn001", "2023-06-05", (20, None), (10, None), obs=" A "), "EL", tallies)
    italian = normalise_row(raw_row(2, "ITSYN001", "2020-06-10T00:00:00", (3, None), (4, None), remarks=1), "IT", tallies)
    assert greek is not None and greek.country == "GR" and greek.bw_id == "elsyn001" and greek.obs_status == "A"
    assert italian is not None and italian.country == "IT" and italian.sample_date == "2020-06-10" and italian.has_remarks == 1
    assert tallies.counters["rows_kept"] == 2 and tallies.seasons == {"GR": Counter({2023: 1}), "IT": Counter({2020: 1})}


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"UID": None}, "dropped_bad_uid"),
        ({"UID": True}, "dropped_bad_uid"),
        ({"UID": -4}, "dropped_bad_uid"),
        ({"bathingWaterIdentifier": None}, "dropped_no_identifier"),
        ({"bathingWaterIdentifier": "   "}, "dropped_no_identifier"),
        ({"bathingWaterIdentifier": "DE0001"}, "dropped_wrong_country_prefix"),
        ({"sampleDate": None}, "dropped_bad_date"),
        ({"sampleDate": "2020-02-30"}, "dropped_bad_date"),
        ({"sampleDate": "yesterday"}, "dropped_bad_date"),
        ({"season": None}, "dropped_bad_season"),
        ({"season": 1500}, "dropped_bad_season"),
        ({"season": "2020"}, "dropped_bad_season"),
    ],
)
def test_a_row_that_cannot_be_trusted_is_dropped_and_counted(changes, reason):
    tallies = Tallies.new()
    assert normalise_row({**raw_row(1, "ITSYN001", "2020-06-10", (1, None), (1, None)), **changes}, "IT", tallies) is None
    assert tallies.counters[reason] == 1 and tallies.counters["rows_kept"] == 0


def test_the_remarks_text_is_never_stored_only_whether_one_exists():
    row = {**raw_row(1, "ITSYN001", "2020-06-10", (1, None), (1, None)), "remarks": "free text with <br> markup"}
    sample = normalise_row(row, "IT", Tallies.new())
    assert sample is not None and "remarks" not in sample.__dataclass_fields__


# --- the whole build ------------------------------------------------------------------------------------------------------


def test_the_build_keeps_every_row_with_its_kind_and_reports_the_counts(tmp_path: Path):
    store = build_fixture_store(tmp_path)
    total = len(dataset())
    assert total == 33  # 6 Greek rows and 27 Italian rows, counted by hand in samples_fixtures.dataset
    info = _provenance(store)
    assert json.loads(info["rows_by_prefix_extracted"]) == {"EL": 6, "IT": 27, "NO": 0}
    assert json.loads(info["rows_by_prefix_service_count"]) == json.loads(info["rows_by_prefix_extracted"])
    assert json.loads(info["rows_kept_by_country"]) == {"GR": 6, "IT": 27}  # Norway has no row and no key
    by_season = json.loads(info["rows_by_country_season"])
    assert by_season["GR"] == {"2023": 6} and by_season["IT"] == {"2020": 15, "2021": 1, "2022": 11}
    kinds = json.loads(info["kind_counts"])
    assert kinds["escherichia_coli"] == {"Q": 28, "C": 1, "D": 2, "M": 1, "I": 1}
    assert kinds["intestinal_enterococci"] == {"Q": 29, "D": 1, "M": 2, "U": 1}
    statuses = json.loads(info["status_counts"])
    assert statuses["escherichia_coli"] == {"(none)": 29, "confirmedValue": 1, "limitOfDetectionValue": 2, "missingValue": 1}
    assert statuses["intestinal_enterococci"] == {"(none)": 30, "limitOfDetectionValue": 1, "missingValue": 1, "weirdStatus": 1}
    assert json.loads(info["sample_status_counts"]) == {"(none)": 30, "confirmationSample": 1, "missingSample": 1, "preSeasonSample": 1}
    assert json.loads(info["observation_status_counts"]) == {"A": total}
    counters = json.loads(info["row_counts"])
    assert counters["rows_scanned"] == counters["rows_kept"] == total and counters["rows_with_remarks"] == 1
    assert counters["duplicate_uid"] == 0 and counters["ie_value_null_without_status"] == 1
    assert json.loads(info["table_sizes"])["samples"] == total


def test_the_placeholder_zero_of_a_missing_value_is_stored_but_is_not_a_concentration(tmp_path: Path):
    store = build_fixture_store(tmp_path)
    row = _table(store, "SELECT ec_value, ec_status, ec_kind, ie_value, ie_kind, sample_status FROM samples WHERE bw_id = 'ITSYN001' AND sample_date = '2022-08-20'")
    assert row == [(0, "missingValue", "M", 0, "M", "missingSample")]
    flagged = _table(store, "SELECT ec_value, ec_kind FROM samples WHERE bw_id = 'ITSYN001' AND sample_date = '2022-08-10'")
    assert flagged == [(1, "D")]
    assert _table(store, "SELECT COUNT(*) FROM samples WHERE ec_kind IN ('Q','C') AND ec_value = 0") == [(0,)]


def test_the_stored_countries_are_gr_and_it_and_norway_is_absent(tmp_path: Path):
    store = build_fixture_store(tmp_path)
    assert _table(store, "SELECT country, bathing_waters, n_samples FROM country_summary ORDER BY country") == [("GR", 2, 6), ("IT", 4, len(dataset()) - 6)]
    assert _table(store, "SELECT COUNT(*) FROM samples WHERE country NOT IN ('GR', 'IT')") == [(0,)]
    assert _table(store, "SELECT country FROM sites WHERE bw_id = 'ELSYN001'") == [("GR",)]  # written EL, stored GR
    assert json.loads(_provenance(store)["rows_by_prefix_extracted"])["NO"] == 0


def test_the_provenance_documents_the_source_the_queries_and_the_licence(tmp_path: Path):
    info = _provenance(build_fixture_store(tmp_path))
    assert info["schema_version"] == "2" and info["complete"] == "true" and info["build_date_utc"] == "2026-10-03T00:00:00Z"
    assert info["endpoint"] == "https://discodata.eea.europa.eu/sql"
    assert info["table"] == "[WISE_BWD].[latest].[timeseries_MonitoringResult]"
    assert info["licence"].startswith("EEA CC BY 4.0") and "CC BY 4.0" in info["attribution"]
    assert info["unit"] == "cfu/100ml" and "table metadata" in info["unit_statement"]
    queries = json.loads(info["query_texts"])
    assert set(queries) == {"EL", "IT", "NO"} and all("ORDER BY UID" in text and "OFFSET" not in text.upper() for text in queries.values())
    assert "no threshold" in info["content"] and info["latest_view_proxy_observed"].endswith("[timeseries_MonitoringResult]")
    stats = json.loads(info["fetch_stats"])
    assert stats["requests"] == 14 and stats["retries"] == 0 and stats["max_rows_in_a_reply"] == 5 and stats["short_pages_before_end"] == 0
    assert json.loads(info["fetch_stats"])["pages_per_prefix"] == {"EL": 2, "IT": 6, "NO": 0}
    assert json.loads(info["sample_date_range_by_country"]) == {"GR": ["2023-05-05", "2023-08-05"], "IT": ["2020-05-10", "2022-08-25"]}


def test_the_build_is_deterministic_and_the_write_is_atomic(tmp_path: Path):
    first = build_fixture_store(tmp_path, name="one.sqlite")
    second = build_fixture_store(tmp_path, name="two.sqlite", page_size=3)  # another page size gives the same tables
    for table in ("samples", "sites", "country_summary"):
        assert _table(first, f"SELECT * FROM {table}") == _table(second, f"SELECT * FROM {table}")
    assert not list(tmp_path.glob("*.tmp"))


def test_a_failed_build_leaves_the_previous_store_untouched(tmp_path: Path, monkeypatch):
    store = build_fixture_store(tmp_path)
    before = store.read_bytes()

    def explode(*_a: Any, **_k: Any):
        raise RuntimeError("disk full")

    monkeypatch.setattr(build_module, "write_store", explode)
    with pytest.raises(RuntimeError):
        build_fixture_store(tmp_path)
    assert store.read_bytes() == before and not list(tmp_path.glob("*.tmp"))


def test_the_work_files_are_removed_after_a_good_build_and_kept_on_request(tmp_path: Path):
    build_fixture_store(tmp_path, name="a.sqlite")
    assert list((tmp_path / "a.sqlite.work").glob("*.json")) == [] and not (tmp_path / "a.sqlite.work" / "raw.sqlite").exists()
    build_fixture_store(tmp_path, name="b.sqlite", keep_work=True)
    assert (tmp_path / "b.sqlite.work" / "IT-00001.json").is_file() and (tmp_path / "b.sqlite.work" / "NO-complete.json").is_file()


# --- failures and resume --------------------------------------------------------------------------------------------------


def test_a_count_mismatch_stops_the_build_and_writes_nothing(tmp_path: Path):
    service = FakeDiscodata(dataset())
    service.counts_override["IT"] = 999_999
    target = tmp_path / "s.sqlite"
    with pytest.raises(ExtractionError, match="differ from the service's own count"):
        build_store(make_client(service), target, tmp_path / "work", page_size=5)
    assert not target.exists()
    assert (tmp_path / "work" / "IT-00001.json").is_file()  # kept for a clean attempt


def test_max_pages_gives_an_incomplete_build_that_resumes_from_the_saved_pages(tmp_path: Path):
    target, work = tmp_path / "s.sqlite", tmp_path / "work"
    service = FakeDiscodata(dataset())
    with pytest.raises(IncompleteExtraction):
        build_store(make_client(service), target, work, page_size=5, max_pages=1)
    assert not target.exists()
    assert load_resume(work, "IT").pages == 1 and load_resume(work, "IT").complete is False
    resumed = FakeDiscodata(dataset())
    build_store(make_client(resumed), target, work, page_size=5)
    assert target.is_file() and _table(target, "SELECT COUNT(*) FROM samples") == [(len(dataset()),)]
    first_page_queries = [q for q in resumed.queries if "UID > 0 " in q and "'IT%'" in q]
    assert first_page_queries == []  # the saved first page was not downloaded again


def test_an_interrupted_download_resumes_after_a_service_failure(tmp_path: Path):
    target, work = tmp_path / "s.sqlite", tmp_path / "work"
    failing = FakeDiscodata(dataset(), script=[None, DiscodataError("the service refused the query")])
    with pytest.raises(DiscodataError):
        build_store(make_client(failing), target, work, page_size=5)
    assert load_resume(work, "EL").pages == 1 and not target.exists()  # the first Greek page was saved before the failure
    build_store(make_client(FakeDiscodata(dataset())), target, work, page_size=5)
    assert _table(target, "SELECT COUNT(*) FROM samples") == [(len(dataset()),)]


def test_a_transient_failure_during_the_build_is_retried_inside_the_build(tmp_path: Path):
    service = FakeDiscodata(dataset(), script=[transient(), transient()])
    sleeps: list[float] = []
    build_store(make_client(service, sleeps), tmp_path / "s.sqlite", tmp_path / "work", page_size=5)
    stats = json.loads(_provenance(tmp_path / "s.sqlite")["fetch_stats"])
    assert stats["retries"] == 2 and sleeps == [2.0, 4.0]


def test_a_damaged_or_foreign_page_file_is_discarded_with_the_later_ones(tmp_path: Path):
    work = tmp_path / "work"
    build_store(make_client(FakeDiscodata(dataset())), tmp_path / "a.sqlite", work, page_size=5, keep_work=True)
    pages = sorted(work.glob("IT-0*.json"))
    assert len(pages) >= 3
    pages[1].write_text("{not json", encoding="utf-8")
    state = load_resume(work, "IT")
    assert state.pages == 1 and state.complete is False and not pages[1].exists() and not pages[2].exists()
    assert not (work / "IT-complete.json").exists()
    # a page made with other query texts is not trusted either
    other = json.loads(pages[0].read_text(encoding="utf-8"))
    other["template_sha256"] = "0" * 64
    pages[0].write_text(json.dumps(other), encoding="utf-8")
    assert load_resume(work, "IT").pages == 0


def test_a_page_out_of_sequence_or_with_a_wrong_last_uid_is_not_trusted(tmp_path: Path):
    work = tmp_path / "work"
    build_store(make_client(FakeDiscodata(dataset())), tmp_path / "a.sqlite", work, page_size=5, keep_work=True)
    first = work / "IT-00001.json"
    data = json.loads(first.read_text(encoding="utf-8"))
    data["last_uid"] += 1
    first.write_text(json.dumps(data), encoding="utf-8")
    assert load_resume(work, "IT").pages == 0
    (work / "NO-complete.json").write_text(json.dumps({"format": 1, "template_sha256": "x", "last_uid": 0, "rows": 0}), encoding="utf-8")
    assert load_resume(work, "NO").complete is False and not (work / "NO-complete.json").exists()


def test_restart_deletes_the_saved_pages(tmp_path: Path):
    work = tmp_path / "work"
    build_store(make_client(FakeDiscodata(dataset())), tmp_path / "a.sqlite", work, page_size=5, keep_work=True)
    service = FakeDiscodata(dataset())
    build_store(make_client(service), tmp_path / "b.sqlite", work, page_size=5, restart=True)
    assert any("UID > 0 " in q and "'IT%'" in q for q in service.queries)  # downloaded again from the start


def test_an_empty_extraction_writes_no_store(tmp_path: Path):
    with pytest.raises(ExtractionError, match="no row survived"):
        build_store(make_client(FakeDiscodata([])), tmp_path / "s.sqlite", tmp_path / "work", page_size=5)
    assert not (tmp_path / "s.sqlite").exists() and not (tmp_path / "work" / "raw.sqlite").exists()


def test_rows_that_fail_the_checks_are_dropped_and_counted_in_the_store(tmp_path: Path):
    rows = [
        raw_row(1, "ITSYN001", "2020-06-10", (5, None), (6, None)),
        {**raw_row(2, "ITSYN001", "2020-06-11", (5, None), (6, None)), "sampleDate": "not-a-date"},
        {**raw_row(3, "ITSYN001", "2020-06-12", (5, None), (6, None)), "season": 3000},
    ]
    store = build_fixture_store(tmp_path, rows=rows)
    counters = json.loads(_provenance(store)["row_counts"])
    assert counters["rows_scanned"] == 3 and counters["rows_kept"] == 1 and counters["dropped_bad_date"] == 1 and counters["dropped_bad_season"] == 1
    assert _table(store, "SELECT COUNT(*) FROM samples") == [(1,)]


def test_the_page_size_is_validated(tmp_path: Path):
    with pytest.raises(ValueError):
        build_store(make_client(FakeDiscodata([])), tmp_path / "s.sqlite", tmp_path / "work", page_size=0)


# --- the command line -------------------------------------------------------------------------------------------------------


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_bathing_samples_store", SCRIPT_DIR / "build_bathing_samples_store.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["build_bathing_samples_store"] = module
    spec.loader.exec_module(module)
    return module


def test_the_dry_run_prints_the_plan_and_makes_no_request(tmp_path: Path, monkeypatch, capsys):
    script = _load_script()

    def forbidden(*_a: Any, **_k: Any):
        raise AssertionError("a dry run must not build a client")

    monkeypatch.setattr(script, "DiscodataClient", forbidden)
    assert script.main(["--dry-run", "--output", str(tmp_path / "s.sqlite"), "--work-dir", str(tmp_path / "work")]) == 0
    out = capsys.readouterr().out
    assert "discodata.eea.europa.eu" in out and "UID > <last UID> ORDER BY UID" in out and "OFFSET" not in out.upper()
    assert "EL -> GR" in out and "NO -> NO" in out


def test_the_command_line_builds_and_reports(tmp_path: Path, monkeypatch, capsys):
    script = _load_script()
    service = FakeDiscodata(dataset())
    monkeypatch.setattr(script, "DiscodataClient", lambda **_k: make_client(service))
    code = script.main(["--output", str(tmp_path / "s.sqlite"), "--work-dir", str(tmp_path / "work"), "--page-size", "7", "--min-interval", "0.25"])
    out = capsys.readouterr().out
    assert code == 0 and (tmp_path / "s.sqlite").is_file()
    assert "rows_kept_by_country" in out and "kind_counts" in out and "status_counts" in out and "seasons GR" in out


def test_the_command_line_exit_codes_for_an_incomplete_and_a_failed_extraction(tmp_path: Path, monkeypatch, capsys):
    script = _load_script()
    monkeypatch.setattr(script, "DiscodataClient", lambda **_k: make_client(FakeDiscodata(dataset())))
    assert script.main(["--output", str(tmp_path / "s.sqlite"), "--work-dir", str(tmp_path / "w1"), "--page-size", "5", "--max-pages", "1"]) == 3
    assert "incomplete" in capsys.readouterr().err
    broken = FakeDiscodata(dataset())
    broken.counts_override["IT"] = 1
    monkeypatch.setattr(script, "DiscodataClient", lambda **_k: make_client(broken))
    assert script.main(["--output", str(tmp_path / "t.sqlite"), "--work-dir", str(tmp_path / "w2"), "--page-size", "5"]) == 2
    assert "extraction error" in capsys.readouterr().err


@pytest.mark.parametrize(
    "arguments",
    [["--page-size", "0"], ["--page-size", "50001"], ["--max-pages", "0"], ["--min-interval", "0.1"], ["--output", "relative/path.sqlite"]],
)
def test_the_command_line_refuses_unsafe_options(tmp_path: Path, arguments: list[str]):
    script = _load_script()
    with pytest.raises((SystemExit, RuntimeError)):
        script.main(["--dry-run", *arguments])


def test_the_default_client_is_polite():
    client = DiscodataClient()
    assert client.min_interval >= 0.5 and client.max_attempts == 5
