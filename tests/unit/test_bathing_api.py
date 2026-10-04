"""Bathing-water classification in the API and the chat tools: routes, /countries, tools, prompt facts, end to end.

The store is built from a SYNTHETIC workbook (``bathing_fixtures``); the identifiers, names and classes are invented.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from bathing_fixtures import build_fixture_store
from fastapi.testclient import TestClient

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.llm_guard import ChatSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.chat.prompts import CHAT_SYSTEM_PROMPT
from oah.chat.tools import ALL_TOOLS, TOOL_DEFINITIONS, TOOLS_BY_INDEX, allowed_tools, citations_for, origin_for, run_tool, trace_arguments

ORIGIN = "real-eea-bathing-water"


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
    path = build_fixture_store(tmp_path)
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(path))
    return path


# --- GET /bathing-waters ----------------------------------------------------------------------------------------------


def test_the_list_is_labelled_a_classification_with_attribution_and_freshness(http, built):
    body = http.get("/bathing-waters").json()
    assert body["origin"] == ORIGIN and body["attribution"].endswith("(EEA CC BY 4.0)")
    assert "classification" in body["notice"].lower() and "not a concentration" in body["notice"] and "not a statement of legal compliance" in body["notice"]
    assert body["bathing_water"]["state"] == "ready" and body["data_freshness"]["status"] == "snapshot"
    assert body["data_freshness"]["as_of"] == "2026-10-02T00:00:00Z"
    assert (body["total_matching"], body["returned"], body["limit"], body["offset"], body["truncated"]) == (8, 8, 200, 0, False)
    first = body["bathing_waters"][0]
    assert first["id"] == "EL001" and first["country"] == "GR" and first["origin"] == first["source"] == ORIGIN
    assert (first["latest_season"], first["latest_quality"], first["latest_quality_class"], first["n_seasons"]) == (2025, "2 - Good", "Good", 2)
    assert first["type"] == "coastalBathingWater" and first["latitude"] == 35.1 and first["location_status"] == "located"


def test_a_profile_link_is_plain_text_never_fetched_and_odd_schemes_are_not_passed(http, built, monkeypatch):
    import socket

    def refuse(*_a, **_k):
        raise AssertionError("a bathing-water request must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", refuse)
    by_id = {b["id"]: b for b in http.get("/bathing-waters").json()["bathing_waters"]}
    assert by_id["EL001"]["bw_profile_url"] == "https://example.invalid/synthetic/profile/EL001"
    assert by_id["IT003"]["bw_profile_url"] is None  # the file's javascript: value was dropped at build time
    detail = http.get("/bathing-waters/EL001").json()
    assert "never fetched" in detail["profile_note"]


def test_filters_narrow_the_list_and_el_is_read_as_gr(http, built):
    ids = lambda query: [b["id"] for b in http.get(f"/bathing-waters?{query}").json()["bathing_waters"]]  # noqa: E731
    assert ids("country=IT") == ["IT001", "IT002", "IT003", "IT004"]
    assert ids("country=EL") == ids("country=gr") == ["EL001", "EL002", "GR003"]
    assert ids("country=NO") == ["NO001"] and ids("country=DE") == []
    assert ids("q=synthetic%20beach") == ["EL001", "GR003"]
    assert ids("type=lakeBathingWater") == ["EL002"] and ids("type=riverBathingWater") == ["IT002"]
    assert ids("quality=Excellent") == ids("quality=1%20-%20Excellent") == ["EL002", "IT004", "NO001"]
    assert ids("country=IT&quality=Poor") == ["IT003"]


def test_pagination_and_bounds(http, built):
    first = http.get("/bathing-waters?limit=3").json()
    assert [b["id"] for b in first["bathing_waters"]] == ["EL001", "EL002", "GR003"] and first["truncated"] is True and first["returned"] == 3
    second = http.get("/bathing-waters?limit=3&offset=3").json()
    assert [b["id"] for b in second["bathing_waters"]] == ["IT001", "IT002", "IT003"] and second["truncated"] is True
    last = http.get("/bathing-waters?limit=3&offset=6").json()
    assert [b["id"] for b in last["bathing_waters"]] == ["IT004", "NO001"] and last["truncated"] is False
    assert http.get("/bathing-waters?limit=500").status_code == 200
    for bad in ("limit=501", "limit=0", "offset=-1", "country=ITA", "country=1", "q=" + "x" * 65, "type=" + "x" * 65, "quality=" + "x" * 65):
        assert http.get(f"/bathing-waters?{bad}").status_code == 422, bad


def test_the_filters_are_inert_against_sql(http, built):
    for field_name in ("q", "type", "quality"):
        response = http.get("/bathing-waters", params={field_name: "'; DROP TABLE sites; --"})
        assert response.status_code == 200 and response.json()["bathing_waters"] == []
    assert http.get("/bathing-waters").json()["total_matching"] == 8


def test_without_a_store_the_list_is_empty_and_the_state_is_stated(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "absent.sqlite"))
    body = http.get("/bathing-waters").json()
    assert body["bathing_waters"] == [] and body["total_matching"] == 0 and body["bathing_water"]["state"] == "not-built"
    assert "build_bathing_water_store.py" in body["bathing_water"]["detail"] and body["origin"] == ORIGIN
    missing = http.get("/bathing-waters/EL001")
    assert missing.status_code == 404 and "not-built" in missing.json()["detail"]


def test_a_corrupt_store_is_reported_not_raised(http, tmp_path: Path, monkeypatch):
    broken = tmp_path / "broken.sqlite"
    broken.write_bytes(b"garbage" * 100)
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(broken))
    assert http.get("/bathing-waters").json()["bathing_water"]["state"] == "unreadable"
    assert http.get("/countries").json()["bathing_water"]["state"] == "unreadable"


# --- GET /bathing-waters/{id} ---------------------------------------------------------------------------------------


def test_the_history_lists_each_season_with_class_calendar_and_management(http, built):
    body = http.get("/bathing-waters/IT001").json()
    assert body["origin"] == ORIGIN and body["attribution"].endswith("(EEA CC BY 4.0)") and "not a concentration" in body["notice"]
    assert body["bathing_water"]["id"] == "IT001" and body["bathing_water"]["name"] == "IT001"  # the placeholder name is not shown
    assert body["history"] == [
        {"season": 2020, "quality": "3 - Good or Sufficient", "quality_class": "Good or Sufficient",
         "monitoring_calendar": "1 - Implemented", "management": "1 - Continuously monitored"},
        {"season": 2021, "quality": "0 - Not classified", "quality_class": "Not classified",
         "monitoring_calendar": "0 - Not implemented", "management": "4 - Monitoring gap"},
    ]
    assert body["data_freshness"]["status"] == "snapshot"


def test_unknown_values_blank_values_and_missing_coordinates_pass_through_as_written(http, built):
    odd = http.get("/bathing-waters/IT002").json()
    assert [(h["season"], h["quality"], h["quality_class"]) for h in odd["history"]] == [(2024, None, None), (2025, "9 - Surprise", "Surprise")]
    nowhere = http.get("/bathing-waters/IT004").json()["bathing_water"]
    assert nowhere["latitude"] is None and nowhere["longitude"] is None and nowhere["location_status"] == "no-location"


def test_an_unknown_or_oversized_identifier_is_a_404(http, built):
    assert http.get("/bathing-waters/NOPE").status_code == 404
    assert http.get("/bathing-waters/" + "x" * 300).status_code == 404
    assert http.get("/bathing-waters/%27%3B%20DROP%20TABLE%20sites%3B%20--").status_code == 404
    assert http.get("/bathing-waters").json()["total_matching"] == 8


def test_the_bathing_routes_are_protected_like_the_others(http, built, monkeypatch):
    monkeypatch.setenv("OAH_API_KEY", "secret")
    monkeypatch.delenv("OAH_INSECURE_NO_AUTH", raising=False)
    assert http.get("/bathing-waters").status_code == 401 and http.get("/bathing-waters/EL001").status_code == 401
    assert http.get("/bathing-waters", headers={"X-API-Key": "secret"}).status_code == 200


# --- /countries -------------------------------------------------------------------------------------------------------


def test_countries_gain_the_bathing_water_block(http, built):
    body = http.get("/countries").json()
    assert body["bathing_water"]["state"] == "ready"
    by_code = {c["code"]: c for c in body["countries"]}
    greece = by_code["GR"]["bathing_water"]
    assert (greece["bathing_waters"], greece["classification_rows"], greece["first_season"], greece["latest_season"]) == (3, 4, 2024, 2025)
    assert greece["latest_season_counts"] == {"1 - Excellent": 1, "2 - Good": 1, "3 - Sufficient": 1}
    assert greece["origin"] == ORIGIN and greece["content"] == "classification-only"
    assert by_code["IT"]["bathing_water"]["latest_season_counts"]["9 - Surprise"] == 1
    assert by_code["NO"]["bathing_water"]["bathing_waters"] == 1
    # the country status and the other fields do not depend on the bathing store
    assert by_code["GR"]["status"] == "no-evaluable-water-data" and by_code["GR"]["total_sites"] == 0


def test_countries_without_a_store_have_a_null_block_and_a_state(http, tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "absent.sqlite"))
    body = http.get("/countries").json()
    assert body["bathing_water"]["state"] == "not-built" and all(c["bathing_water"] is None for c in body["countries"])


# --- chat tools -------------------------------------------------------------------------------------------------------


def _ctx(country: str | None = None):
    return app_module._chat_tool_context(country)


def test_the_two_tools_exist_and_the_microbiology_index_uses_only_them(built):
    assert {"list_bathing_waters", "get_bathing_water_history"} <= set(ALL_TOOLS)
    assert set(TOOLS_BY_INDEX["microbiology"]) == {
        "list_countries", "list_bathing_waters", "get_bathing_water_history", "compare_bathing_seasons",
        "get_bathing_samples", "compare_bathing_concentrations", "get_weather_context",  # weather context: package 7
    }
    assert allowed_tools("microbiology") == TOOLS_BY_INDEX["microbiology"]
    assert "get_site_measurements" not in allowed_tools("microbiology")
    assert "list_bathing_waters" in allowed_tools(None)
    assert TOOL_DEFINITIONS["get_bathing_water_history"]["input_schema"]["required"] == ["bathing_water_id"]


def test_list_bathing_waters_returns_a_labelled_bounded_result(built):
    outcome = run_tool(_ctx(), "list_bathing_waters", {"country": "EL"}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["origin"] == ORIGIN and result["country"] == "GR" and result["total_bathing_waters"] == 3 and result["truncated"] is False
    assert result["data_freshness"] == {"status": "snapshot", "as_of": None}
    assert result["attribution"].endswith("(EEA CC BY 4.0)") and "not a concentration" in result["notice"]
    first = result["bathing_waters"][0]
    assert first == {"id": "EL001", "country": "GR", "name": "SYNTHETIC BEACH ONE", "type": "coastalBathingWater", "first_season": 2024,
                     "latest_season": 2025, "n_seasons": 2, "latest_quality": "2 - Good", "location_status": "located"}
    assert "bw_profile_url" not in json.dumps(result) and "http" not in outcome.content.replace("https://", "x")  # no link reaches the model
    assert outcome.summary == "3 of 3 bathing waters"


def test_list_bathing_waters_filters_and_limit(built):
    named = run_tool(_ctx(), "list_bathing_waters", {"query": "river", "quality": "Surprise", "type": "riverBathingWater", "country": "IT"}, ALL_TOOLS).result
    assert named is not None and [b["id"] for b in named["bathing_waters"]] == ["IT002"] and named["type"] == "riverBathingWater"
    limited = run_tool(_ctx(), "list_bathing_waters", {"limit": 2}, ALL_TOOLS).result
    assert limited is not None and limited["returned"] == 2 and limited["total_bathing_waters"] == 8 and limited["truncated"] is True
    nothing = run_tool(_ctx(), "list_bathing_waters", {"country": "NO", "query": "zzz"}, ALL_TOOLS).result
    assert nothing is not None and nothing["bathing_waters"] == [] and "held for: GR, IT, NO" in nothing["note"]


@pytest.mark.parametrize(
    "arguments",
    [{"limit": 0}, {"limit": 51}, {"limit": True}, {"limit": "5"}, {"query": "x" * 65}, {"query": "bad\x00text"}, {"query": ""}, {"query": 5},
     {"quality": "x" * 65}, {"type": "x" * 65}, {"country": "ITA"}, {"country": "1"}, {"extra": 1}],
)
def test_list_bathing_waters_inputs_are_bounded(built, arguments):
    outcome = run_tool(_ctx(), "list_bathing_waters", arguments, ALL_TOOLS)
    assert outcome.ok is False and outcome.error and json.loads(outcome.content) == {"error": outcome.error}


def test_list_bathing_waters_enforces_the_selected_country_and_knows_the_codes(built):
    other = run_tool(_ctx("GR"), "list_bathing_waters", {"country": "IT"}, ALL_TOOLS)
    assert other.ok is False and "selected country is GR" in (other.error or "")
    own = run_tool(_ctx("GR"), "list_bathing_waters", {}, ALL_TOOLS).result
    assert own is not None and {b["country"] for b in own["bathing_waters"]} == {"GR"}
    unknown = run_tool(_ctx(), "list_bathing_waters", {"country": "ZZ"}, ALL_TOOLS)
    assert unknown.ok is False and "Unknown country code" in (unknown.error or "")


def test_the_injection_style_query_is_inert_and_instruction_text_in_a_name_is_removed(built):
    injected = run_tool(_ctx(), "list_bathing_waters", {"query": "'; DROP TABLE sites; --"}, ALL_TOOLS)
    assert injected.ok and injected.result is not None and injected.result["bathing_waters"] == []
    named = run_tool(_ctx(), "list_bathing_waters", {"country": "IT", "quality": "Poor"}, ALL_TOOLS)
    assert named.ok and named.result is not None
    assert named.result["bathing_waters"][0]["name"] == "[removed: instruction-like text]" and named.notes
    assert "<" not in named.content


def test_get_bathing_water_history_returns_seasons_and_enforces_the_country(built):
    outcome = run_tool(_ctx(), "get_bathing_water_history", {"bathing_water_id": "IT001"}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["origin"] == ORIGIN and result["bathing_water"]["id"] == "IT001" and result["total_seasons"] == 2
    assert result["history"][1] == {"season": 2021, "quality": "0 - Not classified", "monitoring_calendar": "0 - Not implemented", "management": "4 - Monitoring gap"}
    assert result["data_freshness"]["status"] == "snapshot" and "not a concentration" in result["notice"] and outcome.summary == "2 seasons"
    refused = run_tool(_ctx("GR"), "get_bathing_water_history", {"bathing_water_id": "IT001"}, ALL_TOOLS)
    assert refused.ok is False and "belongs to country IT" in (refused.error or "")
    assert run_tool(_ctx("IT"), "get_bathing_water_history", {"bathing_water_id": "IT001"}, ALL_TOOLS).ok


@pytest.mark.parametrize("arguments", [{}, {"bathing_water_id": ""}, {"bathing_water_id": "../etc"}, {"bathing_water_id": "x" * 129}, {"bathing_water_id": 5}, {"other": 1}])
def test_get_bathing_water_history_inputs_are_bounded(built, arguments):
    assert run_tool(_ctx(), "get_bathing_water_history", arguments, ALL_TOOLS).ok is False


def test_an_unknown_bathing_water_is_an_error_result_the_model_can_read(built):
    outcome = run_tool(_ctx(), "get_bathing_water_history", {"bathing_water_id": "NOPE-1"}, ALL_TOOLS)
    assert outcome.ok is False and "Unknown bathing water" in (outcome.error or "")


def test_the_tools_say_so_when_the_store_is_not_built(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "absent.sqlite"))
    listed = run_tool(_ctx(), "list_bathing_waters", {}, ALL_TOOLS)
    assert listed.ok and listed.result is not None and listed.result["bathing_waters"] == [] and "no country" in listed.result["note"]
    assert run_tool(_ctx(), "get_bathing_water_history", {"bathing_water_id": "IT001"}, ALL_TOOLS).ok is False


def test_a_context_without_the_bathing_store_refuses_the_tools():
    from oah.chat import ToolContext

    ctx = ToolContext(None, lambda: [], lambda: ([], 0), lambda _l: None, lambda *_a: None, lambda: {}, lambda: {})
    for name, arguments in (("list_bathing_waters", {}), ("get_bathing_water_history", {"bathing_water_id": "A"})):
        outcome = run_tool(ctx, name, arguments, ALL_TOOLS)
        assert outcome.ok is False and "not available in this deployment" in (outcome.error or "")


def test_list_countries_shows_the_bathing_block_and_citations_name_the_source(built):
    countries = run_tool(_ctx(), "list_countries", {}, ALL_TOOLS).result
    assert countries is not None
    assert {c["code"]: c["bathing_water"]["latest_season"] for c in countries["countries"] if c["bathing_water"]} == {"GR": 2025, "IT": 2025, "NO": 2025}
    listed = run_tool(_ctx(), "list_bathing_waters", {"country": "GR"}, ALL_TOOLS)
    history = run_tool(_ctx(), "get_bathing_water_history", {"bathing_water_id": "EL001"}, ALL_TOOLS)
    cited = citations_for(listed) + citations_for(history)
    assert {c["source"] for c in cited} == {ORIGIN} and {c["site_id"] for c in cited} == {"EL001", "EL002", "GR003"}
    assert [c["period_start"] for c in citations_for(history)] == ["2024", "2025"]
    assert origin_for([listed, history]) == ORIGIN
    sandbox = run_tool(_ctx(), "list_sites", {}, ALL_TOOLS)
    assert origin_for([listed, sandbox]) == "real-mixed"
    assert trace_arguments("list_bathing_waters", {"country": "GR", "limit": 5, "stray": 1}) == {"country": "GR", "limit": 5}


def test_a_long_history_is_cut_to_the_bound_and_says_so(tmp_path: Path, monkeypatch):
    from bathing_fixtures import HEADER, row

    from oah.chat.tools import MAX_TOOL_RESULT_CHARS

    rows = [HEADER, *(row("IT", "LONG1", 1990 + i, "1 - Excellent", name="X" * 150) for i in range(36))]
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(build_fixture_store(tmp_path, rows=rows)))
    outcome = run_tool(_ctx(), "get_bathing_water_history", {"bathing_water_id": "LONG1"}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None and len(outcome.content) <= MAX_TOOL_RESULT_CHARS
    assert outcome.result["total_seasons"] == 36 and outcome.result["returned"] == 36


# --- prompt facts -----------------------------------------------------------------------------------------------------


def test_the_prompt_states_what_is_and_is_not_available():
    text = CHAT_SYSTEM_PROMPT
    for needle in (
        "real-eea-bathing-water", "CLASSIFICATION", "NOT a concentration", "not a statement of legal compliance",
        "real-eea-bathing-samples", "INDIVIDUAL sample results", "NO threshold", "protozoa", "(Giardia, Cryptosporidium) are NOT available",
        "Greece and Italy", "Norway has no bathing water in that file", "never turn a class into a concentration or a threshold",
    ):
        assert needle in text, needle
    assert "are not available yet" not in text  # the earlier "not available yet" sentence is gone


# --- the chat route end to end ----------------------------------------------------------------------------------------


@dataclass
class _Text:
    text: str
    type: str = "text"


@dataclass
class _ToolUse:
    id: str
    name: str
    input: Any
    type: str = "tool_use"


@dataclass
class _Client:
    replies: list[Any]
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        def _create(**kwargs: Any) -> Any:
            self.calls.append({**kwargs, "messages": json.loads(json.dumps(kwargs["messages"], default=str))})
            return self.replies[len(self.calls) - 1]

        self.messages = SimpleNamespace(create=_create)


def _reply(*blocks: Any) -> Any:
    return SimpleNamespace(content=list(blocks), usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _guard(monkeypatch) -> None:
    guard = ChatSpendGuard(per_minute=10_000, daily_cap=100, cache_ttl_seconds=60.0, max_steps=6)
    monkeypatch.setattr(deps_module, "get_chat_guard", lambda: guard)


def test_a_chat_answer_from_the_bathing_store_is_labelled_and_cited(http, built, monkeypatch):
    _guard(monkeypatch)
    client = _Client([
        _reply(_ToolUse("t1", "list_bathing_waters", {"country": "GR", "query": "beach one"})),
        _reply(_ToolUse("t2", "get_bathing_water_history", {"bathing_water_id": "EL001"})),
        _reply(_Text("EEA bathing-water classification for SYNTHETIC BEACH ONE: 1 - Excellent in the 2024 season and 2 - Good in 2025. It is a classification, not a concentration.")),
    ])
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: client)
    response = http.post("/chat", json={"message": "How was the classification of Beach One?", "country": "GR", "index": "microbiology"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered" and body["origin"] == ORIGIN and body["index"] == "microbiology"
    assert [s["tool"] for s in body["steps"]] == ["list_bathing_waters", "get_bathing_water_history"] and all(s["ok"] for s in body["steps"])
    cited = [c for c in body["citations"] if c["tool"] == "get_bathing_water_history"]
    assert [c["period_start"] for c in cited] == ["2024", "2025"] and {c["source"] for c in cited} == {ORIGIN}
    offered = {tool["name"] for tool in client.calls[0]["tools"]}
    assert offered == {
        "list_countries", "list_bathing_waters", "get_bathing_water_history", "compare_bathing_seasons",
        "get_bathing_samples", "compare_bathing_concentrations", "get_weather_context",
    }  # the microbiology index narrows the tools (weather context for a bathing water: package 7)
    assert "real-eea-bathing-water" in client.calls[0]["system"] and body["grounded"] is True


def test_the_chat_refuses_a_bathing_water_of_another_country(http, built, monkeypatch):
    _guard(monkeypatch)
    client = _Client([
        _reply(_ToolUse("t1", "get_bathing_water_history", {"bathing_water_id": "IT001"})),
        _reply(_Text("That bathing water is in another country than the one selected.")),
    ])
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: client)
    body = http.post("/chat", json={"message": "History of IT001?", "country": "GR"}).json()
    assert body["steps"][0]["ok"] is False and body["origin"] == "real-sandbox"  # no successful tool result
    assert "belongs to country IT" in client.calls[1]["messages"][-1]["content"][0]["content"]


def test_the_microbiology_index_is_an_accepted_request_value(http, built, monkeypatch):
    _guard(monkeypatch)
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: _Client([_reply(_Text("No data was consulted."))]))
    assert http.post("/chat", json={"message": "Anything?", "index": "microbiology"}).status_code == 200
    assert http.post("/chat", json={"message": "Anything?", "index": "colloids"}).status_code == 422
