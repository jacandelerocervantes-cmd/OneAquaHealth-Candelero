"""The API must not open itself when OAH_API_KEY is missing (audit finding, 2026-09-26)."""
import pytest
from fastapi.testclient import TestClient

from oah import config
from oah.api import app as app_module
import oah.api.deps as deps_module


@pytest.fixture
def client():
    return TestClient(app_module.app)


def test_without_a_key_and_without_the_local_flag_protected_routes_are_refused(client, monkeypatch):
    monkeypatch.delenv("OAH_API_KEY", raising=False)
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    response = client.get("/risk/Loc-Almyros")
    assert response.status_code == 503
    assert "OAH_API_KEY" in response.json()["detail"]
    assert client.get("/health").status_code == 200  # the health probe stays open


def test_the_explicit_local_flag_reopens_the_demo_mode(client, monkeypatch):
    monkeypatch.delenv("OAH_API_KEY", raising=False)
    monkeypatch.setenv("OAH_INSECURE_NO_AUTH", "1")
    assert client.get("/risk/Loc-Almyros").status_code != 503


def test_a_configured_key_is_enforced_and_a_non_ascii_key_is_a_401_not_a_crash(client, monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "demo-secret")
    assert client.get("/risk/Loc-Almyros").status_code == 401
    assert client.get("/risk/Loc-Almyros", headers={"X-API-Key": "wrong"}).status_code == 401
    odd = client.get("/risk/Loc-Almyros", headers={"X-API-Key": "clé-inconnue".encode("latin-1")})
    assert odd.status_code == 401
    assert client.get("/risk/Loc-Almyros", headers={"X-API-Key": "demo-secret"}).status_code != 401


def test_failed_key_attempts_are_throttled_by_their_own_limiter(client, monkeypatch):
    """Guessing is not free: failed attempts have a separate bounded limiter (the authenticated bucket is not charged;
    see tests/unit/test_auth_order.py)."""
    from oah.api.rate_limit import RateLimiter

    monkeypatch.setenv("OAH_API_KEY", "demo-secret")
    tight = RateLimiter(max_requests=3, window_seconds=60.0)
    monkeypatch.setattr(deps_module, "get_auth_failure_limiter", lambda: tight)
    statuses = [
        client.get("/risk/Loc-Almyros", headers={"X-API-Key": f"guess-{i}"}).status_code for i in range(8)
    ]
    assert statuses == [401, 401, 401, 429, 429, 429, 429, 429], statuses  # brute-force guesses are throttled, not free


def test_secrets_do_not_appear_in_the_settings_repr(monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "super-secret-value")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-secret-value")
    text = repr(config.load_settings())
    assert "super-secret-value" not in text and "sk-ant-secret-value" not in text


def test_a_wildcard_cors_origin_is_rejected(monkeypatch):
    monkeypatch.setenv("OAH_CORS_ORIGINS", "*")
    with pytest.raises(ValueError, match="wildcard"):
        config.load_settings()
