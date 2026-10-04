"""The state-changing demo routes are off unless OAH_ENABLE_WRITE_ROUTES is on (security audit F5), and the cheap-guard
bounds of the read-only synthetic routes."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import oah.api.deps as deps_module
import oah.api.services as services_module
from oah import config
from oah.api import app as app_module
from oah.api.rate_limit import RateLimiter
from oah.review.queue import submit_to_queue
from oah.store.review_store import ReviewStore
from oah.uncertainty.conformal import ConformalPredictionSet

client = TestClient(app_module.app)
DECISION = {"final_label": "A", "reviewer_id": "reviewer-1"}
WRITE_ROUTES = ("/fhir/export", "/fhir/export/indicators", "/review/SPEC-W/decide")


@pytest.fixture(autouse=True)
def _world(monkeypatch, tmp_path):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: [])
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [])
    monkeypatch.setattr(deps_module, "export_path", lambda name: tmp_path / name)
    store = ReviewStore(tmp_path / "write.db")
    submit_to_queue(store, ConformalPredictionSet("SPEC-W", ("A", "B"), {"A": 0.55, "B": 0.45}, 0.5, "one-coin"))
    monkeypatch.setattr(deps_module, "get_review_store", lambda: store)
    monkeypatch.delenv("OAH_ENABLE_WRITE_ROUTES", raising=False)
    return store


def _post(path):
    return client.post(path, json=DECISION) if path.endswith("/decide") else client.post(path)


@pytest.mark.parametrize("path", WRITE_ROUTES)
def test_write_routes_answer_404_by_default_as_if_they_did_not_exist(path):
    response = _post(path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}  # the same body as a path that does not exist
    assert response.json() == client.post("/no/such/route").json()


def test_nothing_is_written_when_the_routes_are_off(_world, tmp_path):
    assert _post("/fhir/export").status_code == 404
    assert _post("/fhir/export/indicators").status_code == 404
    assert _post("/review/SPEC-W/decide").status_code == 404
    assert not list(tmp_path.glob("*.json"))
    assert _world.get_review_item("SPEC-W").status == "pending"


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", " 1 "])
def test_truthy_values_switch_the_write_routes_on(monkeypatch, value, tmp_path):
    monkeypatch.setenv("OAH_ENABLE_WRITE_ROUTES", value)
    assert config.load_settings().enable_write_routes is True
    assert _post("/review/SPEC-W/decide").status_code == 200
    assert _post("/fhir/export").status_code == 200


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "2", "enabled"])
def test_any_other_value_keeps_them_off(monkeypatch, value):
    monkeypatch.setenv("OAH_ENABLE_WRITE_ROUTES", value)
    assert config.load_settings().enable_write_routes is False
    assert _post("/fhir/export/indicators").status_code == 404


def test_the_default_is_off():
    assert config.load_settings({}).enable_write_routes is False


def test_the_key_is_checked_before_the_switch(monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "k" * 40)
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    assert client.post("/fhir/export").status_code == 401  # an unauthenticated caller learns nothing about the switch
    assert client.post("/fhir/export", headers={"X-API-Key": "k" * 40}).status_code == 404
    monkeypatch.setenv("OAH_ENABLE_WRITE_ROUTES", "1")
    assert client.post("/fhir/export", headers={"X-API-Key": "k" * 40}).status_code == 200


def test_the_read_only_routes_stay_available_when_the_write_routes_are_off():
    assert client.get("/review/queue").status_code == 200
    assert client.get("/risk/Loc-Almyros").status_code == 200
    assert client.get("/reliability/campaign?seed=1&observer_count=3&specimens_per_site=2&annotators_per_specimen=2").status_code == 200


def test_the_openapi_file_keeps_the_routes_and_documents_the_404():
    paths = app_module.app.openapi()["paths"]
    for path in ("/fhir/export", "/fhir/export/indicators", "/review/{specimen_id}/decide"):
        assert "404" in paths[path]["post"]["responses"], path


# --- the read-only synthetic routes: bounded input and a bounded result cache ------------------------------------------
CAMPAIGN = "/reliability/campaign?seed={seed}&observer_count={o}&specimens_per_site={s}&annotators_per_specimen={a}"


@pytest.mark.parametrize(
    ("o", "s", "a"),
    [(31, 5, 3), (1, 5, 3), (8, 201, 3), (8, 0, 3), (8, 5, 11), (8, 5, 1)],
)
def test_the_campaign_parameters_are_bounded(o, s, a):
    assert client.get(CAMPAIGN.format(seed=1, o=o, s=s, a=a)).status_code == 422


def test_the_campaign_seed_is_bounded():
    assert client.get(CAMPAIGN.format(seed=2_000_000_001, o=8, s=5, a=3)).status_code == 422
    assert client.get(CAMPAIGN.format(seed=-1, o=8, s=5, a=3)).status_code == 422


def test_an_identical_campaign_request_is_computed_once(monkeypatch):
    services_module._campaign_cache.clear()
    calls = []
    real = services_module._compute_reliability_campaign

    def spy(params, labels):
        calls.append(params.seed)
        return real(params, labels)

    monkeypatch.setattr(services_module, "_compute_reliability_campaign", spy)
    url = CAMPAIGN.format(seed=424242, o=4, s=3, a=2)
    first, second = client.get(url), client.get(url)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    assert calls == [424242]
    assert client.get(CAMPAIGN.format(seed=424243, o=4, s=3, a=2)).status_code == 200
    assert calls == [424242, 424243]


def test_the_campaign_cache_is_bounded_and_drops_the_oldest(monkeypatch):
    services_module._campaign_cache.clear()
    monkeypatch.setattr(services_module, "CAMPAIGN_CACHE_SIZE", 2)
    monkeypatch.setattr(services_module, "_compute_reliability_campaign", lambda params, labels: {"seed": params.seed})
    for seed in (1, 2, 3):
        params = SimpleNamespace(seed=seed, observer_count=3, specimens_per_site=2, annotators_per_specimen=2)
        assert services_module.run_reliability_campaign(params, ("A",)) == {"seed": seed}
    assert len(services_module._campaign_cache) == 2
    assert [key[0] for key in services_module._campaign_cache] == [2, 3]
    services_module._campaign_cache.clear()
