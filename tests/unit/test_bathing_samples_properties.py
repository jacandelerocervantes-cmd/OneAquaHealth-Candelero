"""Property tests of the samples store arithmetic over SYNTHETIC generated samples (hypothesis).

For any mix of quantified, confirmed, detection-limit, missing and unrecognised values: the statistics equal the plain Python
statistics of the quantified values alone, a flagged value never changes them, the counts add up, and the period comparison
of one bathing water agrees with a direct computation. No network, no real data.
"""

from __future__ import annotations

import os
import statistics
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from samples_fixtures import build_fixture_store, raw_row

from oah.bathing_samples import change, store
from oah.indices.period_change import Period, month_position

# (value, status) as the service writes it; the generated mix covers every kind
value_status = st.one_of(
    st.tuples(st.integers(min_value=0, max_value=200_000), st.none()),
    st.tuples(st.integers(min_value=1, max_value=200_000), st.just("confirmedValue")),
    st.tuples(st.integers(min_value=0, max_value=50), st.just("limitOfDetectionValue")),
    st.tuples(st.just(0), st.just("missingValue")),
    st.tuples(st.integers(min_value=0, max_value=1000), st.just("newStatus")),
    st.tuples(st.none(), st.none()),
)
samples = st.lists(st.tuples(value_status, value_status, st.integers(min_value=1, max_value=28), st.integers(min_value=5, max_value=9)), min_size=1, max_size=40)


def _expected(pairs: list[tuple[int | None, str | None]]) -> list[int]:
    return [value for value, status in pairs if value is not None and status in (None, "confirmedValue")]


def _store(items: list[tuple[Any, Any, int, int]]) -> tuple[Path, tempfile.TemporaryDirectory[str]]:
    directory = tempfile.TemporaryDirectory()
    rows = [raw_row(index + 1, "ITPROP001", f"2021-{month:02d}-{day:02d}", ec, ie) for index, (ec, ie, day, month) in enumerate(items)]
    return build_fixture_store(Path(directory.name), rows=rows), directory


@given(samples)
@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_statistics_equal_the_plain_statistics_of_the_quantified_values(items):
    path, directory = _store(items)
    try:
        for indicator, position in (("escherichia_coli", 0), ("intestinal_enterococci", 1)):
            stats = store.indicator_stats("ITPROP001", indicator, path=path)
            assert stats is not None
            expected = _expected([(item[position][0], item[position][1]) for item in items])
            assert stats.n_rows == len(items) and stats.n_quantified == len(expected)
            assert stats.n_quantified + stats.n_detection_limit + stats.n_missing + stats.n_unknown_status + stats.n_invalid == stats.n_rows
            if expected:
                assert (stats.low, stats.high, stats.total) == (min(expected), max(expected), sum(expected))
                assert stats.mean == sum(expected) / len(expected) and stats.median == float(statistics.median(expected))
                assert min(expected) <= stats.mean <= max(expected) and stats.low <= stats.median <= stats.high
            else:
                assert stats.mean is None and stats.median is None and stats.low is None
    finally:
        directory.cleanup()


@given(samples, st.integers(min_value=1, max_value=100_000))
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_a_detection_limit_or_missing_value_never_moves_a_statistic(items, extra):
    path_a, directory_a = _store(items)
    flagged = [*items, ((extra, "limitOfDetectionValue"), (0, "missingValue"), 15, 7)]
    path_b, directory_b = _store(flagged)
    try:
        for indicator in ("escherichia_coli", "intestinal_enterococci"):
            before, after = store.indicator_stats("ITPROP001", indicator, path=path_a), store.indicator_stats("ITPROP001", indicator, path=path_b)
            assert before is not None and after is not None
            assert (before.n_quantified, before.low, before.high, before.total, before.median) == (after.n_quantified, after.low, after.high, after.total, after.median)
            assert after.n_rows == before.n_rows + 1
    finally:
        directory_a.cleanup()
        directory_b.cleanup()


@given(samples)
@settings(max_examples=25, deadline=None, suppress_health_check=[HealthCheck.too_slow])
def test_the_period_comparison_agrees_with_a_direct_computation(items):
    path, directory = _store(items)
    try:
        period_a, period_b = Period(month_position(2021, 5), month_position(2021, 7)), Period(month_position(2021, 8), month_position(2021, 9))
        with patch.dict(os.environ, {"OAH_BATHING_SAMPLES_STORE": str(path)}):
            result = change.site_change("ITPROP001", "IT", period_a, period_b)["indicators"]["escherichia_coli"]
        for key, months in (("a", (5, 6, 7)), ("b", (8, 9))):
            values = _expected([(ec[0], ec[1]) for ec, _ie, _day, month in items if month in months])
            view = result["periods"][key]
            assert view["n_samples"] == len(values)
            if values:
                assert view["mean"] == round(sum(values) / len(values), 6) and view["median"] == round(float(statistics.median(values)), 6)
                assert (view["min"], view["max"]) == (float(min(values)), float(max(values)))
            else:
                assert view["mean"] is None and view["median"] is None
        assert "crossed_limit" not in result and result["unit"] == "cfu/100ml"
    finally:
        directory.cleanup()
