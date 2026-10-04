"""Audit batch D: bounded sandbox client, validated sandbox URL, thread-safe limiters and caches, docs off."""

import json
import threading
import time

import pytest
from fastapi import HTTPException

from oah import config
from oah.api.app import app
from oah.api.cache import TTLCache
from oah.api.llm_guard import LLMSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.ingest import sandbox_client
from oah.ingest.sandbox_client import SandboxClient

BASE = "https://sandbox.hl7europe.eu/oneaquahealth/fhir"


class Response:
    def __init__(self, body, size=None):
        self.body, self.size = body, size

    def raise_for_status(self):
        pass

    def json(self):
        return self.body

    @property
    def content(self):
        return b"x" * self.size if self.size else json.dumps(self.body).encode()


# M4 ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url",
    ["http://sandbox.example.test/fhir", "ftp://sandbox.example.test", "https:///fhir", "https://user:pw@sandbox.example.test/fhir", "sandbox.example.test"],
)
def test_sandbox_url_must_be_https_with_a_host_and_no_credentials(url):
    with pytest.raises(ValueError):
        config.load_settings({"OAH_SANDBOX_URL": url})


@pytest.mark.parametrize("url", ["https://sandbox.example.test/fhir", "http://localhost:8080/fhir", "http://127.0.0.1:9/fhir"])
def test_valid_sandbox_urls_are_accepted(url):
    assert config.load_settings({"OAH_SANDBOX_URL": url}).sandbox_url == url


# M3 ---------------------------------------------------------------------------------------------
def test_a_cycling_next_link_stops_instead_of_looping(monkeypatch):
    body = {"entry": [{"resource": {"id": "1"}}], "link": [{"relation": "next", "url": f"{BASE}?page=2"}]}
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *a, **k: Response(body))
    with pytest.raises(RuntimeError, match="does not terminate"):
        list(SandboxClient(BASE).pages("Observation"))


def test_the_page_limit_is_enforced(monkeypatch):
    counter = iter(range(10_000))
    monkeypatch.setattr(sandbox_client, "MAX_PAGES", 3)
    monkeypatch.setattr(
        sandbox_client.httpx, "get", lambda *a, **k: Response({"entry": [], "link": [{"relation": "next", "url": f"{BASE}?page={next(counter)}"}]})
    )
    with pytest.raises(RuntimeError, match="does not terminate"):
        list(SandboxClient(BASE).pages("Observation"))


def test_the_resource_and_response_size_limits_are_enforced(monkeypatch):
    monkeypatch.setattr(sandbox_client, "MAX_RESOURCES", 2)
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *a, **k: Response({"entry": [{"resource": {"id": str(i)}} for i in range(3)]}))
    with pytest.raises(RuntimeError, match="more resources"):
        list(SandboxClient(BASE).pages("Observation"))
    monkeypatch.setattr(sandbox_client, "MAX_RESPONSE_BYTES", 10)
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *a, **k: Response({}, size=100))
    monkeypatch.setattr(sandbox_client.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="size limit"):
        list(SandboxClient(BASE, retries=0).pages("Observation"))


def test_entries_without_a_resource_are_skipped_and_non_objects_rejected(monkeypatch):
    body = {"entry": [{"resource": {"id": "1"}}, {"response": {"status": "200"}}, "junk", {"resource": "bad"}]}
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *a, **k: Response(body))
    assert list(SandboxClient(BASE).pages("Observation")) == [[{"id": "1"}]]
    monkeypatch.setattr(sandbox_client.httpx, "get", lambda *a, **k: Response([1, 2]))
    with pytest.raises(RuntimeError, match="not a JSON object"):
        list(SandboxClient(BASE, retries=0).pages("Observation"))


# M5 ---------------------------------------------------------------------------------------------
def test_concurrent_reservations_never_exceed_the_daily_cap():
    guard = LLMSpendGuard(per_minute=1000, daily_cap=5, cache_ttl_seconds=60.0)
    granted, refused = [], []

    def worker():
        try:
            guard.reserve_call()
            granted.append(1)
        except HTTPException:
            refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 5 and len(refused) == 35


def test_concurrent_cache_misses_trigger_one_fetch():
    calls = []

    def fetch():
        calls.append(1)
        time.sleep(0.1)
        return [{"id": "1"}]

    cache = TTLCache(fetch)
    threads = [threading.Thread(target=cache.get) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1


def test_the_rate_limiter_drops_idle_keys():
    limiter = RateLimiter(max_requests=1_000_000, window_seconds=0.001)
    for i in range(1500):
        limiter.allow(f"10.0.{i // 256}.{i % 256}")
    time.sleep(0.01)
    limiter.allow("fresh")
    assert len(limiter._hits) < 1500


def test_the_rate_limiter_counts_exactly_under_threads():
    strict = RateLimiter(max_requests=10, window_seconds=60.0)
    results = []
    threads = [threading.Thread(target=lambda: results.append(strict.allow("k"))) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(results) == 10


# M6 ---------------------------------------------------------------------------------------------
def test_interactive_docs_and_schema_routes_are_off_by_default():
    assert not config.load_settings({}).enable_docs
    assert config.load_settings({"OAH_ENABLE_DOCS": "1"}).enable_docs
    paths = {getattr(route, "path", None) for route in app.routes}
    assert not ({"/docs", "/redoc", "/openapi.json"} & paths)
    assert app.openapi()["info"]["title"]  # the schema is still available in-process
