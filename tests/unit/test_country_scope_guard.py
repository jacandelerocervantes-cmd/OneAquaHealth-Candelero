"""Bounds of the country-scope comparisons: the concurrency guard and result cache, the hard row and time caps, the 503 and 422
answers, the SQL plan, and parity of the bathing-samples SQL path. SYNTHETIC stores only; no network.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from period_fixtures import LOCATIONS, OBSERVATIONS, PERIODS, rows
from samples_fixtures import build_fixture_store as build_samples_store
from waterbase_fixtures import NITRATE, build_fixture_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.bathing_samples import change as samples_change
from oah.bathing_samples import country_scan
from oah.bathing_samples import store as samples_store
from oah.bathing_samples.storage import DDL as SAMPLES_DDL
from oah.bathing_samples.storage import INDEXES as SAMPLES_INDEXES
from oah.chat.tools import ALL_TOOLS, run_tool
from oah.indices import scope_guard, sqlite_aggregates
from oah.indices.period_change import Period
from oah.indices.scope_guard import ScopeBusy, ScopeGuard, file_signature
from oah.waterbase import change, scope_read, store

COUNTRY_QUERY = f"parameter=Nitrate&{PERIODS}"


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path, rows=rows())
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    return path


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


# --- the guard: cache ----------------------------------------------------------------------------------------------------------


def test_an_identical_question_is_answered_from_the_cache_and_a_copy_is_returned():
    guard, calls = ScopeGuard(), []

    def compute() -> dict[str, Any]:
        calls.append(1)
        return {"mean": 1.5, "nested": {"flags": ["a"]}}

    first = guard.run(("k",), compute)
    first["nested"]["flags"].append("tampered")  # a caller can never alter what is cached
    second = guard.run(("k",), compute)
    assert second == {"mean": 1.5, "nested": {"flags": ["a"]}} and len(calls) == 1
    guard.run(("other",), compute)
    assert len(calls) == 2 and len(guard) == 2
    guard.clear()
    guard.run(("k",), compute)
    assert len(calls) == 3


def test_a_cached_result_expires_after_the_ttl_and_the_least_recently_used_entry_is_evicted():
    clock = Clock()
    guard = ScopeGuard(cache_entries=2, ttl_seconds=10.0, clock=clock)
    calls: list[str] = []

    def producer(name: str):
        def produce() -> str:
            calls.append(name)
            return name

        return produce

    guard.run("a", producer("a"))
    guard.run("b", producer("b"))
    guard.run("a", producer("a"))  # a is now the most recent
    guard.run("c", producer("c"))  # evicts b, not a
    assert calls == ["a", "b", "c"]
    guard.run("a", producer("a"))
    assert calls == ["a", "b", "c"]
    guard.run("b", producer("b"))
    assert calls[-1] == "b"
    clock.now += 11.0  # past the TTL
    guard.run("a", producer("a"))
    assert calls[-1] == "a"


def test_a_failure_is_never_cached():
    guard, attempts = ScopeGuard(), []

    def flaky() -> int:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("first attempt fails")
        return 7

    with pytest.raises(RuntimeError):
        guard.run("k", flaky)
    assert guard.run("k", flaky) == 7 and len(attempts) == 2


# --- the guard: concurrency ----------------------------------------------------------------------------------------------------


def test_a_second_comparison_waits_a_bounded_time_and_is_then_refused_as_busy():
    guard = ScopeGuard(max_concurrent=1, wait_seconds=0.05)
    entered, release = threading.Event(), threading.Event()
    holder = threading.Thread(target=lambda: guard.run("slow", lambda: (entered.set(), release.wait(5))))
    holder.start()
    assert entered.wait(5)
    with pytest.raises(ScopeBusy) as caught:
        guard.run("other", lambda: 1)
    assert caught.value.retry_after == scope_guard.RETRY_AFTER_SECONDS and "busy" in str(caught.value)
    release.set()
    holder.join(5)
    assert guard.run("other", lambda: 1) == 1  # the slot is free again, nothing is stuck


def test_an_identical_question_that_waited_is_answered_from_the_cache_without_a_second_computation():
    guard = ScopeGuard(max_concurrent=1, wait_seconds=5.0)
    entered, release, calls = threading.Event(), threading.Event(), []

    def slow() -> str:
        calls.append(1)
        entered.set()
        release.wait(5)
        return "done"

    results: list[str] = []
    first = threading.Thread(target=lambda: results.append(guard.run("same", slow)))
    first.start()
    assert entered.wait(5)
    second = threading.Thread(target=lambda: results.append(guard.run("same", slow)))
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert results == ["done", "done"] and len(calls) == 1


def test_the_default_limits_are_one_or_two_slots_and_a_short_wait():
    assert 1 <= scope_guard.MAX_CONCURRENT <= 2 and 0 < scope_guard.WAIT_SECONDS <= 10 and scope_guard.CACHE_ENTRIES >= 1


def test_the_file_signature_changes_when_the_store_is_rebuilt(tmp_path: Path):
    path = tmp_path / "store.sqlite"
    assert file_signature(path) == ("", 0, 0)
    path.write_bytes(b"one")
    first = file_signature(path)
    path.write_bytes(b"three")
    assert file_signature(path) != first


# --- the Waterbase country path ----------------------------------------------------------------------------------------------


def _series() -> change.Series:
    series = change.resolve_series("Nitrate")
    assert series is not None
    return series


def test_the_country_comparison_is_cached_and_a_rebuilt_store_is_not_answered_from_the_old_result(built, tmp_path, monkeypatch):
    periods = (Period(2021 * 12, 2021 * 12 + 11), Period(2023 * 12, 2023 * 12 + 11))
    calls: list[int] = []
    real = scope_read.scope_country_aggregates

    def counting(*args: Any, **kwargs: Any):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(scope_read, "scope_country_aggregates", counting)
    first = change.country_change("IT", _series(), *periods)
    again = change.country_change("IT", _series(), *periods)
    assert first == again and len(calls) == 1  # the repeated question did not touch the store
    (tmp_path / "second").mkdir()
    rebuilt = build_fixture_store(tmp_path / "second", rows=rows()[:-1])
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(rebuilt))
    change.country_change("IT", _series(), *periods)
    assert len(calls) == 2  # another file, another key


def test_a_busy_process_answers_503_with_retry_after_on_the_route_and_a_tool_error_in_the_chat(http, built, monkeypatch):
    busy = ScopeGuard(max_concurrent=1, wait_seconds=0.01)
    monkeypatch.setattr(change, "GUARD", busy)
    assert busy._slots.acquire(timeout=1)  # every slot taken by "another request"
    try:
        response = http.get(f"/countries/IT/change?{COUNTRY_QUERY}")
        assert response.status_code == 503 and response.headers["Retry-After"] == str(scope_guard.RETRY_AFTER_SECONDS)
        assert "busy" in response.json()["detail"]
        context = app_module._chat_tool_context("IT")
        outcome = run_tool(
            context, "compare_periods",
            {"scope": "country", "id_or_country": "IT", "parameter": "Nitrate", "a_from": "2021-01", "a_to": "2021-12",
             "b_from": "2023-01", "b_to": "2023-12"},
            ALL_TOOLS,
        )
        assert not outcome.ok and "busy" in (outcome.error or "")
        assert http.get(f"/sites/IT01-001025/change?{COUNTRY_QUERY}").status_code == 200  # one site is not a country scan
    finally:
        busy._slots.release()
    assert http.get(f"/countries/IT/change?{COUNTRY_QUERY}").status_code == 200


def test_the_row_cap_fails_with_a_clear_422_instead_of_reading_everything(http, built, monkeypatch):
    monkeypatch.setattr(store, "MAX_SCOPE_ROWS", 3)
    response = http.get(f"/countries/IT/change?{COUNTRY_QUERY}")
    assert response.status_code == 422 and "too large" in response.json()["detail"] and "Narrow the periods" in response.json()["detail"]
    monkeypatch.setattr(store, "MAX_SCOPE_ROWS", 2_000_000)
    assert http.get(f"/countries/IT/change?{COUNTRY_QUERY}").status_code == 200  # a failure was not cached


def test_the_time_cap_interrupts_the_read_with_a_clear_422(http, built, monkeypatch):
    monkeypatch.setattr(scope_read, "SCOPE_QUERY_SECONDS", -1.0)
    monkeypatch.setattr(sqlite_aggregates, "PROGRESS_STEPS", 1)
    response = http.get(f"/countries/IT/change?{COUNTRY_QUERY}")
    assert response.status_code == 422 and "too large" in response.json()["detail"] and "allowed time" in response.json()["detail"]


def test_the_aggregated_read_uses_the_primary_key_for_every_statement_and_is_parameterised(built, monkeypatch):
    statements: list[str] = []
    original = store._open

    def traced(path: Path) -> sqlite3.Connection:
        connection = original(path)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_open", traced)
    hostile = "IT'; DROP TABLE measurements; --"
    change.country_change(hostile, _series(), Period(2021 * 12, 2021 * 12 + 11), Period(2023 * 12, 2023 * 12 + 11))
    change.country_change("IT", _series(), Period(2021 * 12, 2021 * 12 + 11), Period(2023 * 12, 2023 * 12 + 11))
    aggregates = [s for s in statements if "oah_fsum" in s and "'IT'" in s]
    assert aggregates, statements
    connection = sqlite3.connect(built)
    sqlite_aggregates.register(connection, sqlite_aggregates.ReadGuard(10**9, 60.0))
    try:
        for statement in aggregates[:1]:
            plan = " ".join(str(row) for row in connection.execute("EXPLAIN QUERY PLAN " + statement))
            assert "SEARCH measurements USING PRIMARY KEY" in plan and "SCAN measurements" not in plan, plan
        assert connection.execute("SELECT COUNT(*) FROM measurements").fetchone()[0] > 0  # nothing was dropped
    finally:
        connection.close()
    assert not any("DROP TABLE" in s and "oah_fsum" in s for s in statements)


def test_the_exact_sum_is_the_correctly_rounded_exact_sum_where_sqlite_sum_is_not():
    values = [0.1] * 10 + [1e16, 1.0, -1e16]
    connection = sqlite3.connect(":memory:")
    sqlite_aggregates.register(connection, sqlite_aggregates.ReadGuard(10**9, 60.0))
    connection.execute("CREATE TABLE v (x REAL)")
    connection.executemany("INSERT INTO v VALUES (?)", [(x,) for x in values])
    import math

    assert connection.execute("SELECT oah_fsum(x) FROM v").fetchone()[0] == math.fsum(values)
    assert connection.execute("SELECT oah_fsum(x) FROM v WHERE x > 5").fetchone()[0] == math.fsum([1e16])
    assert connection.execute("SELECT oah_fsum(x) FROM v WHERE x > 1e30").fetchone()[0] is None
    assert sqlite_aggregates.mask_value(connection.execute("SELECT oah_months(CAST(x AS INTEGER)) FROM v WHERE x = 1.0").fetchone()[0]) == 2
    assert sqlite_aggregates.mask_value(None) == 0
    connection.close()


def test_the_store_that_vanished_gives_the_empty_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(tmp_path / "absent.sqlite"))
    result = change.country_change("IT", _series(), Period(2021 * 12, 2021 * 12 + 11), Period(2023 * 12, 2023 * 12 + 11))
    assert result["n_sites_paired"] == 0 and result["status"] == "insufficient-data" and result["truncated"] is False
    assert scope_read.scope_country_aggregates(NITRATE[0], "W", [], "IT", lambda weights: {}).sites == {}


# --- the bathing-samples country path ----------------------------------------------------------------------------------------


@pytest.fixture()
def samples(tmp_path: Path, monkeypatch) -> Path:
    path = build_samples_store(tmp_path)
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(path))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "none.sqlite"))
    return path


WINDOWS = [
    (Period(2020 * 12 + 4, 2020 * 12 + 7), Period(2022 * 12 + 4, 2022 * 12 + 7)),
    (Period(2020 * 12, 2020 * 12 + 11), Period(2021 * 12, 2022 * 12 + 11)),
    (Period(2022 * 12 + 4, 2022 * 12 + 7), Period(2020 * 12 + 4, 2020 * 12 + 7)),  # swapped
    (Period(2020 * 12 + 4, 2022 * 12 + 7), Period(2022 * 12 + 4, 2022 * 12 + 7)),  # overlapping
    (Period(2026 * 12 + 4, 2026 * 12 + 4), Period(2020 * 12 + 4, 2020 * 12 + 7)),  # beyond the data
]


@pytest.mark.parametrize("country", ["IT", "GR"])
@pytest.mark.parametrize("periods", WINDOWS)
def test_the_samples_sql_path_equals_the_row_path_on_the_synthetic_store(samples, country, periods):
    assert samples_change.country_change(country, *periods) == samples_change.country_change_rows(country, *periods)


def test_the_samples_scan_equals_the_values_read_one_by_one(samples):
    import statistics

    windows = [(2020 * 12, 2022 * 12 + 11), (2022 * 12 + 4, 2022 * 12 + 7)]
    for indicator in ("escherichia_coli", "intestinal_enterococci"):
        found = samples_store.country_window_aggregates("IT", indicator, windows)
        for index, window in enumerate(windows):
            values = samples_store.window_values("country", "IT", indicator, window)
            scanned = {bw: entry[index] for bw, entry in found.items() if entry[index] is not None}
            assert set(scanned) == set(values)
            for bw, entry in scanned.items():
                assert entry.n == len(values[bw]) and entry.total == sum(values[bw])
                assert (entry.low, entry.high) == (min(values[bw]), max(values[bw]))
                assert entry.median == float(statistics.median(values[bw]))
    assert samples_store.country_window_aggregates("IT", "escherichia_coli", [(2000 * 12, 2000 * 12)]) == {}
    assert samples_store.country_window_aggregates("IT", "escherichia_coli", [window], Path("absent.sqlite")) == {}


def test_the_samples_kind_counts_of_a_country_equal_the_per_window_counts(samples):
    windows = [(2020 * 12, 2022 * 12 + 11), (2022 * 12 + 4, 2022 * 12 + 7), (2000 * 12, 2000 * 12)]
    for country in ("IT", "GR"):
        both = samples_store.country_kind_counts(country, windows[:2])
        for indicator in ("escherichia_coli", "intestinal_enterococci"):
            for index, window in enumerate(windows[:2]):
                assert both[indicator][index] == samples_store.kind_counts("country", country, indicator, window)
        assert samples_store.country_kind_counts(country, [windows[2]])["escherichia_coli"] == ({},)
    assert samples_store.country_kind_counts("IT", windows[:2], Path("absent.sqlite")) == {}
    with pytest.raises(ValueError):
        samples_store.country_kind_counts("IT", [])
    with pytest.raises(ValueError):
        samples_store.country_window_aggregates("IT", "escherichia_coli", windows)


def test_the_samples_scan_has_its_row_cap_and_its_clock(samples, monkeypatch):
    window = (2020 * 12, 2022 * 12 + 11)
    assert samples_store.country_window_aggregates("IT", "escherichia_coli", [window])
    monkeypatch.setattr(samples_store, "MAX_COUNTRY_ROWS", 3)
    with pytest.raises(samples_store.RowCapExceeded):
        samples_store.country_window_aggregates("IT", "escherichia_coli", [window])
    monkeypatch.setattr(samples_store, "MAX_COUNTRY_ROWS", 1_500_000)
    monkeypatch.setattr(samples_store, "COUNTRY_READ_SECONDS", -1.0)
    monkeypatch.setattr(samples_store, "PROGRESS_STEPS", 1)
    monkeypatch.setattr(country_scan, "PROGRESS_STEPS", 1)
    with pytest.raises(samples_store.RowCapExceeded):
        samples_store.country_window_aggregates("IT", "escherichia_coli", [window])
    with pytest.raises(samples_store.RowCapExceeded):
        samples_store.country_kind_counts("IT", [window])


def test_the_samples_caps_give_a_422_and_a_busy_process_a_503(http, samples, monkeypatch):
    url = "/bathing-waters/samples/change?country=IT&a_from=2020-05&a_to=2020-08&b_from=2022-05&b_to=2022-08"
    assert http.get(url).status_code == 200
    scope_guard.GUARD.clear()
    monkeypatch.setattr(samples_store, "MAX_COUNTRY_ROWS", 3)
    response = http.get(url)
    assert response.status_code == 422 and "too large" in response.json()["detail"]
    monkeypatch.setattr(samples_store, "MAX_COUNTRY_ROWS", 1_500_000)
    busy = ScopeGuard(max_concurrent=1, wait_seconds=0.01)
    monkeypatch.setattr(samples_change, "GUARD", busy)
    assert busy._slots.acquire(timeout=1)
    try:
        blocked = http.get(url)
        assert blocked.status_code == 503 and "Retry-After" in blocked.headers
        outcome = run_tool(
            app_module._chat_tool_context("IT"), "compare_bathing_concentrations",
            {"scope": "country", "id_or_country": "IT", "a_from": "2020-05", "a_to": "2020-08", "b_from": "2022-05", "b_to": "2022-08"},
            ALL_TOOLS,
        )
        assert not outcome.ok and "busy" in (outcome.error or "")
    finally:
        busy._slots.release()


def _random_samples_store(path: Path, plan: list[tuple[str, str, int, int, str, int, str, int]]) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(SAMPLES_DDL + SAMPLES_INDEXES)
    connection.execute("INSERT INTO provenance VALUES ('schema_version', ?)", [samples_store.SUPPORTED_SCHEMA])
    quantified: dict[str, list[str]] = {"ec": [], "ie": []}
    for uid, (bw, day, season, ec_value, ec_kind, ie_value, ie_kind, _unused) in enumerate(plan):
        connection.execute(
            "INSERT INTO samples VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [bw, day, uid, "IT", season, ec_value, None, ec_kind, ie_value, None, ie_kind, None, "A", 0],
        )
        if ec_kind in ("Q", "C"):
            quantified["ec"].append(day)
        if ie_kind in ("Q", "C"):
            quantified["ie"].append(day)
    bounds = {key: (min(days), max(days)) if days else (None, None) for key, days in quantified.items()}
    connection.execute(
        "INSERT INTO country_summary VALUES ('IT', 1, ?, '2018-01-01', '2020-12-28', 2018, 2020, ?, ?, ?, ?, ?, ?)",
        [len(plan), len(quantified["ec"]), len(quantified["ie"]), *bounds["ec"], *bounds["ie"]],
    )
    connection.commit()
    connection.close()


sample_row = st.tuples(
    st.sampled_from(["B1", "B2", "B3", "B4"]), st.integers(2018, 2020), st.integers(1, 12), st.integers(1, 28),
    st.integers(0, 3000), st.sampled_from("QQQCDMUI"), st.integers(0, 400), st.sampled_from("QQQCDMUI"),
)


@given(st.lists(sample_row, min_size=1, max_size=60), st.integers(0, 35), st.integers(0, 35), st.integers(0, 12), st.integers(0, 12))
@settings(max_examples=120, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_the_samples_sql_path_equals_the_row_path_on_random_stores(monkeypatch, items, first_a, first_b, length_a, length_b):
    plan = [
        (bw, f"{year}-{month:02d}-{day:02d}", year, ec, ec_kind, ie, ie_kind, 0)
        for bw, year, month, day, ec, ec_kind, ie, ie_kind in items
    ]
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "samples.sqlite"
        _random_samples_store(path, plan)
        monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(path))
        period_a = Period(2018 * 12 + first_a, 2018 * 12 + first_a + length_a)
        period_b = Period(2018 * 12 + first_b, 2018 * 12 + first_b + length_b)
        scope_guard.GUARD.clear()
        assert samples_change.country_change_rows("IT", period_a, period_b) == samples_change.country_change("IT", period_a, period_b)
