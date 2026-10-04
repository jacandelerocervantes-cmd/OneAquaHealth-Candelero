"""A stale-while-revalidate in-process cache for the sandbox resources behind the API.

Why: fetching the public sandbox takes about 12 seconds (hundreds of paged requests). With a plain TTL cache every visitor
who arrives after the entry expired waits for that fetch. This cache serves the copy it holds at once and refreshes it in
the background, so only the very first request of a process (no copy at all) or a request that finds a copy older than
the maximum staleness has to wait.

Rules (see ``docs/architecture.md``, "Sandbox cache"):

* age < ``ttl_seconds``: served as is.
* ``ttl_seconds`` <= age < ``max_stale_seconds``: the copy is served immediately and, if no refresh is running and the
  back-off allows it, ONE refresh starts in a daemon thread (single flight). The refresh is REQUEST-DRIVEN: nothing here
  needs a timer. On a platform that throttles the CPU outside requests (Cloud Run with CPU throttling) the thread only
  progresses while some request is processed (plus the start-up boost), so a refresh started by the last request before
  an idle period may only finish during the next request. The copy then stays stale until that happens; callers learn
  it through ``is_past_ttl`` (the API labels such responses, see ``oah.api.services.get_data_freshness``).
* no copy, or age >= ``max_stale_seconds``: the caller waits for a fetch (single flight, the others wait for the same
  fetch) and a failure propagates to it.
* a refresh that raises keeps the old copy and backs off exponentially (``backoff_initial_seconds`` doubling up to
  ``backoff_max_seconds``) so a sandbox that is down is not hammered; a refresh that exceeds ``refresh_timeout_seconds`` is
  abandoned (its late result is discarded) and counts as a failure.

The clock and the thread starter are injectable so the tests are deterministic. The clock is monotonic.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_REFRESH_TIMEOUT_SECONDS = 120.0
DEFAULT_BACKOFF_INITIAL_SECONDS = 30.0
DEFAULT_BACKOFF_MAX_SECONDS = 600.0
REFRESH_THREAD_NAME = "oah-sandbox-refresh"

Fetched = tuple[list[dict[str, Any]], Any]  # (resources, metadata handed to ``on_store``)


def _start_daemon_thread(target: Callable[[], None]) -> None:
    threading.Thread(target=target, name=REFRESH_THREAD_NAME, daemon=True).start()


class RevalidatingCache:
    """A single-entry stale-while-revalidate cache around a fetch function returning ``(value, metadata)``."""

    def __init__(
        self,
        fetch: Callable[[], Fetched],
        *,
        ttl_seconds: float,
        max_stale_seconds: float,
        refresh_fetch: Callable[[], Fetched] | None = None,
        on_store: Callable[[Any], None] | None = None,
        refresh_timeout_seconds: float = DEFAULT_REFRESH_TIMEOUT_SECONDS,
        backoff_initial_seconds: float = DEFAULT_BACKOFF_INITIAL_SECONDS,
        backoff_max_seconds: float = DEFAULT_BACKOFF_MAX_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        start_thread: Callable[[Callable[[], None]], None] = _start_daemon_thread,
    ) -> None:
        if ttl_seconds <= 0.0:
            raise ValueError(f"ttl_seconds must be positive, got {ttl_seconds}.")
        if max_stale_seconds < ttl_seconds:
            raise ValueError("max_stale_seconds must be at least ttl_seconds.")
        if refresh_timeout_seconds <= 0.0 or backoff_initial_seconds <= 0.0 or backoff_max_seconds < backoff_initial_seconds:
            raise ValueError("refresh timeout and back-off must be positive, with the maximum at least the initial delay.")
        self._fetch = fetch
        self._refresh_fetch = refresh_fetch or fetch
        self._on_store = on_store
        self._ttl = ttl_seconds
        self._max_stale = max_stale_seconds
        self._refresh_timeout = refresh_timeout_seconds
        self._backoff_initial = backoff_initial_seconds
        self._backoff_max = backoff_max_seconds
        self._clock = clock
        self._start_thread = start_thread
        self._lock = threading.Lock()  # guards the state below; never held while fetching
        self._fill_lock = threading.Lock()  # one blocking fetch at a time (the others wait for it)
        self._value: list[dict[str, Any]] | None = None
        self._stored_at = 0.0
        self._token: object | None = None  # identifies the running refresh; None when none is running
        self._refresh_started_at = 0.0
        self._failures = 0
        self._retry_at = 0.0

    # --- reading ------------------------------------------------------------------------------

    def get(self) -> list[dict[str, Any]]:
        """Return the held copy at once when it is young enough; otherwise wait for a fetch (see the module docstring)."""
        token: object | None = None
        with self._lock:
            now = self._clock()
            if self._value is not None:
                age = now - self._stored_at
                if age < self._ttl:
                    return self._value
                if age < self._max_stale:
                    token = self._claim_refresh(now)
                    value = self._value
                else:
                    value = None
            else:
                value = None
        if value is not None:
            if token is not None:
                self._launch(token)
            return value
        return self._fetch_blocking()

    def age_seconds(self) -> float | None:
        """Age of the held copy, or None when there is none."""
        with self._lock:
            return None if self._value is None else max(0.0, self._clock() - self._stored_at)

    def is_past_ttl(self) -> bool:
        """Whether the held copy is older than the TTL (it would be served as stale, never as current)."""
        age = self.age_seconds()
        return age is not None and age >= self._ttl

    def refresh_running(self) -> bool:
        with self._lock:
            return self._token is not None

    def clear(self) -> None:
        """Drop the copy and any back-off; a running refresh is abandoned and its result discarded."""
        with self._lock:
            self._value = None
            self._token = None
            self._failures = 0
            self._retry_at = 0.0

    # --- warming ------------------------------------------------------------------------------

    def warm(self) -> bool:
        """Fill the cache in the CALLING thread when it holds no usable copy. Never raises; True when a copy is held."""
        try:
            self._fetch_blocking()  # returns at once when a young copy is already held
            return True
        except Exception as error:  # noqa: BLE001  (a failed warm-up must not crash the server; the first request retries)
            logger.warning("Sandbox cache warm-up failed: %s", getattr(error, "detail", error))
            return False

    # --- internals ----------------------------------------------------------------------------

    def _fetch_blocking(self) -> list[dict[str, Any]]:
        with self._fill_lock:  # concurrent callers wait for ONE fetch instead of each fetching
            with self._lock:
                if self._value is not None and self._clock() - self._stored_at < self._ttl:
                    return self._value
            value, metadata = self._fetch()
            with self._lock:
                self._store(value, metadata)
                self._token = None  # a refresh that was running is now obsolete: its result is discarded
            return value

    def _store(self, value: list[dict[str, Any]], metadata: Any) -> None:
        """Keep a fetched copy (caller holds ``_lock``)."""
        self._value = value
        self._stored_at = self._clock()
        self._failures = 0
        self._retry_at = 0.0
        if self._on_store is not None:
            self._on_store(metadata)

    def _register_failure(self, now: float) -> None:
        self._failures += 1
        delay = min(self._backoff_max, self._backoff_initial * 2 ** (self._failures - 1))
        self._retry_at = now + delay

    def _claim_refresh(self, now: float) -> object | None:
        """Decide, under the lock, whether this request starts the refresh; returns its token or None."""
        if self._token is not None:
            if now - self._refresh_started_at < self._refresh_timeout:
                return None  # single flight: one is running
            logger.warning("Sandbox refresh abandoned after %.0f s; backing off.", now - self._refresh_started_at)
            self._token = None
            self._register_failure(now)
        if now < self._retry_at:
            return None  # backing off after a failure
        self._token = object()
        self._refresh_started_at = now
        return self._token

    def _launch(self, token: object) -> None:
        try:
            self._start_thread(lambda: self._run_refresh(token))
        except Exception as error:  # noqa: BLE001  (for example the interpreter cannot start a thread)
            logger.warning("Could not start the sandbox refresh: %s", error)
            self._finish(token, None)

    def _run_refresh(self, token: object) -> None:
        try:
            fetched: Fetched | None = self._refresh_fetch()
        except Exception as error:  # noqa: BLE001  (the stale copy keeps being served; the detail goes to the log only)
            logger.warning("Sandbox refresh failed, keeping the stale copy: %s", getattr(error, "detail", error))
            fetched = None
        self._finish(token, fetched)

    def _finish(self, token: object, fetched: Fetched | None) -> None:
        with self._lock:
            if self._token is not token:
                return  # superseded by a blocking fetch, a clear() or a timeout: discard
            self._token = None
            if fetched is None:
                self._register_failure(self._clock())
            else:
                self._store(*fetched)
