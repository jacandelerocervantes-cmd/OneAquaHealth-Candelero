"""Catalogue of the web app sidebar for one country: which families and indices apply, and why not when they do not.

``GET /catalog?country=XX`` is the authoritative list; the web app hides only what this module marks as not applicable
(docs/indices_catalog.md, docs/web_app_design.md). Nothing here is a country list: applicability is derived from the data
the service really holds (the sandbox sites, the Waterbase, bathing-water and bathing-samples stores and the external
context switches), passed in as plain values (``CountryEvidence``, ``Availability``), so every rule is unit-tested with
synthetic inputs. Pure module: no I/O.

What "applies" means: the service holds at least the data the index needs for the country. It never means that a value
is good, safe or compliant. A store that is not loaded (not built, unreadable, a layout to rebuild, an unreachable sandbox
without snapshot) cannot supply data, so the indices that depend only on it do not apply, with the reason ``data-not-loaded``
(which differs from ``no-data-for-country``: the store is loaded and holds nothing for this country).

Never returned, by decision of the maintainer (``NEVER_RETURNED``): biotic quality, protozoa, air quality and population
health. They are not available as data and the sidebar does not show them at all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from oah.waterbase.mapping import GROUP_ORGANIC_MATTER, GROUP_SOLIDS_TURBIDITY, GROUP_WATER_CHEMISTRY

ORIGIN_REAL = "real"
ORIGIN_EXTERNAL = "external"
ORIGIN_SYNTHETIC = "synthetic"

SITE_KIND_WATER_BODY = "water-body"

# Reason codes (stable, for a client or a test) and the key of the fixed string that says each in a language.
REASON_NO_DATA = "no-data-for-country"
REASON_NOT_LOADED = "data-not-loaded"
REASON_PROVIDER_OFF = "provider-off"
REASON_NO_SITE = "no-located-site"
REASON_NO_RIVER_SITE = "no-located-river-site"
REASON_STRING_KEYS: dict[str, str] = {
    REASON_NO_DATA: "catalog_reason_no_data",
    REASON_NOT_LOADED: "catalog_reason_not_loaded",
    REASON_PROVIDER_OFF: "catalog_reason_provider_off",
    REASON_NO_SITE: "catalog_reason_no_site",
    REASON_NO_RIVER_SITE: "catalog_reason_no_river_site",
}

# What the project knows and deliberately does not offer (kept here so a test can pin that none is ever returned).
NEVER_RETURNED: tuple[str, ...] = ("biotic-quality", "protozoa", "air-quality", "population-health")

# Families in the order of the sidebar: (id, title).
FAMILIES: tuple[tuple[str, str], ...] = (
    ("water", "Water"),
    ("microbiology", "Microbiology"),
    ("context", "Context"),
    ("data", "Data"),
    ("synthetic-labs", "Synthetic labs"),
)


@dataclass(frozen=True)
class IndexSpec:
    id: str
    family: str
    title: str
    origin_kind: str  # real, external or synthetic
    origins: tuple[str, ...]  # the origin labels of the data behind the index (the labels the routes carry)
    routes: tuple[str, ...]  # paths as listed in docs/api_routes.md and docs/architecture.md
    chat_index: str | None  # a value of ChatIndex, or None when the chat has no index of its own for it


_MEASUREMENT_ROUTES = (
    "/sites", "/sites/{location_id}/measurements", "/sites/{site_id}/change", "/countries/{country_code}/change",
)

# The order of this tuple is the order of the response (a test pins it).
INDEX_SPECS: tuple[IndexSpec, ...] = (
    IndexSpec(
        "water-quality", "water", "Water quality", ORIGIN_REAL, ("real-sandbox",),
        ("/sites", "/indices/{location_id}", "/explain/indices/{location_id}"), "water-quality",
    ),
    IndexSpec(
        "water-parameters", "water", "Water parameters", ORIGIN_REAL, ("real-sandbox", "real-eea-waterbase"),
        _MEASUREMENT_ROUTES, "water-parameters",
    ),
    # Sub-views of the water-parameters tools (the same tools answer them, by the Waterbase labels such as Turbidity).
    IndexSpec(
        "solids-turbidity", "water", "Solids and turbidity", ORIGIN_REAL, ("real-eea-waterbase",),
        _MEASUREMENT_ROUTES, "water-parameters",
    ),
    IndexSpec(
        "organic-matter", "water", "Organic matter", ORIGIN_REAL, ("real-eea-waterbase",),
        _MEASUREMENT_ROUTES, "water-parameters",
    ),
    IndexSpec(
        "bathing-classes", "microbiology", "Bathing classes", ORIGIN_REAL, ("real-eea-bathing-water",),
        ("/bathing-waters", "/bathing-waters/{bw_id}", "/bathing-waters/change"), "microbiology",
    ),
    IndexSpec(
        "bathing-samples", "microbiology", "E. coli and enterococci", ORIGIN_REAL, ("real-eea-bathing-samples",),
        (
            "/bathing-waters/{bw_id}/samples", "/bathing-waters/{bw_id}/samples/change",
            "/bathing-waters/samples/change",
        ),
        "microbiology",
    ),
    IndexSpec("weather", "context", "Weather", ORIGIN_EXTERNAL, ("external-open-meteo",), ("/sites/{site_id}/weather",), None),
    IndexSpec(
        "river-discharge", "context", "River discharge", ORIGIN_EXTERNAL, ("external-open-meteo",),
        ("/sites/{site_id}/discharge",), None,
    ),
    IndexSpec(
        "species-nearby", "context", "Species nearby", ORIGIN_EXTERNAL, ("external-gbif",), ("/sites/{site_id}/species",), None
    ),
    IndexSpec("data-quality", "data", "Data quality", ORIGIN_REAL, ("real-sandbox",), ("/qc/report",), "data-quality"),
    IndexSpec(
        "citizen-science", "synthetic-labs", "Citizen science", ORIGIN_SYNTHETIC, ("synthetic",),
        ("/reliability/campaign",), None,
    ),
    IndexSpec(
        # Read-only: the decision route changes state and is off unless OAH_ENABLE_WRITE_ROUTES is on, so it is not listed.
        "review-queue", "synthetic-labs", "Review queue (read-only)", ORIGIN_SYNTHETIC, ("synthetic",),
        ("/review/queue",), None,
    ),
    IndexSpec("river-risk", "synthetic-labs", "River risk", ORIGIN_SYNTHETIC, ("synthetic",), ("/risk/{site_id}",), None),
)

INDEX_IDS: tuple[str, ...] = tuple(spec.id for spec in INDEX_SPECS)
FAMILY_IDS: tuple[str, ...] = tuple(family for family, _ in FAMILIES)


@dataclass(frozen=True)
class CountryEvidence:
    """What the service holds for one country (counts come from the stores' own summaries and site lists)."""

    sandbox_evaluated_sites: int = 0  # sandbox sites with a CCME index
    parameter_groups: frozenset[str] = frozenset()  # the groups of GET /countries (Waterbase groups, plus water-chemistry)
    sandbox_water_sites: int = 0  # sandbox water-body sites (they always carry a position)
    waterbase_located_river_sites: int = 0
    waterbase_located_lake_sites: int = 0
    bathing_waters: int = 0  # classification store
    bathing_located_waters: int = 0
    bathing_samples: int = 0  # individual samples held


@dataclass(frozen=True)
class Availability:
    """Whether each source can supply data now, and which external providers are switched on."""

    sandbox: bool = True
    waterbase: bool = True  # the store state is ready
    bathing: bool = True
    samples: bool = True
    weather: bool = True
    discharge: bool = True
    species: bool = True


def evidence_for(
    overview_entry: Mapping[str, Any],
    sandbox_sites: Sequence[Mapping[str, Any]],
    country: str,
    waterbase_located: Mapping[str, tuple[int, int]],
    bathing_located: Mapping[str, int],
    samples: Mapping[str, Mapping[str, Any]],
) -> CountryEvidence:
    """The evidence of ``country`` from its ``GET /countries`` entry, the sandbox site list (``list_sites_with_status``), the
    located-site counts of the two stores and the samples blocks (``oah.bathing_samples.service.country_blocks``)."""
    rivers, lakes = waterbase_located.get(country, (0, 0))
    bathing = overview_entry.get("bathing_water") or {}
    held_samples = samples.get(country) or {}
    return CountryEvidence(
        sandbox_evaluated_sites=int(overview_entry.get("evaluated_sites") or 0),
        parameter_groups=frozenset(overview_entry.get("parameter_groups") or ()),
        sandbox_water_sites=sum(
            1
            for site in sandbox_sites
            if site.get("limit_country") == country
            and site.get("kind") == SITE_KIND_WATER_BODY
            and site.get("latitude") is not None
            and site.get("longitude") is not None
        ),
        waterbase_located_river_sites=rivers,
        waterbase_located_lake_sites=lakes,
        bathing_waters=int(bathing.get("bathing_waters") or 0),
        bathing_located_waters=bathing_located.get(country, 0),
        bathing_samples=int(held_samples.get("n_samples") or 0),
    )


def _empty(*sources_available: bool) -> str:
    """The reason when nothing was found: a source that is not loaded may hold it (not loaded), else there is none."""
    return REASON_NO_DATA if all(sources_available) else REASON_NOT_LOADED


def _group_rule(group: str, evidence: CountryEvidence, *sources_available: bool) -> str | None:
    return None if group in evidence.parameter_groups else _empty(*sources_available)


def reason_for(index_id: str, evidence: CountryEvidence, availability: Availability) -> str | None:
    """The reason code when ``index_id`` does not apply to the country, None when it does."""
    if index_id == "water-quality":
        return None if evidence.sandbox_evaluated_sites > 0 else _empty(availability.sandbox)
    if index_id == "water-parameters":
        return _group_rule(GROUP_WATER_CHEMISTRY, evidence, availability.sandbox, availability.waterbase)
    if index_id == "solids-turbidity":
        return _group_rule(GROUP_SOLIDS_TURBIDITY, evidence, availability.waterbase)
    if index_id == "organic-matter":
        return _group_rule(GROUP_ORGANIC_MATTER, evidence, availability.waterbase)
    if index_id == "bathing-classes":
        return None if evidence.bathing_waters > 0 else _empty(availability.bathing)
    if index_id == "bathing-samples":
        return None if evidence.bathing_samples > 0 else _empty(availability.samples)
    if index_id == "weather":
        if not availability.weather:
            return REASON_PROVIDER_OFF
        located = (
            evidence.sandbox_water_sites + evidence.waterbase_located_river_sites + evidence.waterbase_located_lake_sites
            + evidence.bathing_located_waters
        )
        return None if located > 0 else _site_reason(REASON_NO_SITE, availability, bathing=True)
    if index_id == "river-discharge":
        if not availability.discharge:
            return REASON_PROVIDER_OFF
        rivers = evidence.sandbox_water_sites + evidence.waterbase_located_river_sites
        return None if rivers > 0 else _site_reason(REASON_NO_RIVER_SITE, availability, bathing=False)
    if index_id == "species-nearby":
        if not availability.species:
            return REASON_PROVIDER_OFF
        located = evidence.sandbox_water_sites + evidence.waterbase_located_river_sites + evidence.waterbase_located_lake_sites
        return None if located > 0 else _site_reason(REASON_NO_SITE, availability, bathing=False)
    if index_id == "data-quality":
        return None if availability.sandbox else REASON_NOT_LOADED
    if index_id in ("citizen-science", "review-queue", "river-risk"):
        return None  # synthetic by design: they apply to every country and are labelled synthetic
    raise KeyError(index_id)


def _site_reason(reason: str, availability: Availability, *, bathing: bool) -> str:
    sources = [availability.sandbox, availability.waterbase] + ([availability.bathing] if bathing else [])
    return reason if all(sources) else REASON_NOT_LOADED


def build_catalog(
    evidence: CountryEvidence,
    availability: Availability,
    localise: Callable[[str], str] = lambda key: key,
) -> tuple[list[dict[str, Any]], int]:
    """``(families, applicable_count)``: every family in sidebar order with ALL its indices (each with ``applies`` and, when
    it does not, a ``reason_code`` and the ``reason`` text ``localise(string key)`` returns), and how many indices apply."""
    families: list[dict[str, Any]] = []
    applicable = 0
    for family_id, family_title in FAMILIES:
        indices: list[dict[str, Any]] = []
        for spec in (item for item in INDEX_SPECS if item.family == family_id):
            reason = reason_for(spec.id, evidence, availability)
            applicable += reason is None
            indices.append(
                {
                    "id": spec.id,
                    "family_id": family_id,
                    "family_title": family_title,
                    "title": spec.title,
                    "origin_kind": spec.origin_kind,
                    "origins": list(spec.origins),
                    "applies": reason is None,
                    "reason_code": reason,
                    "reason": localise(REASON_STRING_KEYS[reason]) if reason is not None else None,
                    "routes": list(spec.routes),
                    "chat_index": spec.chat_index,
                }
            )
        families.append({"id": family_id, "title": family_title, "indices": indices})
    return families, applicable
