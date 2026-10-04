"""The stale-while-revalidate cache: fresh hit, stale-and-refresh, single flight, back-off, maximum staleness, warm-up.

A fake clock and a fake thread starter make the state machine deterministic; two tests use real threads for the
single-flight guarantee and every test checks that no refresh or warm-up thread outlives it.
"""
import threading
import time

import pytest

from oah.api.swr_cache import REFRESH_THREAD_NAME, RevalidatingCache

TTL = 100.0
MAX_STALE = 1000.0


class Clock:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class Spawner:
    """Records the background jobs instead of starting threads; ``run_all`` runs them on the calling thread."""

    def __init__(self) -> None:
        self.jobs: list = []

    def __call__(self, job) -> None:
        self.jobs.append(job)

    def run_all(self) -> None:
        jobs, self.jobs = self.jobs, []
        for job in jobs:
            job()


class Source:
    """A fetch function that counts calls, returns numbered copies and can be told to fail."""

    def __init__(self) -> None:
        self.calls = 0
        self.fail = False

    def __call__(self):
        self.calls += 1
        if self.fail:
            raise RuntimeError("sandbox down")
        return [{"copy": self.calls}], f"meta-{self.calls}"


@pytest.fixture(autouse=True)
def _no_leaked_threads():
    yield
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        leaked = [t for t in threading.enumerate() if t.name.startswith("oah-sandbox")]
        if not leaked:
            return
        time.sleep(0.01)
    raise AssertionError(f"leaked threads: {leaked}")


def make(source=None, clock=None, spawner=None, **overrides):
    source = source or Source()
    clock = clock or Clock()
    spawner = spawner if spawner is not None else Spawner()
    stored: list = []
    options = dict(ttl_seconds=TTL, max_stale_seconds=MAX_STALE, on_store=stored.append, clock=clock, start_thread=spawner)
    options.update(overrides)
    cache = RevalidatingCache(source, **options)
    return cache, source, clock, spawner, stored


def test_a_young_copy_is_served_without_another_fetch_or_a_refresh():
    cache, source, clock, spawner, stored = make()
    assert cache.get() == [{"copy": 1}]
    clock.advance(TTL - 0.1)
    assert cache.get() == [{"copy": 1}]
    assert source.calls == 1 and spawner.jobs == [] and stored == ["meta-1"]
    assert not cache.is_past_ttl()


def test_no_copy_at_all_waits_for_the_fetch_and_a_failure_reaches_the_caller():
    cache, source, _clock, spawner, stored = make()
    source.fail = True
    with pytest.raises(RuntimeError, match="down"):
        cache.get()
    assert cache.age_seconds() is None and stored == [] and spawner.jobs == []
    source.fail = False  # a failed fetch is not cached and not backed off: the next caller retries at once
    assert cache.get() == [{"copy": 2}]


def test_an_expired_copy_is_served_at_once_and_triggers_exactly_one_refresh():
    cache, source, clock, spawner, stored = make()
    cache.get()
    clock.advance(TTL)  # the TTL boundary is inclusive
    assert cache.is_past_ttl()
    assert cache.get() == [{"copy": 1}]  # the stale copy, immediately
    assert source.calls == 1 and len(spawner.jobs) == 1 and cache.refresh_running()
    assert cache.get() == [{"copy": 1}] and cache.get() == [{"copy": 1}]  # still one job: single flight
    assert len(spawner.jobs) == 1
    spawner.run_all()
    assert source.calls == 2 and not cache.refresh_running() and stored == ["meta-1", "meta-2"]
    assert cache.get() == [{"copy": 2}] and not cache.is_past_ttl() and spawner.jobs == []


def test_the_refresh_uses_its_own_fetch_when_one_is_given():
    foreground, background = Source(), Source()
    cache, _s, clock, spawner, _stored = make(foreground, refresh_fetch=background)
    cache.get()
    clock.advance(TTL)
    cache.get()
    spawner.run_all()
    assert (foreground.calls, background.calls) == (1, 1)
    assert cache.get() == [{"copy": 1}]  # the copy the background source produced


def test_a_failed_refresh_keeps_serving_the_stale_copy_and_backs_off_exponentially():
    cache, source, clock, spawner, stored = make(backoff_initial_seconds=30.0, backoff_max_seconds=100.0)
    cache.get()
    clock.advance(TTL)
    source.fail = True
    cache.get()
    spawner.run_all()  # failure 1: next attempt allowed 30 s later
    assert cache.get() == [{"copy": 1}] and spawner.jobs == [] and source.calls == 2
    clock.advance(29.9)
    cache.get()
    assert spawner.jobs == []
    clock.advance(0.1)
    cache.get()
    spawner.run_all()  # failure 2: 60 s
    clock.advance(59.9)
    cache.get()
    assert spawner.jobs == []
    clock.advance(0.1)
    cache.get()
    spawner.run_all()  # failure 3: 120 s, capped at 100 s
    clock.advance(99.9)
    cache.get()
    assert spawner.jobs == []
    clock.advance(0.1)
    source.fail = False
    assert cache.get() == [{"copy": 1}]  # still stale while the refresh runs
    spawner.run_all()
    assert cache.get() == [{"copy": 5}] and stored == ["meta-1", "meta-5"]  # success resets the back-off
    clock.advance(TTL)
    cache.get()
    assert len(spawner.jobs) == 1


def test_a_copy_older_than_the_maximum_staleness_is_not_served_the_caller_waits():
    cache, source, clock, spawner, _stored = make()
    cache.get()
    clock.advance(MAX_STALE - 0.1)
    assert cache.get() == [{"copy": 1}] and len(spawner.jobs) == 1  # still within the limit: stale and refreshing
    clock.advance(0.1)
    assert cache.get() == [{"copy": 2}]  # the caller waited for a fresh fetch
    assert source.calls == 2
    spawner.run_all()  # the refresh started earlier was superseded: it still fetches but its result is discarded
    assert source.calls == 3 and cache.get() == [{"copy": 2}]


def test_beyond_the_maximum_staleness_a_failed_fetch_reaches_the_caller_and_the_old_copy_is_not_served():
    cache, source, clock, _spawner, _stored = make()
    cache.get()
    clock.advance(MAX_STALE)
    source.fail = True
    with pytest.raises(RuntimeError):
        cache.get()
    assert cache.is_past_ttl()  # the old copy is still held (age reporting) but never handed out again
    with pytest.raises(RuntimeError):
        cache.get()


def test_a_refresh_that_never_finishes_is_abandoned_after_the_timeout_and_its_late_result_is_discarded():
    cache, source, clock, spawner, stored = make(refresh_timeout_seconds=50.0, backoff_initial_seconds=10.0)
    cache.get()
    clock.advance(TTL)
    cache.get()
    hung = spawner.jobs.pop()
    clock.advance(49.9)
    cache.get()
    assert spawner.jobs == []  # still within its time limit
    clock.advance(0.1)  # timed out: counts as a failure, back-off 10 s
    cache.get()
    assert spawner.jobs == []
    clock.advance(10.0)
    cache.get()
    assert len(spawner.jobs) == 1  # a new refresh may start
    hung()  # the abandoned one finishes late: discarded
    assert source.calls == 2 and stored == ["meta-1"] and cache.refresh_running()
    spawner.run_all()
    assert stored == ["meta-1", "meta-3"]


def test_clear_drops_the_copy_the_back_off_and_a_running_refresh():
    cache, source, clock, spawner, _stored = make()
    cache.get()
    clock.advance(TTL)
    source.fail = True
    cache.get()
    spawner.run_all()
    source.fail = False
    cache.clear()
    assert cache.age_seconds() is None and not cache.refresh_running() and not cache.is_past_ttl()
    assert cache.get() == [{"copy": 3}]
    clock.advance(TTL)
    cache.get()
    pending = spawner.jobs.pop()
    cache.clear()
    pending()
    assert cache.age_seconds() is None


def test_a_refresh_thread_that_cannot_start_counts_as_a_failure():
    def broken(_job):
        raise RuntimeError("can't start new thread")

    cache, source, clock, _spawner, _stored = make(start_thread=broken)
    cache.get()
    clock.advance(TTL)
    assert cache.get() == [{"copy": 1}] and not cache.refresh_running()
    cache.get()  # backing off: no second attempt to start a thread
    assert source.calls == 1


def test_warm_fills_the_cache_in_the_calling_thread_and_never_raises():
    cache, source, clock, _spawner, _stored = make()
    source.fail = True
    assert cache.warm() is False and cache.age_seconds() is None
    source.fail = False
    assert cache.warm() is True and source.calls == 2
    assert cache.warm() is True and source.calls == 2  # a young copy is not fetched again
    clock.advance(TTL)
    assert cache.warm() is True and source.calls == 3


def test_a_failed_warm_up_http_style_error_is_logged_without_leaking_detail_text(caplog):
    class Failure(Exception):
        detail = "Sandbox data is unavailable"

    def fetch():
        raise Failure("https://secret.example/transport text")

    cache = RevalidatingCache(fetch, ttl_seconds=TTL, max_stale_seconds=MAX_STALE)
    with caplog.at_level("WARNING"):
        assert cache.warm() is False
    assert "Sandbox data is unavailable" in caplog.text and "secret.example" not in caplog.text


@pytest.mark.parametrize(
    "options",
    [
        {"ttl_seconds": 0.0, "max_stale_seconds": 10.0},
        {"ttl_seconds": 10.0, "max_stale_seconds": 5.0},
        {"ttl_seconds": 10.0, "max_stale_seconds": 20.0, "refresh_timeout_seconds": 0.0},
        {"ttl_seconds": 10.0, "max_stale_seconds": 20.0, "backoff_initial_seconds": 0.0},
        {"ttl_seconds": 10.0, "max_stale_seconds": 20.0, "backoff_initial_seconds": 5.0, "backoff_max_seconds": 1.0},
    ],
)
def test_invalid_timing_is_rejected(options):
    with pytest.raises(ValueError):
        RevalidatingCache(Source(), **options)


def _wait_for(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def test_concurrent_requests_on_an_expired_copy_start_one_real_refresh_thread_and_none_wait():
    clock = Clock()
    release = threading.Event()
    calls: list[int] = []

    def fetch():
        calls.append(1)
        if len(calls) > 1:
            assert release.wait(5.0)
        return [{"copy": len(calls)}], None

    cache = RevalidatingCache(fetch, ttl_seconds=TTL, max_stale_seconds=MAX_STALE, clock=clock)
    cache.get()
    clock.advance(TTL)
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(cache.get())) for _ in range(30)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)  # all return while the refresh is still blocked: nobody waited for it
    assert len(results) == 30 and all(result == [{"copy": 1}] for result in results)
    _wait_for(lambda: len(calls) == 2)
    assert any(t.name == REFRESH_THREAD_NAME for t in threading.enumerate())
    release.set()
    _wait_for(lambda: not cache.refresh_running())
    assert len(calls) == 2 and cache.get() == [{"copy": 2}]


def test_concurrent_requests_with_no_copy_share_one_fetch():
    started = threading.Event()
    calls: list[int] = []

    def fetch():
        calls.append(1)
        started.set()
        time.sleep(0.1)
        return [{"copy": 1}], None

    cache = RevalidatingCache(fetch, ttl_seconds=TTL, max_stale_seconds=MAX_STALE)
    results: list = []
    threads = [threading.Thread(target=lambda: results.append(cache.get())) for _ in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5.0)
    assert len(calls) == 1 and results == [[{"copy": 1}]] * 20
