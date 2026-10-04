"""HTTP middleware of the API: CORS from ``OAH_CORS_ORIGINS`` and the defensive response headers.

``install_middleware`` adds CORS first and the header middleware second, so the headers wrap CORS exactly as before.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from oah.api import deps
from oah.api.client_ip import is_https

_DOC_PATHS = ("/docs", "/redoc", "/openapi.json")


async def security_headers(request: Request, call_next):
    """Defensive headers on every response. The API returns JSON only, so a strict CSP and no caching are safe;
    the interactive docs load assets from a CDN and are left without a CSP."""
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    peer = request.client.host if request.client else None
    if is_https(request.url.scheme, peer, request.headers.get("x-forwarded-proto"), deps.settings.trusted_proxies):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    if not request.url.path.startswith(_DOC_PATHS):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    return response


def install_middleware(app: FastAPI) -> None:
    """Attach CORS (allow-list from the settings) and the security-header middleware to ``app``."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(deps.settings.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["X-API-Key", "Content-Type"],
    )
    app.middleware("http")(security_headers)
