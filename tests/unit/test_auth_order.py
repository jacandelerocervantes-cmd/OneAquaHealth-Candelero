"""The access key is checked BEFORE the rate limit (security audit F2).

An unauthenticated flood must not use up the bucket of callers who hold the right key. Failed attempts have their own
small limiter, and the 401 text gives no hint about the key.
"""
import pytest
from fastapi.testclient import TestClient

import oah.api.deps as deps_module
from oah.api import app as app_module
from oah.api.rate_limit import RateLimiter

KEY = "k" * 40
GOOD = {"X-API-Key": KEY}
PATH = "/risk/Loc-Almyros"  # a cheap synthetic route behind the key


@pytest.fixture
def client():
    return TestClient(app_module.app)


@pytest.fixture
def keyed(monkeypatch):
    """A configured key, a tight authenticated bucket (3) and a separate failure bucket (generous by default)."""
    monkeypatch.setenv("OAH_API_KEY", KEY)
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    authenticated = RateLimiter(3, 60.0)
    failures = RateLimiter(10_000, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: authenticated)
    monkeypatch.setattr(deps_module, "get_auth_failure_limiter", lambda: failures)
    return authenticated, failures


def test_a_flood_of_wrong_keys_does_not_exhaust_the_authenticated_bucket(client, keyed):
    for attempt in range(50):
        assert client.get(PATH, headers={"X-API-Key": f"guess-{attempt}"}).status_code == 401
    assert client.get(PATH).status_code == 401  # no key at all counts as a failure too
    # all three authenticated requests of the bucket are still available
    assert [client.get(PATH, headers=GOOD).status_code for _ in range(3)] == [200, 200, 200]


def test_correct_key_requests_are_still_limited_at_the_configured_rate(client, keyed):
    statuses = [client.get(PATH, headers=GOOD).status_code for _ in range(5)]
    assert statuses == [200, 200, 200, 429, 429]
    limited = client.get(PATH, headers=GOOD)
    assert limited.status_code == 429 and "Retry-After" in limited.headers


def test_failed_attempts_have_their_own_bound_and_never_touch_the_authenticated_bucket(client, keyed, monkeypatch):
    authenticated, _ = keyed
    tiny = RateLimiter(2, 60.0)
    monkeypatch.setattr(deps_module, "get_auth_failure_limiter", lambda: tiny)
    statuses = [client.get(PATH, headers={"X-API-Key": "nope"}).status_code for _ in range(5)]
    assert statuses == [401, 401, 429, 429, 429]
    refused = client.get(PATH, headers={"X-API-Key": "nope"})
    assert refused.headers["Retry-After"] == "60"
    assert KEY not in refused.text and "nope" not in refused.text
    # the authenticated bucket was never charged, and a correct key is not refused because failures are throttled
    assert authenticated.allow("probe-untouched") is True
    assert client.get(PATH, headers=GOOD).status_code == 200


def test_the_401_is_identical_for_a_missing_and_a_wrong_key_and_carries_no_hint(client, keyed):
    missing = client.get(PATH)
    wrong = client.get(PATH, headers={"X-API-Key": KEY[:-1]})  # one character short of the real key
    long_wrong = client.get(PATH, headers={"X-API-Key": "x" * 200})
    assert missing.status_code == wrong.status_code == long_wrong.status_code == 401
    assert missing.json() == wrong.json() == long_wrong.json()
    text = missing.text.lower()
    assert KEY not in text and "length" not in text and "characters" not in text and "short" not in text
    assert "www-authenticate" not in {name.lower() for name in missing.headers}


def test_a_non_ascii_key_is_a_401_not_a_crash(client, keyed):
    assert client.get(PATH, headers={"X-API-Key": "clé-inconnue".encode("latin-1")}).status_code == 401


def test_health_is_unaffected_by_failures_and_by_exhausted_buckets(client, keyed, monkeypatch):
    monkeypatch.setattr(deps_module, "get_auth_failure_limiter", lambda: RateLimiter(1, 60.0))
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(1, 60.0))
    for _ in range(5):
        client.get(PATH, headers={"X-API-Key": "nope"})
    for _ in range(3):
        client.get(PATH, headers=GOOD)
    assert [client.get("/health").status_code for _ in range(5)] == [200] * 5


def test_without_a_key_configured_the_routes_stay_closed_and_no_bucket_is_used(client, monkeypatch):
    monkeypatch.delenv("OAH_API_KEY", raising=False)
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    authenticated, failures = RateLimiter(1, 60.0), RateLimiter(1, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: authenticated)
    monkeypatch.setattr(deps_module, "get_auth_failure_limiter", lambda: failures)
    assert [client.get(PATH).status_code for _ in range(4)] == [503] * 4
    assert authenticated.allow("a") is True and failures.allow("a") is True  # nothing was charged


def test_the_local_demo_flag_still_uses_the_normal_limiter_only(client, monkeypatch):
    monkeypatch.delenv("OAH_API_KEY", raising=False)
    monkeypatch.setenv("OAH_INSECURE_NO_AUTH", "1")
    limiter = RateLimiter(2, 60.0)
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: limiter)
    assert [client.get(PATH).status_code for _ in range(3)] == [200, 200, 429]


def test_the_failure_limiter_is_per_client_address(client, keyed, monkeypatch):
    # two peers behind one limiter: one exhausting its failures does not lock the other out of a 401 (or a 200)
    failures = RateLimiter(1, 60.0)
    monkeypatch.setattr(deps_module, "get_auth_failure_limiter", lambda: failures)
    assert failures.allow("203.0.113.9") is True
    assert failures.allow("203.0.113.9") is False
    assert client.get(PATH, headers={"X-API-Key": "nope"}).status_code == 401  # testclient peer is another key
