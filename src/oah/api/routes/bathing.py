"""EEA bathing waters: the classification routes and the individual-samples routes."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from oah.api import change as change_service
from oah.api import samples as samples_api
from oah.api.change_schemas import BathingChangeResponse
from oah.api.payloads import _http_error
from oah.api.samples_schemas import (
    BathingSamplesChangeResponse,
    BathingSamplesCountryChangeResponse,
    BathingSamplesResponse,
)
from oah.api.schemas import BathingWaterHistoryResponse, BathingWatersResponse, ErrorResponse
from oah.api.services import resolve_language
from oah.bathing import service as bathing
from oah.bathing.constants import ATTRIBUTION as BATHING_ATTRIBUTION
from oah.bathing.constants import NOTICE as BATHING_NOTICE
from oah.bathing.constants import PROFILE_NOTE as BATHING_PROFILE_NOTE
from oah.bathing.constants import SOURCE_ID as BATHING_SOURCE
from oah.bathing_samples import service as bathing_samples
from oah.chat import normalise_country

router = APIRouter()


@router.get("/bathing-waters", response_model=BathingWatersResponse)
def bathing_waters(
    country: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$"),
    q: str | None = Query(default=None, max_length=64),
    water_type: str | None = Query(default=None, alias="type", max_length=64),
    quality: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict[str, Any]:
    """EEA bathing waters of Greece and Italy (Norway has no row in the file) with the classification of their latest season.

    A CLASSIFICATION under Directive 2006/7/EC, not a concentration of E. coli or enterococci and not legal compliance
    (``notice``). ``country`` (EL is read as GR), ``q`` (part of a name or identifier), ``type`` (as written in the file,
    for example ``coastalBathingWater``) and ``quality`` (latest season, the file's string such as ``1 - Excellent`` or
    its label ``Excellent``) narrow the list; ``limit`` (default 200, at most 500) and ``offset`` page it. Without a built
    store the list is empty and ``bathing_water.state`` says ``not-built``. See docs/bathing_water_store.md.
    """
    wanted_country = normalise_country(country) if country else None
    total, items = bathing.list_page(wanted_country, q, water_type, quality, limit, offset)
    return {
        "origin": BATHING_SOURCE,
        "data_freshness": bathing.freshness(),
        "attribution": BATHING_ATTRIBUTION,
        "notice": BATHING_NOTICE,
        "bathing_water": bathing.status_payload(),
        "bathing_waters": items,
        "total_matching": total,
        "returned": len(items),
        "limit": limit,
        "offset": offset,
        "truncated": offset + len(items) < total,
    }


@router.get(
    "/bathing-waters/change",
    response_model=BathingChangeResponse,
    responses={422: {"model": ErrorResponse}},
)
def bathing_waters_change(
    country: str = Query(pattern=r"^[A-Za-z]{2}$"),
    season_a: int = Query(ge=1900, le=2100),
    season_b: int = Query(ge=1900, le=2100),
    water_type: str | None = Query(default=None, alias="type", max_length=64),
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """How the bathing-water CLASSIFICATIONS of one country moved between two seasons.

    Counts only, using the archive README's order of four classes (excellent, good, sufficient, poor): bathing waters
    with the class "not classified" or "good or sufficient" (or a blank class) in either season are not comparable and are
    counted separately; a bathing water present in one season only is counted as such. No concentration, no threshold.
    ``type`` narrows to one water type; ``language`` localises the fixed notices. See docs/bathing_water_store.md.
    """
    code = resolve_language(language)
    return change_service.bathing_change(normalise_country(country), season_a, season_b, water_type, code)


@router.get(
    "/bathing-waters/{bw_id}",
    response_model=BathingWaterHistoryResponse,
    responses={404: {"model": ErrorResponse}},
)
def bathing_water_history(bw_id: str) -> dict[str, Any]:
    """The classification of one bathing water by season (quality class, monitoring calendar, management status).

    Coordinates can be null. ``bw_profile_url`` is plain text from the file, never fetched by this API. A
    classification, not a concentration and not legal compliance (``notice``).
    """
    found = bathing.find(bw_id)
    if found is None:
        state = bathing.status_payload()["state"]
        suffix = "" if state == "ready" else f" (the bathing-water store is {state}; see GET /countries)"
        raise HTTPException(status_code=404, detail=f"Unknown bathing water {bw_id[:128]!r}{suffix}.")
    history = found.pop("history")
    return {
        "origin": BATHING_SOURCE,
        "data_freshness": bathing.freshness(),
        "attribution": BATHING_ATTRIBUTION,
        "notice": BATHING_NOTICE,
        "profile_note": BATHING_PROFILE_NOTE,
        "bathing_water": found,
        "history": history,
        "samples": bathing_samples.link_for(bw_id),
    }


@router.get(
    "/bathing-waters/samples/change",
    response_model=BathingSamplesCountryChangeResponse,
    responses={422: {"model": ErrorResponse}},
)
def bathing_samples_country_change(
    country: str = Query(pattern=r"^[A-Za-z]{2}$"),
    a_from: str = Query(min_length=7, max_length=7),
    a_to: str = Query(min_length=7, max_length=7),
    b_from: str = Query(min_length=7, max_length=7),
    b_to: str = Query(min_length=7, max_length=7),
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """How the individual E. coli and intestinal enterococci samples of one country changed between two periods.

    Periods are ``YYYY-MM`` ranges, both ends included. Uses PAIRED bathing waters only (enough quantified samples in BOTH
    periods; the same set in both), reports the mean of the site means and the median of the site medians per period, the
    change of each, the median of the per-site relative changes and the counts that increased, decreased or stayed. No
    significance is tested and no threshold exists, so no limit crossing is reported. Values flagged below the limit of
    detection, missing or of an unrecognised status are counted apart. ``EL`` is read as ``GR``; Norway has no bathing-water
    samples. A country with none answers 200 with the flag ``no-samples-for-country``. See docs/bathing_samples_store.md.
    """
    code = resolve_language(language)
    try:
        period_a, period_b = change_service.parse_periods(a_from, a_to, b_from, b_to)
        return samples_api.bathing_samples_country_change(normalise_country(country), period_a, period_b, code)
    except change_service.ChangeError as error:
        raise _http_error(error) from error


@router.get(
    "/bathing-waters/{bw_id}/samples",
    response_model=BathingSamplesResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def bathing_water_samples(
    bw_id: str,
    date_from: date | None = None,
    date_to: date | None = None,
    season: int | None = Query(default=None, ge=1900, le=2100),
    limit: int = Query(default=200, ge=1, le=500),
    order: Literal["asc", "desc"] = "asc",
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """Individual E. coli and intestinal enterococci results (cfu/100ml) of one bathing water, with a summary.

    ``date_from`` and ``date_to`` are ISO days (sample date, both included), ``season`` the bathing season, ``limit`` 1 to
    500 (default 200), ``order`` by sample date (``asc`` or ``desc``). Each sample carries both values, both EEA statuses and
    the sample status. ``summary`` covers ALL matching samples, not only the page: counts by kind, minimum, maximum, mean and
    exact median of the quantified values. Values flagged below the limit of detection, missing or of an unrecognised status
    are counted apart and never shown as a plain number. These are individual results, not a classification and not a
    compliance assessment, and no threshold is applied. 404 for an unknown bathing water; a store that is not built answers
    with ``bathing_samples.state``. See docs/bathing_samples_store.md.
    """
    code = resolve_language(language)
    try:
        return samples_api.bathing_samples(bw_id, date_from, date_to, season, limit, order == "desc", code)
    except change_service.ChangeError as error:
        raise _http_error(error) from error


@router.get(
    "/bathing-waters/{bw_id}/samples/change",
    response_model=BathingSamplesChangeResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def bathing_water_samples_change(
    bw_id: str,
    a_from: str = Query(min_length=7, max_length=7),
    a_to: str = Query(min_length=7, max_length=7),
    b_from: str = Query(min_length=7, max_length=7),
    b_to: str = Query(min_length=7, max_length=7),
    language: str | None = Query(default=None, min_length=2, max_length=12),
) -> dict[str, Any]:
    """How the individual samples of one bathing water changed between period A and period B (``YYYY-MM``, both included).

    Per indicator and period: ``n_samples`` (quantified values), mean, median, min, max and the counts of values flagged
    below the limit of detection, missing or unrecognised; the change of the mean and of the median (absolute, relative
    percent, direction). The same coverage rules and flags as GET /sites/{site_id}/change (a period needs 3 quantified
    samples; ``period-outside-data`` with ``data_range`` when a period lies beyond the data; nothing is shifted). Bathing
    waters are sampled in the bathing season only, so a period with other months carries ``partial-period``. No significance
    claim, no limit and no limit crossing. See docs/bathing_samples_store.md.
    """
    code = resolve_language(language)
    try:
        period_a, period_b = change_service.parse_periods(a_from, a_to, b_from, b_to)
        return samples_api.bathing_samples_change(bw_id, period_a, period_b, code)
    except change_service.ChangeError as error:
        raise _http_error(error) from error
