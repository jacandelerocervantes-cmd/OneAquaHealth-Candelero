"""Concurrency limit and result cache for country-scope comparisons (``docs/period_change.md`` section 11).

A country comparison scans up to millions of monthly rows. Even aggregated inside SQLite it is the most expensive read
of the API, so every country-scope comparison (Waterbase and bathing-water samples, from the REST routes and from the chat
tool alike) goes through ONE process-wide guard:

* at most ``MAX_CONCURRENT`` comparisons run at once; another waits at most ``WAIT_SECONDS`` and then gets ``ScopeBusy``
  (the API answers 503 with ``Retry-After``; the chat tool reports the same sentence). Nothing queues without limit;
* a small TTL + LRU cache keyed by what determines the answer (source, store file, country, parameter series, both windows;
  never the language, which is applied outside) makes a repeated identical question free. A failure is never cached.

State is per process and resets with every restart (a crash, a deploy, a failed probe); nothing here is shared between
instances. The values below are code constants, not settings: they bound memory, and no variable can raise them.
"""
from __future__ import annotations

import copy
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import TypeVar

MAX_CONCURRENT = 2  # country-scope comparisons running at the same time in this process
WAIT_SECONDS = 5.0  # how long another one waits for a slot before it is refused as busy
RETRY_AFTER_SECONDS = 5  # the ``Retry-After`` hint of a busy answer
CACHE_ENTRIES = 64  # results kept (LRU); each is a few kilobytes of numbers
CACHE_TTL_SECONDS = 600.0  # how long a result is served from the cache

T = TypeVar("T")


class ScopeTooLarge(Exception):
    """A country-scope read exceeded the hard row cap or the time cap; narrow the periods. The message is safe to show."""


class ScopeBusy(Exception):
    """Every comparison slot stayed taken for ``WAIT_SECONDS``; try again shortly. The message is safe to show."""

    retry_after = RETRY_AFTER_SECONDS

    def __init__(self) -> None:
        super().__init__(
            "The server is busy with other country-wide comparisons; try again in a few seconds "
            "(or compare one site, or a shorter period)."
        )


class ScopeGuard:
    """A bounded semaphore with a bounded wait, and a small TTL + LRU cache of finished results."""

    def __init__(
        self,
        max_concurrent: int = MAX_CONCURRENT,
        wait_seconds: float = WAIT_SECONDS,
        cache_entries: int = CACHE_ENTRIES,
        ttl_seconds: float = CACHE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._slots = threading.BoundedSemaphore(max(1, int(max_concurrent)))
        self._wait = max(0.0, float(wait_seconds))
        self._entries = max(1, int(cache_entries))
        self._ttl = max(0.0, float(ttl_seconds))
        self._clock = clock
        self._cache: OrderedDict[Hashable, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()

    def _cached(self, key: Hashable) -> tuple[bool, object]:
        with self._lock:
            found = self._cache.get(key)
            if found is None:
                return False, None
            stored_at, value = found
            if self._clock() - stored_at > self._ttl:
                del self._cache[key]
                return False, None
            self._cache.move_to_end(key)
            return True, copy.deepcopy(value)

    def _store(self, key: Hashable, value: object) -> None:
        with self._lock:
            self._cache[key] = (self._clock(), copy.deepcopy(value))
            self._cache.move_to_end(key)
            while len(self._cache) > self._entries:
                self._cache.popitem(last=False)

    def run(self, key: Hashable, compute: Callable[[], T]) -> T:
        """The cached result for ``key``, else ``compute()`` under a slot; ``ScopeBusy`` when no slot frees up in time.

        The result must be a plain structure (it is deep-copied in and out, so a caller can never alter a cached answer).
        An exception from ``compute`` propagates and nothing is cached.
        """
        hit, value = self._cached(key)
        if hit:
            return value  # type: ignore[return-value]
        if not self._slots.acquire(timeout=self._wait):
            raise ScopeBusy
        try:
            hit, value = self._cached(key)  # an identical question may have finished while this one waited
            if hit:
                return value  # type: ignore[return-value]
            result = compute()
            self._store(key, result)
            return result
        finally:
            self._slots.release()

    def clear(self) -> None:
        """Forget every cached result (tests; a restart does the same)."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)


GUARD = ScopeGuard()  # the process-wide guard used by both country-scope comparisons


def file_signature(path: Path) -> tuple[str, int, int]:
    """``(path, modification time in ns, size)`` of a store file, so a rebuilt store never answers from the cache of its
    predecessor; ``("", 0, 0)`` when it cannot be read."""
    try:
        info = path.stat()
    except OSError:
        return ("", 0, 0)
    return (str(path), info.st_mtime_ns, info.st_size)
