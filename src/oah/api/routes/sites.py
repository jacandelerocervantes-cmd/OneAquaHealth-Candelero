"""Sites, countries, per-site measurements and the CCME index of one sandbox site."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query

from oah.api import deps, payloads
from oah.api.payloads import _countries_overview, _official_observations
from oah.api.schemas import (
    CountriesResponse,
    ErrorResponse,
    FhirBundleResponse,
    IndexResponse,
    ParameterGroup,
    SiteMeasurementsResponse,
    SitesResponse,
    SiteSource,
)
from oah.api.services import get_data_freshness
from oah.bathing import service as bathing
from oah.bathing_samples import service as bathing_samples
from oah.chat import normalise_country
from oah.fhir.output.measurements import NoValuesError, measurements_bundle
from oah.indices.apply_to_sandbox import list_sites_with_status
from oah.indices.regimes import INTERPRETATION_NOTICE
from oah.indices.site_measurements import location_known, parameter_names, site_measurement_records
from oah.timeutil import format_utc, utc_now
from oah.waterbase import service as waterbase
from oah.waterbase.mapping import ATTRIBUTION as WATERBASE_ATTRIBUTION
from oah.waterbase.mapping import GROUP_WATER_CHEMISTRY
from oah.waterbase.mapping import SOURCE_ID as WATERBASE_SOURCE
from oah.waterbase.measurements import INDEX_STATUS as WATERBASE_INDEX_STATUS
from oah.waterbase.measurements import site_info as waterbase_site_info

router = APIRouter()


@router.get("/sites", response_model=SitesResponse)
def sites(
    country: str | None = Query(default=None, pattern=r"^[A-Za-z]{2}$"),
    q: str | None = Query(default=None, max_length=64),
    source: SiteSource | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=1_000_000),
) -> dict[str, Any]:
    """Sites for a map or list view, from the sandbox (each joined to its own CCME WQI result, if computable) and from
    the EEA Waterbase store (annual measurements only, ``source`` ``real-eea-waterbase``).

    Bounded: ``limit`` (default 200, at most 500) and ``offset`` page through the matches, sandbox sites first.
    ``country`` (EL is read as GR), ``q`` (part of a name or id) and ``source`` narrow the list. A Waterbase site
    can have no coordinates (``location_status`` ``no-location``). Without a built store only sandbox sites appear.
    """
    wanted_country = normalise_country(country) if country else None
    text = q.strip().lower() if q and q.strip() else None
    use_sandbox = source in (None, "real-sandbox")
    use_waterbase = source in (None, WATERBASE_SOURCE)
    sandbox: list[dict[str, Any]] = []
    freshness: Any
    if use_sandbox:
        sandbox = [
            site
            for site in list_sites_with_status(_official_observations(), deps.get_cached_locations())
            if (wanted_country is None or site.get("limit_country") == wanted_country)
            and (text is None or text in str(site["name"]).lower() or text in str(site["id"]).lower())
        ]
        freshness = get_data_freshness()
    else:
        freshness = waterbase.freshness()
    taken = sandbox[offset : offset + limit]
    stored_total = 0
    stored: list[dict[str, Any]] = []
    if use_waterbase:
        room = limit - len(taken)
        stored_total, stored = waterbase.sites_page(wanted_country, q, max(room, 1), max(0, offset - len(sandbox)))
        stored = stored[: max(room, 0)]
    found: set[str] = ({"real-sandbox"} if taken else set()) | ({WATERBASE_SOURCE} if stored else set())
    if len(found) == 2:
        origin = "real-mixed"
    elif found:
        origin = next(iter(found))
    else:
        origin = WATERBASE_SOURCE if source == WATERBASE_SOURCE else "real-sandbox"
    total = len(sandbox) + stored_total
    returned = len(taken) + len(stored)
    return {
        "origin": origin,
        "data_freshness": freshness,
        "interpretation_notice": INTERPRETATION_NOTICE,
        "sites": [*taken, *stored],
        "sources": sorted(found),
        "total_matching": total,
        "returned": returned,
        "limit": limit,
        "offset": offset,
        "truncated": offset + returned < total,
        "waterbase": waterbase.status_payload(),
    }


@router.get("/countries", response_model=CountriesResponse)
def countries() -> dict[str, Any]:
    """Distinct countries with their limit regime, limit sources, site counts and a per-source breakdown (see docs/api_routes.md)."""
    overview, without_country = _countries_overview()
    held = any(item["measurement_only_sites"] for item in overview)
    return {
        "origin": "real-mixed" if held else "real-sandbox",
        "data_freshness": get_data_freshness(),
        "interpretation_notice": INTERPRETATION_NOTICE,
        "countries": overview,
        "sites_without_country": without_country,
        "waterbase": waterbase.status_payload(),
        "bathing_water": bathing.status_payload(),
        "bathing_samples": bathing_samples.status_payload(),
    }


@router.get(
    "/sites/{location_id}/measurements",
    response_model=SiteMeasurementsResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def site_measurements(
    location_id: str,
    parameter: str | None = Query(default=None, max_length=64),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    group: ParameterGroup | None = None,
    resolution: Literal["annual", "monthly"] = "annual",
) -> dict[str, Any]:
    """Per-parameter measurements of one site (official records only), each with the limit it was judged against.

    ``parameter`` must be one of the closed names in ``oah.indices.water_parameter_limits`` (for a Waterbase site
    also the label of a listed-but-not-compared or measurement-only determinand); the dates are ISO days (UTC) and keep
    records whose period overlaps them. ``group`` (``water-chemistry``, ``solids-turbidity`` or ``organic-matter``)
    keeps only the parameters of that group; every record carries its ``group``. At most ``limit`` records are
    returned. A Waterbase site (``source`` ``real-eea-waterbase``) returns annual aggregates with ``n``, mean, min and
    max; the solids-turbidity and organic-matter parameters are measurement only (no limit regime, status
    ``not-scored``); see docs/waterbase_store.md.

    ``resolution`` (``annual`` by default, additive) asks a Waterbase site for one record per MONTH (``monthly``, each with
    its ``month``); the number of records is still bounded by ``limit``. Sandbox records are period summaries and have no
    monthly resolution: ``monthly`` for a sandbox site is a 422.
    """
    stored_site = waterbase.find_site(location_id)  # Waterbase first: a local read, no sandbox fetch
    known = parameter_names() + (waterbase.known_parameter_names() if stored_site is not None else [])
    if parameter is not None and parameter.strip().lower() not in {name.lower() for name in known}:
        raise HTTPException(status_code=422, detail=f"Unknown parameter {parameter!r}; known: {sorted(known)}.")
    if date_from is not None and date_to is not None and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must not be after date_to.")
    if stored_site is not None:
        total, stored_records = waterbase.measurement_page(
            stored_site, parameter, date_from.year if date_from else None, date_to.year if date_to else None, limit, group,
            resolution,
        )
        return {
            "origin": WATERBASE_SOURCE,
            "source": WATERBASE_SOURCE,
            "resolution": resolution,
            "data_freshness": waterbase.freshness(),
            "interpretation_notice": INTERPRETATION_NOTICE,
            "attribution": WATERBASE_ATTRIBUTION,
            "index_status": WATERBASE_INDEX_STATUS,
            "site": waterbase_site_info(stored_site),
            "location_id": location_id,
            "parameter": parameter,
            "group": group,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
            "limit": limit,
            "total_matching": total,
            "returned": len(stored_records),
            "truncated": total > len(stored_records),
            "records": stored_records,
        }
    observations = _official_observations()
    locations = deps.get_cached_locations()
    if not location_known(location_id, observations, locations):
        raise HTTPException(status_code=404, detail=f"Unknown site {location_id!r}.")
    if resolution == "monthly":
        raise HTTPException(
            status_code=422,
            detail="Monthly resolution exists only for Waterbase sites; sandbox records are period summaries (annual aggregates).",
        )
    # Sandbox records use the closed parameter names, the same ones the Waterbase chemistry is mapped to.
    records = [
        {**record, "group": GROUP_WATER_CHEMISTRY}
        for record in site_measurement_records(observations, locations, location_id, parameter, date_from, date_to)
    ]
    if group is not None:
        records = [record for record in records if record["group"] == group]
    return {
        "origin": "real-sandbox",
        "resolution": "period-summary",
        "data_freshness": get_data_freshness(),
        "interpretation_notice": INTERPRETATION_NOTICE,
        "location_id": location_id,
        "parameter": parameter,
        "group": group,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "limit": limit,
        "total_matching": len(records),
        "returned": min(len(records), limit),
        "truncated": len(records) > limit,
        "records": records[:limit],
    }


@router.get(
    "/sites/{location_id}/fhir",
    response_model=FhirBundleResponse,
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def site_fhir(
    location_id: str,
    parameter: str | None = Query(default=None, max_length=64),
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=200, ge=1, le=500),
    group: ParameterGroup | None = None,
    resolution: Literal["annual", "monthly"] = "annual",
) -> dict[str, Any]:
    """The measurements of ONE site as a FHIR R4 collection Bundle in JSON (read-only; same selection as ``/measurements``).

    The Bundle holds a ``Location``, one ``Observation`` per measurement that has a numeric value (the parameter is text
    only: no code is invented; a UCUM unit code only where the unit is written the UCUM way), a software ``Device`` and a
    ``Provenance`` naming the source and its attribution. Each resource carries the project-defined data-origin tag.
    It does not claim conformance to the OneAquaHealth profiles. A selection without any numeric value is a 404.
    See docs/fhir_mapping.md, section "Site measurements export".
    """
    payload = site_measurements(location_id, parameter, date_from, date_to, limit, group, resolution)
    try:
        return measurements_bundle(payload, format_utc(utc_now()))
    except NoValuesError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/indices/{location_id}", response_model=IndexResponse, responses={404: {"model": ErrorResponse}})
def indices_for_location(location_id: str) -> dict[str, Any]:
    """CCME Water Quality Index for one real sandbox Location, if computable.

    location_id is the bare id (e.g. "Loc-Almyros"), not the full "Location/..." reference.
    """
    return {
        **payloads._indices_payload(location_id),
        "data_freshness": get_data_freshness(),
        "interpretation_notice": INTERPRETATION_NOTICE,
    }
