"""Assembly of the bathing-water SAMPLES answers, shared by the REST routes and the chat tools.

No new computation: ``oah.bathing_samples.service`` (the samples and their summary) and ``oah.bathing_samples.change`` (the
period comparison over ``oah.indices.period_change``) do the work; this module labels the answer (origin, attribution, data
freshness) and attaches the fixed notices in the requested language. Errors are ``ChangeError`` (404 unknown bathing water,
422 invalid input). The values are individual sample results: no threshold, limit or classification is applied or implied.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from oah.api.change import ChangeError, scope_limits
from oah.bathing_samples import change as samples_change
from oah.bathing_samples import service as samples_service
from oah.bathing_samples import store as samples_store
from oah.bathing_samples.constants import ATTRIBUTION, DEFAULT_LIMIT, MAX_LIMIT, SOURCE_ID, UNIT
from oah.i18n.strings import load_strings
from oah.indices.period_change import Period

NO_COUNTRY_SAMPLES_NOTE = "no-samples-for-country"


def notices(language: str) -> dict[str, str]:
    """The fixed notices of a samples answer in ``language`` (a canonical registry code)."""
    strings = load_strings(language)
    return {
        "notice": strings.get("bathing_samples_notice"),
        "no_threshold_notice": strings.get("bathing_no_threshold_notice"),
        "flagged_values_note": strings.get("bathing_flagged_values_note"),
    }


def _header(language: str) -> dict[str, Any]:
    return {
        "origin": SOURCE_ID,
        "data_freshness": samples_service.freshness(),
        "attribution": ATTRIBUTION,
        "language": language,
        "unit": UNIT,
        "bathing_samples": samples_service.status_payload(),
    }


def bathing_samples(
    bw_id: str, date_from: date | None, date_to: date | None, season: int | None, limit: int, descending: bool, language: str
) -> dict[str, Any]:
    """The samples of one bathing water with a summary. 404 when neither the classification nor the samples store knows it."""
    if date_from is not None and date_to is not None and date_from > date_to:
        raise ChangeError(422, "date_from must not be after date_to.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise ChangeError(422, f"limit must be an integer from 1 to {MAX_LIMIT}.")
    found = samples_service.samples_for(bw_id, date_from, date_to, season, limit, descending)
    if found is None:
        state = samples_service.status_payload()["state"]
        suffix = "" if state == "ready" else f" (the bathing-water samples store is {state}; see GET /countries)"
        raise ChangeError(404, f"Unknown bathing water {bw_id[:128]!r}{suffix}.")
    return {**_header(language), **notices(language), "limit": limit, "truncated": found["total_matching"] > found["returned"], **found}


def _change_notices(language: str) -> dict[str, str]:
    return {**notices(language), "change_notice": load_strings(language).get("bathing_samples_change_notice")}


def bathing_samples_change(bw_id: str, period_a: Period, period_b: Period, language: str) -> dict[str, Any]:
    """The comparison of one bathing water's samples between two periods (404 when the bathing water is unknown)."""
    site = samples_service.known_bathing_water(bw_id)
    if site is None:
        state = samples_service.status_payload()["state"]
        suffix = "" if state == "ready" else f" (the bathing-water samples store is {state}; see GET /countries)"
        raise ChangeError(404, f"Unknown bathing water {bw_id[:128]!r}{suffix}.")
    result = samples_change.site_change(bw_id, site["country"], period_a, period_b)
    return {
        **_header(language),
        **_change_notices(language),
        "scope": {"type": "bathing-water", "id": site["id"], "code": None, "name": site["name"], "country": site["country"]},
        **result,
    }


def bathing_samples_country_change(country: str, period_a: Period, period_b: Period, language: str) -> dict[str, Any]:
    """The comparison of one country's samples (EL is read as GR) over paired bathing waters; 200 with a flag when it has none.

    503 with ``Retry-After`` when the process is busy with other country comparisons, 422 when the read is too large."""
    code = samples_store.normalise_country(country)
    flags: list[str] = []
    status = samples_store.store_status()
    held = {item.country for item in samples_store.countries_summary()} if status.ready else set()
    if not status.ready:
        flags.append("store-not-ready")
    elif code not in held:
        flags.append(NO_COUNTRY_SAMPLES_NOTE)
    with scope_limits():
        result = samples_change.country_change(code, period_a, period_b)
    return {
        **_header(language),
        **_change_notices(language),
        "scope": {"type": "country", "id": None, "code": code, "name": None, "country": code},
        **result,
        "flags": flags,
    }


__all__ = [
    "ChangeError", "DEFAULT_LIMIT", "MAX_LIMIT", "bathing_samples", "bathing_samples_change",
    "bathing_samples_country_change", "notices",
]
