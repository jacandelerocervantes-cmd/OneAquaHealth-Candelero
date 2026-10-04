"""FastAPI application assembling the existing OneAquaHealth modules.

This layer adds NO new business logic: every endpoint is a thin wrapper around a function
already implemented and tested elsewhere in oah.* (directly, or via oah.api.services for the
handful of orchestration steps -- freshness-aware fetch+cache, the LLM explain budget, the
reliability-campaign pipeline, and FHIR export -- factored out there to keep the routes a
routing layer). Endpoints that touch synthetic data always carry an explicit "origin": "synthetic"
field; endpoints reading the sandbox carry "origin": "real-sandbox". Real network access (the
FHIR sandbox) is cached with a TTL so a burst of requests does not refetch on every call.

Module layout (see docs/architecture.md): this module only builds the single FastAPI instance (``app``, the ASGI entry
point ``oah.api.app:app``): settings and the limit-override file, the middleware (``oah.api.middleware``: CORS and the
security headers), ``GET /health`` and the protected router. The routes live in ``oah.api.routes`` (one module per
domain), the process-wide wiring and test seams in ``oah.api.deps`` and the payload assembly in ``oah.api.payloads``
and ``oah.api.chat_context``.

Every route except /health is behind one dependency, ``oah.api.deps.authenticate_and_limit``: the shared-secret check
(oah.api.auth, fail closed) first, then a per-process rate limiter (oah.api.rate_limit, fixed-window, keyed by client
host) for authenticated requests only; failed attempts have their own small limiter. CORS is configured from
OAH_CORS_ORIGINS (default: common local frontend dev ports). All three are stated,
documented mitigations for this project's own earlier security review, not a hardened
production posture: the rate limiter is single-process, and the shared API key is not
per-user identity. See docs/architecture.md for the full detail.

The /explain/* endpoints add a single-call LLM explanation layer (oah.explain) over data this
layer already computed and already tests elsewhere; they add no new business logic either, and
their evidence-grounding check (oah.explain.grounding) is applied to every response. Each takes
an optional ?mode= query parameter: "describe" (default, a strictly factual restatement of the
evidence) or "assess" (an interpretive concern-level + recommendation reading on the same
evidence, deliberately a separate call so a caller who needs only the auditable, factual
description never has to pay for or receive the opinionated one).
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from oah.api import deps
from oah.api.chat_context import _chat_tool_context  # noqa: F401  (re-export: tests build the chat tool context from here)
from oah.api.middleware import install_middleware
from oah.api.payloads import _sandbox_site_entries  # noqa: F401  (re-export, called by tests)
from oah.api.routes import protected_router
from oah.api.schemas import HealthResponse
from oah.api.services import (
    _freshness_by_type,  # noqa: F401  (re-export: tests clear the caches through this module)
    _locations_cache,  # noqa: F401  (re-export)
    _observations_cache,  # noqa: F401  (re-export)
    get_data_freshness,  # noqa: F401  (re-export, read by tests)
    start_sandbox_warmup,
)
from oah.config import check_auth_policy
from oah.indices.limit_overrides import ensure_overrides_loaded

ensure_overrides_loaded(deps.settings.limits_file, strict=True)  # a wrong OAH_LIMITS_FILE stops the server with a clear message

logger = logging.getLogger(__name__)

# The access-control policy: refuse to start on Cloud Run without a strong key (or with the no-authentication flag), and warn
# elsewhere about a short key. The message never contains the key or its length.
for _warning in check_auth_policy(deps.settings):
    logger.warning(_warning)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the sandbox cache warm-up in background threads; it never delays start-up and a failure never stops the server."""
    if deps.settings.sandbox_warmup:
        try:
            start_sandbox_warmup()
        except Exception:  # noqa: BLE001  (for example no thread can be started: the first request fetches instead)
            logger.exception("Could not start the sandbox cache warm-up.")
    yield


app = FastAPI(
    lifespan=_lifespan,
    # The interactive docs and the OpenAPI schema disclose every route and are unauthenticated: off unless
    # OAH_ENABLE_DOCS=1 (local development). app.openapi() still works for tests and client generation.
    docs_url="/docs" if deps.settings.enable_docs else None,
    redoc_url="/redoc" if deps.settings.enable_docs else None,
    openapi_url="/openapi.json" if deps.settings.enable_docs else None,
    title="OneAquaHealth backend API",
    description=(
        "Read-only and demo endpoints over the OneAquaHealth pipeline. Every response is "
        "labeled with its data origin (real-sandbox or synthetic)."
    ),
)

install_middleware(app)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


app.include_router(protected_router)
