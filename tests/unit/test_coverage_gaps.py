"""Targeted tests for behaviour that had no coverage: the TTL cache, regime experiments and input validation."""
import pytest

from oah.api.cache import TTLCache
from oah.indices import biotic, diversity
from oah.reliability.eval import _scalar, run_regime_experiment


# --- TTLCache -----------------------------------------------------------------------------------


def test_cache_rejects_a_non_positive_ttl():
    for ttl in (0.0, -1.0):
        with pytest.raises(ValueError, match="ttl_seconds"):
            TTLCache(lambda: [], ttl)


def test_cache_fetches_once_within_the_ttl_and_again_after_it(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr("oah.api.cache.time.monotonic", lambda: now[0])
    calls = []

    def fetch():
        calls.append(now[0])
        return [{"call": len(calls)}]

    cache = TTLCache(fetch, ttl_seconds=10.0)
    assert cache.get() == [{"call": 1}] and cache.get() == [{"call": 1}]
    now[0] += 9.9
    assert cache.get() == [{"call": 1}] and len(calls) == 1
    now[0] += 0.1  # the TTL boundary is inclusive: an entry that is exactly ttl old is expired
    assert cache.get() == [{"call": 2}] and len(calls) == 2


def test_cache_clear_forces_a_refetch(monkeypatch):
    monkeypatch.setattr("oah.api.cache.time.monotonic", lambda: 5.0)
    calls = []
    cache = TTLCache(lambda: calls.append(1) or [{"n": len(calls)}], ttl_seconds=60.0)
    cache.get()
    cache.clear()
    assert cache.get() == [{"n": 2}]


def test_a_failed_fetch_is_not_cached(monkeypatch):
    monkeypatch.setattr("oah.api.cache.time.monotonic", lambda: 5.0)
    state = {"fail": True}

    def fetch():
        if state["fail"]:
            raise RuntimeError("down")
        return [{"ok": True}]

    cache = TTLCache(fetch, ttl_seconds=60.0)
    with pytest.raises(RuntimeError):
        cache.get()
    state["fail"] = False
    assert cache.get() == [{"ok": True}]


# --- reliability evaluation -----------------------------------------------------------------------


def test_regime_experiment_summarises_every_metric_over_seeds():
    summary = run_regime_experiment(
        seeds=[1, 2, 3], site_ids=("Loc-A", "Loc-B"), observer_count=4, specimens_per_site=6, annotators_per_specimen=3
    )
    for key in ("mv_accuracy", "ds_accuracy", "mv_macro_f1", "ds_macro_f1", "log_loss"):
        assert 0.0 <= summary[key]["mean"] and summary[key]["std"] >= 0.0
    assert 0.0 <= summary["ds_win_fraction"] <= 1.0


def test_regime_experiment_rejects_an_empty_seed_list_instead_of_returning_nan():
    with pytest.raises(ValueError, match="seeds must not be empty"):
        run_regime_experiment([], ("Loc-A",), 4, 5, 3)


def test_scalar_rejects_nested_metrics():
    assert _scalar({"a": 0.5}, "a") == 0.5
    with pytest.raises(TypeError, match="not a scalar"):
        _scalar({"a": {"x": 1.0}}, "a")


# --- biotic and diversity input validation ----------------------------------------------------------


def test_bmwp_validates_scores():
    assert biotic.bmwp({}) == 0
    assert biotic.bmwp({"A": 3, "B": 10}) == 13
    with pytest.raises(TypeError):
        biotic.bmwp({"A": 3.5})
    with pytest.raises(TypeError):
        biotic.bmwp({"A": True})
    for bad in (0, 11):
        with pytest.raises(ValueError, match="between 1 and 10"):
            biotic.bmwp({"A": bad})


def test_aspt_and_ept_ratio_validate_inputs():
    assert biotic.aspt(30, 6) == 5.0
    with pytest.raises(ValueError):
        biotic.aspt(30, 0)
    with pytest.raises(ValueError):
        biotic.ept_ratio({})
    with pytest.raises(ValueError, match="negative"):
        biotic.ept_ratio({"Ephemeroptera": -1, "Diptera": 4})
    assert biotic.ept_ratio({"Ephemeroptera": 2, "Plecoptera": 1, "Trichoptera": 1, "Diptera": 4}) == 0.5


def test_diversity_indices_reject_negative_counts_and_handle_empty_samples():
    for function in (diversity.shannon, diversity.simpson):
        assert function({}) == 0.0
        with pytest.raises(ValueError, match="negative"):
            function({"a": 3, "b": -1})
    for arguments in ((-1, 1, 1), (5, -1, 1), (5, 1, -1)):
        with pytest.raises(ValueError, match="negative"):
            diversity.chao1(*arguments)
