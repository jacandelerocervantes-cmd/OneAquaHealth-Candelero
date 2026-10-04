"""Period comparison of one parameter at a site or across the sites of a country (``docs/period_change.md``)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Path, Query

from oah.api import change as change_service
from oah.api.change_schemas import CountryChangeResponse, SiteChangeResponse
from oah.api.payloads import _http_error, _known_country, _sandbox_access
from oah.api.schemas import ErrorResponse, SiteSource
from oah.api.services import resolve_language
from oah.chat import normalise_country

router = APIRouter()


_MONTH_QUERY: dict[str, Any] = {"min_length": 7, "max_length": 7}  # YYYY-MM; the exact check is in oah.indices.period_change


@router.get(
    "/sites/{site_id}/change",
    response_model=SiteChangeResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def site_change(
    site_id: str,
    parameter: str = Query(min_length=1, max_length=64),
    a_from: str = Query(**_MONTH_QUERY),
    a_to: str = Query(**_MONTH_QUERY),
    b_from: str = Query(**_MONTH_QUERY),
    b_to: str = Query(**_MONTH_QUERY),
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """How one parameter changed at one site between period A (``a_from`` to ``a_to``) and period B (YYYY-MM, both included).

    Works for both sources (Waterbase: monthly data; sandbox: annual aggregates, flagged ``annual-only``). Deterministic
    arithmetic on stored values, no model: per period ``n_samples``, ``mean`` (sum / n of the quantified values), ``min``,
    ``max``, ``n_below_loq``, the limit where the project has one (with ``limit_basis``), the absolute change (mean_B minus
    mean_A), the relative percent, the direction and ``crossed_limit``. ``data_range`` gives the first and last month the site
    holds, so a client can propose the latest available period when a period lies beyond the data (flag
    ``period-outside-data``; nothing is shifted or filled). A screening aid, not a compliance assessment
    (``approximation_notice``, localised when ``language`` is given). 404 unknown site, 422 invalid or inverted period or
    unknown parameter. See docs/period_change.md.
    """
    code = resolve_language(language)
    try:
        period_a, period_b = change_service.parse_periods(a_from, a_to, b_from, b_to)
        payload = change_service.site_change(site_id, parameter, period_a, period_b, _sandbox_access())
    except change_service.ChangeError as error:
        raise _http_error(error) from error
    return {**payload, "language": code, **change_service.notices(code)}


@router.get(
    "/countries/{country_code}/change",
    response_model=CountryChangeResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def country_change(
    country_code: str = Path(pattern=r"^[A-Za-z]{2}$"),
    parameter: str = Query(min_length=1, max_length=64),
    a_from: str = Query(**_MONTH_QUERY),
    a_to: str = Query(**_MONTH_QUERY),
    b_from: str = Query(**_MONTH_QUERY),
    b_to: str = Query(**_MONTH_QUERY),
    source: SiteSource | None = None,
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """How one parameter changed across the sites of one country (``GR``; ``EL`` is read as ``GR``) between two periods.

    Uses PAIRED sites only: the sites that meet the minimum number of samples in BOTH periods; the same site set is used for
    both periods, a site present in one period only is excluded (``n_sites_excluded`` and ``exclusion_reasons``), never
    imputed. Reports the mean of the site means per period, its change, the median of the per-site relative changes, how
    many sites increased, decreased or stayed unchanged, and, for river sites, how many were over the limit in each period.
    One result per source (``results``), never combined; ``source`` narrows to one. Same flags, notices and errors as
    GET /sites/{site_id}/change. See docs/period_change.md.
    """
    code = resolve_language(language)
    country = normalise_country(country_code)
    try:
        period_a, period_b = change_service.parse_periods(a_from, a_to, b_from, b_to)
        payload = change_service.country_change(
            country, parameter, period_a, period_b, _sandbox_access(), _known_country, source
        )
    except change_service.ChangeError as error:
        raise _http_error(error) from error
    return {**payload, "language": code, **change_service.notices(code)}
