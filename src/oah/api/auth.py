"""Shared-secret authentication for the API layer (fail closed).

Every protected request must carry an `X-API-Key` header matching OAH_API_KEY. When OAH_API_KEY is
not set the API refuses protected requests with 503, so a deployment that forgot the key is closed,
not open. Local demos opt out explicitly with OAH_INSECURE_NO_AUTH=1; that flag must never be set on
a reachable host. This is a shared-secret check, not per-user identity.

The key is checked BEFORE any rate limit (``oah.api.deps.authenticate_and_limit``): ``key_decision`` only decides, it
neither limits nor raises, so the caller can charge a failed attempt to its own small limiter instead of the bucket of
the authenticated callers.
"""
from __future__ import annotations

import hmac
from typing import Literal

from fastapi import Header, HTTPException

from oah.config import load_settings

KeyDecision = Literal["open", "accepted", "denied", "unconfigured"]

UNAUTHORIZED_DETAIL = "Missing or invalid X-API-Key header."  # one text for a missing and a wrong key: no hint about the key
UNCONFIGURED_DETAIL = (
    "Authentication is not configured: set OAH_API_KEY (or OAH_INSECURE_NO_AUTH=1 for local demos only)."
)


def key_decision(supplied_key: str | None) -> KeyDecision:
    """Classify a request by its key: ``open`` (local-demo flag, no key needed), ``accepted``, ``denied`` or
    ``unconfigured`` (no key configured and no local-demo flag: fail closed). The comparison is constant-time and
    encodes both sides to bytes, so a non-ASCII header is a denial, not a crash."""
    settings = load_settings()
    configured = settings.api_key
    if configured is None:
        return "open" if settings.insecure_no_auth else "unconfigured"
    supplied = (supplied_key or "").encode("utf-8")
    if supplied_key and hmac.compare_digest(supplied, configured.encode("utf-8")):
        return "accepted"
    return "denied"


def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """FastAPI dependency: enforce the key; refuse when it is unset unless the local-demo flag is on.

    The protected router uses ``oah.api.deps.authenticate_and_limit`` (this check plus the rate limits in the right
    order); this plain form stays for callers that need only the key check.
    """
    decision = key_decision(x_api_key)
    if decision == "unconfigured":
        raise HTTPException(status_code=503, detail=UNCONFIGURED_DETAIL)
    if decision == "denied":
        raise HTTPException(status_code=401, detail=UNAUTHORIZED_DETAIL)
