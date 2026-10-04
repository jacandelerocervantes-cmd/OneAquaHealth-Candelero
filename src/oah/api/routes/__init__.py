"""The protected routes, one module per domain, behind one router.

``protected_router`` attaches one dependency to every route it holds, ``authenticate_and_limit``: the API key is checked
FIRST, a failed attempt is charged to a separate small limiter and only an authenticated request uses the normal rate
limiter, so a flood of unauthenticated requests cannot exhaust the bucket of legitimate callers. It also carries the
shared 401, 429 and 503 error responses. ``GET /health`` is deliberately not here (see ``oah.api.app``).
Each domain module owns a plain ``APIRouter``; they are included below, so no route can be added without the protection.
Route paths do not overlap across modules (the literal ``/bathing-waters/change`` and ``/bathing-waters/samples/change``
share a module with the ``{bw_id}`` routes they must precede).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from oah.api.deps import authenticate_and_limit
from oah.api.routes import bathing, catalog, change, chat, explain, external, languages, quality, sites, synthetic
from oah.api.schemas import ErrorResponse

protected_router = APIRouter(
    dependencies=[Depends(authenticate_and_limit)],
    responses={
        401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key."},
        429: {"model": ErrorResponse, "description": "Rate limit exceeded (or too many failed key attempts); see Retry-After."},
        503: {"model": ErrorResponse, "description": "Authentication not configured, or the data source is unavailable."},
    },
)

for _module in (quality, sites, catalog, bathing, change, external, explain, chat, languages, synthetic):
    protected_router.include_router(_module.router)

__all__ = ["protected_router"]
