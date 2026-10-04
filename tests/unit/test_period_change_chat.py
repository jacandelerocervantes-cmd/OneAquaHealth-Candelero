"""The chat tool ``compare_periods``: validation, country enforcement, bounded and sanitised results, grounding of its numbers.

Data is the SYNTHETIC slice of ``period_fixtures`` (invented values). The model is a scripted fake client; no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from period_fixtures import LOCATIONS, OBSERVATIONS, S1, rows
from waterbase_fixtures import build_fixture_store

import oah.api.app as app_module
import oah.api.deps as deps_module
from oah.api.llm_guard import ChatSpendGuard
from oah.api.rate_limit import RateLimiter
from oah.chat.prompts import CHAT_SYSTEM_PROMPT
from oah.chat.tools import (
    ALL_TOOLS,
    MAX_TOOL_RESULT_CHARS,
    TOOL_DEFINITIONS,
    TOOLS_BY_INDEX,
    allowed_tools,
    citations_for,
    run_tool,
    trace_arguments,
)
from oah.i18n.strings import ENGLISH
from oah.indices.regimes import PO4_PER_P


@pytest.fixture(autouse=True)
def _world(monkeypatch):
    monkeypatch.setattr(deps_module, "get_rate_limiter", lambda: RateLimiter(10_000, 60.0))
    monkeypatch.setattr(deps_module, "get_cached_observations", lambda: OBSERVATIONS)
    monkeypatch.setattr(deps_module, "get_cached_locations", lambda: LOCATIONS)


@pytest.fixture()
def http() -> TestClient:
    return TestClient(app_module.app)


@pytest.fixture()
def built(tmp_path: Path, monkeypatch) -> Path:
    path = build_fixture_store(tmp_path, rows=rows())
    monkeypatch.setenv("OAH_WATERBASE_STORE", str(path))
    return path


def ctx(country: str | None = None):
    return app_module._chat_tool_context(country)


def arguments(scope: str = "site", target: str = S1, parameter: str = "Total phosphates", **periods: str) -> dict[str, str]:
    base = {"a_from": "2021-01", "a_to": "2021-12", "b_from": "2023-01", "b_to": "2023-12"}
    return {"scope": scope, "id_or_country": target, "parameter": parameter, **{**base, **periods}}


def call(arguments_: dict[str, Any], country: str | None = None, tools=ALL_TOOLS):
    return run_tool(ctx(country), "compare_periods", arguments_, tools)


# --- the tool result ----------------------------------------------------------------------------------------------------------


def test_the_site_result_has_every_number_with_its_unit_the_limit_and_the_flags(built):
    outcome = call(arguments())
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["origin"] == result["source"] == "real-eea-waterbase" and result["status"] == "ok"
    assert result["data_freshness"] == {"status": "snapshot", "as_of": None} and result["attribution"].startswith("EEA Waterbase")
    a, b = result["period_a"], result["period_b"]
    assert (a["n_samples"], b["n_samples"], a["start"], b["end"]) == (3, 3, "2021-01", "2023-12")
    assert a["mean"]["unit"] == "mg/L" and b["mean"]["unit"] == "mg/L" and a["mean"]["amount"] == pytest.approx(0.04 * PO4_PER_P, abs=1e-6)
    assert result["change"]["absolute"]["unit"] == "mg/L" and result["change"]["relative_percent"] == {"amount": 200.0, "unit": "%"}
    assert result["change"]["direction"] == "increased" and result["crossed_limit"] == "within-to-exceeds"
    assert a["limit_check"]["limit"]["unit"] == "mg/L" and a["limit_check"]["limit"]["type"] == "maximum"
    assert a["limit_check"]["limit_basis"].startswith("national: DM 260/2010") and b["limit_check"]["status"] == "exceeds-limit"
    assert b["below_loq_percent"] == {"amount": 25.0, "unit": "%"} and "below-loq-excluded-bias-upward" in b["flags"]
    assert result["data_range"] == {"first": "2021-03", "last": "2023-08"} and "below-loq-excluded-bias-upward" in result["flags"]
    # the fixed sentences survive the sanitiser whole (each is shorter than its 200-character cut) and are the English text
    assert result["approximation_notice"] == ENGLISH["approximation_notice"] and result["interpretation_notice"] == ENGLISH["interpretation_notice"]
    assert "mean_B minus mean_A" in result["definition"] and "Quote only the numbers" in result["definition"]
    assert outcome.summary == "comparison status ok" and "<" not in outcome.content and len(outcome.content) < MAX_TOOL_RESULT_CHARS


def test_a_period_beyond_the_data_comes_back_with_the_range_and_no_shifted_numbers(built):
    outcome = call(arguments(parameter="Nitrate", a_from="2021-05", a_to="2021-05", b_from="2026-05", b_to="2026-05"))
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["data_range"] == {"first": "2021-05", "last": "2024-12"} and result["status"] == "insufficient-data"
    assert result["period_b"]["n_samples"] == 0 and "mean" not in result["period_b"] and "period-outside-data" in result["period_b"]["flags"]
    assert (result["period_b"]["start"], result["period_b"]["end"]) == ("2026-05", "2026-05")
    assert "absolute" not in result["change"] and "direction" not in result["change"]


def test_a_country_result_names_the_paired_sites_and_both_sources_stay_apart(built):
    outcome = call(arguments("country", "IT", "Nitrate"))
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    waterbase, sandbox = result["results"]  # Italy has a sandbox site too: the sources are separate entries, never merged
    assert result["origin"] == "real-mixed" and waterbase["source"] == "real-eea-waterbase" and sandbox["source"] == "real-sandbox"
    assert sandbox["status"] == "insufficient-data" and sandbox["n_sites_paired"] == 0  # no sandbox record lies in 2021 or 2023
    assert (waterbase["n_sites_paired"], waterbase["n_sites_excluded"], waterbase["exclusion_reasons"]) == (3, 1, {"absent-in-period-b": 1})
    assert waterbase["period_a"]["mean_of_site_means"]["unit"] == "mg/L" and waterbase["median_site_relative_change"]["unit"] == "%"
    assert waterbase["river_limit_period_a"]["limit"]["unit"] == "mg/L" and waterbase["period_b"]["river_sites_over_limit"] == 2
    assert "few-sites" in waterbase["flags"] and waterbase["sites_increased"] == 3
    mixed = call(arguments("country", "IT", "Nitrate", a_from="2018-01", a_to="2018-12", b_from="2019-01", b_to="2019-12"))
    assert mixed.result is not None and mixed.result["origin"] == "real-mixed"
    assert [item["source"] for item in mixed.result["results"]] == ["real-eea-waterbase", "real-sandbox"]
    assert mixed.result["results"][1]["resolution"] == "annual-only" and "annual-only" in mixed.result["results"][1]["flags"]
    assert len(mixed.content) < MAX_TOOL_RESULT_CHARS and mixed.summary == "comparison status insufficient-data, ok"


def test_a_sandbox_site_is_compared_on_annual_aggregates(built):
    outcome = call(arguments(target="Loc-Almyros", parameter="Nitrate", a_from="2018-01", a_to="2018-12", b_from="2019-01", b_to="2019-12"))
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["origin"] == "real-sandbox" and result["resolution"] == "annual-only" and "annual-only" in result["flags"]
    assert result["period_a"]["n_unit"] == "aggregate-records" and result["change"]["absolute"] == {"amount": 1.0, "unit": "mg/L"}
    assert "data_freshness" in result and result["data_range"]["last"] == "2021-12"


def test_the_citation_names_the_scope_the_periods_the_mean_and_the_limit_basis(built):
    outcome = call(arguments())
    [citation] = citations_for(outcome)
    assert (citation["tool"], citation["site_id"], citation["parameter"]) == ("compare_periods", S1, "Total phosphates")
    assert (citation["period_start"], citation["period_end"], citation["unit"], citation["source"]) == ("2021-01", "2023-12", "mg/L", "real-eea-waterbase")
    assert citation["value"] == pytest.approx(0.12 * PO4_PER_P, abs=1e-6) and citation["limit_basis"].startswith("national: DM 260/2010")
    country = citations_for(call(arguments("country", "IT", "Nitrate")))
    assert country[0]["site_id"] == "IT" and country[0]["source"] == "real-eea-waterbase"


# --- validation and enforcement ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"scope": "region"}, {"scope": "SITE"}, {"scope": ""}, {"parameter": "Unobtainium"}, {"parameter": "x" * 200},
        {"a_from": "2021-13"}, {"a_from": "2021-12", "a_to": "2021-01"}, {"b_from": "2023-1"}, {"b_to": "2023-12-31"},
        {"a_from": "1800-01"}, {"a_from": 202101}, {"a_to": None}, {"id_or_country": "bad id with spaces"},
        {"id_or_country": "x'; DROP TABLE sites; --"}, {"id_or_country": "../../etc/passwd"}, {"id_or_country": ""},
    ],
)
def test_invalid_arguments_become_a_tool_error_the_model_can_read(built, bad):
    outcome = call({**arguments(), **bad})
    assert outcome.ok is False and outcome.error and outcome.result is None
    assert json.loads(outcome.content) == {"error": outcome.error}


def test_missing_and_unknown_arguments_are_refused(built):
    for name in ("scope", "id_or_country", "parameter", "a_from", "a_to", "b_from", "b_to"):
        partial = arguments()
        del partial[name]
        assert call(partial).ok is False, name
    assert call({**arguments(), "extra": "x"}).ok is False and call({**arguments(), "limit": 5}).ok is False
    assert call("not an object").ok is False and call(None).ok is False
    assert call(arguments("country", "ITA")).ok is False and call(arguments("country", "1T")).ok is False
    assert call(arguments(target="NOPE-1")).ok is False  # an unknown site


def test_the_selected_country_is_enforced_for_a_site_and_for_a_country(built):
    assert call(arguments(), country="IT").ok is True
    refused = call(arguments(), country="GR")
    assert refused.ok is False and "belongs to country IT, not the selected country GR" in str(refused.error)
    assert call(arguments("country", "IT", "Nitrate"), country="IT").ok is True
    other = call(arguments("country", "IT", "Nitrate"), country="GR")
    assert other.ok is False and "other countries are not mixed" in str(other.error)
    assert call(arguments("country", "EL", "Nitrate"), country="GR").ok is True  # EL is read as GR
    unknown = call(arguments("country", "ZZ", "Nitrate"))
    assert unknown.ok is False and "Unknown country" in str(unknown.error)


def test_the_tool_is_offered_only_where_it_belongs():
    assert "compare_periods" in ALL_TOOLS and "compare_bathing_seasons" in ALL_TOOLS
    assert "compare_periods" in TOOLS_BY_INDEX["water-quality"] and "compare_periods" in TOOLS_BY_INDEX["water-parameters"]
    assert "compare_periods" not in TOOLS_BY_INDEX["data-quality"] and "compare_periods" not in TOOLS_BY_INDEX["microbiology"]
    assert "compare_bathing_seasons" in TOOLS_BY_INDEX["microbiology"] and "compare_bathing_seasons" not in TOOLS_BY_INDEX["water-quality"]
    assert allowed_tools("data-quality") == ("list_sites", "get_qc_summary")
    assert call(arguments(), tools=("list_sites",)).ok is False  # not allowed by the selected index


def test_the_definition_asks_for_every_period_and_nothing_else():
    schema = TOOL_DEFINITIONS["compare_periods"]["input_schema"]
    assert schema["required"] == ["scope", "id_or_country", "parameter", "a_from", "a_to", "b_from", "b_to"]
    assert schema["additionalProperties"] is False and set(schema["properties"]) == set(schema["required"])
    assert "never shifted" in TOOL_DEFINITIONS["compare_periods"]["description"]


def test_the_step_trace_keeps_schema_keys_only_and_hides_credentials():
    traced = trace_arguments("compare_periods", {**arguments(), "id_or_country": "sk-abcdefgh12345678", "secret": "x"})
    assert set(traced) <= set(TOOL_DEFINITIONS["compare_periods"]["input_schema"]["properties"])
    assert traced["id_or_country"] == "[redacted]" and "secret" not in traced


def test_without_the_wiring_the_tool_says_it_is_unavailable():
    from oah.chat.tools import ToolContext

    bare = ToolContext(country=None, sites=lambda: [], countries=lambda: ([], 0), index=lambda _i: None,
                       measurements=lambda *_a: None, qc=lambda: {}, freshness=lambda: {})
    for scope, target in (("site", S1), ("country", "IT")):
        outcome = run_tool(bare, "compare_periods", arguments(scope, target), ALL_TOOLS)
        assert outcome.ok is False and "not available" in str(outcome.error)


# --- the system prompt --------------------------------------------------------------------------------------------------------


def test_the_prompt_states_the_period_rules():
    text = CHAT_SYSTEM_PROMPT
    for needle in (
        "PERIOD QUESTIONS", "compare_periods", "compare_bathing_seasons", "NEVER shift or replace a requested period",
        "data_range", "period-outside-data", "insufficient-data", "n_samples", "partial-period", "below-loq-excluded-bias-upward",
        "annual-only", "few-sites", "Increase means mean_B minus mean_A as computed by the tool", "quote the tool's numbers only",
        "say plainly that no limit exists", "screening aid, not a compliance assessment", "never present it as compliance",
        "LIMeco", "HWQI", "only sites with data in both periods", "never describe them as monthly", "not comparable",
    ):
        assert needle in text, needle
    assert "ANNUAL aggregates" in text and "latest_year" in text  # the earlier data facts are still there


# --- end to end with the scripted client -------------------------------------------------------------------------------------


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


def _numbers() -> dict[str, float]:
    result = call(arguments()).result
    assert result is not None
    return {
        "a": result["period_a"]["mean"]["amount"], "b": result["period_b"]["mean"]["amount"],
        "diff": result["change"]["absolute"]["amount"], "limit": result["period_a"]["limit_check"]["limit"]["amount"],
    }


def _chat(http, monkeypatch, answer: str, message: str = "How much did total phosphates change at IT01-001025 from 2021 to 2023?") -> dict[str, Any]:
    _guard(monkeypatch)
    client = _Client([_reply(_ToolUse("t1", "compare_periods", arguments())), _reply(_Text(answer))])
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: client)
    response = http.post("/chat", json={"message": message, "country": "IT", "index": "water-parameters"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert client.calls[0]["system"] == CHAT_SYSTEM_PROMPT and {t["name"] for t in client.calls[0]["tools"]} >= {"compare_periods"}
    return body


def test_the_numbers_of_the_tool_result_are_accepted_as_evidence(http, built, monkeypatch):
    n = _numbers()
    answer = (
        f"At IT01-001025 the mean total phosphates rose from {n['a']} mg/L (n_samples 3) in 2021 to {n['b']} mg/L (n_samples 3) in 2023, "
        f"an increase of {n['diff']} mg/L or 200%. The limit is {n['limit']} mg/L (national: DM 260/2010 LIMeco (Italy)), so the mean "
        "went from within the limit to above it. One 2023 sample was below the quantification limit and is not in the mean. "
        "This is a screening aid, not a compliance assessment."
    )
    body = _chat(http, monkeypatch, answer)
    assert body["status"] == "answered" and body["grounded"] is True and body["ungrounded_numbers"] == [] and body["unit_mismatches"] == []
    assert body["origin"] == "real-eea-waterbase" and [s["tool"] for s in body["steps"]] == ["compare_periods"]
    assert body["steps"][0]["ok"] is True and body["steps"][0]["summary"] == "comparison status ok"
    [citation] = [c for c in body["citations"] if c["tool"] == "compare_periods"]
    assert citation["site_id"] == S1 and citation["period_start"] == "2021-01" and citation["period_end"] == "2023-12"
    assert body["usage"]["model_calls"] == 2


def test_a_number_the_tool_did_not_return_is_reported_as_ungrounded(http, built, monkeypatch):
    n = _numbers()
    answer = f"Total phosphates rose from {n['a']} mg/L to {n['b']} mg/L, a rise of 55% since 2021 (n_samples 3)."
    body = _chat(http, monkeypatch, answer)
    assert body["status"] == "withheld-ungrounded" and body["answer"] is None
    assert body["grounded"] is False and "55%" in body["ungrounded_numbers"]
    assert "withheld_ungrounded_notice" in body["notices"] and body["citations"]


def test_a_right_number_with_the_wrong_unit_is_a_unit_mismatch(http, built, monkeypatch):
    n = _numbers()
    body = _chat(http, monkeypatch, f"The mean in 2023 was {n['b']} ug/L (n_samples 3).")
    assert body["grounded"] is False and any("ug/L" in item for item in body["unit_mismatches"])


def test_the_chat_does_not_reach_another_country_through_the_tool(http, built, monkeypatch):
    _guard(monkeypatch)
    client = _Client([
        _reply(_ToolUse("t1", "compare_periods", arguments("country", "IT", "Nitrate"))),
        _reply(_Text("The selected country is Greece, so I cannot compare Italy here.")),
    ])
    monkeypatch.setattr(deps_module, "get_llm_client", lambda: client)
    body = http.post("/chat", json={"message": "Compare nitrate in Italy.", "country": "GR"}).json()
    assert body["steps"][0]["ok"] is False and body["origin"] == "real-sandbox"
    assert "other countries are not mixed" in client.calls[1]["messages"][-1]["content"][0]["content"]
