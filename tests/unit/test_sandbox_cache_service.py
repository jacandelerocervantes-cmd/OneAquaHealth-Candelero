"""The sandbox caches as the API wires them: freshness labels of stale copies, live-only refresh, warm-up and lifespan."""
import dataclasses
import threading
import time

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
import oah.api.services as services
from oah.api.rate_limit import RateLimiter
from oah.indices.sandbox_loader import SandboxDataUnavailableError
from oah.ingest.freshness import make_freshness, worst_status

TTL = 300.0
MAX_STALE = 6 * 3600.0
DAY = 24 * 3600.0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Jobs:
    def __init__(self) -> None:
        self.pending: list = []

    def __call__(self, job) -> None:
        self.pending.append(job)

    def run(self) -> None:
        pending, self.pending = self.pending, []
        for job in pending:
            job()


class Sandbox:
    """A fake of ``load_sandbox_resources_with_freshness``: live by default, can be down, can answer from a snapshot."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mode = "live"
        self.generation = 0
        self.empty = False  # answer with no resources (the routes then have nothing odd to parse)

    def __call__(self, resource_type, max_age_seconds=0.0):
        self.calls.append(resource_type)
        if self.mode == "down":
            raise SandboxDataUnavailableError("down")
        if self.mode == "snapshot-stale":
            return [{"id": "old", "kind": resource_type}], make_freshness("snapshot-stale", 1_700_000_000.0, 1_700_000_100.0)
        self.generation += 1
        resources = [] if self.empty else [{"id": f"g{self.generation}", "kind": resource_type}]
        return resources, make_freshness("live", time.time())


@pytest.fixture
def wired(monkeypatch):
    """Both caches replaced by ones with a controllable clock and a manual thread starter, and a fake sandbox."""
    clock, jobs, sandbox = Clock(), Jobs(), Sandbox()
    monkeypatch.setattr(services, "load_sandbox_resources_with_freshness", sandbox)
    observations = services._new_cache("Observation", clock=clock, start_thread=jobs, ttl_seconds=TTL, max_stale_seconds=MAX_STALE)
    locations = services._new_cache("Location", clock=clock, start_thread=jobs, ttl_seconds=TTL, max_stale_seconds=MAX_STALE)
    monkeypatch.setattr(services, "_observations_cache", observations)
    monkeypatch.setattr(services, "_locations_cache", locations)
    monkeypatch.setattr(services, "_caches", {"Observation": observations, "Location": locations})
    monkeypatch.setattr(services, "_freshness_by_type", {})
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    yield clock, jobs, sandbox
    deadline = time.monotonic() + 5.0
    while any(t.name.startswith("oah-sandbox") for t in threading.enumerate()) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not [t for t in threading.enumerate() if t.name.startswith("oah-sandbox")]


def _freshness():
    return services.get_data_freshness()


def test_the_first_request_waits_for_the_sandbox_and_the_data_is_live(wired):
    _clock, jobs, sandbox = wired
    assert _freshness()["status"] == "unknown"
    assert services.get_cached_observations()[0]["id"] == "g1"
    services.get_cached_locations()
    assert sandbox.calls == ["Observation", "Location"] and jobs.pending == []
    assert _freshness()["status"] == "live"


def test_a_copy_within_the_ttl_is_live_and_triggers_no_refresh(wired):
    clock, jobs, sandbox = wired
    services.get_cached_observations()
    services.get_cached_locations()
    clock.now += TTL - 1
    services.get_cached_observations()
    assert jobs.pending == [] and _freshness()["status"] == "live" and len(sandbox.calls) == 2


def test_a_copy_past_the_ttl_is_served_at_once_and_is_never_labelled_live(wired):
    clock, jobs, sandbox = wired
    services.get_cached_observations()
    services.get_cached_locations()
    clock.now += TTL + 1
    assert services.get_cached_observations()[0]["id"] == "g1"  # the stale copy, no wait
    assert len(sandbox.calls) == 2 and len(jobs.pending) == 1
    fresh = _freshness()
    assert fresh["status"] == "snapshot"  # a held copy: its as_of and age say how old it is
    assert fresh["as_of"] is not None and fresh["age_seconds"] is not None


def test_after_the_refresh_the_label_returns_to_live_with_the_new_as_of(wired):
    clock, jobs, _sandbox = wired
    services.get_cached_observations()
    services.get_cached_locations()
    clock.now += TTL + 1
    services.get_cached_observations()
    services.get_cached_locations()
    assert len(jobs.pending) == 2
    jobs.run()
    assert services.get_cached_observations()[0]["id"] == "g3"
    assert services.get_cached_locations()[0]["id"] == "g4"
    assert _freshness()["status"] == "live"


def test_one_stale_resource_type_lowers_the_whole_label(wired):
    clock, jobs, _sandbox = wired
    services.get_cached_locations()
    clock.now += TTL + 1
    services.get_cached_observations()  # fetched now, young
    assert _freshness()["status"] == "snapshot"  # the Location copy is past its TTL
    jobs.run()


def test_a_copy_older_than_a_day_is_snapshot_stale(monkeypatch, wired):
    clock, jobs, sandbox = wired
    long_lived = services._new_cache("Observation", clock=clock, start_thread=jobs, ttl_seconds=TTL, max_stale_seconds=3 * DAY)
    monkeypatch.setattr(services, "_observations_cache", long_lived)
    monkeypatch.setitem(services._caches, "Observation", long_lived)
    long_lived.get()
    clock.now += DAY - 1
    long_lived.get()
    assert _freshness()["status"] == "snapshot"
    clock.now += 2
    long_lived.get()
    assert _freshness()["status"] == "snapshot-stale"
    jobs.run()
    assert sandbox.calls.count("Observation") >= 2


def test_a_recorded_snapshot_stale_status_is_never_improved_by_the_label_rule(wired):
    clock, jobs, sandbox = wired
    sandbox.mode = "snapshot-stale"
    services.get_cached_observations()  # nothing held and the live sandbox is down: the old snapshot is served
    assert _freshness()["status"] == "snapshot-stale"
    clock.now += TTL + 1
    services.get_cached_observations()
    assert _freshness()["status"] == "snapshot-stale"
    jobs.run()


def test_a_refresh_that_only_reaches_a_snapshot_keeps_the_held_live_copy_and_backs_off(wired):
    clock, jobs, sandbox = wired
    services.get_cached_observations()
    clock.now += TTL + 1
    sandbox.mode = "snapshot-stale"
    services.get_cached_observations()
    jobs.run()  # the refresh got an older snapshot: refused, the live copy stays
    assert services.get_cached_observations()[0]["id"] == "g1"
    assert services._freshness_by_type["Observation"]["status"] == "live"
    assert jobs.pending == []  # backing off
    clock.now += 31
    sandbox.mode = "live"
    services.get_cached_observations()
    assert len(jobs.pending) == 1
    jobs.run()
    assert services.get_cached_observations()[0]["id"] == "g2"


def test_a_refresh_while_the_sandbox_is_down_keeps_the_copy(wired):
    clock, jobs, sandbox = wired
    services.get_cached_observations()
    clock.now += TTL + 1
    sandbox.mode = "down"
    assert services.get_cached_observations()[0]["id"] == "g1"
    jobs.run()
    assert services.get_cached_observations()[0]["id"] == "g1"


def test_beyond_the_maximum_staleness_the_request_waits_and_gets_the_snapshot_or_a_503(wired):
    clock, jobs, sandbox = wired
    services.get_cached_observations()
    clock.now += MAX_STALE + 1
    sandbox.mode = "snapshot-stale"
    assert services.get_cached_observations()[0]["id"] == "old"  # the existing fallback, labelled snapshot-stale
    assert services._freshness_by_type["Observation"]["status"] == "snapshot-stale"
    clock.now += MAX_STALE + 1
    sandbox.mode = "down"
    with pytest.raises(HTTPException) as caught:
        services.get_cached_observations()
    assert caught.value.status_code == 503
    jobs.run()


def test_the_routes_label_a_stale_copy_through_the_existing_field(wired):
    clock, jobs, sandbox = wired
    sandbox.empty = True
    client = TestClient(app_module.app)
    assert client.get("/sites").json()["data_freshness"]["status"] == "live"
    clock.now += TTL + 1
    body = client.get("/sites").json()
    assert body["origin"] == "real-sandbox" and body["data_freshness"]["status"] == "snapshot"
    assert body["data_freshness"]["as_of"] is not None
    jobs.run()
    assert client.get("/sites").json()["data_freshness"]["status"] == "live"


def test_worst_status_orders_like_combine_freshness():
    assert worst_status("live", "snapshot") == "snapshot"
    assert worst_status("snapshot-stale", "snapshot") == "snapshot-stale"
    assert worst_status("unknown", "live") == "unknown"
    assert worst_status("live", "live") == "live"


def test_warm_up_fills_both_caches_in_background_threads(wired):
    _clock, _jobs, sandbox = wired
    threads = services.start_sandbox_warmup()
    assert {t.name for t in threads} == {"oah-sandbox-warmup-observation", "oah-sandbox-warmup-location"}
    for thread in threads:
        thread.join(5.0)
    assert sorted(sandbox.calls) == ["Location", "Observation"]
    services.get_cached_observations()
    services.get_cached_locations()
    assert len(sandbox.calls) == 2 and _freshness()["status"] == "live"


def test_a_failed_warm_up_does_not_raise_and_the_first_request_retries(wired):
    _clock, _jobs, sandbox = wired
    sandbox.mode = "down"
    for thread in services.start_sandbox_warmup():
        thread.join(5.0)
        assert not thread.is_alive()
    assert _freshness()["status"] == "unknown"
    sandbox.mode = "live"
    assert services.get_cached_observations()[0]["id"] == "g1"


def _settings(**changes):
    return dataclasses.replace(deps_module.settings, **changes)


def test_the_lifespan_starts_the_warm_up_without_waiting_for_it(monkeypatch):
    release = threading.Event()
    started: list[threading.Thread] = []

    def slow_warmup():
        thread = threading.Thread(target=lambda: release.wait(5.0), name="oah-sandbox-warmup-test", daemon=True)
        thread.start()
        started.append(thread)
        return [thread]

    monkeypatch.setattr(app_module, "start_sandbox_warmup", slow_warmup)
    monkeypatch.setattr(deps_module, "settings", _settings(sandbox_warmup=True))
    begin = time.monotonic()
    with TestClient(app_module.app) as client:
        assert client.get("/health").status_code == 200  # start-up finished while the warm-up is still blocked
        assert time.monotonic() - begin < 4.0 and started[0].is_alive()
    release.set()
    started[0].join(5.0)


def test_the_lifespan_survives_a_warm_up_that_cannot_start(monkeypatch, caplog):
    def broken():
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(app_module, "start_sandbox_warmup", broken)
    monkeypatch.setattr(deps_module, "settings", _settings(sandbox_warmup=True))
    with caplog.at_level("ERROR"), TestClient(app_module.app) as client:
        assert client.get("/health").status_code == 200
    assert "warm-up" in caplog.text


def test_the_warm_up_can_be_switched_off(monkeypatch):
    called: list[int] = []
    monkeypatch.setattr(app_module, "start_sandbox_warmup", lambda: called.append(1))
    monkeypatch.setattr(deps_module, "settings", _settings(sandbox_warmup=False))
    with TestClient(app_module.app) as client:
        assert client.get("/health").status_code == 200
    assert called == []
