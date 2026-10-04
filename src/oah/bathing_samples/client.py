"""Read-only paged extraction from the EEA Discodata SQL endpoint (the only network code of this package).

The endpoint (``https://discodata.eea.europa.eu/sql?query=<T-SQL>&p=<page>&nrOfHits=<n>``) is a public, read-only GET
service. Observed on 2026-10-03 (``docs/bathing_samples_store.md``): ``OFFSET ... FETCH`` is refused (error code
10002) and so are system tables (10001), so a page is read with a KEYSET: ``TOP n ... WHERE UID > <last> ORDER BY UID``
over the table's unique integer ``UID``. No row cap was met up to 300,000 rows in one reply.

Rules of this module:

* the URL is built here from constants and validated integers only (the host is fixed, https only; nothing a caller can
  type reaches the query text);
* requests are paced (at most about two per second) and carry a descriptive User-Agent;
* a transient failure (network error, timeout, HTTP 408/425/429/500/502/503/504, a body that is not JSON or lacks
  ``results``, an ``errors`` reply WITHOUT an error code such as "Service currently offline") is retried with exponential
  backoff; an ``errors`` reply WITH an error code (10002 query refused, 10001 system tables) or any other HTTP status is a
  refusal and raises ``DiscodataError`` at once;
* the HTTP layer and the sleep are injectable, so tests script the service and never open a network connection.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from oah.bathing_samples.constants import (
    BACKOFF_BASE_SECONDS,
    BACKOFF_CAP_SECONDS,
    ENDPOINT,
    HARD_MAX_PAGES,
    HARD_MAX_ROWS_PER_COUNTRY,
    MAX_ATTEMPTS,
    MAX_PAGE_SIZE,
    MIN_REQUEST_INTERVAL_SECONDS,
    PREFIX_TO_COUNTRY,
    REQUEST_TIMEOUT_SECONDS,
    TABLE,
    USER_AGENT,
)

TRANSIENT_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
MAX_RESPONSE_BYTES = 400_000_000  # a page of 50,000 rows is about 13 MB; this only stops a runaway body
_ALLOWED_HOST = "discodata.eea.europa.eu"

SELECT_LIST = (
    "UID, season, bathingWaterIdentifier, sampleDate, escherichiaColiValue, intestinalEnterococciValue, "
    "escherichiaColiStatus, intestinalEnterococciStatus, sampleStatus, metadata_observationStatus, "
    "CASE WHEN remarks IS NULL THEN 0 ELSE 1 END AS hasRemarks"
)
PAGE_QUERY_TEMPLATE = (
    "SELECT TOP {page_size} " + SELECT_LIST + " FROM " + TABLE
    + " WHERE bathingWaterIdentifier LIKE '{prefix}%' AND UID > {after_uid} ORDER BY UID"
)
COUNT_QUERY_TEMPLATE = "SELECT COUNT(*) AS n FROM " + TABLE + " WHERE bathingWaterIdentifier LIKE '{prefix}%'"


class DiscodataError(RuntimeError):
    """The service refused a query, or kept failing after the allowed retries, or returned something unusable."""


class TransientFetchError(Exception):
    """A failure worth retrying (raised by a fetcher). ``retry_after`` is the service's own wait, in seconds, when given."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


Fetcher = Callable[[str, float], bytes]


def _check_prefix(prefix: str) -> str:
    if prefix not in PREFIX_TO_COUNTRY:
        raise ValueError(f"unknown identifier prefix {prefix!r}; known: {sorted(PREFIX_TO_COUNTRY)}")
    return prefix


def page_query(prefix: str, after_uid: int, page_size: int) -> str:
    """The keyset page query for one identifier prefix. Only validated constants and integers enter the text."""
    if isinstance(after_uid, bool) or not isinstance(after_uid, int) or after_uid < 0:
        raise ValueError("after_uid must be a non-negative integer")
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be an integer from 1 to {MAX_PAGE_SIZE}")
    return PAGE_QUERY_TEMPLATE.format(page_size=page_size, prefix=_check_prefix(prefix), after_uid=after_uid)


def count_query(prefix: str) -> str:
    return COUNT_QUERY_TEMPLATE.format(prefix=_check_prefix(prefix))


def query_url(sql: str, page_size: int) -> str:
    """``<endpoint>?query=<sql>&p=1&nrOfHits=<page_size>``: the format the service documents."""
    params = urllib.parse.urlencode({"query": sql, "p": 1, "nrOfHits": page_size}, quote_via=urllib.parse.quote)
    return f"{ENDPOINT}?{params}"


def urllib_fetch(url: str, timeout: float) -> bytes:
    """One GET with the standard library. Maps transport failures and transient HTTP statuses to ``TransientFetchError``."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != _ALLOWED_HOST:
        raise DiscodataError("refusing to fetch anything but the Discodata endpoint over https")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body: bytes = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in TRANSIENT_STATUSES:
            retry = error.headers.get("Retry-After") if error.headers else None
            wait = float(retry) if retry and retry.strip().isdigit() else None
            raise TransientFetchError(f"HTTP {error.code}", wait) from error
        raise DiscodataError(f"the service answered HTTP {error.code}") from error
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        raise TransientFetchError(f"{type(error).__name__}") from error
    if len(body) > MAX_RESPONSE_BYTES:
        raise DiscodataError("the reply is larger than the safety bound; use a smaller page size")
    return body


def parse_rows(body: bytes) -> list[dict[str, Any]]:
    """The ``results`` of a reply. A body that is not JSON or has no ``results`` is transient; ``errors`` is a refusal."""
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise TransientFetchError("the reply is not valid JSON") from error
    if not isinstance(data, dict):
        raise TransientFetchError("the reply is not a JSON object")
    if "errors" in data:
        errors = data["errors"] if isinstance(data["errors"], list) else [data["errors"]]
        detail = "; ".join(
            f"{item.get('error')} (code {item.get('errorcode')})" if isinstance(item, dict) else str(item) for item in errors
        )
        coded = any(isinstance(item, dict) and item.get("errorcode") is not None for item in errors)
        if not coded:
            # Observed 2026-10-03: ``{"errors": [{"error": "Service currently offline"}]}`` with no error code, both for a
            # request with ``p`` but without ``nrOfHits`` (a malformed request the build never sends) and, by its wording,
            # for a real outage. Without a code the reply is treated as transient: retried, then reported.
            raise TransientFetchError(f"the service reported an error without a code: {detail[:200]}")
        raise DiscodataError(f"the service refused the query: {detail[:300]}")
    rows = data.get("results")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise TransientFetchError("the reply has no usable 'results' list")
    return rows


@dataclass
class FetchStats:
    """What a run observed about the service (kept in the store provenance)."""

    requests: int = 0
    retries: int = 0
    transient_errors: list[str] = field(default_factory=list)
    bytes_received: int = 0
    seconds_waiting: float = 0.0
    max_rows_in_a_reply: int = 0
    max_reply_bytes: int = 0
    short_pages_before_end: int = 0  # a page smaller than requested that was NOT the last (would mean a row cap)

    def as_dict(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "transient_errors": self.transient_errors[:20],
            "bytes_received": self.bytes_received,
            "seconds_waiting": round(self.seconds_waiting, 1),
            "max_rows_in_a_reply": self.max_rows_in_a_reply,
            "max_reply_bytes": self.max_reply_bytes,
            "short_pages_before_end": self.short_pages_before_end,
        }


class DiscodataClient:
    """Paced, retrying, read-only client. ``fetch`` and ``sleep`` are injectable for tests."""

    def __init__(
        self,
        fetch: Fetcher = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        min_interval: float = MIN_REQUEST_INTERVAL_SECONDS,
        max_attempts: int = MAX_ATTEMPTS,
        timeout: float = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        self._fetch, self._sleep, self._clock = fetch, sleep, clock
        self.min_interval = max(0.0, float(min_interval))
        self.max_attempts = max(1, int(max_attempts))
        self.timeout = float(timeout)
        self.stats = FetchStats()
        self._last_request: float | None = None
        self.reached_end = False

    def _pace(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
                self.stats.seconds_waiting += wait
        self._last_request = self._clock()

    def query(self, sql: str, page_size: int) -> list[dict[str, Any]]:
        """Run one query and return its rows; retry transient failures with exponential backoff, then give up."""
        url = query_url(sql, page_size)
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            self.stats.requests += 1
            try:
                body = self._fetch(url, self.timeout)
                rows = parse_rows(body)
            except TransientFetchError as error:
                last_error = str(error)
                self.stats.transient_errors.append(last_error)
                if attempt == self.max_attempts:
                    break
                self.stats.retries += 1
                delay = min(BACKOFF_CAP_SECONDS, BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))
                if error.retry_after is not None:
                    delay = min(BACKOFF_CAP_SECONDS, max(delay, error.retry_after))
                self._sleep(delay)
                self.stats.seconds_waiting += delay
                self._last_request = self._clock()
                continue
            self.stats.bytes_received += len(body)
            self.stats.max_reply_bytes = max(self.stats.max_reply_bytes, len(body))
            self.stats.max_rows_in_a_reply = max(self.stats.max_rows_in_a_reply, len(rows))
            return rows
        raise DiscodataError(f"the service kept failing after {self.max_attempts} attempts (last: {last_error})")

    def count(self, prefix: str) -> int:
        """The number of rows the service holds for one identifier prefix (a sanity check of the extraction)."""
        rows = self.query(count_query(prefix), 1)
        value = rows[0].get("n") if len(rows) == 1 else None
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise DiscodataError("the count query returned something that is not a count")
        return value

    def iter_pages(
        self, prefix: str, page_size: int, *, after_uid: int = 0, max_pages: int | None = None
    ) -> Iterator[list[dict[str, Any]]]:
        """Keyset pages of one prefix after ``after_uid``, until an empty page (the end) or ``max_pages`` pages.

        ``reached_end`` is True after the loop when an empty page was seen (the data is complete), False when
        ``max_pages`` stopped it. The service must honour ``ORDER BY UID`` and ``UID > after``: a page whose UIDs do not
        strictly increase and stay above ``after`` raises ``DiscodataError`` instead of silently duplicating or
        skipping rows. A page smaller than requested is NOT taken as the end (a silent row cap would look the same);
        only an empty page ends the data, and a short page followed by more rows is counted in the stats.
        """
        self.reached_end = False
        limit = HARD_MAX_PAGES if max_pages is None else min(max_pages, HARD_MAX_PAGES)
        fetched = rows_seen = 0
        previous_short = False
        while fetched < limit:
            rows = self.query(page_query(prefix, after_uid, page_size), page_size)
            if not rows:
                self.reached_end = True
                return
            if previous_short:
                self.stats.short_pages_before_end += 1
            fetched += 1
            rows_seen += len(rows)
            if rows_seen > HARD_MAX_ROWS_PER_COUNTRY:
                raise DiscodataError("more rows than the safety bound for one country; refusing to continue")
            uids: list[int] = []
            for row in rows:
                uid = row.get("UID")
                if isinstance(uid, bool) or not isinstance(uid, int):
                    raise DiscodataError("a row without an integer UID; the keyset cannot continue")
                uids.append(uid)
            if uids[0] <= after_uid or any(b <= a for a, b in zip(uids, uids[1:], strict=False)):
                raise DiscodataError("the service did not return rows in strictly increasing UID order")
            previous_short = len(rows) < page_size
            yield rows
            after_uid = uids[-1]
