"""The runtime: switches, budget per attempt, breaker, cache, status entries, the process-wide accessor."""
from __future__ import annotations

import httpx
import pytest

from oah.external import constants as c
from oah.external import runtime as runtime_module
from oah.external.http import ExternalError
from oah.external.runtime import ExternalRuntime, get_runtime, set_runtime
from oah.external.settings import ExternalSettings
from external_fakes import Router, json_response, make_runtime

PARAMS = [("a", "1")]


def call(runtime: ExternalRuntime, provider: str = c.PROVIDER_WEATHER, host: str = c.ARCHIVE_HOST, units: float = 1.0):
    return runtime.call(provider, host, "/v1/archive", PARAMS, units=units)


def test_a_call_goes_through_and_is_counted_against_the_budget() -> None:
    runtime, router, _ = make_runtime()
    router.on(c.ARCHIVE_HOST, lambda request: json_response({"ok": True}))
    assert call(runtime, units=3.0) == {"ok": True}
    assert runtime.budget_remaining(c.PROVIDER_WEATHER)["per_minute_remaining"] == runtime.settings.open_meteo_per_minute - 3.0


def test_master_switch_and_provider_switches_stop_the_call() -> None:
    for settings, provider, host in [
        (ExternalSettings(enabled=False), c.PROVIDER_WEATHER, c.ARCHIVE_HOST),
        (ExternalSettings(open_meteo_enabled=False), c.PROVIDER_WEATHER, c.ARCHIVE_HOST),
        (ExternalSettings(glofas_enabled=False), c.PROVIDER_DISCHARGE, c.FLOOD_HOST),
        (ExternalSettings(gbif_enabled=False), c.PROVIDER_GBIF, c.GBIF_HOST),
    ]:
        runtime, router, _ = make_runtime(settings=settings)
        assert runtime.enabled(provider) is False
        with pytest.raises(ExternalError) as caught:
            call(runtime, provider, host)
        assert caught.value.reason == c.REASON_DISABLED and router.requests == []
    # one switched-off provider leaves the others on
    runtime, _, _ = make_runtime(settings=ExternalSettings(gbif_enabled=False))
    assert runtime.enabled(c.PROVIDER_WEATHER) and runtime.enabled(c.PROVIDER_DISCHARGE) and not runtime.enabled(c.PROVIDER_GBIF)


def test_budget_exhaustion_is_reported_and_nothing_is_sent() -> None:
    runtime, router, clock = make_runtime(settings=ExternalSettings(open_meteo_per_minute=5, max_retries=0))
    router.on(c.ARCHIVE_HOST, lambda request: json_response({}))
    call(runtime, units=4.0)
    with pytest.raises(ExternalError) as caught:
        call(runtime, units=2.0)
    assert caught.value.reason == c.REASON_BUDGET and router.count() == 1
    assert not runtime.breaker_open(c.PROVIDER_WEATHER)  # running out of budget is not a provider failure
    clock.advance(61)
    call(runtime, units=2.0)
    assert router.count() == 2


def test_weather_and_discharge_share_the_open_meteo_budget_but_gbif_has_its_own() -> None:
    runtime, router, _ = make_runtime(settings=ExternalSettings(open_meteo_per_minute=3, max_retries=0))
    router.on(c.ARCHIVE_HOST, lambda request: json_response({}))
    router.on(c.FLOOD_HOST, lambda request: json_response({}))
    router.on(c.GBIF_HOST, lambda request: json_response({}))
    runtime.call(c.PROVIDER_WEATHER, c.ARCHIVE_HOST, "/v1/archive", PARAMS, units=2.0)
    with pytest.raises(ExternalError) as caught:
        runtime.call(c.PROVIDER_DISCHARGE, c.FLOOD_HOST, "/v1/flood", PARAMS, units=2.0)
    assert caught.value.reason == c.REASON_BUDGET
    runtime.call(c.PROVIDER_GBIF, c.GBIF_HOST, "/v1/occurrence/search", PARAMS)


def test_every_retry_attempt_is_charged() -> None:
    runtime, router, _ = make_runtime(settings=ExternalSettings(max_retries=2, open_meteo_per_minute=100))
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(503))
    with pytest.raises(ExternalError):
        call(runtime, units=10.0)
    assert router.count() == 3
    assert runtime.budget_remaining(c.PROVIDER_WEATHER)["per_minute_remaining"] == 70.0


def test_a_429_opens_the_breaker_for_retry_after_and_later_calls_are_refused_without_a_request() -> None:
    runtime, router, clock = make_runtime()
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(429, headers={"retry-after": "120"}))
    with pytest.raises(ExternalError) as caught:
        call(runtime)
    assert caught.value.reason == c.REASON_RATE_LIMITED
    with pytest.raises(ExternalError) as cooling:
        call(runtime)
    assert cooling.value.reason == c.REASON_COOLING_DOWN and router.count() == 1
    assert runtime.breaker_open(c.PROVIDER_WEATHER)
    clock.advance(121)
    router.on(c.ARCHIVE_HOST, lambda request: json_response({"back": 1}))
    assert call(runtime) == {"back": 1}


def test_a_429_without_retry_after_uses_the_default_cooldown() -> None:
    runtime, router, clock = make_runtime()
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(429))
    with pytest.raises(ExternalError):
        call(runtime)
    clock.advance(runtime_module.DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS - 1)
    assert runtime.breaker_open(c.PROVIDER_WEATHER)
    clock.advance(2)
    assert not runtime.breaker_open(c.PROVIDER_WEATHER)


def test_three_consecutive_failures_open_the_breaker_and_a_success_resets_the_run() -> None:
    runtime, router, clock = make_runtime()
    state = {"fail": True}
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(500) if state["fail"] else json_response({}))
    for _ in range(2):
        with pytest.raises(ExternalError):
            call(runtime)
    state["fail"] = False
    call(runtime)  # success resets the count
    state["fail"] = True
    for _ in range(3):
        with pytest.raises(ExternalError):
            call(runtime)
    with pytest.raises(ExternalError) as caught:
        call(runtime)
    assert caught.value.reason == c.REASON_COOLING_DOWN
    clock.advance(runtime_module.FAILURE_COOLDOWN_SECONDS + 1)
    state["fail"] = False
    call(runtime)


def test_a_client_error_or_blocked_call_does_not_count_as_a_provider_failure() -> None:
    runtime, router, _ = make_runtime()
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(400))
    for _ in range(5):
        with pytest.raises(ExternalError) as caught:
            call(runtime)
        assert caught.value.reason == c.REASON_HTTP
    assert not runtime.breaker_open(c.PROVIDER_WEATHER)


def test_malformed_bodies_count_as_failures() -> None:
    runtime, router, _ = make_runtime()
    router.on(c.ARCHIVE_HOST, lambda request: httpx.Response(200, content=b"nope", headers={"content-type": "application/json"}))
    for _ in range(3):
        with pytest.raises(ExternalError):
            call(runtime)
    assert runtime.breaker_open(c.PROVIDER_WEATHER)


def test_cached_stores_only_successes_and_expires() -> None:
    runtime, _, clock = make_runtime(settings=ExternalSettings(cache_ttl_seconds=10.0))
    calls: list[int] = []

    def producer() -> dict[str, int]:
        calls.append(1)
        return {"n": len(calls)}

    assert runtime.cached("k", producer) == ({"n": 1}, False)
    assert runtime.cached("k", producer) == ({"n": 1}, True)
    assert len(calls) == 1
    clock.advance(11)
    assert runtime.cached("k", producer) == ({"n": 2}, False)

    def failing() -> dict[str, int]:
        raise ExternalError(c.REASON_TIMEOUT)

    with pytest.raises(ExternalError):
        runtime.cached("bad", failing)
    assert runtime.cache.get("bad") == (False, None)  # a failure is never cached
    runtime.cached("short", producer, ttl_seconds=2.0)
    clock.advance(3)
    assert runtime.cache.get("short")[0] is False


def test_status_entries_list_every_provider_without_secrets() -> None:
    runtime, _, _ = make_runtime(settings=ExternalSettings(gbif_enabled=False, contact_url="https://example.org/contact"))
    entries = runtime.status_entries()
    assert [entry["provider"] for entry in entries] == list(c.PROVIDERS)
    by_provider = {entry["provider"]: entry for entry in entries}
    assert by_provider[c.PROVIDER_GBIF]["enabled"] is False and by_provider[c.PROVIDER_WEATHER]["enabled"] is True
    assert by_provider[c.PROVIDER_WEATHER]["attribution"].startswith("Weather data by Open-Meteo.com")
    assert by_provider[c.PROVIDER_WEATHER]["attribution_verified"] is True
    assert by_provider[c.PROVIDER_DISCHARGE]["attribution_verified"] is False
    assert by_provider[c.PROVIDER_WEATHER]["budget_unit"] == "estimated-call-units" and by_provider[c.PROVIDER_GBIF]["budget_unit"] == "requests"
    assert by_provider[c.PROVIDER_WEATHER]["budget"]["per_day_remaining"] == runtime.settings.open_meteo_daily
    text = repr(entries)
    assert "example.org" not in text  # the contact URL is not exposed


def test_get_and_set_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_module, "_runtime", None)
    monkeypatch.setattr(runtime_module, "load_external_settings", lambda environment=None: ExternalSettings(enabled=False))
    first = get_runtime()
    assert first.settings.enabled is False and get_runtime() is first
    replacement, _, _ = make_runtime()
    set_runtime(replacement)
    assert get_runtime() is replacement
    set_runtime(None)
    assert get_runtime() is not replacement
    set_runtime(None)


def test_router_helper_requires_a_scripted_host() -> None:
    router = Router()
    with pytest.raises(AssertionError):
        router(httpx.Request("GET", "https://" + c.GBIF_HOST + "/v1/x"))
