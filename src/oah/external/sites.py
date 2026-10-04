"""Where the coordinates of an external-context question come from: the project's own sites, never the caller.

A route or tool gives a SITE ID; ``SiteLocator.locate`` finds it in the EEA Waterbase store, the EEA bathing-water store or the
sandbox sites (the three sources never share an id in the real stores, checked 2026-10-03; the first match wins, and the two
local stores are tried before the sandbox, which may need the network) and returns its coordinates, country and water category. A site without usable coordinates is refused
(``no-location``). The data access is injected (the same read functions the REST routes use), so this module is pure.
"""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from oah.external.coords import CoordinateError, validate
from oah.waterbase.mapping import location_publishable

SITE_ID = re.compile(r"^[\w.\-]{1,128}$")
KIND_WATERBASE = "waterbase-site"
KIND_SANDBOX = "sandbox-site"
KIND_BATHING = "bathing-water"
CATEGORY_RIVER = "river"
CATEGORY_LAKE = "lake"
CATEGORY_COASTAL = "coastal-or-transitional"


class SiteLookupError(Exception):
    """The site cannot be used. ``status_code`` is the HTTP status a route returns (404 unknown, 422 unusable)."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class LocatedSite:
    site_id: str
    name: str
    kind: str
    source: str  # the origin label of the store the site comes from
    country: str | None
    latitude: float
    longitude: float
    water_category: str | None  # river, lake, coastal-or-transitional, or None when the source does not say


def _bathing_category(water_type: object) -> str | None:
    text = str(water_type or "").lower()
    if "river" in text:
        return CATEGORY_RIVER
    if "lake" in text:
        return CATEGORY_LAKE
    if "coastal" in text or "transitional" in text:
        return CATEGORY_COASTAL
    return None


def _restricted_location(entry: Mapping[str, Any], kind: str) -> bool:
    """True when the entry itself says it has no publishable location, whatever coordinates it carries.

    Defence in depth for the privacy rule of ``docs/waterbase_store.md``: a Waterbase site that is not free for
    publication (confidentiality other than ``F``) or that is listed as ``no-location`` is never sent to a provider.
    """
    if entry.get("location_status") == "no-location":
        return True
    return kind == KIND_WATERBASE and "confidentiality" in entry and not location_publishable(entry.get("confidentiality"))


def _checked(site_id: str, entry: Mapping[str, Any], kind: str, country: object, category: str | None) -> LocatedSite:
    if _restricted_location(entry, kind):
        raise SiteLookupError(
            422, f"Site {site_id!r} is no-location (no publishable coordinates); no external context can be given."
        )
    try:
        lat, lon = validate(entry.get("latitude"), entry.get("longitude"))
    except CoordinateError as error:
        raise SiteLookupError(422, f"Site {site_id!r} has no usable coordinates ({error}); no external context can be given.") from error
    return LocatedSite(
        site_id=site_id,
        name=str(entry.get("name") or site_id),
        kind=kind,
        source=str(entry.get("source") or entry.get("origin") or ""),
        country=str(country) if country else None,
        latitude=lat,
        longitude=lon,
        water_category=category,
    )


@dataclass(frozen=True)
class SiteLocator:
    """The three read functions behind ``locate``; any of them may be None (that source is not available)."""

    waterbase: Callable[[str], dict[str, Any] | None] | None = None  # one ``/sites`` entry of a Waterbase site
    sandbox: Callable[[], list[dict[str, Any]]] | None = None  # the sandbox ``/sites`` entries
    bathing: Callable[[str], dict[str, Any] | None] | None = None  # one bathing water (``oah.bathing.service.find``)

    def locate(self, site_id: str, *, allow_bathing: bool = True) -> LocatedSite:
        """The site with its coordinates; ``SiteLookupError`` 422 for a malformed id or no coordinates, 404 when unknown."""
        if not isinstance(site_id, str) or not SITE_ID.fullmatch(site_id):
            raise SiteLookupError(422, "A site id is letters, digits, dot, dash and underscore, at most 128 characters.")
        if self.waterbase is not None:
            entry = self.waterbase(site_id)
            if entry is not None:
                category = entry.get("water_category")
                return _checked(site_id, entry, KIND_WATERBASE, entry.get("limit_country"), str(category) if category else None)
        if allow_bathing and self.bathing is not None:  # a local store, tried before the sandbox (which may need the network)
            entry = self.bathing(site_id)
            if entry is not None:
                return _checked(site_id, entry, KIND_BATHING, entry.get("country"), _bathing_category(entry.get("type")))
        if self.sandbox is not None:
            for entry in self.sandbox():
                if entry.get("id") == site_id:
                    return _checked(site_id, entry, KIND_SANDBOX, entry.get("limit_country"), None)
        raise SiteLookupError(404, f"Unknown site {site_id[:128]!r}.")
