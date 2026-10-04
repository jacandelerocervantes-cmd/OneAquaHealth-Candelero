"""The API must degrade cleanly when the public sandbox is unreachable (no network, mocked loaders)."""
import pytest
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
import oah.api.services as services_module
from oah.api.rate_limit import RateLimiter
from oah.indices.sandbox_loader import SandboxDataUnavailableError
from oah.ingest.freshness import make_freshness

LIVE = make_freshness("live", 1_800_000_000.0, 1_800_000_000.0)

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    app_module._observations_cache.clear()
    app_module._locations_cache.clear()
    app_module._freshness_by_type.clear()
    yield
    app_module._observations_cache.clear()
    app_module._locations_cache.clear()
    app_module._freshness_by_type.clear()


def test_an_unreachable_sandbox_with_no_snapshot_is_a_clear_503_not_a_500(monkeypatch):
    def unavailable(resource_type, max_age_seconds=0.0):
        raise SandboxDataUnavailableError(f"Could not obtain {resource_type} resources from a snapshot or the live sandbox: down")

    monkeypatch.setattr(services_module, "load_sandbox_resources_with_freshness", unavailable)
    for path in ("/qc/report", "/sites", "/indices/Loc-X"):
        response = client.get(path)
        assert response.status_code == 503, path
        assert "unavailable" in response.json()["detail"]
        assert "http" not in response.json()["detail"].lower()  # no URL or transport text reaches the caller


def test_the_api_reads_the_live_sandbox_first_and_never_prefers_a_fresh_snapshot(monkeypatch):
    seen = []

    def loader(resource_type, max_age_seconds=None):
        seen.append((resource_type, max_age_seconds))
        return [], LIVE

    monkeypatch.setattr(services_module, "load_sandbox_resources_with_freshness", loader)
    client.get("/qc/report")
    assert seen and all(age == 0.0 for _t, age in seen), seen


def test_a_failed_load_is_not_cached_so_the_next_request_recovers(monkeypatch):
    state = {"down": True}

    def loader(resource_type, max_age_seconds=0.0):
        if state["down"]:
            raise SandboxDataUnavailableError("down")
        return [], LIVE

    monkeypatch.setattr(services_module, "load_sandbox_resources_with_freshness", loader)
    assert client.get("/qc/report").status_code == 503
    state["down"] = False
    assert client.get("/qc/report").status_code == 200


def test_a_stale_snapshot_is_reported_as_such_and_never_as_live(monkeypatch):
    stale = make_freshness("snapshot-stale", 1_700_000_000.0, 1_700_360_000.0)

    def loader(resource_type, max_age_seconds=0.0):
        return [], stale

    monkeypatch.setattr(services_module, "load_sandbox_resources_with_freshness", loader)
    for path in ("/qc/report", "/sites"):
        body = client.get(path).json()
        assert body["origin"] == "real-sandbox"
        assert body["data_freshness"]["status"] == "snapshot-stale", path
        assert body["data_freshness"]["as_of"].startswith("2023-11-14"), path


def test_freshness_reports_the_worst_source_when_observations_and_locations_differ(monkeypatch):
    def loader(resource_type, max_age_seconds=0.0):
        if resource_type == "Location":
            return [], make_freshness("snapshot-stale", 1_700_000_000.0, 1_700_000_100.0)
        return [], LIVE

    monkeypatch.setattr(services_module, "load_sandbox_resources_with_freshness", loader)
    assert client.get("/sites").json()["data_freshness"]["status"] == "snapshot-stale"


def test_freshness_is_unknown_before_any_fetch():
    assert app_module.get_data_freshness()["status"] == "unknown"
