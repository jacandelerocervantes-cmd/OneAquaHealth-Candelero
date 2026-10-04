"""Cache, budget and circuit breaker for the external providers. In-process, thread-safe, injectable clock.

Like the spend guards of ``oah.api.llm_guard`` these are valid for one process; they do not coordinate across workers
(docs/external_context.md section 6).
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Hashable
from typing import Any

MINUTE_SECONDS = 60.0
DAY_SECONDS = 24 * 3600.0


class TtlCache:
    """A small LRU cache whose entries also expire after a TTL (per entry or the default one)."""

    def __init__(self, ttl_seconds: float, max_entries: int, clock: Callable[[], float] = time.monotonic) -> None:
        if ttl_seconds <= 0.0 or max_entries <= 0:
            raise ValueError("ttl_seconds and max_entries must be positive.")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._lock = threading.RLock()
        self._entries: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()

    def get(self, key: Hashable) -> tuple[bool, Any]:
        """``(True, value)`` on a live hit, else ``(False, None)``; an expired entry is dropped."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return False, None
            expires_at, value = entry
            if self._clock() >= expires_at:
                del self._entries[key]
                return False, None
            self._entries.move_to_end(key)
            return True, value

    def put(self, key: Hashable, value: Any, ttl_seconds: float | None = None) -> None:
        with self._lock:
            self._entries[key] = (self._clock() + (ttl_seconds if ttl_seconds is not None else self._ttl), value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class RollingBudget:
    """Units spent in the last minute and the last 24 hours; a reservation that would pass either cap is refused.

    A refused reservation counts nothing. ``units`` may be fractional (the provider counts a long request as several
    calls); an amount above a whole cap can never be reserved, so a request that large is refused outright.
    """

    def __init__(
        self, per_minute: float, per_day: float, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if per_minute <= 0 or per_day <= 0:
            raise ValueError("per_minute and per_day must be positive.")
        self.per_minute = per_minute
        self.per_day = per_day
        self._clock = clock
        self._lock = threading.RLock()
        self._spent: deque[tuple[float, float]] = deque()  # (time, units), oldest first

    def _prune(self, now: float) -> None:
        while self._spent and self._spent[0][0] <= now - DAY_SECONDS:
            self._spent.popleft()

    def _sums(self, now: float) -> tuple[float, float]:
        day = sum(units for _, units in self._spent)
        minute = sum(units for stamp, units in self._spent if stamp > now - MINUTE_SECONDS)
        return minute, day

    def try_reserve(self, units: float) -> bool:
        if units <= 0:
            raise ValueError("units must be positive.")
        with self._lock:
            now = self._clock()
            self._prune(now)
            minute, day = self._sums(now)
            if minute + units > self.per_minute or day + units > self.per_day:
                return False
            self._spent.append((now, units))
            return True

    def remaining(self) -> tuple[float, float]:
        """``(units left this minute, units left in the rolling day)``."""
        with self._lock:
            now = self._clock()
            self._prune(now)
            minute, day = self._sums(now)
            return max(0.0, self.per_minute - minute), max(0.0, self.per_day - day)


class Breaker:
    """Opens for ``cooldown`` seconds after ``failure_limit`` consecutive failures, or at once for a rate limit."""

    def __init__(
        self, failure_limit: int = 3, cooldown_seconds: float = 30.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limit = failure_limit
        self._cooldown = cooldown_seconds
        self._clock = clock
        self._lock = threading.RLock()
        self._failures = 0
        self._open_until = 0.0

    def allow(self) -> bool:
        with self._lock:
            return self._clock() >= self._open_until

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self._limit:
                self._open_until = self._clock() + self._cooldown
                self._failures = 0

    def open_for(self, seconds: float) -> None:
        """Open at once (a 429): no call until ``seconds`` have passed (never shorter than an open breaker already is)."""
        with self._lock:
            self._open_until = max(self._open_until, self._clock() + max(seconds, 0.0))
            self._failures = 0
