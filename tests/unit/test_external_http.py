"""The hardened GET client: allow-list, JSON only, size cap, redirects, retries, 429, timeouts. Scripted transport only."""
from __future__ import annotations

import httpx
import pytest

from oah.external import constants as c
from oah.external.http import ExternalError, ExternalHttp, default_client
from external_fakes import Router, json_response, make_http

HOST = c.ARCHIVE_HOST
PATH = "/v1/archive"


def get(router: Router, *, retries: int = 2, params: list[tuple[str, str]] | None = None, max_bytes: int = 1024, sleeps: list[float] | None = None,
        host: str = HOST, path: str = PATH, before=None):
    http = make_http(router, retries=retries, sleeps=sleeps)
    return http.get_json(host, path, params if params is not None else [("a", "1")], max_bytes=max_bytes, before_attempt=before)


def test_success_sends_user_agent_json_accept_and_the_parameters() -> None:
    router = Router()
    router.on(HOST, lambda request: json_response({"ok": 1}))
    assert get(router, params=[("a", "1"), ("daily", "x,y"), ("taxonKey", "1"), ("taxonKey", "2")]) == {"ok": 1}
    request = router.requests[0]
    assert request.url.scheme == "https" and request.url.host == HOST and request.url.path == PATH
    assert request.headers["user-agent"] == "OneAquaHealth/0.1 (test)" and request.headers["accept"] == "application/json"
    assert request.method == "GET"
    assert router.params()["taxonKey"] == ["1", "2"] and router.params()["daily"] == ["x,y"]


@pytest.mark.parametrize("host", ["example.org", "api.open-meteo.com", "archive-api.open-meteo.com.evil.test", "localhost", "127.0.0.1", "ARCHIVE-API.open-meteo.com"])
def test_a_host_outside_the_allow_list_is_refused_before_any_request(host: str) -> None:
    router = Router()
    with pytest.raises(ExternalError) as caught:
        get(router, host=host)
    assert caught.value.reason == c.REASON_BLOCKED and router.requests == []


@pytest.mark.parametrize("path", ["/v2/archive", "v1/archive", "/v1/../etc", "/v1//x", "/v1/archive?x=1", "/v1/a b", "/v1/", "/v1/" + "a" * 130])
def test_a_path_outside_the_pattern_is_refused(path: str) -> None:
    router = Router()
    with pytest.raises(ExternalError) as caught:
        get(router, path=path)
    assert caught.value.reason == c.REASON_BLOCKED and router.requests == []


def test_parameters_are_checked() -> None:
    router = Router()
    for bad in ([("bad name", "1")], [("a", "line\nbreak")], [("a", "x" * 2000)], [("a", "1")] * 41, [("1a", "x")]):
        with pytest.raises(ExternalError) as caught:
            get(router, params=bad)
        assert caught.value.reason == c.REASON_BLOCKED
    assert router.requests == []


def test_redirect_to_another_host_is_refused() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(302, headers={"location": "https://example.org/steal"}))
    with pytest.raises(ExternalError) as caught:
        get(router)
    assert caught.value.reason == c.REASON_REDIRECT and router.count() == 1


@pytest.mark.parametrize("location", ["http://archive-api.open-meteo.com/v1/archive", "https://user:pw@archive-api.open-meteo.com/v1/archive",
                                      "https://archive-api.open-meteo.com:8443/v1/archive", "https://flood-api.open-meteo.com/v1/flood", ""])
def test_unsafe_redirect_targets_are_refused(location: str) -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(301, headers={"location": location} if location else {}))
    with pytest.raises(ExternalError) as caught:
        get(router)
    assert caught.value.reason == c.REASON_REDIRECT


def test_redirect_on_the_same_host_is_followed_a_bounded_number_of_times() -> None:
    router = Router()
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] <= 2:
            return httpx.Response(307, headers={"location": "/v1/archive"})
        return json_response({"done": True})

    router.on(HOST, handler)
    assert get(router) == {"done": True} and router.count() == 3

    loop = Router()
    loop.on(HOST, lambda request: httpx.Response(302, headers={"location": "/v1/archive"}))
    with pytest.raises(ExternalError) as caught:
        get(loop)
    assert caught.value.reason == c.REASON_REDIRECT and loop.count() == 3


def test_a_non_json_content_type_is_refused() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(200, content=b"<html>hello</html>", headers={"content-type": "text/html"}))
    with pytest.raises(ExternalError) as caught:
        get(router)
    assert caught.value.reason == c.REASON_BAD_RESPONSE


def test_a_vendor_json_content_type_is_accepted() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(200, content=b'{"a": 1}', headers={"content-type": "application/vnd.x+json; charset=utf-8"}))
    assert get(router) == {"a": 1}


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b'"text"', b"{", b"[" * 5000])
def test_malformed_or_non_object_json_is_a_bad_response(body: bytes) -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(200, content=body, headers={"content-type": "application/json"}))
    with pytest.raises(ExternalError) as caught:
        get(router, max_bytes=10_000)
    assert caught.value.reason == c.REASON_BAD_RESPONSE and router.count() == 1  # never retried


def test_an_oversized_body_is_refused_even_without_a_content_length() -> None:
    router = Router()
    big = b'{"x": "' + b"a" * 5000 + b'"}'
    router.on(HOST, lambda request: httpx.Response(200, content=big, headers={"content-type": "application/json"}))
    with pytest.raises(ExternalError) as caught:
        get(router, max_bytes=1000)
    assert caught.value.reason == c.REASON_TOO_LARGE


def test_an_oversized_declared_length_is_refused_early() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(200, content=b"{}", headers={"content-type": "application/json", "content-length": "99999999"}))
    with pytest.raises(ExternalError) as caught:
        get(router, max_bytes=1000)
    assert caught.value.reason == c.REASON_TOO_LARGE


def test_429_is_not_retried_and_carries_retry_after() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(429, headers={"retry-after": "42"}))
    with pytest.raises(ExternalError) as caught:
        get(router, retries=3)
    assert caught.value.reason == c.REASON_RATE_LIMITED and caught.value.retry_after == 42.0 and router.count() == 1


@pytest.mark.parametrize("header, expected", [("99999", 600.0), ("-5", 0.0), ("abc", None), ("nan", None)])
def test_retry_after_is_clamped_or_dropped(header: str, expected: float | None) -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(429, headers={"retry-after": header}))
    with pytest.raises(ExternalError) as caught:
        get(router)
    assert caught.value.retry_after == expected


def test_a_4xx_is_not_retried_but_a_5xx_is_retried_with_backoff_then_fails() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(400, content=b'{"error": true}', headers={"content-type": "application/json"}))
    with pytest.raises(ExternalError) as caught:
        get(router)
    assert caught.value.reason == c.REASON_HTTP and router.count() == 1

    flaky = Router()
    flaky.on(HOST, lambda request: httpx.Response(503))
    sleeps: list[float] = []
    with pytest.raises(ExternalError) as caught_again:
        get(flaky, retries=2, sleeps=sleeps)
    assert caught_again.value.reason == c.REASON_HTTP and flaky.count() == 3 and sleeps == [0.25, 0.5]


def test_a_5xx_followed_by_success_is_a_success() -> None:
    router = Router()
    answers = [httpx.Response(502), json_response({"v": 7})]
    router.on(HOST, lambda request: answers.pop(0))
    assert get(router) == {"v": 7} and router.count() == 2


def test_timeout_and_network_errors_are_retried_then_reported() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    slow = Router()
    slow.on(HOST, timeout)
    with pytest.raises(ExternalError) as caught:
        get(slow, retries=2)
    assert caught.value.reason == c.REASON_TIMEOUT and slow.count() == 3

    down = Router()
    down.on(HOST, refused)
    with pytest.raises(ExternalError) as caught_down:
        get(down, retries=1)
    assert caught_down.value.reason == c.REASON_NETWORK and down.count() == 2


def test_before_attempt_is_called_for_every_attempt_and_can_stop_the_call() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(503))
    charged: list[int] = []
    with pytest.raises(ExternalError):
        get(router, retries=2, before=lambda: charged.append(1))
    assert len(charged) == 3

    stopped = Router()
    stopped.on(HOST, lambda request: json_response({}))

    def refuse() -> None:
        raise ExternalError(c.REASON_BUDGET, "no budget")

    with pytest.raises(ExternalError) as caught:
        get(stopped, before=refuse)
    assert caught.value.reason == c.REASON_BUDGET and stopped.requests == []


def test_a_non_200_success_status_is_unexpected() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(204))
    with pytest.raises(ExternalError) as caught:
        get(router)
    assert caught.value.reason == c.REASON_BAD_RESPONSE


def test_the_error_text_carries_no_url_or_coordinates() -> None:
    router = Router()
    router.on(HOST, lambda request: httpx.Response(500))
    with pytest.raises(ExternalError) as caught:
        get(router, retries=0, params=[("latitude", "45.07"), ("longitude", "7.69")])
    text = str(caught.value) + caught.value.detail
    assert "45.07" not in text and "://" not in text and HOST not in text and "7.69" not in text


def test_default_client_does_not_follow_redirects_and_negative_retries_mean_none() -> None:
    client = default_client()
    try:
        assert client.follow_redirects is False
    finally:
        client.close()
    router = Router()
    router.on(HOST, lambda request: httpx.Response(503))
    http = ExternalHttp("ua", 1.0, -4, client_factory=lambda: httpx.Client(transport=httpx.MockTransport(router)), sleep=lambda s: None)
    with pytest.raises(ExternalError):
        http.get_json(HOST, PATH, [])
    assert router.count() == 1
