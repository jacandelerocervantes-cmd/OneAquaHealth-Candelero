"""A small in-process, fixed-window rate limiter for the API layer.

This is a single-process limiter: it does not coordinate across multiple uvicorn workers or
multiple machines. That is a stated limitation, not an oversight -- real distributed rate
limiting needs a shared store (e.g. Redis), which is out of scope for a local/demo deployment.
It still stops one client process from hammering the API, which is the gap this project's own
security review flagged as missing.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Fixed-window request counter per key (e.g. client IP)."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        if max_requests <= 0:
            raise ValueError(f"max_requests must be positive, got {max_requests}.")
        if window_seconds <= 0.0:
            raise ValueError(f"window_seconds must be positive, got {window_seconds}.")
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()  # sync endpoints run in a thread pool

    def allow(self, key: str) -> bool:
        """Record one request for `key`; return whether it is within the limit."""
        now = time.monotonic()
        cutoff = now - self._window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self._max_requests:
                return False
            hits.append(now)
            if len(self._hits) > 1024:  # drop idle keys so many source addresses cannot grow memory without bound
                for idle in [k for k, v in self._hits.items() if not v or v[-1] < cutoff]:
                    del self._hits[idle]
            return True
