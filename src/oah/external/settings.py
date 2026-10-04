"""Settings of the external-context feature, parsed from a mapping of variable names to text.

Pure: no file or environment access (``load_external_settings`` in ``oah.external.runtime`` supplies the values), so the
parsing is tested with plain dictionaries. Every limit has a ceiling; a configured value above it is lowered to it, the
way the chat limits are, so a typo cannot lift a budget above what the providers' published terms allow.

Variables (all optional; see docs/external_context.md):

* ``OAH_EXTERNAL_ENABLED`` (default true): the master switch. False disables every provider.
* ``OAH_EXTERNAL_OPEN_METEO_ENABLED``, ``OAH_EXTERNAL_GLOFAS_ENABLED``, ``OAH_EXTERNAL_GBIF_ENABLED`` (default true).
* ``OAH_CONTACT_URL``: an https URL placed in the User-Agent so a provider can reach the operator.
* ``OAH_EXTERNAL_TIMEOUT_SECONDS`` (default 8, ceiling 20), ``OAH_EXTERNAL_CACHE_TTL_SECONDS`` (default 3600),
  ``OAH_EXTERNAL_CACHE_SIZE`` (default 256, ceiling 2048).
* ``OAH_EXTERNAL_OPEN_METEO_PER_MINUTE`` and ``OAH_EXTERNAL_OPEN_METEO_DAILY``: budget in ESTIMATED CALL UNITS (the
  provider counts a long request as several calls; see ``oah.external.openmeteo.request_units``).
* ``OAH_EXTERNAL_GBIF_PER_MINUTE`` and ``OAH_EXTERNAL_GBIF_DAILY``: requests.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

# Open-Meteo free tier (https://open-meteo.com/en/terms, read 2026-10-03): 600 calls per minute, 5,000 per hour, 10,000
# per day, 300,000 per month. The defaults stay well below; the ceilings stay below the published figures.
DEFAULT_OPEN_METEO_PER_MINUTE = 200
DEFAULT_OPEN_METEO_DAILY = 3000
OPEN_METEO_PER_MINUTE_CEILING = 400
OPEN_METEO_DAILY_CEILING = 8000
# GBIF publishes no numeric read limit that this project has verified; these are self-imposed courtesy limits.
DEFAULT_GBIF_PER_MINUTE = 30
DEFAULT_GBIF_DAILY = 1500
GBIF_PER_MINUTE_CEILING = 120
GBIF_DAILY_CEILING = 10_000
DEFAULT_TIMEOUT_SECONDS = 8.0
TIMEOUT_CEILING_SECONDS = 20.0
DEFAULT_CACHE_TTL_SECONDS = 3600.0
CACHE_TTL_CEILING_SECONDS = 7 * 24 * 3600.0
DEFAULT_CACHE_SIZE = 256
CACHE_SIZE_CEILING = 2048
MAX_RETRIES = 2  # extra attempts after the first, for a timeout, a network error or a 5xx; never for a 429

PRODUCT = "OneAquaHealth/0.1"
DEFAULT_USER_AGENT = f"{PRODUCT} (research prototype)"
MAX_CONTACT_URL_CHARS = 200

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


@dataclass(frozen=True)
class ExternalSettings:
    enabled: bool = True
    open_meteo_enabled: bool = True  # ERA5 weather (archive host)
    glofas_enabled: bool = True  # river discharge (flood host)
    gbif_enabled: bool = True
    contact_url: str | None = None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS
    cache_size: int = DEFAULT_CACHE_SIZE
    open_meteo_per_minute: int = DEFAULT_OPEN_METEO_PER_MINUTE
    open_meteo_daily: int = DEFAULT_OPEN_METEO_DAILY
    gbif_per_minute: int = DEFAULT_GBIF_PER_MINUTE
    gbif_daily: int = DEFAULT_GBIF_DAILY
    max_retries: int = MAX_RETRIES

    @property
    def user_agent(self) -> str:
        return user_agent(self.contact_url)


def user_agent(contact_url: str | None) -> str:
    """The descriptive User-Agent: the product, and the operator's contact URL when one is configured."""
    return f"{PRODUCT} (research prototype; +{contact_url})" if contact_url else DEFAULT_USER_AGENT


def _flag(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    text = raw.strip().lower()
    if text in _TRUE:
        return True
    if text in _FALSE:
        return False
    raise ValueError(f"{name} must be one of 1, 0, true, false, yes, no, on, off; got {raw!r}.")


def _positive_int(values: Mapping[str, str], name: str, default: int, ceiling: int) -> int:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = int(raw.strip())
    except ValueError as error:
        raise ValueError(f"{name} must be an integer, got {raw!r}.") from error
    if parsed <= 0:
        raise ValueError(f"{name} must be positive, got {parsed}.")
    return min(parsed, ceiling)


def _positive_float(values: Mapping[str, str], name: str, default: float, ceiling: float) -> float:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        parsed = float(raw.strip())
    except ValueError as error:
        raise ValueError(f"{name} must be a number, got {raw!r}.") from error
    if not 0.0 < parsed < float("inf"):
        raise ValueError(f"{name} must be a positive finite number, got {raw!r}.")
    return min(parsed, ceiling)


def validated_contact_url(value: str | None) -> str | None:
    """``OAH_CONTACT_URL``: unset or empty is None; otherwise a plain https URL (no credentials, query or fragment)."""
    text = (value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if (
        len(text) > MAX_CONTACT_URL_CHARS
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not text.isprintable()
        or " " in text
    ):
        raise ValueError(
            "OAH_CONTACT_URL must be a plain https URL of at most 200 characters, without credentials, query or fragment."
        )
    return text


def parse_external_settings(values: Mapping[str, str]) -> ExternalSettings:
    """Build the settings from variable values; an invalid value raises ``ValueError`` naming the variable."""
    return ExternalSettings(
        enabled=_flag(values, "OAH_EXTERNAL_ENABLED", True),
        open_meteo_enabled=_flag(values, "OAH_EXTERNAL_OPEN_METEO_ENABLED", True),
        glofas_enabled=_flag(values, "OAH_EXTERNAL_GLOFAS_ENABLED", True),
        gbif_enabled=_flag(values, "OAH_EXTERNAL_GBIF_ENABLED", True),
        contact_url=validated_contact_url(values.get("OAH_CONTACT_URL")),
        timeout_seconds=_positive_float(
            values, "OAH_EXTERNAL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, TIMEOUT_CEILING_SECONDS
        ),
        cache_ttl_seconds=_positive_float(
            values, "OAH_EXTERNAL_CACHE_TTL_SECONDS", DEFAULT_CACHE_TTL_SECONDS, CACHE_TTL_CEILING_SECONDS
        ),
        cache_size=_positive_int(values, "OAH_EXTERNAL_CACHE_SIZE", DEFAULT_CACHE_SIZE, CACHE_SIZE_CEILING),
        open_meteo_per_minute=_positive_int(
            values, "OAH_EXTERNAL_OPEN_METEO_PER_MINUTE", DEFAULT_OPEN_METEO_PER_MINUTE, OPEN_METEO_PER_MINUTE_CEILING
        ),
        open_meteo_daily=_positive_int(
            values, "OAH_EXTERNAL_OPEN_METEO_DAILY", DEFAULT_OPEN_METEO_DAILY, OPEN_METEO_DAILY_CEILING
        ),
        gbif_per_minute=_positive_int(
            values, "OAH_EXTERNAL_GBIF_PER_MINUTE", DEFAULT_GBIF_PER_MINUTE, GBIF_PER_MINUTE_CEILING
        ),
        gbif_daily=_positive_int(values, "OAH_EXTERNAL_GBIF_DAILY", DEFAULT_GBIF_DAILY, GBIF_DAILY_CEILING),
    )
