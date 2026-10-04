"""TTL+LRU cache, rolling budget and circuit breaker."""
from __future__ import annotations

import pytest

from oah.external.guard import Breaker, RollingBudget, TtlCache
from external_fakes import FakeClock


def test_cache_hit_miss_and_ttl() -> None:
    clock = FakeClock()
    cache = TtlCache(10.0, 5, clock)
    assert cache.get("k") == (False, None)
    cache.put("k", {"v": 1})
    assert cache.get("k") == (True, {"v": 1})
    clock.advance(9.9)
    assert cache.get("k")[0] is True
    clock.advance(0.2)
    assert cache.get("k") == (False, None) and len(cache) == 0  # expired and dropped


def test_cache_per_entry_ttl_and_none_values_are_hits() -> None:
    clock = FakeClock()
    cache = TtlCache(10.0, 5, clock)
    cache.put("short", None, ttl_seconds=1.0)
    cache.put("long", "x", ttl_seconds=100.0)
    assert cache.get("short") == (True, None)
    clock.advance(2.0)
    assert cache.get("short")[0] is False and cache.get("long")[0] is True


def test_cache_is_lru_bounded() -> None:
    cache = TtlCache(100.0, 3, FakeClock())
    for key in ("a", "b", "c"):
        cache.put(key, key)
    cache.get("a")  # a is now the most recently used
    cache.put("d", "d")  # evicts b, the least recently used
    assert [cache.get(k)[0] for k in ("a", "b", "c", "d")] == [True, False, True, True]
    cache.clear()
    assert len(cache) == 0


def test_cache_rejects_non_positive_settings() -> None:
    with pytest.raises(ValueError):
        TtlCache(0.0, 5)
    with pytest.raises(ValueError):
        TtlCache(5.0, 0)


def test_budget_minute_and_day_windows() -> None:
    clock = FakeClock()
    budget = RollingBudget(per_minute=10, per_day=25, clock=clock)
    assert budget.try_reserve(6) and budget.try_reserve(4)
    assert not budget.try_reserve(0.5)  # the minute cap is reached
    assert budget.remaining() == (0.0, 15.0)
    clock.advance(61)
    assert budget.remaining() == (10.0, 15.0)
    assert budget.try_reserve(10)
    clock.advance(61)
    assert budget.try_reserve(5)
    assert not budget.try_reserve(1)  # day cap 25 reached: 10 + 10 + 5
    clock.advance(24 * 3600)
    assert budget.remaining() == (10.0, 25.0)


def test_a_refused_reservation_counts_nothing_and_a_request_above_the_cap_never_passes() -> None:
    budget = RollingBudget(5, 100, FakeClock())
    assert not budget.try_reserve(6)
    assert budget.remaining() == (5.0, 100.0)
    assert budget.try_reserve(2.5) and budget.try_reserve(2.5) and not budget.try_reserve(0.1)


def test_budget_validates_input() -> None:
    with pytest.raises(ValueError):
        RollingBudget(0, 10)
    with pytest.raises(ValueError):
        RollingBudget(10, 0)
    with pytest.raises(ValueError):
        RollingBudget(10, 10).try_reserve(0)


def test_breaker_opens_after_consecutive_failures_and_closes_after_the_cooldown() -> None:
    clock = FakeClock()
    breaker = Breaker(failure_limit=3, cooldown_seconds=30.0, clock=clock)
    assert breaker.allow()
    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()  # resets the run
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.allow()
    breaker.record_failure()
    assert not breaker.allow()
    clock.advance(29)
    assert not breaker.allow()
    clock.advance(2)
    assert breaker.allow()


def test_breaker_open_for_never_shortens_an_open_breaker() -> None:
    clock = FakeClock()
    breaker = Breaker(failure_limit=1, cooldown_seconds=100.0, clock=clock)
    breaker.record_failure()
    breaker.open_for(5)
    clock.advance(50)
    assert not breaker.allow()
    other = Breaker(clock=clock)
    other.open_for(10)
    assert not other.allow()
    clock.advance(11)
    assert other.allow()
    other.open_for(-3)  # a negative duration opens nothing
    assert other.allow()
