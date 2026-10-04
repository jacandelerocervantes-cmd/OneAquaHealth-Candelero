"""Client address behind Cloud Run (OAH_TRUSTED_PROXY_HOPS) and the optional end-user token (security audit F3, backend part)."""
import pytest
from fastapi import HTTPException
from hypothesis import given
from hypothesis import strategies as st
from starlette.requests import Request

import oah.api.deps as deps_module
from oah import config
from oah.api.client_ip import END_USER_HEADER, client_key, end_user_token, rate_key
from oah.api.llm_guard import ChatSpendGuard, LLMSpendGuard

PEER = "10.0.0.1"


# --- OAH_TRUSTED_PROXY_HOPS -----------------------------------------------------------------------------------------
def test_the_default_is_disabled_and_the_header_is_ignored():
    assert config.load_settings({}).trusted_proxy_hops == 0
    assert client_key(PEER, "198.51.100.7", (), 0) == PEER
    assert client_key(PEER, "198.51.100.7", ()) == PEER  # the old call shape is unchanged


def test_one_hop_takes_the_last_entry():
    assert client_key(PEER, "198.51.100.7", (), 1) == "198.51.100.7"
    assert client_key(PEER, "1.1.1.1, 198.51.100.7", (), 1) == "198.51.100.7"


def test_spoofed_leading_entries_are_ignored():
    chain = "6.6.6.6, 7.7.7.7, 198.51.100.7"
    assert client_key(PEER, chain, (), 1) == "198.51.100.7"
    assert client_key(PEER, chain, (), 2) == "7.7.7.7"  # two hops: the entry the outer proxy recorded
    assert client_key(PEER, chain, (), 3) == "6.6.6.6"


@pytest.mark.parametrize(
    "chain",
    [
        None,
        "",
        "   ",
        "not-an-address",
        "198.51.100.7, garbage",  # the entry that counts is malformed
        "198.51.100.7,",  # an empty last entry
        "unknown",
        "198.51.100.7:8080",  # a port is not an address
    ],
)
def test_a_malformed_chain_falls_back_to_the_peer(chain):
    assert client_key(PEER, chain, (), 1) == PEER


def test_fewer_entries_than_hops_falls_back_to_the_peer():
    assert client_key(PEER, "198.51.100.7", (), 2) == PEER
    assert client_key(PEER, "198.51.100.7", (), 5) == PEER


def test_ipv6_entries_are_accepted():
    assert client_key(PEER, "2001:db8::1", (), 1) == "2001:db8::1"


def test_a_missing_peer_is_unknown_even_with_hops():
    assert client_key(None, "198.51.100.7", (), 1) == "unknown"


def test_a_peer_listed_in_trusted_proxies_keeps_the_address_based_rule():
    assert client_key(PEER, "198.51.100.7, 10.0.0.1", (PEER,), 1) == "198.51.100.7"  # the proxy itself is skipped
    assert client_key("10.0.0.9", "198.51.100.7", (PEER,), 1) == "198.51.100.7"  # another peer: the hops rule


@given(st.text(max_size=80), st.integers(min_value=0, max_value=5))
def test_the_key_is_always_the_peer_or_a_valid_address(chain, hops):
    import ipaddress

    result = client_key(PEER, chain, (), hops)
    assert result == PEER or ipaddress.ip_address(result)


def test_the_hops_setting_is_validated():
    assert config.load_settings({"OAH_TRUSTED_PROXY_HOPS": "1"}).trusted_proxy_hops == 1
    assert config.load_settings({"OAH_TRUSTED_PROXY_HOPS": " 2 "}).trusted_proxy_hops == 2
    assert config.load_settings({"OAH_TRUSTED_PROXY_HOPS": ""}).trusted_proxy_hops == 0
    assert config.load_settings({"OAH_TRUSTED_PROXY_HOPS": "0"}).trusted_proxy_hops == 0
    for bad in ("-1", "6", "one", "1.5", "999"):
        with pytest.raises(ValueError, match="OAH_TRUSTED_PROXY_HOPS"):
            config.load_settings({"OAH_TRUSTED_PROXY_HOPS": bad})


# --- the end-user token -----------------------------------------------------------------------------------------------
GOOD_TOKEN = "AbCdEf0123456789_-xyz"


@pytest.mark.parametrize("value", [GOOD_TOKEN, "a" * 16, "A" * 64, "0123456789abcdef"])
def test_a_token_matching_the_pattern_is_accepted(value):
    assert end_user_token(value) == value


@pytest.mark.parametrize(
    "value",
    [None, "", "short", "a" * 15, "a" * 65, "has space in it 123", "semi;colon;colon1234", "new\nline1234567890", "ünïcödé-token-1234", "<script>alert(1)", "a" * 16 + "\n", "../../etc/passwd1"],
)
def test_anything_else_is_ignored(value):
    assert end_user_token(value) is None


@given(st.text(max_size=100))
def test_the_token_is_never_changed_only_accepted_or_dropped(value):
    assert end_user_token(value) in (None, value)


def test_the_rate_key_adds_the_token_without_replacing_the_address():
    assert rate_key("203.0.113.9", None) == "203.0.113.9"
    assert rate_key("203.0.113.9", GOOD_TOKEN) == f"203.0.113.9|u:{GOOD_TOKEN}"


def _request(headers: dict[str, str], peer: str = PEER) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/chat",
            "headers": [(name.lower().encode(), value.encode("latin-1")) for name, value in headers.items()],
            "client": (peer, 5000),
        }
    )


def _chat_guard(per_minute: int) -> ChatSpendGuard:
    return ChatSpendGuard(per_minute, 100, 60.0, 6)


def test_visitors_with_different_tokens_have_their_own_chat_bucket(monkeypatch):
    guard = _chat_guard(1)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: guard)
    first = _request({END_USER_HEADER: "a" * 20})
    second = _request({END_USER_HEADER: "b" * 20})
    deps_module.enforce_chat_rate(first)
    deps_module.enforce_chat_rate(second)  # another visitor behind the same proxy address: not limited by the first
    with pytest.raises(HTTPException) as limited:
        deps_module.enforce_chat_rate(first)
    assert limited.value.status_code == 429


def test_without_a_token_or_with_an_invalid_one_the_host_bucket_is_shared(monkeypatch):
    guard = _chat_guard(1)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: guard)
    deps_module.enforce_chat_rate(_request({}))
    for headers in ({}, {END_USER_HEADER: "bad token!"}, {END_USER_HEADER: "x"}):
        with pytest.raises(HTTPException) as limited:
            deps_module.enforce_chat_rate(_request(headers))
        assert limited.value.status_code == 429


def test_the_explanation_limiter_uses_the_token_too(monkeypatch):
    guard = LLMSpendGuard(1, 100, 60.0)
    monkeypatch.setattr(deps_module, "get_llm_guard", lambda: guard)
    deps_module.enforce_explain_rate(_request({END_USER_HEADER: "a" * 20}))
    deps_module.enforce_explain_rate(_request({END_USER_HEADER: "b" * 20}))
    with pytest.raises(HTTPException):
        deps_module.enforce_explain_rate(_request({END_USER_HEADER: "a" * 20}))


def test_the_token_does_not_touch_the_general_limiter_key(monkeypatch):
    # the general limiter (every route) is keyed by the address only: a token is a fairness aid for chat and explain, nothing else
    seen = []

    class _Spy:
        def allow(self, key):
            seen.append(key)
            return True

    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: _Spy())
    deps_module.enforce_rate_limit(_request({END_USER_HEADER: GOOD_TOKEN}))
    assert seen == [PEER]


def test_the_configured_hops_are_used_by_the_dependencies(monkeypatch):
    monkeypatch.setattr(deps_module, "settings", config.load_settings({"OAH_TRUSTED_PROXY_HOPS": "1"}))
    guard = _chat_guard(1)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: guard)
    deps_module.enforce_chat_rate(_request({"x-forwarded-for": "6.6.6.6, 198.51.100.7"}))
    deps_module.enforce_chat_rate(_request({"x-forwarded-for": "6.6.6.6, 198.51.100.8"}))  # another real client, same spoofed lead
    with pytest.raises(HTTPException):
        deps_module.enforce_chat_rate(_request({"x-forwarded-for": "9.9.9.9, 198.51.100.7"}))  # same client, other spoofed lead
