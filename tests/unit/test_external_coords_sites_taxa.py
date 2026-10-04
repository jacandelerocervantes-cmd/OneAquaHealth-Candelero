"""Coordinates (validation, rounding, search square, distance), the site locator and the taxon list."""
from __future__ import annotations

import copy
import json
import math

import pytest

from oah.external import coords
from oah.external import taxa as taxa_module
from oah.external.constants import COORD_DECIMALS
from oah.external.sites import (
    CATEGORY_COASTAL,
    CATEGORY_LAKE,
    CATEGORY_RIVER,
    KIND_BATHING,
    KIND_SANDBOX,
    KIND_WATERBASE,
    SiteLocator,
    SiteLookupError,
)
from oah.external.taxa import TaxaError, load_catalogue, parse_catalogue
from oah.paths import source_path
from external_fakes import fake_locator

# --- coordinates ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("lat, lon", [(float("nan"), 1.0), (1.0, float("inf")), (91.0, 0.0), (0.0, 181.0), (None, 1.0), ("45", 7.0), (True, 7.0), (0.0, 0.0)])
def test_invalid_coordinates_are_refused(lat: object, lon: object) -> None:
    with pytest.raises(coords.CoordinateError):
        coords.validate(lat, lon)


def test_valid_coordinates_pass_and_ints_become_floats() -> None:
    assert coords.validate(45, 7) == (45.0, 7.0)
    assert coords.validate(0.0, 12.5) == (0.0, 12.5)  # only the exact (0, 0) placeholder is refused


def test_rounding_uses_the_documented_precision_and_removes_negative_zero() -> None:
    assert COORD_DECIMALS == 2
    assert coords.rounded(45.07649, 7.68551) == (45.08, 7.69)
    lat, lon = coords.rounded(-0.001, 0.004)
    assert math.copysign(1.0, lat) == 1.0 and math.copysign(1.0, lon) == 1.0 and (lat, lon) == (0.0, 0.0)
    assert coords.rounded(45.071, 7.691) == coords.rounded(45.074, 7.694)  # nearby points share one cache key


def test_search_square_is_ten_kilometres_wide_and_counter_clockwise() -> None:
    west, south, east, north = coords.search_square(45.07, 7.69)
    assert west < 7.69 < east and south < 45.07 < north
    height_km = coords.distance_km(south, 7.69, north, 7.69)
    width_km = coords.distance_km(45.07, west, 45.07, east)
    assert height_km == pytest.approx(10.0, abs=0.1) and width_km == pytest.approx(10.0, abs=0.1)
    wkt = coords.search_wkt(45.07, 7.69)
    assert wkt.startswith("POLYGON((") and wkt.endswith("))")
    ring = [tuple(float(x) for x in pair.split()) for pair in wkt[9:-2].split(", ")]
    assert ring[0] == ring[-1] and len(ring) == 5
    area2 = sum(ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1] for i in range(4))
    assert area2 > 0  # positive signed area: counter-clockwise
    assert coords.search_wkt(45.071, 7.691) == coords.search_wkt(45.074, 7.694)


def test_search_square_refuses_poles_and_the_antimeridian() -> None:
    with pytest.raises(coords.CoordinateError):
        coords.search_square(85.0, 10.0)
    with pytest.raises(coords.CoordinateError):
        coords.search_square(45.0, 179.99)
    with pytest.raises(coords.CoordinateError):
        coords.search_square(45.0, -179.99)


def test_haversine_distance() -> None:
    assert coords.distance_km(45.0, 7.0, 45.0, 7.0) == 0.0
    assert coords.distance_km(0.0, 0.0, 0.0, 1.0) == pytest.approx(111.195, abs=0.01)
    assert coords.distance_km(0.0, 0.0, 0.0, 180.0) == pytest.approx(math.pi * 6371.0088, rel=1e-9)


# --- site locator ----------------------------------------------------------------------------------------------------


def test_waterbase_sandbox_and_bathing_sites_are_located_with_their_category() -> None:
    locator = fake_locator()
    river = locator.locate("ITRIVER1")
    assert (river.kind, river.country, river.water_category, river.latitude) == (KIND_WATERBASE, "IT", CATEGORY_RIVER, 45.07)
    assert locator.locate("ITLAKE1").water_category == CATEGORY_LAKE
    sandbox = locator.locate("Loc-Almyros")
    assert sandbox.kind == KIND_SANDBOX and sandbox.country == "GR" and sandbox.water_category is None
    lake_bathing = locator.locate("IT001001050001")
    assert lake_bathing.kind == KIND_BATHING and lake_bathing.water_category == CATEGORY_LAKE
    assert locator.locate("GRCOAST").water_category == CATEGORY_COASTAL


def test_unknown_malformed_and_unlocated_sites() -> None:
    locator = fake_locator()
    with pytest.raises(SiteLookupError) as unknown:
        locator.locate("NOPE")
    assert unknown.value.status_code == 404
    for bad in ["", "a b", "../x", "x" * 129, "id;drop", "a/b"]:
        with pytest.raises(SiteLookupError) as malformed:
            locator.locate(bad)
        assert malformed.value.status_code == 422
    with pytest.raises(SiteLookupError) as nolocation:
        locator.locate("ITNOLOC")
    assert nolocation.value.status_code == 422 and "coordinates" in nolocation.value.detail
    with pytest.raises(SiteLookupError):
        SiteLocator().locate("ITRIVER1")  # no source at all: unknown


def test_a_site_at_the_zero_placeholder_is_refused() -> None:
    locator = SiteLocator(waterbase=lambda site_id: {"id": site_id, "latitude": 0.0, "longitude": 0.0})
    with pytest.raises(SiteLookupError) as caught:
        locator.locate("X1")
    assert caught.value.status_code == 422


# --- taxon list -----------------------------------------------------------------------------------------------------


def test_the_shipped_taxon_file_loads_and_is_small_and_explicit() -> None:
    catalogue = load_catalogue()
    ids = [item.id for item in catalogue.groups]
    assert ids == ["ephemeroptera", "plecoptera", "trichoptera", "odonata", "chironomidae", "gammaridae", "unionida"]
    assert len(catalogue.groups) <= taxa_module.MAX_GROUPS
    keys = {item.id: item.usage_key for item in catalogue.groups}
    # keys discovered on 2026-10-03 through GBIF species/match (rank and kingdom given)
    assert keys["ephemeroptera"] == 1225 and keys["plecoptera"] == 787 and keys["trichoptera"] == 1003
    assert catalogue.discovered_on.isoformat() == "2026-10-03"
    assert all(item.confidence >= 90 for item in catalogue.groups)
    assert catalogue.aliases == {"ept": ("ephemeroptera", "plecoptera", "trichoptera")}
    assert catalogue.group("plecoptera") is not None and catalogue.group("nope") is None
    assert "ept" in catalogue.selectable() and "odonata" in catalogue.selectable()


def test_the_taxon_file_records_the_rejected_matches() -> None:
    raw = json.loads(source_path("external", "data", "gbif_taxa.json").read_text(encoding="utf-8"))
    rejected = {item["name"]: item for item in raw["rejected_matches"]}
    assert "HIGHERRANK" in rejected["Plecoptera"]["result"] and "787" in rejected["Plecoptera"]["action"]
    assert "Oligochaeta" in rejected and "Hirudinea" in rejected


def test_resolve_groups_aliases_and_unknowns() -> None:
    catalogue = load_catalogue()
    assert [g.id for g in catalogue.resolve(None)] == [g.id for g in catalogue.groups]
    assert [g.id for g in catalogue.resolve(" EPT ")] == ["ephemeroptera", "plecoptera", "trichoptera"]
    assert [g.id for g in catalogue.resolve("Odonata")] == ["odonata"]
    with pytest.raises(KeyError):
        catalogue.resolve("birds")
    assert catalogue.group("chironomidae").facet == "FAMILY_KEY"  # type: ignore[union-attr]
    assert catalogue.group("odonata").facet == "ORDER_KEY"  # type: ignore[union-attr]


def _good() -> dict:
    return copy.deepcopy(json.loads(source_path("external", "data", "gbif_taxa.json").read_text(encoding="utf-8")))


def test_parse_catalogue_rejects_data_that_breaks_the_discovery_rules() -> None:
    parse_catalogue(_good())
    mutations = {
        "schema": lambda d: d.update(schema_version=2),
        "date": lambda d: d.update(discovered_on="soon"),
        "empty": lambda d: d.update(groups=[]),
        "too many": lambda d: d.update(groups=d["groups"] * 3),
        "rank": lambda d: d["groups"][0].update(rank="CLASS"),
        "status": lambda d: d["groups"][0].update(status="SYNONYM"),
        "match": lambda d: d["groups"][0].update(match_type="HIGHERRANK"),
        "key text": lambda d: d["groups"][0].update(usage_key="1225"),
        "key bool": lambda d: d["groups"][0].update(usage_key=True),
        "key zero": lambda d: d["groups"][0].update(usage_key=0),
        "confidence": lambda d: d["groups"][0].update(confidence=101),
        "confidence text": lambda d: d["groups"][0].update(confidence="98"),
        "id": lambda d: d["groups"][0].update(id="Bad Id"),
        "duplicate id": lambda d: d["groups"][1].update(id="ephemeroptera"),
        "duplicate key": lambda d: d["groups"][1].update(usage_key=1225),
        "text": lambda d: d["groups"][0].update(caveat=""),
        "not object": lambda d: d["groups"].__setitem__(0, "x"),
        "alias unknown member": lambda d: d.update(aliases={"ept": ["nope"]}),
        "alias empty": lambda d: d.update(aliases={"ept": []}),
        "alias clash": lambda d: d.update(aliases={"odonata": ["plecoptera"]}),
        "alias bad name": lambda d: d.update(aliases={"Bad Alias": ["odonata"]}),
        "aliases type": lambda d: d.update(aliases=[]),
        "method": lambda d: d.pop("method"),
    }
    for label, mutate in mutations.items():
        data = _good()
        mutate(data)
        with pytest.raises(TaxaError):
            parse_catalogue(data)
        assert label  # the label names the failing case in a pytest report
    with pytest.raises(TaxaError):
        parse_catalogue([])


def test_load_catalogue_reports_an_unreadable_file(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    load_catalogue.cache_clear()
    try:
        monkeypatch.setattr(taxa_module, "source_path", lambda *parts: tmp_path / "missing.json")
        with pytest.raises(TaxaError):
            load_catalogue()
        broken = tmp_path / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        load_catalogue.cache_clear()
        monkeypatch.setattr(taxa_module, "source_path", lambda *parts: broken)
        with pytest.raises(TaxaError):
            load_catalogue()
    finally:
        load_catalogue.cache_clear()


def test_local_stores_are_tried_before_the_sandbox_which_may_need_the_network() -> None:
    calls: list[int] = []

    def sandbox() -> list[dict]:
        calls.append(1)
        return [{"id": "Loc-X", "name": "X", "latitude": 35.3, "longitude": 24.4, "limit_country": "GR"}]

    bathing = {"BW1": {"id": "BW1", "name": "B", "country": "IT", "type": "riverBathingWater", "latitude": 45.0, "longitude": 7.0}}
    locator = SiteLocator(waterbase=lambda site_id: None, bathing=lambda site_id: bathing.get(site_id), sandbox=sandbox)
    assert locator.locate("BW1").kind == KIND_BATHING and calls == []
    assert locator.locate("Loc-X").kind == KIND_SANDBOX and calls == [1]
    assert locator.locate("BW1").water_category == CATEGORY_RIVER
    with pytest.raises(SiteLookupError):
        locator.locate("Loc-Y")
    assert calls == [1, 1]
