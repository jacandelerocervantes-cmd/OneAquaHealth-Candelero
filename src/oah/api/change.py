"""Assembly of the period-comparison and season-comparison answers, shared by the REST routes and the chat tools.

No new computation: ``oah.indices.period_change`` (the pure comparison), ``oah.waterbase.change`` and
``oah.indices.sandbox_change`` (the two data adapters) and ``oah.bathing.change`` do the work; this module only picks
the source, labels the answer (origin, source, attribution, data freshness) and attaches the fixed notices in the
requested language. Errors are ``ChangeError`` (a status code and a message that is safe to show); the routes turn them
into HTTP errors and the chat tools into tool errors. Sources are never combined: a country answer holds one result per
source.
"""
from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from oah.bathing import change as bathing_change_module
from oah.bathing import service as bathing
from oah.bathing.constants import ATTRIBUTION as BATHING_ATTRIBUTION
from oah.bathing.constants import SOURCE_ID as BATHING_SOURCE
from oah.i18n.strings import load_strings
from oah.indices import sandbox_change
from oah.indices.scope_guard import ScopeBusy, ScopeTooLarge
from oah.indices.period_change import Period, PeriodError
from oah.indices.regimes import DEFAULT_REGIME, countries_by_location_ref, regimes_by_location_ref
from oah.indices.site_measurements import location_known, parameter_names
from oah.waterbase import change as waterbase_change
from oah.waterbase import service as waterbase
from oah.waterbase.mapping import ATTRIBUTION as WATERBASE_ATTRIBUTION
from oah.waterbase.mapping import SOURCE_ID as WATERBASE_SOURCE
from oah.waterbase.mapping import parameter_names as waterbase_parameter_names

SANDBOX_SOURCE = "real-sandbox"
NO_SOURCE_NOTE = "No consulted source holds this parameter for this country."


class ChangeError(Exception):
    """A refusal with an HTTP-style status (404 unknown scope, 422 invalid input, 503 busy) and a message that is safe to show.

    ``retry_after`` (seconds) is set for a busy answer and becomes the ``Retry-After`` header of the REST route.
    """

    def __init__(self, status_code: int, detail: str, retry_after: int | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.retry_after = retry_after


@contextmanager
def scope_limits() -> Iterator[None]:
    """Turn the country-scope guard's refusals into ``ChangeError``: 503 with ``Retry-After`` when busy, 422 when too large."""
    try:
        yield
    except ScopeBusy as error:
        raise ChangeError(503, str(error), retry_after=error.retry_after) from error
    except ScopeTooLarge as error:
        raise ChangeError(422, str(error)) from error


@dataclass(frozen=True)
class SandboxAccess:
    """The sandbox data, fetched only when a comparison needs it (so a Waterbase answer never touches the network)."""

    observations: Callable[[], Sequence[dict[str, Any]]]
    locations: Callable[[], Sequence[dict[str, Any]]]
    freshness: Callable[[], dict[str, Any]]


def parse_periods(a_from: object, a_to: object, b_from: object, b_to: object) -> tuple[Period, Period]:
    """The two periods, or a 422 ``ChangeError`` (malformed month, inverted period, period longer than 100 years)."""
    try:
        return Period.parse(a_from, a_to, "a"), Period.parse(b_from, b_to, "b")
    except PeriodError as error:
        raise ChangeError(422, str(error)) from error


def notices(language: str) -> dict[str, str]:
    """The fixed notices of a comparison in ``language`` (a canonical registry code)."""
    strings = load_strings(language)
    return {
        "interpretation_notice": strings.get("interpretation_notice"),
        "approximation_notice": strings.get("approximation_notice"),
    }


def _sandbox_parameter(parameter: str) -> str | None:
    return {name.lower(): name for name in parameter_names()}.get(parameter.strip().lower())


def _unknown_parameter(parameter: str, names: Sequence[str]) -> ChangeError:
    return ChangeError(422, f"Unknown parameter {parameter[:64]!r}; known: {sorted(set(names))}.")


# --- one site -------------------------------------------------------------------------------------------------------------


def site_change(site_id: str, parameter: str, period_a: Period, period_b: Period, sandbox: SandboxAccess) -> dict[str, Any]:
    """The comparison for one site of either source (Waterbase first, a local read; the sandbox is fetched only if needed)."""
    stored = waterbase.find_site(site_id)
    if stored is not None:
        series = waterbase_change.resolve_series(parameter)
        if series is None:
            raise _unknown_parameter(parameter, waterbase_parameter_names())
        result = waterbase_change.site_change(stored, series, period_a, period_b)
        return {
            "origin": WATERBASE_SOURCE,
            "source": WATERBASE_SOURCE,
            "data_freshness": waterbase.freshness(),
            "attribution": WATERBASE_ATTRIBUTION,
            "scope": {
                "type": "site", "id": stored.site_id, "name": stored.name or stored.site_id, "country": stored.country,
                "water_category": stored.water_category, "regime": waterbase_change.regime_of(stored.category),
            },
            **result,
        }
    observations, locations = sandbox.observations(), sandbox.locations()
    if not location_known(site_id, observations, locations):
        raise ChangeError(404, f"Unknown site {site_id[:128]!r}.")
    canonical = _sandbox_parameter(parameter)
    if canonical is None:
        raise _unknown_parameter(parameter, parameter_names())
    result = sandbox_change.site_change(observations, locations, site_id, canonical, period_a, period_b)
    ref = f"Location/{site_id}"
    name = next((str(loc.get("name") or site_id) for loc in locations if loc.get("id") == site_id), site_id)
    return {
        "origin": SANDBOX_SOURCE,
        "source": SANDBOX_SOURCE,
        "data_freshness": sandbox.freshness(),
        "attribution": None,
        "scope": {
            "type": "site", "id": site_id, "name": name, "country": countries_by_location_ref(locations).get(ref),
            "water_category": None, "regime": regimes_by_location_ref(locations).get(ref, DEFAULT_REGIME),
        },
        **result,
    }


# --- one country ----------------------------------------------------------------------------------------------------------


def country_change(
    country: str,
    parameter: str,
    period_a: Period,
    period_b: Period,
    sandbox: SandboxAccess,
    known_country: Callable[[str, str | None], bool],
    source: str | None = None,
) -> dict[str, Any]:
    """The comparison for one country, one result per source that holds the parameter (``source`` narrows to one).

    404 when the country is unknown, 422 when the parameter is unknown to every consulted source. A source that has no
    data for the country (a Waterbase store that is not built, no sandbox Location of the country) is simply absent
    from ``results``; ``waterbase`` says whether the store is ready.
    """
    if not known_country(country, source):
        raise ChangeError(404, f"Unknown country {country[:8]!r}; GET /countries lists the known codes.")
    use_waterbase = source in (None, WATERBASE_SOURCE)
    use_sandbox = source in (None, SANDBOX_SOURCE)
    series = waterbase_change.resolve_series(parameter) if use_waterbase else None
    canonical = _sandbox_parameter(parameter) if use_sandbox else None
    if series is None and canonical is None:
        names = [*(waterbase_parameter_names() if use_waterbase else []), *(parameter_names() if use_sandbox else [])]
        raise _unknown_parameter(parameter, names)
    results: list[dict[str, Any]] = []
    sandbox_consulted = False
    if series is not None:
        held = {item.country for item in waterbase.country_summaries()}
        if country in held:
            with scope_limits():
                found_waterbase = waterbase_change.country_change(country, series, period_a, period_b)
            results.append({
                "origin": WATERBASE_SOURCE, "source": WATERBASE_SOURCE, "data_freshness": waterbase.freshness(),
                "attribution": WATERBASE_ATTRIBUTION, **found_waterbase,
            })
    if canonical is not None:
        sandbox_consulted = True
        found = sandbox_change.country_change(sandbox.observations(), sandbox.locations(), country, canonical, period_a, period_b)
        if found is not None:
            results.append({
                "origin": SANDBOX_SOURCE, "source": SANDBOX_SOURCE, "data_freshness": sandbox.freshness(),
                "attribution": None, **found,
            })
    origins = {item["origin"] for item in results}
    if len(origins) == 2:
        origin = "real-mixed"
    elif origins:
        origin = next(iter(origins))
    else:
        origin = WATERBASE_SOURCE if source == WATERBASE_SOURCE or not sandbox_consulted else SANDBOX_SOURCE
    freshness = sandbox.freshness() if sandbox_consulted else waterbase.freshness()  # as /sites: the sandbox's when it was consulted
    return {
        "origin": origin,
        "data_freshness": freshness,
        "scope": {"type": "country", "code": country},
        "parameter": results[0]["parameter"] if results else parameter.strip()[:64],
        "results": results,
        "waterbase": waterbase.status_payload(),
        "note": None if results else NO_SOURCE_NOTE,
    }


# --- bathing-water seasons ------------------------------------------------------------------------------------------------


def bathing_change(country: str, season_a: int, season_b: int, water_type: str | None, language: str) -> dict[str, Any]:
    """The season comparison with the localised fixed notices (a classification comparison, never a concentration)."""
    strings = load_strings(language)
    result = bathing_change_module.season_change(country, season_a, season_b, water_type)
    return {
        "origin": BATHING_SOURCE,
        "data_freshness": bathing.freshness(),
        "attribution": BATHING_ATTRIBUTION,
        "language": language,
        "notice": strings.get("bathing_water_classification_notice"),
        "comparison_notice": strings.get("bathing_change_notice"),
        "bathing_water": bathing.status_payload(),
        **result,
    }
