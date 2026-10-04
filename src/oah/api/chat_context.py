"""The read-only data access of the chat tools (``ToolContext``), built from the same functions the REST routes call.

``_chat_tool_context`` is the one place where the chat's tools are wired to the data; there is no HTTP self-call. Seams
are looked up at call time through ``oah.api.deps`` and ``oah.api.payloads`` so tests can replace them.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import HTTPException

from oah.api import change as change_service
from oah.api import deps, payloads
from oah.api import samples as samples_api
from oah.api.payloads import _countries_overview, _known_country, _official_observations, _sandbox_access
from oah.api.services import get_data_freshness
from oah.bathing import service as bathing
from oah.bathing_samples import service as bathing_samples
from oah.chat import ToolContext
from oah.chat.errors import ToolError
from oah.i18n.languages import SOURCE_LANGUAGE
from oah.indices.apply_to_sandbox import list_sites_with_status
from oah.indices.period_change import Period
from oah.indices.site_measurements import location_known, site_measurement_records
from oah.ingest.official import split_official
from oah.qc.report import build_report
from oah.waterbase import service as waterbase
from oah.waterbase.measurements import site_entry as waterbase_site_entry


def _chat_tool_context(country: str | None) -> ToolContext:
    """The read-only data access of the chat tools: the same functions the REST routes call, no HTTP self-call."""

    def sites() -> list[dict[str, Any]]:
        return list_sites_with_status(_official_observations(), deps.get_cached_locations())

    def countries_overview_() -> tuple[list[dict[str, Any]], int]:
        return _countries_overview()

    def stored_sites(country_code: str | None, name_query: str | None, limit: int) -> tuple[int, list[dict[str, Any]]]:
        return waterbase.sites_page(country_code, name_query, limit, 0)

    def stored_site(location_id: str) -> dict[str, Any] | None:
        found = waterbase.find_site(location_id)
        return waterbase_site_entry(found) if found is not None else None

    def bathing_list(
        country_code: str | None, name_query: str | None, quality: str | None, water_type: str | None, limit: int
    ) -> tuple[int, list[dict[str, Any]]]:
        return bathing.list_page(country_code, name_query, water_type, quality, limit, 0)

    def bathing_get(bw_id: str) -> dict[str, Any] | None:
        return bathing.find(bw_id)

    def samples_get(
        bw_id: str, date_from: date | None, date_to: date | None, season: int | None, limit: int
    ) -> dict[str, Any] | None:
        try:
            return samples_api.bathing_samples(bw_id, date_from, date_to, season, limit, True, SOURCE_LANGUAGE)
        except change_service.ChangeError as error:
            if error.status_code == 404 and bathing_samples.status_payload()["state"] == "ready":
                return None  # unknown identifier (the tool says so); a store that is not ready is reported by the detail below
            raise ToolError(error.detail) from error

    def samples_compare_site(bw_id: str, period_a: Period, period_b: Period) -> dict[str, Any]:
        try:
            return samples_api.bathing_samples_change(bw_id, period_a, period_b, SOURCE_LANGUAGE)
        except change_service.ChangeError as error:
            raise ToolError(error.detail) from error

    def samples_compare_country(country_code: str, period_a: Period, period_b: Period) -> dict[str, Any]:
        try:
            return samples_api.bathing_samples_country_change(country_code, period_a, period_b, SOURCE_LANGUAGE)
        except change_service.ChangeError as error:  # busy (503) or too large (422): a tool error the model can report
            raise ToolError(error.detail) from error

    def index(location_id: str) -> dict[str, Any] | None:
        try:
            return payloads._indices_payload(location_id)
        except HTTPException:  # 404: no evaluated or skipped entry for that site
            return None

    def measurements(
        location_id: str, parameter: str | None, date_from: date | None, date_to: date | None
    ) -> list[dict[str, Any]] | None:
        held = waterbase.find_site(location_id)
        if held is not None:  # one more than the tool's maximum, so it can tell that the result was cut
            return waterbase.measurement_page(
                held, parameter, date_from.year if date_from else None, date_to.year if date_to else None, 501
            )[1]
        observations, locations = _official_observations(), deps.get_cached_locations()
        if not location_known(location_id, observations, locations):
            return None
        return site_measurement_records(observations, locations, location_id, parameter, date_from, date_to)

    def qc() -> dict[str, Any]:
        official, excluded = split_official(deps.get_cached_observations())
        return {
            **build_report(official, default_origin="real-sandbox"),
            "excluded_observations": excluded,
            "excluded_observations_total": sum(excluded.values()),
        }

    def compare_site(site_id: str, parameter: str, period_a: Period, period_b: Period) -> dict[str, Any]:
        try:
            return change_service.site_change(site_id, parameter, period_a, period_b, _sandbox_access())
        except change_service.ChangeError as error:
            raise ToolError(error.detail) from error

    def compare_country(country_code: str, parameter: str, period_a: Period, period_b: Period) -> dict[str, Any]:
        try:
            return change_service.country_change(
                country_code, parameter, period_a, period_b, _sandbox_access(), _known_country, None
            )
        except change_service.ChangeError as error:
            raise ToolError(error.detail) from error

    def bathing_compare(country_code: str, season_a: int, season_b: int) -> dict[str, Any]:
        return change_service.bathing_change(country_code, season_a, season_b, None, SOURCE_LANGUAGE)

    return ToolContext(
        country=country, sites=sites, countries=countries_overview_, index=index,
        measurements=measurements, qc=qc, freshness=get_data_freshness,
        waterbase_sites=stored_sites, waterbase_site=stored_site,
        bathing_list=bathing_list, bathing_get=bathing_get,
        compare_site=compare_site, compare_country=compare_country, bathing_compare=bathing_compare,
        samples_get=samples_get, samples_compare_site=samples_compare_site, samples_compare_country=samples_compare_country,
        external=payloads.get_external_context(),
    )
