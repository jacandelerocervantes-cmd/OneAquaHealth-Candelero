"""Spend and abuse controls for the endpoints that call a paid LLM.

Every ``/explain`` request that reaches the model costs real money and is a target for abuse (loops, scripted
callers, a leaked or absent API key). Three independent limits, all in-process (they do not coordinate across
workers or machines; see docs/security_review.md):

1. a per-client-host requests-per-minute budget that is much tighter than the general API limit;
2. a rolling 24-hour cap on REAL model calls for the whole process, so a runaway cannot spend past a known bound;
3. a small TTL cache: an identical request (same kind, mode, model and evidence) is answered without a model call
   and without consuming the daily cap.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from typing import Any

import threading

from fastapi import HTTPException

from oah.api.rate_limit import RateLimiter

DAY_SECONDS = 24 * 3600.0


class LLMSpendGuard:
    # What the 429 details call the guarded feature; ChatSpendGuard overrides them.
    RATE_DETAIL = "Explanation rate limit exceeded for this client. Slow down and retry in a minute."
    CAP_DETAIL = "Daily budget of {cap} model calls reached; explanations resume when older calls age out."

    def __init__(
        self,
        per_minute: int,
        daily_cap: int,
        cache_ttl_seconds: float,
        cache_size: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if daily_cap <= 0 or cache_size <= 0 or cache_ttl_seconds <= 0.0:
            raise ValueError("daily_cap, cache_size and cache_ttl_seconds must be positive.")
        self._limiter = RateLimiter(per_minute, 60.0)
        self._daily_cap = daily_cap
        self._cache_ttl = cache_ttl_seconds
        self._cache_size = cache_size
        self._clock = clock
        self._calls: deque[float] = deque()
        self._lock = threading.RLock()  # sync endpoints run in a thread pool
        self._cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def check_rate(self, host: str) -> None:
        """Raise 429 (with Retry-After) when ``host`` exceeded the per-minute budget for explanations."""
        if not self._limiter.allow(host):
            raise HTTPException(
                status_code=429,
                detail=self.RATE_DETAIL,
                headers={"Retry-After": "60"},
            )

    def calls_in_last_day(self) -> int:
        with self._lock:
            self._prune()
            return len(self._calls)

    def reserve_call(self) -> None:
        """Count one real model call against the rolling daily cap, or raise 429 when the cap is reached."""
        with self._lock:  # check and append are one step, so a burst cannot overshoot the cap
            self._prune()
            if len(self._calls) >= self._daily_cap:
                raise HTTPException(
                    status_code=429,
                    detail=self.CAP_DETAIL.format(cap=self._daily_cap),
                    headers={"Retry-After": "3600"},
                )
            self._calls.append(self._clock())

    def _prune(self) -> None:
        cutoff = self._clock() - DAY_SECONDS
        while self._calls and self._calls[0] < cutoff:
            self._calls.popleft()

    def remaining_calls(self) -> int:
        """Reservations left in the rolling window."""
        return max(0, self._daily_cap - self.calls_in_last_day())

    @staticmethod
    def key(kind: str, mode: str, model: str, evidence: Mapping[str, Any], language: str = "en") -> str:
        """Cache key. ``language`` is part of it: the English entry is shared, a translation has its own entry
        (the language code and the translation model), so two languages never share a cached text."""
        blob = json.dumps([kind, mode, model, evidence, language], sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def cached(self, key: str) -> Any | None:
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            stored_at, value = entry
            if self._clock() - stored_at >= self._cache_ttl:
                del self._cache[key]
                return None
            self._cache.move_to_end(key)
            return value

    def store(self, key: str, value: Any) -> None:
        with self._lock:
            self._cache[key] = (self._clock(), value)
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)


class ChatSpendGuard(LLMSpendGuard):
    """Spend controls for ``POST /chat``, separate from the explanation budget.

    One conversation chains up to ``max_steps`` model calls, so the two counters differ:

    * ``reserve_call`` (inherited) reserves ONE conversation of the rolling 24-hour cap, process-wide;
    * ``try_reserve_model_call`` counts every model call across all conversations against
      ``daily_cap * max_steps``. A conversation cannot exceed ``max_steps`` calls, so this total is a safety net that
      turns the worst-case bound into an enforced one instead of an assumed one.

    The per-host per-minute limit and the response cache are inherited. Like the parent it is in-process only.
    """

    RATE_DETAIL = "Chat rate limit exceeded for this client. Slow down and retry in a minute."
    CAP_DETAIL = "Daily budget of {cap} chat conversations reached; chat resumes when older conversations age out."

    def __init__(
        self,
        per_minute: int,
        daily_cap: int,
        cache_ttl_seconds: float,
        max_steps: int,
        cache_size: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive.")
        super().__init__(per_minute, daily_cap, cache_ttl_seconds, cache_size, clock)
        self._max_steps = max_steps
        self._model_call_cap = daily_cap * max_steps
        self._model_calls: deque[float] = deque()

    @property
    def max_steps(self) -> int:
        return self._max_steps

    def _prune_model_calls(self) -> None:
        cutoff = self._clock() - DAY_SECONDS
        while self._model_calls and self._model_calls[0] < cutoff:
            self._model_calls.popleft()

    def try_reserve_model_call(self) -> bool:
        """Count one model call; False (nothing counted) when the rolling model-call cap is reached."""
        with self._lock:
            self._prune_model_calls()
            if len(self._model_calls) >= self._model_call_cap:
                return False
            self._model_calls.append(self._clock())
            return True

    def remaining_model_calls(self) -> int:
        with self._lock:
            self._prune_model_calls()
            return max(0, self._model_call_cap - len(self._model_calls))

    @staticmethod
    def chat_key(
        message: str, country: str | None, index: str | None, history: Any, model: str, language: str = "en"
    ) -> str:
        """Cache key; ``language`` is part of it (see ``LLMSpendGuard.key``)."""
        blob = json.dumps([message, country, index, history, model, language], sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
