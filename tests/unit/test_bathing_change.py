"""Season-to-season comparison of the bathing-water classification: README order only, excluded classes counted apart.

The store is built from a SYNTHETIC workbook (``bathing_fixtures``); identifiers, names and classes are invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bathing_fixtures import HEADER, build_fixture_store, row
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.rate_limit import RateLimiter
from oah.bathing import store
from oah.bathing.constants import COMPARISON_NOTICE_SHORT
from oah.bathing.change import ORDER, compare_seasons, rank_of, season_change
from oah.chat.tools import ALL_TOOLS, run_tool
from oah.i18n.strings import ENGLISH, load_strings

ORIGIN = "real-eea-bathing-water"


def _rows() -> list[list]:
    def both(code: str, bw_id: str, first: str | None, second: str | None, **extra):
        return [row(code, bw_id, 2020, first, **extra), row(code, bw_id, 2024, second, **extra)]

    rows: list[list] = [HEADER]
    rows += both("IT", "B1", "1 - Excellent", "2 - Good")  # moved down
    rows += both("IT", "B2", "3 - Sufficient", "1 - Excellent")  # moved up
    rows += both("IT", "B3", "2 - Good", "2 - Good", kind="lakeBathingWater")  # unchanged
    rows += both("IT", "B4", "3 - Good or Sufficient", "1 - Excellent")  # not comparable: the README does not explain the class
    rows += both("IT", "B5", "1 - Excellent", "0 - Not classified")  # not comparable
    rows += both("IT", "B6", "4 - Poor", "3 - Sufficient")  # moved up
    rows.append(row("IT", "B7", 2024, "1 - Excellent"))  # only in the second season
    rows.append(row("IT", "B8", 2020, "2 - Good"))  # only in the first season
    rows += both("IT", "B9", None, "1 - Excellent")  # a blank class: not comparable
    rows += both("EL", "G1", "1 - Excellent", "1 - Excellent")  # Greece, written EL in the file
    rows += both("EL", "G2", "2 - Good", "4 - Poor")
    return rows


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: [])
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: [])


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path, rows=_rows())
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(path))
    return path


# --- the order -----------------------------------------------------------------------------------------------------------


def test_only_the_four_readme_categories_have_a_rank():
    assert ORDER == ("Excellent", "Good", "Sufficient", "Poor")
    assert [rank_of(q) for q in ("1 - Excellent", "2 - Good", "3 - Sufficient", "4 - Poor")] == [0, 1, 2, 3]
    assert rank_of("1 - excellent") == 0  # the label is compared case-insensitively
    for other in ("0 - Not classified", "3 - Good or Sufficient", "(blank)", None, "9 - Surprise", "Good", ""):
        assert rank_of(other) is None, other  # never interpreted, never guessed


# --- the pure comparison -------------------------------------------------------------------------------------------------


def test_transitions_follow_the_order_and_excluded_classes_are_counted_apart():
    pairs = {
        ("1 - Excellent", "2 - Good"): 3,  # down
        ("3 - Sufficient", "1 - Excellent"): 2,  # up
        ("2 - Good", "2 - Good"): 5,  # unchanged
        ("3 - Good or Sufficient", "1 - Excellent"): 4,  # not comparable
        ("1 - Excellent", "0 - Not classified"): 1,  # not comparable
    }
    result = compare_seasons(pairs, {"x": 20}, {"x": 20})
    assert (result["paired_bathing_waters"], result["comparable"]) == (15, 10)
    assert (result["moved_up"], result["moved_down"], result["unchanged"]) == (2, 3, 5)
    assert result["not_comparable"]["count"] == 5 and len(result["not_comparable"]["pairs"]) == 2
    assert result["comparable"] + result["not_comparable"]["count"] == result["paired_bathing_waters"]
    assert result["transitions"] == [
        {"from_class": "Excellent", "to_class": "Good", "count": 3},
        {"from_class": "Good", "to_class": "Good", "count": 5},
        {"from_class": "Sufficient", "to_class": "Excellent", "count": 2},
    ]
    assert (result["only_in_season_a"], result["only_in_season_b"]) == (5, 5)


@settings(max_examples=100, deadline=None)
@given(
    counts=st.dictionaries(
        st.tuples(
            st.sampled_from(["1 - Excellent", "2 - Good", "3 - Sufficient", "4 - Poor", "0 - Not classified", "3 - Good or Sufficient", "(blank)"]),
            st.sampled_from(["1 - Excellent", "2 - Good", "3 - Sufficient", "4 - Poor", "0 - Not classified", "3 - Good or Sufficient", "(blank)"]),
        ),
        st.integers(min_value=1, max_value=50),
    )
)
def test_property_swapping_the_seasons_swaps_up_and_down_and_every_pair_is_accounted_for(counts):
    forward = compare_seasons(counts, {"x": 1000}, {"x": 1000})
    backward = compare_seasons({(b, a): n for (a, b), n in counts.items()}, {"x": 1000}, {"x": 1000})
    assert forward["moved_up"] == backward["moved_down"] and forward["moved_down"] == backward["moved_up"]
    assert forward["unchanged"] == backward["unchanged"] and forward["comparable"] == backward["comparable"]
    assert forward["comparable"] + forward["not_comparable"]["count"] == forward["paired_bathing_waters"] == sum(counts.values())
    assert sum(t["count"] for t in forward["transitions"]) == forward["comparable"]


# --- the store -------------------------------------------------------------------------------------------------------------


def test_the_store_counts_both_seasons_and_the_pairs(built):
    result = season_change("IT", 2020, 2024)
    assert result["country"] == "IT" and result["order"] == ["Excellent", "Good", "Sufficient", "Poor"]
    assert result["data_range"] == {"first_season": 2020, "last_season": 2024} and result["flags"] == []
    assert result["totals"]["a"] == {
        "season": 2020, "bathing_waters": 8,
        "classes": {"(blank)": 1, "1 - Excellent": 2, "2 - Good": 2, "3 - Good or Sufficient": 1, "3 - Sufficient": 1, "4 - Poor": 1},
    }
    assert result["totals"]["b"]["classes"] == {"0 - Not classified": 1, "1 - Excellent": 4, "2 - Good": 2, "3 - Sufficient": 1}
    assert result["paired_bathing_waters"] == 7 and result["comparable"] == 4
    assert (result["moved_up"], result["moved_down"], result["unchanged"]) == (2, 1, 1)
    assert result["transitions"] == [
        {"from_class": "Excellent", "to_class": "Good", "count": 1},
        {"from_class": "Good", "to_class": "Good", "count": 1},
        {"from_class": "Sufficient", "to_class": "Excellent", "count": 1},
        {"from_class": "Poor", "to_class": "Sufficient", "count": 1},
    ]
    assert result["not_comparable"] == {
        "count": 3,
        "pairs": [
            {"quality_a": "(blank)", "quality_b": "1 - Excellent", "count": 1},
            {"quality_a": "1 - Excellent", "quality_b": "0 - Not classified", "count": 1},
            {"quality_a": "3 - Good or Sufficient", "quality_b": "1 - Excellent", "count": 1},
        ],
    }
    assert (result["only_in_season_a"], result["only_in_season_b"]) == (1, 1)  # present in one season only: counted, never imputed


def test_the_type_filter_the_greek_alias_and_the_reverse_order(built):
    lakes = season_change("IT", 2020, 2024, "LAKEBATHINGWATER")  # case-insensitive, like the list route
    assert lakes["type"] == "LAKEBATHINGWATER" and lakes["paired_bathing_waters"] == 1 and lakes["unchanged"] == 1
    assert season_change("EL", 2020, 2024)["country"] == "GR"
    greek = season_change("GR", 2020, 2024)
    assert (greek["moved_down"], greek["unchanged"], greek["moved_up"]) == (1, 1, 0)
    reverse = season_change("IT", 2024, 2020)
    assert (reverse["moved_up"], reverse["moved_down"]) == (1, 2) and reverse["paired_bathing_waters"] == 7
    same = season_change("IT", 2024, 2024)
    assert same["comparable"] == same["unchanged"] and same["moved_up"] == same["moved_down"] == 0


def test_seasons_outside_the_data_and_countries_without_data_are_flagged_not_filled(built):
    outside = season_change("IT", 2010, 2024)
    assert "season-outside-data" in outside["flags"] and outside["totals"]["a"]["bathing_waters"] == 0 and outside["paired_bathing_waters"] == 0
    assert "season-without-classifications" in outside["flags"] and outside["data_range"]["first_season"] == 2020
    future = season_change("IT", 2020, 2030)
    assert "season-outside-data" in future["flags"] and future["comparable"] == 0
    assert "no-bathing-water-data-for-country" in season_change("NO", 2020, 2024)["flags"]
    assert season_change("ZZ", 2020, 2024)["data_range"] == {"first_season": None, "last_season": None}


def test_a_missing_store_is_a_state_not_an_error(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "absent.sqlite"))
    result = season_change("IT", 2020, 2024)
    assert result["flags"] == ["store-not-ready"] and result["comparable"] == 0 and result["totals"]["a"]["bathing_waters"] == 0


def test_the_store_queries_are_parameterised(built):
    for text in ("'; DROP TABLE sites; --", "x' OR '1'='1"):
        assert store.season_class_counts("IT", 2020, text) == {}
        assert store.season_pair_counts("IT", 2020, 2024, text) == {}
        assert store.season_class_counts(text, 2020) == {}
    assert store.list_bathing_waters()[0] > 0  # the tables are intact


# --- the route ---------------------------------------------------------------------------------------------------------------


def test_the_route_is_labelled_a_classification_comparison_with_localised_notices(http, built):
    body = http.get("/bathing-waters/change?country=IT&season_a=2020&season_b=2024").json()
    assert body["origin"] == ORIGIN and body["attribution"].endswith("(EEA CC BY 4.0)") and body["data_freshness"]["status"] == "snapshot"
    assert body["language"] == "en" and body["notice"] == ENGLISH["bathing_water_classification_notice"]
    assert body["comparison_notice"] == ENGLISH["bathing_change_notice"] and "No concentration or threshold" in body["comparison_notice"]
    assert body["bathing_water"]["state"] == "ready" and body["season_a"] == 2020 and body["season_b"] == 2024
    assert (body["moved_up"], body["moved_down"], body["unchanged"], body["comparable"]) == (2, 1, 1, 4)
    assert body["transitions"][0] == {"from_class": "Excellent", "to_class": "Good", "count": 1}
    french = http.get("/bathing-waters/change?country=IT&season_a=2020&season_b=2024&language=fr").json()
    assert french["language"] == "fr" and french["comparison_notice"] == load_strings("fr").get("bathing_change_notice")
    assert french["comparison_notice"] != body["comparison_notice"]
    filtered = http.get("/bathing-waters/change?country=EL&season_a=2020&season_b=2024&type=coastalBathingWater").json()
    assert filtered["country"] == "GR" and filtered["type"] == "coastalBathingWater" and filtered["paired_bathing_waters"] == 2


def test_route_errors_and_the_route_does_not_swallow_a_bathing_water_id(http, built):
    for query in (
        "country=IT&season_a=2020", "season_a=2020&season_b=2024", "country=ITA&season_a=2020&season_b=2024",
        "country=IT&season_a=1800&season_b=2024", "country=IT&season_a=2020&season_b=2200",
        "country=IT&season_a=abc&season_b=2024", "country=IT&season_a=2020&season_b=2024&language=zz",
        f"country=IT&season_a=2020&season_b=2024&type={'x' * 65}",
    ):
        assert http.get(f"/bathing-waters/change?{query}").status_code == 422, query
    assert http.get("/bathing-waters/B1").status_code == 200  # the identifier route still works next to /change
    assert http.get("/bathing-waters/change?country=IT&season_a=2020&season_b=2024&type=%27%3B%20DROP%20TABLE%20sites%3B%20--").json()["paired_bathing_waters"] == 0


def test_without_a_store_the_route_answers_with_the_state(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "absent.sqlite"))
    body = http.get("/bathing-waters/change?country=IT&season_a=2020&season_b=2024").json()
    assert body["bathing_water"]["state"] == "not-built" and body["flags"] == ["store-not-ready"]


# --- the chat tool -------------------------------------------------------------------------------------------------------------


def _ctx(country: str | None = None):
    return app_module._chat_tool_context(country)


def test_the_chat_tool_returns_counts_with_the_notices_and_no_concentration(built):
    outcome = run_tool(_ctx("IT"), "compare_bathing_seasons", {"country": "IT", "season_a": 2020, "season_b": 2024}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["origin"] == ORIGIN and result["moved_up"] == 2 and result["moved_down"] == 1 and result["comparable"] == 4
    assert result["comparison_notice"] == COMPARISON_NOTICE_SHORT and len(result["comparison_notice"]) < 200  # survives the sanitiser's cut
    assert "not a concentration" in result["notice"]
    assert result["data_freshness"] == {"status": "snapshot", "as_of": None} and result["attribution"].endswith("(EEA CC BY 4.0)")
    assert outcome.summary == "4 comparable of 7 paired bathing waters"
    assert "concentration" not in str([k for k in result if k.startswith("conc")])


def test_the_chat_tool_enforces_the_country_and_bounds_its_arguments(built):
    refused = run_tool(_ctx("GR"), "compare_bathing_seasons", {"country": "IT", "season_a": 2020, "season_b": 2024}, ALL_TOOLS)
    assert not refused.ok and "other countries are not mixed" in str(refused.error)
    for arguments in (
        {"country": "IT", "season_a": 2020}, {"season_a": 2020, "season_b": 2024}, {"country": "ITA", "season_a": 2020, "season_b": 2024},
        {"country": "IT", "season_a": "2020", "season_b": 2024}, {"country": "IT", "season_a": 1800, "season_b": 2024},
        {"country": "IT", "season_a": True, "season_b": 2024}, {"country": "IT", "season_a": 2020, "season_b": 2024, "type": "x"},
        {"country": "'; DROP TABLE sites; --", "season_a": 2020, "season_b": 2024},
    ):
        assert not run_tool(_ctx(None), "compare_bathing_seasons", arguments, ALL_TOOLS).ok, arguments
    assert not run_tool(_ctx(None), "compare_bathing_seasons", {"country": "IT", "season_a": 2020, "season_b": 2024}, ("list_sites",)).ok
