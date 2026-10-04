"""The sidebar catalogue of one country: which families and indices apply, and why not."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from oah.api import payloads
from oah.api.schemas import CatalogResponse, ErrorResponse
from oah.api.services import resolve_language
from oah.chat import normalise_country

router = APIRouter()


@router.get("/catalog", response_model=CatalogResponse, responses={422: {"model": ErrorResponse}})
def catalog(
    country: str = Query(pattern=r"^[A-Za-z]{2}$"),
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """The families and indices of the web app sidebar for ONE country (``country`` is required; ``EL`` is read as ``GR``).

    Authoritative: the web app hides only the indices with ``applies`` false. Applicability is derived from the data the
    service holds for the country (the sandbox sites, the Waterbase, bathing-water and bathing-samples stores, the external
    context switches), never from a country list. Every index is returned, in a stable order, with its ``origin_kind``
    (``real``, ``external`` or ``synthetic``), its routes, the ``chat_index`` that fits it (or null) and, when it does not
    apply, a ``reason_code`` and the ``reason`` in ``language``. ``stores`` gives the state of each source so a client can
    show a notice for a store that is not built. Biotic quality, protozoa, air quality and population health are never
    returned. An unknown country is a 422 that lists the known codes. See docs/api_routes.md and docs/indices_catalog.md.
    """
    code = resolve_language(language)
    return payloads._catalog_payload(normalise_country(country), code)
