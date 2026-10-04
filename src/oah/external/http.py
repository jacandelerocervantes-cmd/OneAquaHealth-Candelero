"""A hardened, GET-only JSON client for the few external hosts of this package.

What it refuses, before and after the request:

* any host outside ``oah.external.constants.ALLOWED_HOSTS`` (no caller supplies a URL or a host: the host is a constant
  at the call site, the path is checked against a strict pattern, parameters are rendered here);
* any scheme but https, userinfo in the URL, and any redirect that leaves the original host or scheme (a redirect to
  the same host is followed at most ``MAX_REDIRECTS`` times; there is no automatic redirect handling);
* a response that is not ``application/json``, whose declared or actual size is above ``max_bytes`` (read in chunks
  and stopped), or that is not a JSON object.

Failures are ``ExternalError`` with a reason code from ``oah.external.constants``; the text never carries a URL or a
coordinate. Retries are bounded (``max_retries`` extra attempts, exponential back-off) and only for a timeout, a
network error or a 5xx; a 429 is never retried (the caller opens a cool-down instead). ``before_attempt`` lets the
caller charge its budget for EVERY attempt.

The HTTP layer is injectable (``client_factory``) so the tests use a scripted ``httpx.MockTransport`` and never reach
the network.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from oah.external.constants import (
    ALLOWED_HOSTS,
    REASON_BAD_RESPONSE,
    REASON_BLOCKED,
    REASON_HTTP,
    REASON_NETWORK,
    REASON_RATE_LIMITED,
    REASON_REDIRECT,
    REASON_TIMEOUT,
    REASON_TOO_LARGE,
)

LOGGER = logging.getLogger("oah.external")
MAX_REDIRECTS = 2
DEFAULT_MAX_BYTES = 1024 * 1024
CHUNK_BYTES = 16 * 1024
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_PATH = re.compile(r"^/v1/[A-Za-z0-9._/-]{1,120}$")
_PARAM_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")
_MAX_PARAMS = 40
_MAX_PARAM_VALUE_CHARS = 1500
MAX_RETRY_AFTER_SECONDS = 600.0

Param = tuple[str, str]


class ExternalError(Exception):
    """A provider call failed. ``reason`` is one of ``oah.external.constants.REASONS``; ``retry_after`` is set for a 429."""

    def __init__(
        self, reason: str, detail: str = "", retry_after: float | None = None, retryable: bool = False
    ) -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.retry_after = retry_after
        self.retryable = retryable  # a timeout, a network error or a 5xx; never a 429 or a malformed answer


def default_client() -> httpx.Client:
    return httpx.Client(follow_redirects=False, verify=True)


def _validate_request(host: str, path: str, params: Sequence[Param]) -> None:
    if host not in ALLOWED_HOSTS:
        raise ExternalError(REASON_BLOCKED, "host is not on the allow-list")
    if not _PATH.fullmatch(path) or ".." in path or "//" in path:
        raise ExternalError(REASON_BLOCKED, "path is not allowed")
    if len(params) > _MAX_PARAMS:
        raise ExternalError(REASON_BLOCKED, "too many parameters")
    for name, value in params:
        if not _PARAM_NAME.fullmatch(name) or not isinstance(value, str) or len(value) > _MAX_PARAM_VALUE_CHARS:
            raise ExternalError(REASON_BLOCKED, "parameter is not allowed")
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ExternalError(REASON_BLOCKED, "parameter has control characters")


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS) if seconds == seconds else None  # NaN is dropped


def _next_url(current: httpx.URL, response: httpx.Response) -> httpx.URL:
    """The redirect target, only when it stays on the same https host; otherwise ``redirect-refused``."""
    location = response.headers.get("location")
    if not location or len(location) > 2000:
        raise ExternalError(REASON_REDIRECT, "redirect without a usable location")
    target = urlparse(urljoin(str(current), location))
    if (
        target.scheme != "https"
        or target.hostname != current.host
        or target.hostname not in ALLOWED_HOSTS
        or target.username
        or target.password
        or (target.port not in (None, 443))
    ):
        raise ExternalError(REASON_REDIRECT, "redirect leaves the allowed host")
    return httpx.URL(target.geturl())


def _read_json(response: httpx.Response, max_bytes: int) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json" and not content_type.endswith("+json"):
        raise ExternalError(REASON_BAD_RESPONSE, "response is not JSON")
    declared = response.headers.get("content-length")
    if declared is not None and declared.strip().isdigit() and int(declared.strip()) > max_bytes:
        raise ExternalError(REASON_TOO_LARGE, "declared size above the limit")
    body = bytearray()
    for chunk in response.iter_bytes(CHUNK_BYTES):
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ExternalError(REASON_TOO_LARGE, "body above the limit")
    try:
        payload = json.loads(bytes(body))
    except (ValueError, RecursionError) as error:
        raise ExternalError(REASON_BAD_RESPONSE, "body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise ExternalError(REASON_BAD_RESPONSE, "JSON body is not an object")
    return payload


def _attempt(
    client: httpx.Client, host: str, path: str, params: Sequence[Param], headers: dict[str, str],
    timeout: float, max_bytes: int,
) -> dict[str, Any]:
    url = httpx.URL(f"https://{host}{path}").copy_merge_params(list(params))
    for hop in range(MAX_REDIRECTS + 1):
        with client.stream("GET", url, headers=headers, timeout=httpx.Timeout(timeout)) as response:
            status = response.status_code
            if status in _REDIRECT_STATUSES:
                if hop == MAX_REDIRECTS:
                    raise ExternalError(REASON_REDIRECT, "too many redirects")
                url = _next_url(url, response)
                continue
            if status == 429:
                raise ExternalError(REASON_RATE_LIMITED, "provider answered 429", retry_after=_retry_after(response))
            if status >= 400:
                raise ExternalError(REASON_HTTP, f"provider answered {status}", retryable=status >= 500)
            if status != 200:
                raise ExternalError(REASON_BAD_RESPONSE, f"unexpected status {status}")
            return _read_json(response, max_bytes)
    raise ExternalError(REASON_REDIRECT, "too many redirects")  # pragma: no cover  (the loop always returns or raises)


class ExternalHttp:
    """GET-only JSON client with bounded retries. ``client_factory`` makes one ``httpx.Client`` per request."""

    def __init__(
        self,
        user_agent: str,
        timeout_seconds: float,
        max_retries: int,
        client_factory: Callable[[], httpx.Client] = default_client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._headers = {"User-Agent": user_agent, "Accept": "application/json"}
        self._timeout = timeout_seconds
        self._max_retries = max(0, max_retries)
        self._factory = client_factory
        self._sleep = sleep

    def get_json(
        self,
        host: str,
        path: str,
        params: Sequence[Param],
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        before_attempt: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        """The JSON object at ``https://<host><path>?<params>``; raises ``ExternalError``. Never returns a non-object."""
        _validate_request(host, path, params)
        last: ExternalError | None = None
        for attempt in range(self._max_retries + 1):
            if before_attempt is not None:
                before_attempt()  # raises ExternalError (budget) before anything leaves the process
            try:
                with self._factory() as client:
                    return _attempt(client, host, path, params, self._headers, self._timeout, max_bytes)
            except ExternalError as error:
                if not error.retryable:
                    LOGGER.info("external call failed: host=%s reason=%s", host, error.reason)
                    raise
                last = error
            except httpx.TimeoutException:
                last = ExternalError(REASON_TIMEOUT, "request timed out", retryable=True)
            except (httpx.TransportError, httpx.InvalidURL, OSError):
                last = ExternalError(REASON_NETWORK, "network error", retryable=True)
            if attempt < self._max_retries:
                self._sleep(min(0.25 * (2**attempt), 2.0))
        assert last is not None
        LOGGER.info("external call failed after retries: host=%s reason=%s", host, last.reason)
        raise last
