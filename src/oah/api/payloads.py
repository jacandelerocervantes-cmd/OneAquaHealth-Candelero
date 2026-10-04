"""Payload assembly shared by the REST routes and the chat tool context.

Package-internal (the underscore names are imported by ``oah.api.routes`` and ``oah.api.chat_context``). Two names here
are test seams (``_indices_payload`` and ``get_external_context``): callers elsewhere look them up as ``payloads.NAME`` at
call time so a monkeypatch on this module is honoured. The sandbox accessors come from ``oah.api.deps`` the same way.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from oah.api import change as change_service
from oah.api import deps
from oah.api.services import get_data_freshness
from oah.bathing import service as bathing
from oah.bathing_samples import service as bathing_samples
from oah.external.service import ExternalContext
from oah.external.sites import SiteLocator
from oah.indices.apply_to_sandbox import apply_ccme_wqi_to_sandbox, data_quality, limits_note, list_sites_with_status
from oah.external.constants import PROVIDER_DISCHARGE, PROVIDER_GBIF, PROVIDER_WEATHER
from oah.external.runtime import get_runtime
from oah.i18n.strings import load_strings
from oah.indices import catalog
from oah.indices.countries import countries_overview
from oah.indices.regimes import INTERPRETATION_NOTICE, countries_by_location_ref, country_name, known_countries
from oah.indices.sandbox_change import country_ranges as sandbox_country_ranges
from oah.ingest.official import split_official
from oah.waterbase import service as waterbase
from oah.waterbase.mapping import SOURCE_ID as WATERBASE_SOURCE
from oah.waterbase.measurements import site_entry as waterbase_site_entry


def _official_observations() -> list[dict[str, Any]]:
    """The cached sandbox Observations that are official OAH records (see oah.ingest.official)."""
    return split_official(deps.get_cached_observations())[0]


def _bathing_blocks() -> dict[str, dict[str, Any]]:
    """The ``bathing_water`` block of each country, each with its ``samples`` block."""
    samples = bathing_samples.country_blocks()
    return {code: {**block, "samples": samples.get(code)} for code, block in bathing.country_blocks().items()}


def _overview_with_sites() -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    """``(countries, sites_without_country, sandbox sites)``: the sandbox sites are returned so a caller that also needs
    them (the catalogue) does not compute the indices twice."""
    locations = deps.get_cached_locations()
    observations = _official_observations()
    sandbox_sites = list_sites_with_status(observations, locations)
    overview, without_country = countries_overview(
        sandbox_sites, locations, waterbase.country_summaries(), _bathing_blocks(),
        sandbox_country_ranges(observations, locations),
    )
    return overview, without_country, sandbox_sites


def _countries_overview() -> tuple[list[dict[str, Any]], int]:
    """The countries of both real sources (sandbox sites joined to the Waterbase store summaries, when it is built)."""
    overview, without_country, _ = _overview_with_sites()
    return overview, without_country


def _sandbox_access() -> change_service.SandboxAccess:
    """The sandbox data for a comparison, read through this module's own (patchable) names and only when needed."""
    return change_service.SandboxAccess(
        observations=_official_observations, locations=deps.get_cached_locations, freshness=lambda: dict(get_data_freshness())
    )


def _known_country(code: str, source: str | None) -> bool:
    """Whether ``code`` is a country of ``GET /countries`` (a Waterbase-only question never touches the sandbox)."""
    if source == WATERBASE_SOURCE:
        return code in set(known_countries()) | {item.country for item in waterbase.country_summaries()}
    return code in {item["code"] for item in _countries_overview()[0]}


def _http_error(error: change_service.ChangeError) -> HTTPException:
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after else None
    return HTTPException(status_code=error.status_code, detail=error.detail, headers=headers)


def _stored_site_entry(site_id: str) -> dict[str, Any] | None:
    found = waterbase.find_site(site_id)
    return waterbase_site_entry(found) if found is not None else None


def _sandbox_site_entries() -> list[dict[str, Any]]:
    """The sandbox Locations as ``/sites`` entries (id, name, position, country), without computing any index."""
    locations = deps.get_cached_locations()
    countries = countries_by_location_ref(locations)
    entries: list[dict[str, Any]] = []
    for location in locations:
        location_id = location.get("id")
        position = location.get("position")
        if not location_id or not isinstance(position, dict):
            continue
        entries.append(
            {
                "id": location_id, "name": location.get("name", location_id), "latitude": position.get("latitude"),
                "longitude": position.get("longitude"), "limit_country": countries.get(f"Location/{location_id}"),
                "source": "real-sandbox",
            }
        )
    return entries


def get_external_context() -> ExternalContext:
    """The external-context facade over the stores' sites (the same read functions as the routes), exposed for tests."""
    return ExternalContext(SiteLocator(waterbase=_stored_site_entry, sandbox=_sandbox_site_entries, bathing=bathing.find))


def _indices_payload(location_id: str) -> dict[str, Any]:
    """Per-location CCME result without freshness (the freshness age changes every second)."""
    observations = _official_observations()
    results = apply_ccme_wqi_to_sandbox(observations, deps.get_cached_locations())
    location_ref = f"Location/{location_id}"

    quality = data_quality(results)
    note = limits_note(results)
    for entry in results["evaluated_locations"]:
        if entry["location_ref"] == location_ref:
            return {"origin": "real-sandbox", "status": "evaluated", **entry, "data_quality": quality, "objective_limits_source": note}
    for entry in results["skipped_locations"]:
        if entry["location_ref"] == location_ref:
            return {"origin": "real-sandbox", "status": "skipped", **entry, "data_quality": quality, "objective_limits_source": note}

    raise HTTPException(
        status_code=404,
        detail=(
            f"No water-quality-profile sandbox observations found for {location_ref}. "
            "The location may still have sandbox Observations under a different profile "
            "(e.g. population-health measures), which this index does not evaluate."
        ),
    )


def _catalog_payload(country: str, language: str) -> dict[str, Any]:
    """The ``GET /catalog`` answer for one (already normalised) country code; a 422 that lists the known codes otherwise.

    An unreachable sandbox without a snapshot (503 from the accessors) does not fail the catalogue: the sandbox counts as
    unavailable, so the indices that need it do not apply (``data-not-loaded``) and the stores still answer.
    """
    sandbox_up = True
    try:
        overview, _, sandbox_sites = _overview_with_sites()
    except HTTPException as error:
        if error.status_code != 503:
            raise
        sandbox_up = False
        sandbox_sites = []
        overview, _ = countries_overview([], [], waterbase.country_summaries(), _bathing_blocks(), {})
    entries = {item["code"]: item for item in overview}
    if country not in entries:
        raise HTTPException(status_code=422, detail=f"Unknown country {country!r}; known: {sorted(entries)}.")
    waterbase_state, bathing_state, samples_state = waterbase.status_payload(), bathing.status_payload(), bathing_samples.status_payload()
    runtime = get_runtime()
    switches = {
        "weather": runtime.enabled(PROVIDER_WEATHER),
        "discharge": runtime.enabled(PROVIDER_DISCHARGE),
        "species": runtime.enabled(PROVIDER_GBIF),
    }
    availability = catalog.Availability(
        sandbox=sandbox_up,
        waterbase=waterbase_state["state"] == "ready",
        bathing=bathing_state["state"] == "ready",
        samples=samples_state["state"] == "ready",
        **switches,
    )
    evidence = catalog.evidence_for(
        entries[country], sandbox_sites, country, waterbase.located_counts(), bathing.located_counts(),
        bathing_samples.country_blocks(),
    )
    strings = load_strings(language)
    families, applicable = catalog.build_catalog(evidence, availability, strings.get)
    held = any(item["measurement_only_sites"] for item in overview)
    return {
        "origin": "real-mixed" if held else "real-sandbox",
        "data_freshness": get_data_freshness(),
        "interpretation_notice": INTERPRETATION_NOTICE,
        "language": strings.code,
        "country": country,
        "country_name": country_name(country),
        "families": families,
        "applicable_count": applicable,
        "stores": {
            "sandbox": "available" if sandbox_up else "unavailable",
            "waterbase": waterbase_state,
            "bathing_water": bathing_state,
            "bathing_samples": samples_state,
            "external": {"enabled": runtime.settings.enabled, **switches},
        },
    }
