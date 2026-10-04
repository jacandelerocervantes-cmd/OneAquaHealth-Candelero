"""What the REST routes and the chat tools call: external context for a SITE ID, as plain dictionaries.

``ExternalContext`` joins the three parts: the site locator (coordinates only from the stores' sites), the provider
functions and the process-wide runtime (cache, budgets, switches). It never takes a raw coordinate and never raises
for a provider problem: that is an ``external-unavailable`` result. ``SiteLookupError`` (unknown or unusable site) and
``ExternalInputError`` (invalid period, group or limit) are the caller's errors, answered 404 or 422.

Fixed notices are NOT built here: each response names the keys of the localised strings that apply
(``NOTICE_KEYS``), and the route or tool adds the text in the requested language.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from oah.external import coords, gbif, openmeteo
from oah.external.constants import COORD_DECIMALS, GBIF_HALF_SIDE_KM, MAX_SPAN_DAYS, PROVIDER_DISCHARGE, PROVIDER_GBIF, PROVIDER_WEATHER
from oah.external.runtime import ExternalRuntime, get_runtime
from oah.external.sites import KIND_BATHING, LocatedSite, SiteLocator, SiteLookupError
from oah.external.taxa import load_catalogue
from oah.timeutil import utc_now

# The keys of ``oah.i18n.strings`` that every response of that kind must show (docs/external_context.md section 8).
NOTICE_KEYS: dict[str, tuple[str, ...]] = {
    PROVIDER_WEATHER: ("external_context_notice", "external_reanalysis_notice", "external_no_causation_notice"),
    PROVIDER_DISCHARGE: ("external_context_notice", "external_discharge_notice", "external_no_causation_notice"),
    PROVIDER_GBIF: ("external_context_notice", "external_occurrence_notice", "external_licence_notice"),
}
UNAVAILABLE_NOTICE_KEY = "external_unavailable_notice"


def _today() -> date:
    return utc_now().date()


def site_block(site: LocatedSite) -> dict[str, Any]:
    """The site as the response names it, with the coordinates at the precision actually used."""
    lat, lon = coords.rounded(site.latitude, site.longitude)
    return {
        "id": site.site_id, "name": site.name, "kind": site.kind, "source": site.source, "country": site.country,
        "water_category": site.water_category, "latitude": lat, "longitude": lon,
        "coordinate_decimals": COORD_DECIMALS,
    }


def notice_keys(result: dict[str, Any]) -> list[str]:
    """The notice keys of a result: those of its provider, and the unavailability notice when it is unavailable."""
    keys = list(NOTICE_KEYS[result["provider"]])
    if result["status"] == "external-unavailable":
        keys.append(UNAVAILABLE_NOTICE_KEY)
    return keys


class ExternalContext:
    def __init__(
        self,
        locator: SiteLocator,
        runtime: Callable[[], ExternalRuntime] = get_runtime,
        today: Callable[[], date] = _today,
    ) -> None:
        self._locator = locator
        self._runtime = runtime
        self._today = today

    def locate(self, site_id: str, *, allow_bathing: bool = False) -> LocatedSite:
        """The site; a bathing water is accepted only when ``allow_bathing`` (weather), else a 422 that says so."""
        return self._accept(self._locator.locate(site_id, allow_bathing=True), allow_bathing)

    @staticmethod
    def _accept(site: LocatedSite, allow_bathing: bool) -> LocatedSite:
        if site.kind == KIND_BATHING and not allow_bathing:
            raise SiteLookupError(
                422, "This is a bathing water: only the weather context is given for bathing waters; use a water-quality site for this one."
            )
        return site

    def _site(self, site: str | LocatedSite, allow_bathing: bool) -> LocatedSite:
        """A site id is looked up; an already located site (a caller that needed its country first) is only checked."""
        return self._accept(site, allow_bathing) if isinstance(site, LocatedSite) else self.locate(site, allow_bathing=allow_bathing)

    def weather(self, site: str | LocatedSite, date_from: date, date_to: date) -> dict[str, Any]:
        located = self._site(site, True)
        result = openmeteo.weather_context(self._runtime(), located, date_from, date_to, self._today())
        return {**result, "site": site_block(located)}

    def discharge(self, site: str | LocatedSite, date_from: date, date_to: date) -> dict[str, Any]:
        located = self._site(site, False)
        result = openmeteo.discharge_context(self._runtime(), located, date_from, date_to, self._today())
        return {**result, "site": site_block(located)}

    def species(
        self, site: str | LocatedSite, group: str | None, date_from: date | None, date_to: date | None,
        limit: int = gbif.DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        located = self._site(site, False)
        result = gbif.species_context(self._runtime(), located, group, date_from, date_to, limit)
        return {**result, "site": site_block(located)}

    def status(self) -> dict[str, Any]:
        """Providers with their switch, attribution, licence, limits and the budget left (no secret)."""
        runtime = self._runtime()
        catalogue = load_catalogue()
        return {
            "enabled": runtime.settings.enabled,
            "providers": runtime.status_entries(),
            "contact_url_configured": runtime.settings.contact_url is not None,
            "coordinate_decimals": COORD_DECIMALS,
            "max_period_days": MAX_SPAN_DAYS,
            "species_search_half_side_km": GBIF_HALF_SIDE_KM,
            "species_default_limit": gbif.DEFAULT_LIMIT,
            "species_max_limit": gbif.MAX_LIMIT,
            "species_groups": [
                {"id": item.id, "name": item.name, "common_name": item.common_name, "rank": item.rank,
                 "usage_key": item.usage_key, "match_confidence": item.confidence, "caveat": item.caveat}
                for item in catalogue.groups
            ],
            "species_group_aliases": {name: list(members) for name, members in catalogue.aliases.items()},
            "taxa_discovered_on": catalogue.discovered_on.isoformat(),
        }
