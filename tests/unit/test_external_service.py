"""The facade the routes and tools call: site resolution rules, the site block, notice keys and the status payload."""
from __future__ import annotations

from datetime import date

import pytest
from external_fakes import (
    archive_handler,
    fake_locator,
    flood_handler,
    gbif_handler,
    json_response,
    make_runtime,
    occurrence,
    search_payload,
)

from oah.external import constants as c
from oah.external.envelope import ExternalInputError
from oah.external.service import (
    NOTICE_KEYS,
    UNAVAILABLE_NOTICE_KEY,
    ExternalContext,
    notice_keys,
    site_block,
)
from oah.external.settings import ExternalSettings
from oah.external.sites import SiteLookupError

TODAY = date(2026, 10, 3)


def context(settings: ExternalSettings | None = None):
    runtime, router, clock = make_runtime(settings=settings)
    router.on(c.ARCHIVE_HOST, archive_handler())
    router.on(c.FLOOD_HOST, flood_handler())
    router.on(c.GBIF_HOST, gbif_handler(lambda request: json_response(search_payload([occurrence(1)]))))
    return ExternalContext(fake_locator(), lambda: runtime, lambda: TODAY), router, runtime


def test_weather_accepts_sites_and_bathing_waters_and_names_the_site() -> None:
    ctx, router, _ = context()
    river = ctx.weather("ITRIVER1", date(2021, 3, 1), date(2021, 3, 5))
    assert river["site"] == {
        "id": "ITRIVER1", "name": "PO - TEST", "kind": "waterbase-site", "source": "real-eea-waterbase", "country": "IT",
        "water_category": "river", "latitude": 45.07, "longitude": 7.69, "coordinate_decimals": 2,
    }
    bathing = ctx.weather("IT001001050001", date(2021, 3, 1), date(2021, 3, 5))
    assert bathing["site"]["kind"] == "bathing-water" and bathing["status"] == "ok"
    assert ctx.weather("Loc-Almyros", date(2021, 3, 1), date(2021, 3, 5))["site"]["country"] == "GR"
    assert router.count() == 3


def test_discharge_and_species_refuse_a_bathing_water_with_a_clear_422() -> None:
    ctx, router, _ = context()
    for call in (
        lambda: ctx.discharge("IT001001050001", date(2021, 3, 1), date(2021, 3, 5)),
        lambda: ctx.species("IT001001050001", None, None, None),
    ):
        with pytest.raises(SiteLookupError) as caught:
            call()
        assert caught.value.status_code == 422 and "bathing water" in caught.value.detail
    assert router.requests == []
    assert ctx.discharge("ITRIVER1", date(2021, 3, 1), date(2021, 3, 5))["provider"] == c.PROVIDER_DISCHARGE
    assert ctx.species("ITRIVER1", "ept", None, None)["provider"] == c.PROVIDER_GBIF


def test_unknown_unlocated_and_malformed_sites_never_reach_a_provider() -> None:
    ctx, router, _ = context()
    for site_id, status in [("NOPE", 404), ("ITNOLOC", 422), ("bad id", 422)]:
        for call in (
            lambda s=site_id: ctx.weather(s, date(2021, 3, 1), date(2021, 3, 5)),
            lambda s=site_id: ctx.discharge(s, date(2021, 3, 1), date(2021, 3, 5)),
            lambda s=site_id: ctx.species(s, None, None, None),
        ):
            with pytest.raises(SiteLookupError) as caught:
                call()
            assert caught.value.status_code == status
    assert router.requests == []


def test_input_errors_surface_as_external_input_error() -> None:
    ctx, router, _ = context()
    with pytest.raises(ExternalInputError):
        ctx.weather("ITRIVER1", date(2021, 3, 5), date(2021, 3, 1))
    with pytest.raises(ExternalInputError):
        ctx.species("ITRIVER1", "birds", None, None)
    assert router.requests == []


def test_notice_keys_per_provider_and_for_unavailability() -> None:
    ctx, _, _ = context()
    weather = ctx.weather("ITRIVER1", date(2021, 3, 1), date(2021, 3, 5))
    assert notice_keys(weather) == list(NOTICE_KEYS[c.PROVIDER_WEATHER])
    assert "external_no_causation_notice" in notice_keys(weather) and UNAVAILABLE_NOTICE_KEY not in notice_keys(weather)
    species = ctx.species("ITRIVER1", None, None, None)
    assert notice_keys(species) == ["external_context_notice", "external_occurrence_notice", "external_licence_notice"]
    off, _, _ = context(ExternalSettings(enabled=False))
    result = off.discharge("ITRIVER1", date(2021, 3, 1), date(2021, 3, 5))
    assert result["status"] == "external-unavailable" and notice_keys(result)[-1] == UNAVAILABLE_NOTICE_KEY
    assert result["site"]["id"] == "ITRIVER1"


def test_site_block_rounds_the_coordinates() -> None:
    ctx, _, _ = context()
    located = ctx.locate("ITRIVER1")
    assert site_block(located)["latitude"] == 45.07
    assert ctx.locate("IT001001050001", allow_bathing=True).kind == "bathing-water"


def test_status_lists_providers_groups_and_limits_without_secrets() -> None:
    ctx, _, runtime = context(ExternalSettings(contact_url="https://example.org/contact", gbif_enabled=False))
    status = ctx.status()
    assert status["enabled"] is True and status["contact_url_configured"] is True and "example.org" not in repr(status)
    assert [p["provider"] for p in status["providers"]] == list(c.PROVIDERS)
    assert status["coordinate_decimals"] == 2 and status["max_period_days"] == 1096
    assert status["species_search_half_side_km"] == 5.0 and status["species_default_limit"] == 50 and status["species_max_limit"] == 200
    assert [g["id"] for g in status["species_groups"]][:3] == ["ephemeroptera", "plecoptera", "trichoptera"]
    assert status["species_group_aliases"] == {"ept": ["ephemeroptera", "plecoptera", "trichoptera"]}
    assert status["taxa_discovered_on"] == "2026-10-03"
    gbif = next(p for p in status["providers"] if p["provider"] == c.PROVIDER_GBIF)
    assert gbif["enabled"] is False and gbif["budget"]["per_day_limit"] == runtime.settings.gbif_daily


def test_the_default_runtime_and_today_are_used_when_none_are_injected(monkeypatch: pytest.MonkeyPatch) -> None:
    from oah.external import service

    runtime, router, _ = make_runtime(settings=ExternalSettings(enabled=False))
    monkeypatch.setattr(service, "get_runtime", lambda: runtime)
    ctx = ExternalContext(fake_locator(), runtime=lambda: runtime)
    assert ctx.weather("ITRIVER1", date(2021, 3, 1), date(2021, 3, 2))["reason"] == c.REASON_DISABLED
    assert service._today() <= date(9999, 12, 31)
