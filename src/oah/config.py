"""Configuration from an optional .env file and environment variables."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass, field
from collections.abc import Mapping
from os import environ
from pathlib import Path
from urllib.parse import urlparse

from oah.external.settings import ExternalSettings, parse_external_settings
from oah.i18n.languages import DEFAULT_LANGUAGE, normalize_code, supported_codes
from oah.paths import default_data_dir, external_path, repo_path

DEFAULT_SANDBOX_URL = "https://sandbox.hl7europe.eu/oneaquahealth/fhir"
DEFAULT_LLM_MODEL = "claude-sonnet-5-5"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60.0
# LLM calls cost money, so /explain has its own, much tighter budget on top of the general limit.
DEFAULT_EXPLAIN_RATE_LIMIT_PER_MINUTE = 5
DEFAULT_EXPLAIN_DAILY_CAP = 100
DEFAULT_EXPLAIN_CACHE_TTL_SECONDS = 600.0
# The chat agent chains several model calls per question, so it has its own, separate budget (docs/chat_agent.md).
DEFAULT_CHAT_DAILY_CAP = 100  # conversations per rolling 24 hours, process-wide
DEFAULT_CHAT_RATE_LIMIT_PER_MINUTE = 5
DEFAULT_CHAT_MAX_STEPS = 6  # model calls per conversation
CHAT_MAX_STEPS_CEILING = 8  # a configured value above this is lowered to it
DEFAULT_CHAT_TIMEOUT_SECONDS = 45.0
CHAT_TIMEOUT_CEILING_SECONDS = 120.0
# The translation of a validated English answer is one extra, constrained model call (docs/language_support.md).
DEFAULT_TRANSLATION_TIMEOUT_SECONDS = 30.0
TRANSLATION_TIMEOUT_CEILING_SECONDS = 60.0  # the same ceiling as oah.i18n.translator.MAX_TIMEOUT_SECONDS
# The sandbox cache (docs/architecture.md, "Sandbox cache"): a copy younger than the TTL is served as is; a copy older than the
# TTL but younger than the maximum staleness is served at once while a background refresh runs; an older one is not served.
DEFAULT_SANDBOX_CACHE_TTL_SECONDS = 300.0
DEFAULT_SANDBOX_MAX_STALE_SECONDS = 6 * 3600.0
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")
# Shared access key strength (docs/api_routes.md, "Access control"): on Cloud Run (the K_SERVICE variable is set) a key of at least this
# many characters is required at start-up; elsewhere a shorter key only logs a warning, so local development keeps working.
MIN_API_KEY_CHARS = 32
# How many trusted proxy hops sit in front of the service, counted from the right of X-Forwarded-For (0: the header is not used
# unless OAH_TRUSTED_PROXIES lists the peer). Cloud Run's front end appends the address it saw, so 1 is the usual value there.
MAX_TRUSTED_PROXY_HOPS = 5


def _dotenv_values() -> dict[str, str]:
    """Parse simple KEY=VALUE lines without mutating the process environment."""
    dotenv = repo_path(".env")
    if not dotenv.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in dotenv.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    sandbox_url: str
    sources_root: Path | None
    llm_model: str
    anthropic_api_key: str | None = field(repr=False)
    api_key: str | None = field(repr=False)
    cors_origins: tuple[str, ...]
    rate_limit_max_requests: int
    rate_limit_window_seconds: float
    explain_rate_limit_per_minute: int = DEFAULT_EXPLAIN_RATE_LIMIT_PER_MINUTE
    explain_daily_cap: int = DEFAULT_EXPLAIN_DAILY_CAP
    explain_cache_ttl_seconds: float = DEFAULT_EXPLAIN_CACHE_TTL_SECONDS
    insecure_no_auth: bool = False
    enable_docs: bool = False
    trusted_proxies: tuple[str, ...] = ()
    limits_file: Path | None = None
    chat_daily_cap: int = DEFAULT_CHAT_DAILY_CAP
    chat_rate_limit_per_minute: int = DEFAULT_CHAT_RATE_LIMIT_PER_MINUTE
    chat_max_steps: int = DEFAULT_CHAT_MAX_STEPS
    chat_timeout_seconds: float = DEFAULT_CHAT_TIMEOUT_SECONDS
    waterbase_store: Path | None = None  # OAH_WATERBASE_STORE: absolute path of the Waterbase SQLite store
    sevenzip_path: Path | None = None  # OAH_SEVENZIP_PATH: absolute path of the 7-Zip executable (store build only)
    bathing_water_store: Path | None = None  # OAH_BATHING_WATER_STORE: absolute path of the bathing-water SQLite store
    bathing_samples_store: Path | None = None  # OAH_BATHING_SAMPLES_STORE: absolute path of the bathing-water samples SQLite store
    translation_model: str = ""  # OAH_TRANSLATION_MODEL; empty means the same model as llm_model (see translation_model_id)
    translation_timeout_seconds: float = DEFAULT_TRANSLATION_TIMEOUT_SECONDS  # OAH_TRANSLATION_TIMEOUT_SECONDS
    default_language: str = DEFAULT_LANGUAGE  # OAH_DEFAULT_LANGUAGE: answer language when a request names none
    external: ExternalSettings = field(default_factory=ExternalSettings)  # OAH_EXTERNAL_* and OAH_CONTACT_URL (docs/external_context.md)
    sandbox_cache_ttl_seconds: float = DEFAULT_SANDBOX_CACHE_TTL_SECONDS  # OAH_SANDBOX_CACHE_TTL_SECONDS
    sandbox_max_stale_seconds: float = DEFAULT_SANDBOX_MAX_STALE_SECONDS  # OAH_SANDBOX_MAX_STALE_SECONDS (at least the TTL)
    sandbox_warmup: bool = True  # OAH_SANDBOX_WARMUP: fill the sandbox caches in the background at start-up
    enable_write_routes: bool = False  # OAH_ENABLE_WRITE_ROUTES: the state-changing demo routes (review decisions, FHIR exports)
    trusted_proxy_hops: int = 0  # OAH_TRUSTED_PROXY_HOPS: proxies counted from the right of X-Forwarded-For (0: disabled)
    on_cloud_run: bool = False  # K_SERVICE is set: the strict start-up rules of check_auth_policy apply

    @property
    def translation_model_id(self) -> str:
        """The model of the translation call: ``OAH_TRANSLATION_MODEL`` or, when unset, the explanation model."""
        return self.translation_model or self.llm_model


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _parse_trusted_proxies(value: str | None) -> tuple[str, ...]:
    """Comma-separated IP addresses of reverse proxies whose X-Forwarded-For header is believed."""
    if not value or not value.strip():
        return ()
    addresses = [part.strip() for part in value.split(",") if part.strip()]
    for address in addresses:
        try:
            ipaddress.ip_address(address)
        except ValueError as error:
            raise ValueError(f"OAH_TRUSTED_PROXIES must list single IP addresses, got {address!r}.") from error
    return tuple(addresses)


def _parse_trusted_proxy_hops(value: str | None) -> int:
    """``OAH_TRUSTED_PROXY_HOPS``: a whole number from 0 to ``MAX_TRUSTED_PROXY_HOPS``; empty or unset means 0 (disabled)."""
    if value is None or not value.strip():
        return 0
    try:
        hops = int(value.strip())
    except ValueError as error:
        raise ValueError(f"OAH_TRUSTED_PROXY_HOPS must be a whole number, got {value!r}.") from error
    if not 0 <= hops <= MAX_TRUSTED_PROXY_HOPS:
        raise ValueError(f"OAH_TRUSTED_PROXY_HOPS must be between 0 and {MAX_TRUSTED_PROXY_HOPS}, got {hops}.")
    return hops


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes")


def check_auth_policy(settings: Settings) -> list[str]:
    """The access-control start-up policy; returns warnings to log and raises ``ValueError`` when the service must not start.

    On Cloud Run (``settings.on_cloud_run``) the service refuses to start with the no-authentication flag on, with no key, or
    with a key shorter than ``MIN_API_KEY_CHARS``. Elsewhere a short key only produces a warning (local development keeps
    working). The key and its length are never part of a message.
    """
    warnings: list[str] = []
    if settings.on_cloud_run:
        if settings.insecure_no_auth:
            raise ValueError("OAH_INSECURE_NO_AUTH must not be set on Cloud Run.")
        if settings.api_key is None:
            raise ValueError(f"OAH_API_KEY is required on Cloud Run: use a random key of at least {MIN_API_KEY_CHARS} characters.")
        if len(settings.api_key) < MIN_API_KEY_CHARS:
            raise ValueError(f"OAH_API_KEY is too short for Cloud Run: use a random key of at least {MIN_API_KEY_CHARS} characters.")
    elif settings.api_key is not None and len(settings.api_key) < MIN_API_KEY_CHARS:
        warnings.append(
            f"OAH_API_KEY is too short: use a random key of at least {MIN_API_KEY_CHARS} characters before any deployment "
            "(it is required on Cloud Run)."
        )
    return warnings


def _validated_sandbox_url(url: str) -> str:
    """The only outbound target: https (plain http only for a local test server), with a host and no credentials."""
    parsed = urlparse(url)
    local = (parsed.hostname or "") in _LOCAL_HOSTS
    if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
        raise ValueError("OAH_SANDBOX_URL must use https (http is allowed only for localhost).")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("OAH_SANDBOX_URL must name a host and must not embed credentials.")
    return url


def _parse_positive_int(value: str | None, default: int, variable: str) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be an integer, got {value!r}.") from error
    if parsed <= 0:
        raise ValueError(f"{variable} must be positive, got {parsed}.")
    return parsed


def _parse_positive_float(value: str | None, default: float, variable: str) -> float:
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as error:
        raise ValueError(f"{variable} must be a number, got {value!r}.") from error
    if parsed <= 0.0:
        raise ValueError(f"{variable} must be positive, got {parsed}.")
    return parsed


def _parse_optional_positive_float(value: str | None, default: float, variable: str) -> float:
    """Like ``_parse_positive_float`` but an empty value (``NAME=`` in a settings file) means the default, never a crash."""
    if value is None or not value.strip():
        return default
    return _parse_positive_float(value.strip(), default, variable)


def _parse_sandbox_cache(values: Mapping[str, str]) -> tuple[float, float]:
    """``(ttl, max staleness)`` of the sandbox cache; the maximum staleness may not be below the TTL."""
    ttl = _parse_optional_positive_float(
        values.get("OAH_SANDBOX_CACHE_TTL_SECONDS"), DEFAULT_SANDBOX_CACHE_TTL_SECONDS, "OAH_SANDBOX_CACHE_TTL_SECONDS"
    )
    max_stale = _parse_optional_positive_float(
        values.get("OAH_SANDBOX_MAX_STALE_SECONDS"), max(DEFAULT_SANDBOX_MAX_STALE_SECONDS, ttl), "OAH_SANDBOX_MAX_STALE_SECONDS"
    )
    if max_stale < ttl:
        raise ValueError("OAH_SANDBOX_MAX_STALE_SECONDS must be at least OAH_SANDBOX_CACHE_TTL_SECONDS.")
    return ttl, max_stale


def _parse_translation_model(value: str | None) -> str:
    """``OAH_TRANSLATION_MODEL``: empty or unset means the explanation model; otherwise a plausible model id."""
    text = (value or "").strip()
    if text and not _MODEL_ID.fullmatch(text):
        raise ValueError("OAH_TRANSLATION_MODEL must be a model id (letters, digits, '.', '_', ':' and '-').")
    return text


def _parse_default_language(value: str | None) -> str:
    """``OAH_DEFAULT_LANGUAGE``: a supported language code (see GET /languages); a typo stops the server clearly."""
    text = (value or "").strip()
    if not text:
        return DEFAULT_LANGUAGE
    code = normalize_code(text)
    if code is None:
        raise ValueError(f"OAH_DEFAULT_LANGUAGE must be one of: {', '.join(supported_codes())}.")
    return code


def load_settings(environment: Mapping[str, str] | None = None) -> Settings:
    """Read settings; explicit environment values take precedence over `.env`."""
    values = _dotenv_values()
    values.update(environ if environment is None else environment)
    data_value = values.get("OAH_DATA_DIR")
    source_value = values.get("OAH_SOURCES_ROOT")
    sandbox = _validated_sandbox_url(values.get("OAH_SANDBOX_URL", DEFAULT_SANDBOX_URL).rstrip("/"))
    cors_value = values.get("OAH_CORS_ORIGINS")
    cors_origins = (
        tuple(origin.strip() for origin in cors_value.split(",") if origin.strip())
        if cors_value
        else DEFAULT_CORS_ORIGINS
    )
    if "*" in cors_origins:
        raise ValueError("OAH_CORS_ORIGINS must list explicit origins; a wildcard is not allowed.")
    insecure_no_auth = values.get("OAH_INSECURE_NO_AUTH", "").strip().lower() in ("1", "true", "yes")
    enable_docs = values.get("OAH_ENABLE_DOCS", "").strip().lower() in ("1", "true", "yes")
    trusted_proxies = _parse_trusted_proxies(values.get("OAH_TRUSTED_PROXIES"))
    limits_value = (values.get("OAH_LIMITS_FILE") or "").strip()
    store_value = (values.get("OAH_WATERBASE_STORE") or "").strip()
    sevenzip_value = (values.get("OAH_SEVENZIP_PATH") or "").strip()
    bathing_value = (values.get("OAH_BATHING_WATER_STORE") or "").strip()
    samples_value = (values.get("OAH_BATHING_SAMPLES_STORE") or "").strip()
    sandbox_ttl, sandbox_max_stale = _parse_sandbox_cache(values)
    return Settings(
        data_dir=external_path(data_value, "OAH_DATA_DIR") if data_value else default_data_dir(),
        sandbox_url=sandbox,
        sources_root=external_path(source_value, "OAH_SOURCES_ROOT") if source_value else None,
        llm_model=values.get("OAH_LLM_MODEL", DEFAULT_LLM_MODEL),
        anthropic_api_key=values.get("ANTHROPIC_API_KEY") or None,
        api_key=values.get("OAH_API_KEY") or None,
        cors_origins=cors_origins,
        rate_limit_max_requests=_parse_positive_int(
            values.get("OAH_RATE_LIMIT_MAX_REQUESTS"), DEFAULT_RATE_LIMIT_MAX_REQUESTS, "OAH_RATE_LIMIT_MAX_REQUESTS"
        ),
        rate_limit_window_seconds=_parse_positive_float(
            values.get("OAH_RATE_LIMIT_WINDOW_SECONDS"),
            DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
            "OAH_RATE_LIMIT_WINDOW_SECONDS",
        ),
        explain_rate_limit_per_minute=_parse_positive_int(
            values.get("OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE"),
            DEFAULT_EXPLAIN_RATE_LIMIT_PER_MINUTE,
            "OAH_EXPLAIN_RATE_LIMIT_PER_MINUTE",
        ),
        explain_daily_cap=_parse_positive_int(
            values.get("OAH_EXPLAIN_DAILY_CAP"), DEFAULT_EXPLAIN_DAILY_CAP, "OAH_EXPLAIN_DAILY_CAP"
        ),
        explain_cache_ttl_seconds=_parse_positive_float(
            values.get("OAH_EXPLAIN_CACHE_TTL_SECONDS"),
            DEFAULT_EXPLAIN_CACHE_TTL_SECONDS,
            "OAH_EXPLAIN_CACHE_TTL_SECONDS",
        ),
        insecure_no_auth=insecure_no_auth,
        enable_docs=enable_docs,
        trusted_proxies=trusted_proxies,
        limits_file=external_path(limits_value, "OAH_LIMITS_FILE") if limits_value else None,
        chat_daily_cap=_parse_positive_int(values.get("OAH_CHAT_DAILY_CAP"), DEFAULT_CHAT_DAILY_CAP, "OAH_CHAT_DAILY_CAP"),
        chat_rate_limit_per_minute=_parse_positive_int(
            values.get("OAH_CHAT_RATE_LIMIT_PER_MINUTE"), DEFAULT_CHAT_RATE_LIMIT_PER_MINUTE, "OAH_CHAT_RATE_LIMIT_PER_MINUTE"
        ),
        chat_max_steps=min(
            _parse_positive_int(values.get("OAH_CHAT_MAX_STEPS"), DEFAULT_CHAT_MAX_STEPS, "OAH_CHAT_MAX_STEPS"),
            CHAT_MAX_STEPS_CEILING,
        ),
        chat_timeout_seconds=min(
            _parse_positive_float(
                values.get("OAH_CHAT_TIMEOUT_SECONDS"), DEFAULT_CHAT_TIMEOUT_SECONDS, "OAH_CHAT_TIMEOUT_SECONDS"
            ),
            CHAT_TIMEOUT_CEILING_SECONDS,
        ),
        waterbase_store=external_path(store_value, "OAH_WATERBASE_STORE") if store_value else None,
        sevenzip_path=external_path(sevenzip_value, "OAH_SEVENZIP_PATH") if sevenzip_value else None,
        bathing_water_store=external_path(bathing_value, "OAH_BATHING_WATER_STORE") if bathing_value else None,
        bathing_samples_store=external_path(samples_value, "OAH_BATHING_SAMPLES_STORE") if samples_value else None,
        translation_model=_parse_translation_model(values.get("OAH_TRANSLATION_MODEL")),
        translation_timeout_seconds=min(
            _parse_positive_float(
                values.get("OAH_TRANSLATION_TIMEOUT_SECONDS"),
                DEFAULT_TRANSLATION_TIMEOUT_SECONDS,
                "OAH_TRANSLATION_TIMEOUT_SECONDS",
            ),
            TRANSLATION_TIMEOUT_CEILING_SECONDS,
        ),
        default_language=_parse_default_language(values.get("OAH_DEFAULT_LANGUAGE")),
        external=parse_external_settings(values),
        sandbox_cache_ttl_seconds=sandbox_ttl,
        sandbox_max_stale_seconds=sandbox_max_stale,
        sandbox_warmup=values.get("OAH_SANDBOX_WARMUP", "").strip().lower() not in ("0", "false", "no", "off"),
        enable_write_routes=_truthy(values.get("OAH_ENABLE_WRITE_ROUTES")),
        trusted_proxy_hops=_parse_trusted_proxy_hops(values.get("OAH_TRUSTED_PROXY_HOPS")),
        on_cloud_run=bool((values.get("K_SERVICE") or "").strip()),
    )


def data_dir():
    """Configured external cache/data root; intentionally not created here."""
    return load_settings().data_dir


def sandbox_url() -> str:
    return load_settings().sandbox_url


def sources_root():
    """Optional read-only source root, or None when adaptation is not in scope."""
    return load_settings().sources_root
