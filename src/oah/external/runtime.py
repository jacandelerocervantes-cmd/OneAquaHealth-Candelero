"""The process-wide state of the external providers: settings, HTTP client, cache, budgets and breakers.

``ExternalRuntime.call`` is the only way a provider function reaches the network: it checks the switches, the breaker
and the budget, then makes the request through the hardened client. ``cached`` keeps the PARSED, small result of a
provider function (never a raw body) under a rounded-coordinate key, so a repeated question costs no call.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable, Hashable, Mapping, Sequence
from typing import Any, TypeVar

from oah.external.constants import (
    BUDGET_GBIF,
    BUDGET_OPEN_METEO,
    PROVIDER_DISCHARGE,
    PROVIDER_GBIF,
    PROVIDER_INFO,
    PROVIDER_WEATHER,
    PROVIDERS,
    REASON_BAD_RESPONSE,
    REASON_BUDGET,
    REASON_COOLING_DOWN,
    REASON_DISABLED,
    REASON_RATE_LIMITED,
    REASON_TOO_LARGE,
)
from oah.external.guard import Breaker, RollingBudget, TtlCache
from oah.external.http import DEFAULT_MAX_BYTES, ExternalError, ExternalHttp, Param
from oah.external.settings import ExternalSettings

T = TypeVar("T")
DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS = 60.0
FAILURE_COOLDOWN_SECONDS = 30.0
_BUDGET_OF = {PROVIDER_WEATHER: BUDGET_OPEN_METEO, PROVIDER_DISCHARGE: BUDGET_OPEN_METEO, PROVIDER_GBIF: BUDGET_GBIF}


def load_external_settings(environment: Mapping[str, str] | None = None) -> ExternalSettings:
    """The external settings of ``oah.config.load_settings`` (dotenv file and environment; explicit values win)."""
    from oah.config import load_settings  # a function-level import: ``oah.config`` imports the settings parser

    return load_settings(environment).external


class ExternalRuntime:
    def __init__(
        self,
        settings: ExternalSettings,
        http: ExternalHttp | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._http = http or ExternalHttp(settings.user_agent, settings.timeout_seconds, settings.max_retries)
        self._clock = clock
        self.cache = TtlCache(settings.cache_ttl_seconds, settings.cache_size, clock)
        self._budgets = {
            BUDGET_OPEN_METEO: RollingBudget(settings.open_meteo_per_minute, settings.open_meteo_daily, clock),
            BUDGET_GBIF: RollingBudget(settings.gbif_per_minute, settings.gbif_daily, clock),
        }
        self._breakers = {
            provider: Breaker(cooldown_seconds=FAILURE_COOLDOWN_SECONDS, clock=clock) for provider in PROVIDERS
        }

    # -- switches ---------------------------------------------------------------------------------------------------
    def enabled(self, provider: str) -> bool:
        flags = {
            PROVIDER_WEATHER: self.settings.open_meteo_enabled,
            PROVIDER_DISCHARGE: self.settings.glofas_enabled,
            PROVIDER_GBIF: self.settings.gbif_enabled,
        }
        return self.settings.enabled and flags[provider]

    # -- the one network path ----------------------------------------------------------------------------------------
    def call(
        self,
        provider: str,
        host: str,
        path: str,
        params: Sequence[Param],
        *,
        units: float = 1.0,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ) -> dict[str, Any]:
        """One bounded GET. Raises ``ExternalError`` (disabled, cooling down, over budget, or the provider's failure)."""
        if not self.enabled(provider):
            raise ExternalError(REASON_DISABLED, "provider is switched off")
        breaker, budget = self._breakers[provider], self._budgets[_BUDGET_OF[provider]]
        if not breaker.allow():
            raise ExternalError(REASON_COOLING_DOWN, "provider is cooling down after failures")

        def before_attempt() -> None:  # every attempt, retries included, is charged
            if not budget.try_reserve(units):
                raise ExternalError(REASON_BUDGET, "call budget exhausted")

        try:
            payload = self._http.get_json(host, path, params, max_bytes=max_bytes, before_attempt=before_attempt)
        except ExternalError as error:
            if error.reason == REASON_RATE_LIMITED:
                breaker.open_for(error.retry_after if error.retry_after is not None else DEFAULT_RATE_LIMIT_COOLDOWN_SECONDS)
            elif error.reason != REASON_BUDGET and (
                error.retryable or error.reason in (REASON_BAD_RESPONSE, REASON_TOO_LARGE)
            ):
                breaker.record_failure()
            raise
        breaker.record_success()
        return payload

    # -- cache ---------------------------------------------------------------------------------------------------------
    def cached(self, key: Hashable, producer: Callable[[], T], ttl_seconds: float | None = None) -> tuple[T, bool]:
        """``(value, from_cache)``. Only a successful ``producer`` result is stored; its ``ExternalError`` propagates."""
        hit, value = self.cache.get(key)
        if hit:
            return value, True
        produced = producer()
        self.cache.put(key, produced, ttl_seconds)
        return produced, False

    # -- status ---------------------------------------------------------------------------------------------------------
    def budget_remaining(self, provider: str) -> dict[str, float]:
        budget = self._budgets[_BUDGET_OF[provider]]
        minute, day = budget.remaining()
        return {
            "per_minute_limit": budget.per_minute, "per_minute_remaining": round(minute, 2),
            "per_day_limit": budget.per_day, "per_day_remaining": round(day, 2),
        }

    def breaker_open(self, provider: str) -> bool:
        return not self._breakers[provider].allow()

    def status_entries(self) -> list[dict[str, Any]]:
        """One entry per provider for ``GET /external/status``: static facts, the switch, the budget. No secret."""
        entries: list[dict[str, Any]] = []
        for provider in PROVIDERS:
            info = PROVIDER_INFO[provider]
            entries.append(
                {
                    "provider": provider, "name": info.name, "origin": info.origin, "data_kind": info.kind,
                    "enabled": self.enabled(provider), "cooling_down": self.breaker_open(provider),
                    "attribution": info.attribution, "attribution_url": info.attribution_url,
                    "attribution_verified": info.attribution_verified, "licence": info.licence,
                    "licence_note": info.licence_note, "limits": info.limits, "data_note": info.data_note,
                    "budget_unit": "estimated-call-units" if _BUDGET_OF[provider] == BUDGET_OPEN_METEO else "requests",
                    "budget": self.budget_remaining(provider),
                }
            )
        return entries


_runtime: ExternalRuntime | None = None
_runtime_lock = threading.Lock()


def get_runtime() -> ExternalRuntime:
    """The process-wide runtime, built from the settings on first use."""
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = ExternalRuntime(load_external_settings())
        return _runtime


def set_runtime(runtime: ExternalRuntime | None) -> None:
    """Install a runtime (tests, or a deployment with other limits); ``None`` makes the next use rebuild it."""
    global _runtime
    with _runtime_lock:
        _runtime = runtime
