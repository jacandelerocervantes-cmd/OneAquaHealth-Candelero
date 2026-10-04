"""Process-wide wiring of the API: settings, the rate limiters and spend guards, the review store, the LLM client and the
sandbox data accessors.

Every name here that a test replaces is a SEAM (``get_rate_limiter``, ``get_llm_guard``, ``get_chat_guard``,
``get_llm_client``, ``get_review_store``, ``get_cached_locations``, ``get_cached_observations``, ``export_path``).
The routes and the payload helpers look them up as ``deps.NAME`` at call time, never through a ``from`` import, so a
``monkeypatch.setattr(deps, "NAME", ...)`` is honoured everywhere. The FastAPI dependencies (``enforce_*``) live here too.
"""
from __future__ import annotations

from fastapi import Header, HTTPException, Request

from oah.api.auth import UNAUTHORIZED_DETAIL, UNCONFIGURED_DETAIL, key_decision
from oah.api.client_ip import END_USER_HEADER, client_key, end_user_token, rate_key
from oah.api.llm_guard import ChatSpendGuard, LLMSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.api.services import get_cached_locations, get_cached_observations  # noqa: F401  (seams, see above)
from oah.config import load_settings
from oah.explain import build_client
from oah.paths import export_path, review_db_path  # noqa: F401  (``export_path`` is a seam)
from oah.store import ReviewStore

settings = load_settings()


def get_review_store() -> ReviewStore:
    """Return the review store, exposed so tests can monkeypatch it."""
    return ReviewStore(review_db_path())


def get_llm_client():
    """Return an Anthropic client, exposed so tests can monkeypatch it with a fake."""
    return build_client()


_rate_limiter = RateLimiter(settings.rate_limit_max_requests, settings.rate_limit_window_seconds)


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide rate limiter, exposed so tests can monkeypatch it."""
    return _rate_limiter


def _client_key(request: Request) -> str:
    """The address a request is rate-limited under (X-Forwarded-For only through a trusted proxy or the configured hops)."""
    peer = request.client.host if request.client else None
    return client_key(peer, request.headers.get("x-forwarded-for"), settings.trusted_proxies, settings.trusted_proxy_hops)


def _llm_rate_key(request: Request) -> str:
    """The bucket of the chat and explanation per-minute limits: the client address plus the optional end-user token.

    The token (``X-OAH-End-User``, set by the trusted web server layer) is untrusted and valid only in the strict pattern;
    it separates visitors who share one proxy address. It is a fairness aid for these two limits, not authentication.
    """
    return rate_key(_client_key(request), end_user_token(request.headers.get(END_USER_HEADER)))


def enforce_rate_limit(request: Request) -> None:
    """FastAPI dependency: 429 once a client host exceeds the configured window."""
    if not get_rate_limiter().allow(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Slow down and retry shortly.",
            headers={"Retry-After": str(int(settings.rate_limit_window_seconds))},
        )


# Failed authentication has its own, separate bucket per client address: wrong keys must never use up the budget of
# callers who hold the right one. The bound is generous (a typo is not punished) and cheap (nothing but a counter).
AUTH_FAILURE_MAX_PER_WINDOW = 60
AUTH_FAILURE_WINDOW_SECONDS = 60.0
_auth_failure_limiter = RateLimiter(AUTH_FAILURE_MAX_PER_WINDOW, AUTH_FAILURE_WINDOW_SECONDS)


def get_auth_failure_limiter() -> RateLimiter:
    """Return the limiter of failed authentication attempts, exposed so tests can monkeypatch it."""
    return _auth_failure_limiter


def authenticate_and_limit(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency of every protected route: check the key FIRST, then apply the normal rate limit.

    * A wrong or missing key is charged to the failed-authentication limiter only (401, or 429 once that small bucket is
      empty) and never touches the bucket of authenticated callers, so a flood of bad requests cannot make legitimate
      callers receive 429. The 401 text is the same for a missing and a wrong key.
    * No key configured and no local-demo flag: 503, fail closed.
    * An accepted key (or the local-demo flag) goes through ``enforce_rate_limit`` as before.
    """
    decision = key_decision(x_api_key)
    if decision == "denied":
        if not get_auth_failure_limiter().allow(_client_key(request)):
            raise HTTPException(
                status_code=429,
                detail="Too many failed requests. Retry shortly.",
                headers={"Retry-After": str(int(AUTH_FAILURE_WINDOW_SECONDS))},
            )
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
    if decision == "unconfigured":
        raise HTTPException(status_code=503, detail=UNCONFIGURED_DETAIL)
    enforce_rate_limit(request)


def require_write_routes() -> None:
    """FastAPI dependency of the state-changing demo routes: 404, as if the route did not exist, unless
    ``OAH_ENABLE_WRITE_ROUTES`` is on. Read at request time so a test can switch it; the key is checked before this."""
    if not load_settings().enable_write_routes:
        raise HTTPException(status_code=404, detail="Not Found")


_llm_guard = LLMSpendGuard(
    settings.explain_rate_limit_per_minute, settings.explain_daily_cap, settings.explain_cache_ttl_seconds
)


def get_llm_guard() -> LLMSpendGuard:
    """Return the process-wide LLM spend guard, exposed so tests can monkeypatch it."""
    return _llm_guard


def enforce_explain_rate(request: Request) -> None:
    """FastAPI dependency for /explain routes: a tighter per-host budget than the general limit."""
    get_llm_guard().check_rate(_llm_rate_key(request))


_chat_guard = ChatSpendGuard(
    settings.chat_rate_limit_per_minute,
    settings.chat_daily_cap,
    settings.explain_cache_ttl_seconds,
    settings.chat_max_steps,
)


def get_chat_guard() -> ChatSpendGuard:
    """Return the process-wide chat spend guard (separate from the explanation guard), exposed for tests."""
    return _chat_guard


def enforce_chat_rate(request: Request) -> None:
    """FastAPI dependency for POST /chat: its own per-host per-minute budget."""
    get_chat_guard().check_rate(_llm_rate_key(request))
