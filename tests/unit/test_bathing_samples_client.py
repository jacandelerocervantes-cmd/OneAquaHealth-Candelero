"""The Discodata client: query text, retries with backoff, pacing, keyset paging, bad replies. A scripted fake HTTP layer; no network.

All rows are SYNTHETIC (``samples_fixtures``).
"""

from __future__ import annotations

import io
import json
import socket
import urllib.error
import urllib.request
from typing import Any

import pytest
from samples_fixtures import FakeDiscodata, make_client, raw_row, transient

from oah.bathing_samples import client as client_module
from oah.bathing_samples.client import (
    DiscodataClient,
    DiscodataError,
    TransientFetchError,
    count_query,
    page_query,
    parse_rows,
    query_url,
    urllib_fetch,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_a: Any, **_k: Any):
        raise AssertionError("a test must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)


def _rows(count: int, prefix: str = "IT") -> list[dict[str, Any]]:
    return [raw_row(100 + index, f"{prefix}SYN001", "2020-06-01", (index + 1, None), (index + 1, None)) for index in range(count)]


# --- the query text ---------------------------------------------------------------------------------------------------


def test_the_page_query_is_a_keyset_with_no_offset_and_a_deterministic_order():
    text = page_query("EL", 123, 500)
    assert text.startswith("SELECT TOP 500 UID, season, bathingWaterIdentifier, sampleDate")
    assert "[WISE_BWD].[latest].[timeseries_MonitoringResult]" in text
    assert "LIKE 'EL%' AND UID > 123 ORDER BY UID" in text
    assert "OFFSET" not in text.upper() and "FETCH" not in text.upper()
    assert "remarks IS NULL" in text and "remarks," not in text  # only whether a remark exists is read, never its text


@pytest.mark.parametrize("prefix", ["", "el", "EL' OR 1=1 --", "ELX", "GR", "DE", "E%", None, 5])
def test_an_unknown_or_hostile_prefix_never_reaches_the_query(prefix):
    with pytest.raises(ValueError):
        page_query(prefix, 0, 10)
    with pytest.raises(ValueError):
        count_query(prefix)


@pytest.mark.parametrize("after", [-1, True, "5; DROP TABLE x", 1.5, None])
def test_the_keyset_position_must_be_a_plain_non_negative_integer(after):
    with pytest.raises(ValueError):
        page_query("IT", after, 10)


@pytest.mark.parametrize("size", [0, -5, 50_001, True, "10", 2.5])
def test_the_page_size_is_bounded(size):
    with pytest.raises(ValueError):
        page_query("IT", 0, size)


def test_the_url_uses_the_documented_format_and_the_fixed_host():
    url = query_url(page_query("IT", 0, 20), 20)
    assert url.startswith("https://discodata.eea.europa.eu/sql?query=")
    assert url.endswith("&p=1&nrOfHits=20")
    assert " " not in url and "'" not in url  # percent-encoded


def test_only_the_discodata_host_over_https_can_be_fetched():
    for url in ("http://discodata.eea.europa.eu/sql?query=x", "https://example.invalid/sql?query=x", "file:///etc/passwd"):
        with pytest.raises(DiscodataError, match="refusing"):
            urllib_fetch(url, 1.0)


def test_http_failures_map_to_transient_or_permanent_errors(monkeypatch):
    def raising(error: BaseException):
        def opener(*_a: Any, **_k: Any):
            raise error

        return opener

    url = query_url(count_query("IT"), 1)
    headers = {"Retry-After": "7"}
    monkeypatch.setattr(urllib.request, "urlopen", raising(urllib.error.HTTPError(url, 503, "busy", headers, io.BytesIO(b""))))
    with pytest.raises(TransientFetchError) as caught:
        urllib_fetch(url, 1.0)
    assert caught.value.retry_after == 7.0
    monkeypatch.setattr(urllib.request, "urlopen", raising(urllib.error.HTTPError(url, 404, "nope", {}, io.BytesIO(b""))))
    with pytest.raises(DiscodataError, match="HTTP 404"):
        urllib_fetch(url, 1.0)
    monkeypatch.setattr(urllib.request, "urlopen", raising(urllib.error.URLError("down")))
    with pytest.raises(TransientFetchError):
        urllib_fetch(url, 1.0)
    monkeypatch.setattr(urllib.request, "urlopen", raising(TimeoutError()))
    with pytest.raises(TransientFetchError):
        urllib_fetch(url, 1.0)


def test_the_request_carries_a_descriptive_user_agent_and_no_credentials(monkeypatch):
    seen: dict[str, Any] = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *_a: Any) -> None:
            return None

        def read(self, _limit: int) -> bytes:
            return b'{"results": []}'

    def opener(request: urllib.request.Request, timeout: float):
        seen["headers"] = dict(request.header_items())
        seen["timeout"] = timeout
        return Reply()

    monkeypatch.setattr(urllib.request, "urlopen", opener)
    assert urllib_fetch(query_url(count_query("IT"), 1), 12.0) == b'{"results": []}'
    assert seen["headers"]["User-agent"].startswith("OneAquaHealth-store-build/")
    assert set(seen["headers"]) <= {"User-agent", "Accept"} and seen["timeout"] == 12.0


# --- replies ----------------------------------------------------------------------------------------------------------


def test_a_reply_that_is_not_json_or_has_no_results_is_transient():
    for body in (b"<html>gateway</html>", b"", b'{"results": "x"}', b"[1, 2]", b'{"rows": []}', b'{"results": [1]}', b'{"results": [{"a": 1}'):
        with pytest.raises(TransientFetchError):
            parse_rows(body)


def test_an_error_reply_is_a_refusal_not_a_retry():
    body = json.dumps({"errors": [{"error": "Your query is not allowed execution...", "errorcode": 10002}]}).encode()
    with pytest.raises(DiscodataError, match="10002"):
        parse_rows(body)
    calls: list[str] = []

    def fetch(url: str, timeout: float) -> bytes:
        calls.append(url)
        return body

    with pytest.raises(DiscodataError):
        make_client(fetch).query(page_query("IT", 0, 10), 10)
    assert len(calls) == 1  # never retried


def test_an_error_reply_without_a_code_is_transient_and_retried():
    offline = json.dumps({"errors": [{"error": "Service currently offline"}]}).encode()  # as observed 2026-10-03
    with pytest.raises(TransientFetchError, match="without a code"):
        parse_rows(offline)
    service = FakeDiscodata(_rows(2), script=[offline, offline])
    sleeps: list[float] = []
    rows = make_client(service, sleeps).query(page_query("IT", 0, 10), 10)
    assert [row["UID"] for row in rows] == [100, 101] and sleeps == [2.0, 4.0]
    always = FakeDiscodata(_rows(2), script=[offline] * 10)
    with pytest.raises(DiscodataError, match="after 5 attempts"):
        make_client(always).query(page_query("IT", 0, 10), 10)


def test_empty_results_are_a_valid_empty_page():
    assert parse_rows(b'{"results": []}') == []


# --- retries, backoff and pacing ----------------------------------------------------------------------------------------


def test_transient_failures_are_retried_with_exponential_backoff_then_succeed():
    service = FakeDiscodata(_rows(3), script=[transient(), transient("timeout"), b"<html>bad gateway</html>"])
    sleeps: list[float] = []
    client = make_client(service, sleeps)
    rows = client.query(page_query("IT", 0, 10), 10)
    assert [row["UID"] for row in rows] == [100, 101, 102]
    assert sleeps == [2.0, 4.0, 8.0]  # base 2 s, doubled after each failure
    assert client.stats.retries == 3 and client.stats.requests == 4
    assert client.stats.transient_errors[:2] == ["HTTP 503", "timeout"]


def test_the_service_retry_after_is_honoured_and_the_wait_is_capped():
    service = FakeDiscodata(_rows(1), script=[transient("HTTP 429", 30.0), transient("HTTP 429", 9999.0)])
    sleeps: list[float] = []
    make_client(service, sleeps).query(page_query("IT", 0, 10), 10)
    assert sleeps == [30.0, 60.0]  # never above the 60 s cap


def test_it_gives_up_after_the_attempt_limit_with_a_clear_error():
    service = FakeDiscodata(_rows(1), script=[transient()] * 10)
    sleeps: list[float] = []
    client = make_client(service, sleeps, max_attempts=3)
    with pytest.raises(DiscodataError, match="after 3 attempts"):
        client.query(page_query("IT", 0, 10), 10)
    assert client.stats.requests == 3 and len(sleeps) == 2


def test_requests_are_paced():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    client = DiscodataClient(fetch=FakeDiscodata(_rows(1)), sleep=sleep, clock=lambda: now[0], min_interval=0.5)
    client.query(page_query("IT", 0, 10), 10)
    client.query(page_query("IT", 0, 10), 10)
    client.query(page_query("IT", 0, 10), 10)
    assert sleeps == [0.5, 0.5]  # the first request goes at once; every later one waits for the interval


def test_the_count_query_checks_the_reply():
    service = FakeDiscodata(_rows(4))
    assert make_client(service).count("IT") == 4
    assert make_client(service).count("NO") == 0
    bad = FakeDiscodata(_rows(1))
    bad.counts_override["IT"] = -1
    with pytest.raises(DiscodataError, match="not a count"):
        make_client(bad).count("IT")


# --- keyset paging ----------------------------------------------------------------------------------------------------


def test_pages_follow_the_keyset_until_an_empty_page():
    service = FakeDiscodata(_rows(11))
    client = make_client(service)
    pages = list(client.iter_pages("IT", 5))
    assert [len(page) for page in pages] == [5, 5, 1]
    assert [row["UID"] for page in pages for row in page] == list(range(100, 111))
    assert client.reached_end is True
    assert any("UID > 0 " in query for query in service.queries) and any("UID > 104 " in query for query in service.queries)
    assert all("OFFSET" not in query.upper() for query in service.queries)
    assert client.stats.short_pages_before_end == 0


def test_an_empty_table_is_one_request_and_the_end():
    client = make_client(FakeDiscodata(_rows(3)))
    assert list(client.iter_pages("NO", 5)) == [] and client.reached_end is True
    assert client.stats.requests == 1


def test_a_full_last_page_still_needs_the_confirming_empty_page():
    service = FakeDiscodata(_rows(10))
    client = make_client(service)
    assert [len(page) for page in client.iter_pages("IT", 5)] == [5, 5]
    assert client.reached_end is True and client.stats.requests == 3


def test_max_pages_stops_early_and_says_the_end_was_not_reached():
    client = make_client(FakeDiscodata(_rows(30)))
    pages = list(client.iter_pages("IT", 5, max_pages=2))
    assert len(pages) == 2 and client.reached_end is False


def test_resuming_after_a_uid_continues_without_repeating_rows():
    client = make_client(FakeDiscodata(_rows(12)))
    first = [row["UID"] for page in client.iter_pages("IT", 5, after_uid=104) for row in page]
    assert first == list(range(105, 112))


def test_a_service_row_cap_is_counted_and_does_not_end_the_data_early():
    service = FakeDiscodata(_rows(12), cap=3)  # the service answers at most 3 rows although 5 were asked
    client = make_client(service)
    rows = [row["UID"] for page in client.iter_pages("IT", 5) for row in page]
    assert rows == list(range(100, 112))
    assert client.stats.short_pages_before_end == 3  # every short page except the last was followed by more rows


def test_a_service_that_ignores_the_keyset_is_detected():
    class Stuck:
        def __call__(self, url: str, timeout: float) -> bytes:
            return json.dumps({"results": _rows(3)}).encode()  # always the same rows, whatever UID > was asked

    client = make_client(Stuck())
    with pytest.raises(DiscodataError, match="strictly increasing"):
        list(client.iter_pages("IT", 5))


def test_rows_out_of_order_or_without_an_integer_uid_are_refused():
    shuffled = [raw_row(5, "ITX", "2020-06-01"), raw_row(4, "ITX", "2020-06-01")]
    with pytest.raises(DiscodataError, match="strictly increasing"):
        list(make_client(FakeDiscodata(shuffled, script=[json.dumps({"results": shuffled}).encode()])).iter_pages("IT", 5))
    odd = [{**raw_row(1, "ITX", "2020-06-01"), "UID": "7"}]
    with pytest.raises(DiscodataError, match="integer UID"):
        list(make_client(FakeDiscodata([], script=[json.dumps({"results": odd}).encode()])).iter_pages("IT", 5))


def test_the_page_count_has_a_hard_bound(monkeypatch):
    monkeypatch.setattr(client_module, "HARD_MAX_PAGES", 2)
    client = make_client(FakeDiscodata(_rows(50)))
    assert len(list(client.iter_pages("IT", 5))) == 2 and client.reached_end is False


def test_the_row_count_has_a_hard_bound(monkeypatch):
    monkeypatch.setattr(client_module, "HARD_MAX_ROWS_PER_COUNTRY", 8)
    with pytest.raises(DiscodataError, match="safety bound"):
        list(make_client(FakeDiscodata(_rows(50))).iter_pages("IT", 5))


def test_a_transient_failure_in_the_middle_of_paging_is_retried_without_losing_rows():
    service = FakeDiscodata(_rows(12), script=[None, transient(), None, None])
    client = make_client(service)
    rows = [row["UID"] for page in client.iter_pages("IT", 5) for row in page]
    assert rows == list(range(100, 112)) and client.stats.retries == 1
