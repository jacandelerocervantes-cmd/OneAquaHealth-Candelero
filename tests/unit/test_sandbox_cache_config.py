"""The optional sandbox-cache settings: defaults, the empty-value trap, validation and the warm-up switch."""
import pytest

from oah.config import (
    DEFAULT_SANDBOX_CACHE_TTL_SECONDS,
    DEFAULT_SANDBOX_MAX_STALE_SECONDS,
    load_settings,
)


def test_defaults_are_five_minutes_six_hours_and_warm_up_on():
    settings = load_settings({})
    assert settings.sandbox_cache_ttl_seconds == DEFAULT_SANDBOX_CACHE_TTL_SECONDS == 300.0
    assert settings.sandbox_max_stale_seconds == DEFAULT_SANDBOX_MAX_STALE_SECONDS == 6 * 3600.0
    assert settings.sandbox_warmup is True


def test_values_are_read():
    settings = load_settings(
        {"OAH_SANDBOX_CACHE_TTL_SECONDS": "20", "OAH_SANDBOX_MAX_STALE_SECONDS": " 7200.5 ", "OAH_SANDBOX_WARMUP": "0"}
    )
    assert (settings.sandbox_cache_ttl_seconds, settings.sandbox_max_stale_seconds) == (20.0, 7200.5)
    assert settings.sandbox_warmup is False


def test_empty_values_mean_the_defaults_and_never_crash():
    settings = load_settings(
        {"OAH_SANDBOX_CACHE_TTL_SECONDS": "", "OAH_SANDBOX_MAX_STALE_SECONDS": "   ", "OAH_SANDBOX_WARMUP": ""}
    )
    assert settings.sandbox_cache_ttl_seconds == DEFAULT_SANDBOX_CACHE_TTL_SECONDS
    assert settings.sandbox_max_stale_seconds == DEFAULT_SANDBOX_MAX_STALE_SECONDS
    assert settings.sandbox_warmup is True


@pytest.mark.parametrize("text", ["false", "No", "OFF", "0"])
def test_the_warm_up_switch_words(text):
    assert load_settings({"OAH_SANDBOX_WARMUP": text}).sandbox_warmup is False


@pytest.mark.parametrize(
    "name, value",
    [
        ("OAH_SANDBOX_CACHE_TTL_SECONDS", "abc"),
        ("OAH_SANDBOX_CACHE_TTL_SECONDS", "0"),
        ("OAH_SANDBOX_CACHE_TTL_SECONDS", "-5"),
        ("OAH_SANDBOX_MAX_STALE_SECONDS", "soon"),
        ("OAH_SANDBOX_MAX_STALE_SECONDS", "0"),
    ],
)
def test_invalid_numbers_stop_the_server_with_a_clear_message(name, value):
    with pytest.raises(ValueError, match=name):
        load_settings({name: value})


def test_the_maximum_staleness_may_not_be_below_the_ttl():
    with pytest.raises(ValueError, match="at least"):
        load_settings({"OAH_SANDBOX_CACHE_TTL_SECONDS": "600", "OAH_SANDBOX_MAX_STALE_SECONDS": "599"})
    assert load_settings(
        {"OAH_SANDBOX_CACHE_TTL_SECONDS": "600", "OAH_SANDBOX_MAX_STALE_SECONDS": "600"}
    ).sandbox_max_stale_seconds == 600.0


def test_a_ttl_above_the_default_staleness_raises_the_default_staleness_with_it():
    settings = load_settings({"OAH_SANDBOX_CACHE_TTL_SECONDS": str(10 * 3600)})
    assert settings.sandbox_max_stale_seconds == 10 * 3600.0
