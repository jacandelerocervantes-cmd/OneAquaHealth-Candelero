"""Settings of the external-context feature: defaults, switches, ceilings, contact URL, user agent."""
from __future__ import annotations

import pytest

from oah.external import settings as external_settings
from oah.external.runtime import load_external_settings
from oah.external.settings import ExternalSettings, parse_external_settings, user_agent, validated_contact_url


def test_defaults_enable_everything_and_stay_below_published_limits() -> None:
    parsed = parse_external_settings({})
    assert parsed == ExternalSettings()
    assert parsed.enabled and parsed.open_meteo_enabled and parsed.glofas_enabled and parsed.gbif_enabled
    # Open-Meteo free tier: 600 per minute, 10,000 per day.
    assert parsed.open_meteo_per_minute < 600 and parsed.open_meteo_daily < 10_000
    assert parsed.contact_url is None
    assert parsed.user_agent == external_settings.DEFAULT_USER_AGENT


@pytest.mark.parametrize("text, expected", [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False), ("False", False), ("no", False), ("OFF", False)])
def test_boolean_switches(text: str, expected: bool) -> None:
    assert parse_external_settings({"OAH_EXTERNAL_ENABLED": text}).enabled is expected
    assert parse_external_settings({"OAH_EXTERNAL_GBIF_ENABLED": text}).gbif_enabled is expected
    assert parse_external_settings({"OAH_EXTERNAL_GLOFAS_ENABLED": text}).glofas_enabled is expected
    assert parse_external_settings({"OAH_EXTERNAL_OPEN_METEO_ENABLED": text}).open_meteo_enabled is expected


def test_blank_value_means_default_and_garbage_is_refused() -> None:
    assert parse_external_settings({"OAH_EXTERNAL_ENABLED": "  "}).enabled is True
    with pytest.raises(ValueError, match="OAH_EXTERNAL_ENABLED"):
        parse_external_settings({"OAH_EXTERNAL_ENABLED": "maybe"})


def test_numbers_are_validated_and_ceilings_lower_big_values() -> None:
    parsed = parse_external_settings(
        {
            "OAH_EXTERNAL_OPEN_METEO_PER_MINUTE": "100000", "OAH_EXTERNAL_OPEN_METEO_DAILY": "999999",
            "OAH_EXTERNAL_GBIF_PER_MINUTE": "100000", "OAH_EXTERNAL_GBIF_DAILY": "9999999",
            "OAH_EXTERNAL_TIMEOUT_SECONDS": "500", "OAH_EXTERNAL_CACHE_SIZE": "99999999",
            "OAH_EXTERNAL_CACHE_TTL_SECONDS": "99999999999",
        }
    )
    assert parsed.open_meteo_per_minute == external_settings.OPEN_METEO_PER_MINUTE_CEILING
    assert parsed.open_meteo_daily == external_settings.OPEN_METEO_DAILY_CEILING
    assert parsed.gbif_per_minute == external_settings.GBIF_PER_MINUTE_CEILING
    assert parsed.gbif_daily == external_settings.GBIF_DAILY_CEILING
    assert parsed.timeout_seconds == external_settings.TIMEOUT_CEILING_SECONDS
    assert parsed.cache_size == external_settings.CACHE_SIZE_CEILING
    assert parsed.cache_ttl_seconds == external_settings.CACHE_TTL_CEILING_SECONDS
    for name, bad in [
        ("OAH_EXTERNAL_GBIF_DAILY", "0"), ("OAH_EXTERNAL_GBIF_DAILY", "-3"), ("OAH_EXTERNAL_GBIF_DAILY", "x"),
        ("OAH_EXTERNAL_TIMEOUT_SECONDS", "0"), ("OAH_EXTERNAL_TIMEOUT_SECONDS", "nan"), ("OAH_EXTERNAL_TIMEOUT_SECONDS", "inf"),
        ("OAH_EXTERNAL_TIMEOUT_SECONDS", "abc"),
    ]:
        with pytest.raises(ValueError, match=name):
            parse_external_settings({name: bad})


@pytest.mark.parametrize("value", ["http://example.org/contact", "ftp://example.org", "https://user:pw@example.org", "https://example.org/a?b=1",
                                   "https://example.org/#x", "https:///nohost", "https://exa mple.org", "https://example.org/" + "a" * 300,
                                   "not a url"])
def test_contact_url_must_be_a_plain_https_url(value: str) -> None:
    with pytest.raises(ValueError, match="OAH_CONTACT_URL"):
        validated_contact_url(value)


def test_contact_url_reaches_the_user_agent() -> None:
    parsed = parse_external_settings({"OAH_CONTACT_URL": "https://example.org/contact"})
    assert parsed.contact_url == "https://example.org/contact"
    assert parsed.user_agent == "OneAquaHealth/0.1 (research prototype; +https://example.org/contact)"
    assert user_agent(None) == external_settings.DEFAULT_USER_AGENT
    assert validated_contact_url("   ") is None and validated_contact_url(None) is None


def test_load_external_settings_reads_the_given_environment() -> None:
    assert load_external_settings({"OAH_EXTERNAL_ENABLED": "0"}).enabled is False
    assert load_external_settings({}).enabled is True


def test_the_application_settings_carry_the_external_settings() -> None:
    from oah.config import load_settings

    default = load_settings({})
    assert default.external == ExternalSettings() and default.external.enabled is True
    custom = load_settings({"OAH_EXTERNAL_ENABLED": "0", "OAH_CONTACT_URL": "https://example.org/contact", "OAH_EXTERNAL_GBIF_DAILY": "10"})
    assert custom.external.enabled is False and custom.external.contact_url == "https://example.org/contact"
    assert custom.external.gbif_daily == 10
    with pytest.raises(ValueError, match="OAH_CONTACT_URL"):
        load_settings({"OAH_CONTACT_URL": "http://example.org"})
    with pytest.raises(ValueError, match="OAH_EXTERNAL_OPEN_METEO_ENABLED"):
        load_settings({"OAH_EXTERNAL_OPEN_METEO_ENABLED": "sometimes"})
