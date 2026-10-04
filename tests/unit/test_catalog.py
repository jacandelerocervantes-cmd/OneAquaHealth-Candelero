"""The sidebar catalogue rules (``oah.indices.catalog``): applicability from the data held, never from a country list.

Pure inputs only (synthetic evidence and availability); the route is tested in ``test_catalog_api.py``.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, get_args

import pytest

from oah.api.schemas import ChatIndex, ChatOrigin
from oah.api.schemas.catalog import CatalogFamilyId, CatalogIndexId, CatalogOriginKind, CatalogReasonCode
from oah.chat.tools.definitions import INDEX_NAMES
from oah.i18n import strings as s
from oah.i18n.languages import LANGUAGES, SOURCE_LANGUAGE
from oah.indices import catalog as c

EVERYTHING = c.CountryEvidence(
    sandbox_evaluated_sites=2,
    parameter_groups=frozenset({"water-chemistry", "solids-turbidity", "organic-matter"}),
    sandbox_water_sites=2,
    waterbase_located_river_sites=5,
    waterbase_located_lake_sites=1,
    bathing_waters=10,
    bathing_located_waters=9,
    bathing_samples=100,
)
NOTHING = c.CountryEvidence()
ALL_UP = c.Availability()
TRANSLATED = [code for code in LANGUAGES if code != SOURCE_LANGUAGE]


def reasons(evidence: c.CountryEvidence, availability: c.Availability = ALL_UP) -> dict[str, str | None]:
    return {spec.id: c.reason_for(spec.id, evidence, availability) for spec in c.INDEX_SPECS}


# --- the fixed list ----------------------------------------------------------------------------------------------------


def test_the_index_list_and_its_order_are_stable() -> None:
    assert c.INDEX_IDS == (
        "water-quality", "water-parameters", "solids-turbidity", "organic-matter", "bathing-classes", "bathing-samples",
        "weather", "river-discharge", "species-nearby", "data-quality", "citizen-science", "review-queue", "river-risk",
    )
    assert c.FAMILIES == (
        ("water", "Water"), ("microbiology", "Microbiology"), ("context", "Context"), ("data", "Data"),
        ("synthetic-labs", "Synthetic labs"),
    )
    assert [spec.family for spec in c.INDEX_SPECS] == [
        "water", "water", "water", "water", "microbiology", "microbiology", "context", "context", "context", "data",
        "synthetic-labs", "synthetic-labs", "synthetic-labs",
    ]


def test_the_unavailable_indices_are_never_part_of_the_catalogue() -> None:
    assert c.NEVER_RETURNED == ("biotic-quality", "protozoa", "air-quality", "population-health")
    families, _ = c.build_catalog(EVERYTHING, ALL_UP)
    text = repr(families).lower()
    for name in c.NEVER_RETURNED:
        assert name not in c.INDEX_IDS and name not in text
    for word in ("biotic", "protozoa", "air quality", "population health"):
        assert word not in text


def test_the_schema_literals_match_the_catalogue() -> None:
    assert get_args(CatalogIndexId) == c.INDEX_IDS
    assert get_args(CatalogFamilyId) == c.FAMILY_IDS
    assert set(get_args(CatalogOriginKind)) == {c.ORIGIN_REAL, c.ORIGIN_EXTERNAL, c.ORIGIN_SYNTHETIC}
    assert set(get_args(CatalogReasonCode)) == set(c.REASON_STRING_KEYS)


def test_origin_kinds_agree_with_the_origin_labels_and_the_chat_index_is_a_real_one() -> None:
    known_origins = set(get_args(ChatOrigin))
    for spec in c.INDEX_SPECS:
        assert spec.origins and set(spec.origins) <= known_origins, spec.id
        if spec.origin_kind == c.ORIGIN_SYNTHETIC:
            assert spec.origins == ("synthetic",)
        elif spec.origin_kind == c.ORIGIN_EXTERNAL:
            assert all(label.startswith("external-") for label in spec.origins)
        else:
            assert all(label.startswith("real-") for label in spec.origins)
        assert spec.chat_index is None or spec.chat_index in get_args(ChatIndex)
        assert spec.routes and len(set(spec.routes)) == len(spec.routes)
    assert set(get_args(ChatIndex)) == set(INDEX_NAMES)
    assert {spec.id: spec.chat_index for spec in c.INDEX_SPECS if spec.chat_index} == {
        "water-quality": "water-quality", "water-parameters": "water-parameters", "solids-turbidity": "water-parameters",
        "organic-matter": "water-parameters", "bathing-classes": "microbiology", "bathing-samples": "microbiology",
        "data-quality": "data-quality",
    }


def test_every_title_family_and_origin_kind_is_as_the_design_names_it() -> None:
    assert {spec.id: (spec.title, spec.origin_kind) for spec in c.INDEX_SPECS} == {
        "water-quality": ("Water quality", "real"), "water-parameters": ("Water parameters", "real"),
        "solids-turbidity": ("Solids and turbidity", "real"), "organic-matter": ("Organic matter", "real"),
        "bathing-classes": ("Bathing classes", "real"), "bathing-samples": ("E. coli and enterococci", "real"),
        "weather": ("Weather", "external"), "river-discharge": ("River discharge", "external"),
        "species-nearby": ("Species nearby", "external"), "data-quality": ("Data quality", "real"),
        "citizen-science": ("Citizen science", "synthetic"), "review-queue": ("Review queue (read-only)", "synthetic"),
        "river-risk": ("River risk", "synthetic"),
    }


# --- applicability rules, one by one -----------------------------------------------------------------------------------


def test_with_everything_held_every_index_applies() -> None:
    assert set(reasons(EVERYTHING).values()) == {None}


def test_with_nothing_held_only_data_quality_and_the_synthetic_labs_apply() -> None:
    result = reasons(NOTHING)
    assert {key for key, reason in result.items() if reason is None} == {
        "data-quality", "citizen-science", "review-queue", "river-risk",
    }
    assert result["water-quality"] == c.REASON_NO_DATA and result["bathing-samples"] == c.REASON_NO_DATA
    assert result["weather"] == c.REASON_NO_SITE and result["species-nearby"] == c.REASON_NO_SITE
    assert result["river-discharge"] == c.REASON_NO_RIVER_SITE


def test_water_quality_needs_an_evaluated_sandbox_site() -> None:
    assert reasons(replace(EVERYTHING, sandbox_evaluated_sites=0))["water-quality"] == c.REASON_NO_DATA
    assert reasons(replace(NOTHING, sandbox_evaluated_sites=1))["water-quality"] is None
    assert reasons(NOTHING, replace(ALL_UP, sandbox=False))["water-quality"] == c.REASON_NOT_LOADED


@pytest.mark.parametrize(
    ("index_id", "group"),
    [("water-parameters", "water-chemistry"), ("solids-turbidity", "solids-turbidity"), ("organic-matter", "organic-matter")],
)
def test_a_parameter_index_needs_its_group_in_the_country(index_id: str, group: str) -> None:
    others = frozenset({"water-chemistry", "solids-turbidity", "organic-matter"} - {group})
    assert reasons(replace(NOTHING, parameter_groups=frozenset({group})))[index_id] is None
    assert reasons(replace(NOTHING, parameter_groups=others))[index_id] == c.REASON_NO_DATA


def test_the_parameter_indices_depend_on_their_own_sources_only() -> None:
    chemistry_only = replace(NOTHING, parameter_groups=frozenset({"water-chemistry"}))
    no_waterbase = replace(ALL_UP, waterbase=False)
    no_sandbox = replace(ALL_UP, sandbox=False)
    # Greece-like: chemistry held, no solids group: with the store loaded that is "no data", with the store missing "not loaded"
    assert reasons(chemistry_only)["solids-turbidity"] == c.REASON_NO_DATA
    assert reasons(chemistry_only, no_waterbase)["solids-turbidity"] == c.REASON_NOT_LOADED
    assert reasons(chemistry_only, no_waterbase)["organic-matter"] == c.REASON_NOT_LOADED
    # water-parameters held through any source stays applicable; with nothing held both sources matter
    assert reasons(chemistry_only, no_waterbase)["water-parameters"] is None
    assert reasons(NOTHING)["water-parameters"] == c.REASON_NO_DATA
    assert reasons(NOTHING, no_waterbase)["water-parameters"] == c.REASON_NOT_LOADED
    assert reasons(NOTHING, no_sandbox)["water-parameters"] == c.REASON_NOT_LOADED
    # a missing sandbox does not change a solids question
    assert reasons(NOTHING, no_sandbox)["solids-turbidity"] == c.REASON_NO_DATA


def test_bathing_classes_and_samples_follow_their_stores() -> None:
    assert reasons(replace(NOTHING, bathing_waters=3))["bathing-classes"] is None
    assert reasons(NOTHING)["bathing-classes"] == c.REASON_NO_DATA
    assert reasons(NOTHING, replace(ALL_UP, bathing=False))["bathing-classes"] == c.REASON_NOT_LOADED
    assert reasons(replace(NOTHING, bathing_samples=1))["bathing-samples"] is None
    assert reasons(NOTHING)["bathing-samples"] == c.REASON_NO_DATA
    assert reasons(NOTHING, replace(ALL_UP, samples=False))["bathing-samples"] == c.REASON_NOT_LOADED
    # the two bathing stores are independent: samples without a classification store still apply
    assert reasons(replace(NOTHING, bathing_samples=5), replace(ALL_UP, bathing=False))["bathing-samples"] is None
    assert reasons(replace(NOTHING, bathing_waters=5), replace(ALL_UP, samples=False))["bathing-classes"] is None


@pytest.mark.parametrize(
    ("index_id", "switch"), [("weather", "weather"), ("river-discharge", "discharge"), ("species-nearby", "species")]
)
def test_an_external_index_needs_its_provider_switched_on(index_id: str, switch: str) -> None:
    off = replace(ALL_UP, **{switch: False})
    assert reasons(EVERYTHING, off)[index_id] == c.REASON_PROVIDER_OFF
    assert reasons(NOTHING, off)[index_id] == c.REASON_PROVIDER_OFF  # the switch is reported first
    ids = {"weather": "weather", "discharge": "river-discharge", "species": "species-nearby"}
    for other, other_id in ids.items():
        if other != switch:
            assert reasons(EVERYTHING, off)[other_id] is None  # the switches are independent


def test_weather_needs_any_located_site_a_bathing_water_counts() -> None:
    assert reasons(replace(NOTHING, sandbox_water_sites=1))["weather"] is None
    assert reasons(replace(NOTHING, waterbase_located_lake_sites=1))["weather"] is None
    assert reasons(replace(NOTHING, bathing_located_waters=1))["weather"] is None
    assert reasons(NOTHING)["weather"] == c.REASON_NO_SITE
    assert reasons(NOTHING, replace(ALL_UP, bathing=False))["weather"] == c.REASON_NOT_LOADED


def test_river_discharge_needs_a_river_site_not_a_lake_or_a_bathing_water() -> None:
    only_lakes = replace(NOTHING, waterbase_located_lake_sites=4, bathing_located_waters=4)
    assert reasons(only_lakes)["river-discharge"] == c.REASON_NO_RIVER_SITE
    assert reasons(replace(only_lakes, waterbase_located_river_sites=1))["river-discharge"] is None
    assert reasons(replace(NOTHING, sandbox_water_sites=1))["river-discharge"] is None
    assert reasons(only_lakes, replace(ALL_UP, waterbase=False))["river-discharge"] == c.REASON_NOT_LOADED
    # a bathing store that is not built does not matter for discharge
    assert reasons(only_lakes, replace(ALL_UP, bathing=False))["river-discharge"] == c.REASON_NO_RIVER_SITE


def test_species_nearby_needs_a_water_quality_site_not_a_bathing_water() -> None:
    assert reasons(replace(NOTHING, bathing_located_waters=9))["species-nearby"] == c.REASON_NO_SITE
    assert reasons(replace(NOTHING, waterbase_located_lake_sites=1))["species-nearby"] is None
    assert reasons(replace(NOTHING, sandbox_water_sites=1))["species-nearby"] is None
    assert reasons(NOTHING, replace(ALL_UP, sandbox=False))["species-nearby"] == c.REASON_NOT_LOADED


def test_data_quality_applies_everywhere_while_the_sandbox_answers() -> None:
    assert reasons(NOTHING)["data-quality"] is None
    assert reasons(EVERYTHING, replace(ALL_UP, sandbox=False))["data-quality"] == c.REASON_NOT_LOADED


def test_the_synthetic_labs_always_apply_and_are_labelled_synthetic() -> None:
    down = c.Availability(False, False, False, False, False, False, False)
    for index_id in ("citizen-science", "review-queue", "river-risk"):
        assert reasons(NOTHING, down)[index_id] is None
    families, _ = c.build_catalog(NOTHING, down)
    labs = next(family for family in families if family["id"] == "synthetic-labs")
    assert [item["origin_kind"] for item in labs["indices"]] == ["synthetic"] * 3


def test_a_store_that_is_not_built_never_makes_an_index_apply() -> None:
    down = c.Availability(sandbox=False, waterbase=False, bathing=False, samples=False)
    result = reasons(NOTHING, down)
    assert result["water-quality"] == c.REASON_NOT_LOADED and result["water-parameters"] == c.REASON_NOT_LOADED
    assert result["solids-turbidity"] == c.REASON_NOT_LOADED and result["organic-matter"] == c.REASON_NOT_LOADED
    assert result["bathing-classes"] == c.REASON_NOT_LOADED and result["bathing-samples"] == c.REASON_NOT_LOADED
    assert result["weather"] == c.REASON_NOT_LOADED and result["river-discharge"] == c.REASON_NOT_LOADED
    assert result["species-nearby"] == c.REASON_NOT_LOADED and result["data-quality"] == c.REASON_NOT_LOADED


def test_an_unknown_index_id_is_a_programming_error() -> None:
    with pytest.raises(KeyError):
        c.reason_for("air-quality", EVERYTHING, ALL_UP)


# --- the assembled catalogue -------------------------------------------------------------------------------------------


def test_build_catalog_returns_every_index_with_its_reason_in_the_chosen_language() -> None:
    families, count = c.build_catalog(NOTHING, ALL_UP, lambda key: f"[{key}]")
    assert [family["id"] for family in families] == list(c.FAMILY_IDS)
    flat = [item for family in families for item in family["indices"]]
    assert [item["id"] for item in flat] == list(c.INDEX_IDS)  # ALL indices, in the stable order
    assert count == sum(item["applies"] for item in flat) == 4
    hidden = next(item for item in flat if item["id"] == "water-quality")
    assert hidden["applies"] is False and hidden["reason_code"] == "no-data-for-country"
    assert hidden["reason"] == "[catalog_reason_no_data]"
    shown = next(item for item in flat if item["id"] == "data-quality")
    assert shown["applies"] is True and shown["reason_code"] is None and shown["reason"] is None
    assert hidden["family_id"] == "water" and hidden["family_title"] == "Water" and hidden["routes"] == [
        "/sites", "/indices/{location_id}", "/explain/indices/{location_id}",
    ]
    assert families == c.build_catalog(NOTHING, ALL_UP, lambda key: f"[{key}]")[0]  # deterministic


def test_the_default_localiser_returns_the_string_key() -> None:
    families, _ = c.build_catalog(NOTHING, ALL_UP)
    assert families[0]["indices"][0]["reason"] == "catalog_reason_no_data"


# --- evidence from the country entry, the sandbox sites and the stores' counts ----------------------------------------


def test_evidence_is_read_from_the_overview_entry_the_sandbox_sites_and_the_store_counts() -> None:
    entry = {
        "code": "IT", "evaluated_sites": 0, "parameter_groups": ["organic-matter", "water-chemistry"],
        "bathing_water": {"bathing_waters": 7},
    }
    sites: list[dict[str, Any]] = [
        {"id": "a", "limit_country": "IT", "kind": "water-body", "latitude": 1.0, "longitude": 2.0},
        {"id": "b", "limit_country": "IT", "kind": "air-quality-station", "latitude": 1.0, "longitude": 2.0},
        {"id": "c", "limit_country": "GR", "kind": "water-body", "latitude": 1.0, "longitude": 2.0},
        {"id": "d", "limit_country": "IT", "kind": "water-body", "latitude": None, "longitude": 2.0},
    ]
    evidence = c.evidence_for(entry, sites, "IT", {"IT": (4, 2), "GR": (9, 9)}, {"IT": 6}, {"IT": {"n_samples": 50}})
    assert evidence == c.CountryEvidence(
        sandbox_evaluated_sites=0, parameter_groups=frozenset({"organic-matter", "water-chemistry"}),
        sandbox_water_sites=1, waterbase_located_river_sites=4, waterbase_located_lake_sites=2, bathing_waters=7,
        bathing_located_waters=6, bathing_samples=50,
    )


def test_evidence_of_a_country_with_no_data_is_empty() -> None:
    entry = {"code": "NO", "evaluated_sites": 0, "parameter_groups": [], "bathing_water": None}
    assert c.evidence_for(entry, [], "NO", {}, {}, {}) == c.CountryEvidence()


# --- the fixed strings -------------------------------------------------------------------------------------------------


def test_every_reason_code_names_an_english_string() -> None:
    assert set(c.REASON_STRING_KEYS) == set(get_args(CatalogReasonCode))
    for key in c.REASON_STRING_KEYS.values():
        assert key in s.ENGLISH and s.ENGLISH[key].endswith(".") and len(s.ENGLISH[key]) <= 60
    assert s.ENGLISH["catalog_reason_not_loaded"] == "Data not loaded."


@pytest.mark.parametrize("code", TRANSLATED)
def test_every_translation_has_every_reason_as_a_machine_draft(code: str) -> None:
    loaded = s.load_strings(code)
    assert loaded.review_status == "machine-draft"
    for key in c.REASON_STRING_KEYS.values():
        value = loaded.strings[key]
        assert value and value != s.ENGLISH[key], (code, key)
        assert not re.search(r"\d", value), (code, key)
        assert len(value) <= 120 and "reviewed" not in value.lower()
    assert len({loaded.strings[key] for key in c.REASON_STRING_KEYS.values()}) == len(c.REASON_STRING_KEYS)
