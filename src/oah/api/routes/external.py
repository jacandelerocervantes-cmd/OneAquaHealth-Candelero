"""External context around a site (weather, river discharge, species records) and the providers' status."""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Query

from oah.api import external as external_api
from oah.api import payloads
from oah.api.external_schemas import DischargeResponse, ExternalStatusResponse, SpeciesResponse, WeatherResponse
from oah.api.schemas import ErrorResponse
from oah.api.services import resolve_language

router = APIRouter()


@router.get(
    "/sites/{site_id}/weather",
    response_model=WeatherResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def site_weather(
    site_id: str,
    date_from: date,
    date_to: date,
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """EXTERNAL context: monthly precipitation and mean temperature around a site or bathing water, from the ERA5 reanalysis.

    MODELLED values for a coarse grid cell (Open-Meteo, CC BY 4.0), never measurements at the site and never evidence of
    causation. Monthly sums and means of the daily values that exist, with ``n_days`` and ``coverage`` (a missing day is
    never filled); ``data_limits`` and the flags (``era5-delay``, ``period-end-clipped``, ``period-outside-data``,
    ``partial-month``) say what the archive holds. The period is at most about three years (1096 days). The coordinates are
    the site's own, rounded to two decimals; no raw coordinate is accepted. A provider that is off, over its budget or
    failing gives HTTP 200 with ``status`` ``external-unavailable`` and a ``reason``; 404 unknown site, 422 a site without
    coordinates or an invalid period. Show ``attribution`` next to the data. See docs/external_context.md.
    """
    code = resolve_language(language)
    return external_api.payload(lambda: payloads.get_external_context().weather(site_id, date_from, date_to), code)


@router.get(
    "/sites/{site_id}/discharge",
    response_model=DischargeResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def site_discharge(
    site_id: str,
    date_from: date,
    date_to: date,
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """EXTERNAL context: monthly mean river discharge of the river cell nearest to a site, from GloFAS (through Open-Meteo).

    MODELLED, not a gauge reading; the cell (``grid`` with its distance) may be another river than the site's (flag
    ``nearest-cell-may-not-be-the-river``). ``data_range`` is the first and last day with a value; a month with no value is
    flagged ``period-outside-data`` and a month after July 2022, the end of the documented history, ``beyond-documented-history``.
    Water-quality sites only (a bathing water is a 422). Same period, error and unavailability rules as the weather route.
    """
    code = resolve_language(language)
    return external_api.payload(lambda: payloads.get_external_context().discharge(site_id, date_from, date_to), code)


@router.get(
    "/sites/{site_id}/species",
    response_model=SpeciesResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def site_species(
    site_id: str,
    group: str | None = Query(default=None, max_length=32),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """EXTERNAL context: GBIF occurrence records of freshwater macroinvertebrate groups in a 10 km square around a site.

    OPPORTUNISTIC records, not monitoring: no record never means a species is absent. ``group`` is one group of
    GET /external/status (``ephemeroptera``, ``plecoptera``, ``trichoptera``, ``ept``, ``odonata``, ``chironomidae``,
    ``gammaridae``, ``unionida``) or all; ``date_from`` and ``date_to`` filter the event date; ``limit`` (default 50, at most
    200) bounds the records returned while ``group_counts`` and ``total_records`` are GBIF's own counts. Every record carries
    its licence (``CC0-1.0``, ``CC-BY-4.0``, ``CC-BY-NC-4.0`` or ``other-or-unspecified``), dataset and publisher keys and, when
    GBIF provides it, the dataset citation. Water-quality sites only. Same error and unavailability rules as the weather route.
    """
    code = resolve_language(language)
    return external_api.payload(lambda: payloads.get_external_context().species(site_id, group, date_from, date_to, limit), code)


@router.get("/external/status", response_model=ExternalStatusResponse)
def external_status(language: str | None = Query(default=None, min_length=2, max_length=12)) -> dict[str, Any]:
    """The external-context providers: switch, attribution, licence, limits and the call budget left (no secret), the
    species groups and the fixed notices. See docs/external_context.md."""
    return external_api.status_payload(payloads.get_external_context(), resolve_language(language))
