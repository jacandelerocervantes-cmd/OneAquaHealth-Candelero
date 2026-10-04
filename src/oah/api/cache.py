"""A small in-process TTL cache for sandbox Observations used by the API layer.

The API must not re-fetch all of the sandbox's Observations (hundreds) on every request. This module
caches the last successful fetch for a configurable time-to-live, using a monotonic clock
so it is unaffected by wall-clock changes. Callers can bypass or clear the cache for tests.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable

DEFAULT_TTL_SECONDS = 300.0


class TTLCache:
    """A single-entry TTL cache around a zero-argument fetch function."""

    def __init__(self, fetch: Callable[[], list[dict[str, Any]]], ttl_seconds: float = DEFAULT_TTL_SECONDS) -> None:
        if ttl_seconds <= 0.0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}.")
        self._fetch = fetch
        self._ttl_seconds = ttl_seconds
        self._value: list[dict[str, Any]] | None = None
        self._fetched_at: float | None = None
        self._lock = threading.Lock()

    def get(self) -> list[dict[str, Any]]:
        """Return the cached value, refreshing it if missing or expired."""
        with self._lock:  # single flight: concurrent misses wait for one refill instead of each fetching
            now = time.monotonic()
            expired = self._fetched_at is None or (now - self._fetched_at) >= self._ttl_seconds
            if self._value is None or expired:
                self._value = self._fetch()
                self._fetched_at = now
            return self._value

    def clear(self) -> None:
        """Force the next get() call to refetch."""
        with self._lock:
            self._value = None
            self._fetched_at = None
