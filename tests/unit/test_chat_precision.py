"""Presentation rounding of the chat figures (``oah.chat.precision``) and the ``approximate`` block of the statistics tools.

The rounding policy is presentation rounding, NOT statistical uncertainty: these tests check its properties (sign, direction,
never zero, within half a rounding step, monotonic in n), that the tool results carry both the exact numbers and the
approximate block, that the block stays inside the size bound, and that the grounding check stays strict (an approximate
number from the result passes; an invented interval or a wrongly rounded number is withheld). Data are INVENTED (synthetic).
The model is a scripted fake client; no network.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from samples_fixtures import build_fixture_store as build_samples_store
from samples_fixtures import raw_row

import oah.api.app as app_module
from oah.chat import ChatLimits, ToolContext, precision, run_chat
from oah.chat.prompts import CHAT_LEAK_CHECK_PARTS, CHAT_PRECISION_FACTS, CHAT_SYSTEM_PROMPT
from oah.chat.tools import ALL_TOOLS, MAX_TOOL_RESULT_CHARS, compact_site_change, run_tool
from oah.i18n import translator as tr

# --- the policy ---------------------------------------------------------------------------------------------------------------


def test_the_constants_are_the_documented_working_values():
    assert (precision.LARGE_SAMPLE_COUNT, precision.MEDIUM_SAMPLE_COUNT) == (20, 5)
    assert (precision.FIGURES_LARGE, precision.FIGURES_SMALL) == (3, 2)
    assert precision.BELOW_DETECTION_SHARE_THRESHOLD == 0.25


def test_figures_depend_on_the_sample_count_and_low_precision_caps_them():
    assert [precision.significant_figures(n) for n in (0, 1, 4, 5, 19, 20, 500)] == [2, 2, 2, 2, 2, 3, 3]
    assert precision.significant_figures(None) == 2 and precision.significant_figures(True) == 2  # an unknown count claims nothing more
    assert precision.significant_figures(500, low_precision=True) == 2
    assert precision.is_few_samples(4) and not precision.is_few_samples(5) and not precision.is_few_samples(None)
    assert precision.is_high_share(1, 4) and not precision.is_high_share(1, 5) and not precision.is_high_share(1, 0)


@pytest.mark.parametrize(
    ("value", "figures", "expected"),
    [
        (0.340954, 2, 0.34), (0.340954, 3, 0.341), (0.28, 2, 0.28), (233.333, 2, 230.0), (233.333, 3, 233.0), (9.96, 2, 10.0),
        (-0.340954, 2, -0.34), (0.00040456, 2, 0.0004), (1234, 2, 1200), (0.0, 2, 0.0), (0, 2, 0), (5, 2, 5), (0.125, 2, 0.13),
    ],
)
def test_round_figures_examples(value, figures, expected):
    result = precision.round_figures(value, figures)
    assert result == expected and type(result) is type(expected)


def test_outward_rounding_contains_the_observed_range():
    assert precision.round_figures(0.5011, 2, "down") == 0.5 and precision.round_figures(0.524411, 2, "up") == 0.53
    assert precision.approximate_range(0.281234, 0.524411, 2) == (0.28, 0.53)
    assert precision.approximate_range(-0.524411, -0.281234, 2) == (-0.53, -0.28)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1.5", None])
def test_round_figures_refuses_what_is_not_a_finite_number(bad):
    with pytest.raises(ValueError):
        precision.round_figures(bad, 2)
    with pytest.raises(ValueError):
        precision.round_figures(1.5, 0)


def test_an_approximate_mean_never_leaves_the_observed_range():
    # 0.9996 rounds to 1.0 at two figures, past the maximum 0.9998: more figures are used until it lies inside
    assert precision.approximate_value(0.9996, 3, lower=0.9990, upper=0.9998) == 0.9996
    assert precision.approximate_value(0.9996, 3) == 1.0  # without a range the plain rounding applies
    assert precision.approximate_value(0.340954, 3, lower=0.28, upper=0.53) == 0.34


_NONZERO = st.floats(min_value=1e-9, max_value=1e9, allow_nan=False, allow_infinity=False).flatmap(
    lambda magnitude: st.sampled_from([magnitude, -magnitude])
)


def _half_step(value: float, figures: int) -> Decimal:
    exact = Decimal(repr(value))
    return Decimal("0.5") * Decimal(1).scaleb(exact.adjusted() - figures + 1)


@settings(max_examples=300, deadline=None)
@given(value=_NONZERO, figures=st.integers(min_value=1, max_value=8))
def test_property_sign_is_kept_a_nonzero_value_stays_nonzero_and_the_error_is_half_a_step(value, figures):
    rounded = precision.round_figures(value, figures)
    assert rounded != 0 and math.copysign(1, rounded) == math.copysign(1, value)  # an increase stays an increase
    assert abs(Decimal(repr(float(rounded))) - Decimal(repr(value))) <= _half_step(value, figures)


@settings(max_examples=300, deadline=None)
@given(value=_NONZERO, n=st.one_of(st.none(), st.integers(min_value=0, max_value=100)), low=st.booleans())
def test_property_the_approximate_change_keeps_its_direction_and_is_never_zero(value, n, low):
    approximate = precision.approximate_value(value, n, low_precision=low)
    assert approximate != 0 and (approximate > 0) == (value > 0)
    figures = precision.significant_figures(n, low_precision=low)
    assert abs(Decimal(repr(float(approximate))) - Decimal(repr(value))) <= _half_step(value, figures)


@settings(max_examples=200, deadline=None)
@given(n1=st.integers(min_value=0, max_value=200), n2=st.integers(min_value=0, max_value=200), low=st.booleans())
def test_property_figures_never_decrease_with_n(n1, n2, low):
    first, second = sorted((n1, n2))
    assert precision.significant_figures(first, low_precision=low) <= precision.significant_figures(second, low_precision=low)
    assert precision.significant_figures(first, low_precision=True) <= precision.FIGURES_SMALL


@settings(max_examples=300, deadline=None)
@given(
    low=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
    spread=st.floats(min_value=0, max_value=1e6, allow_nan=False),
    share=st.floats(min_value=0, max_value=1),
    n=st.integers(min_value=0, max_value=60),
)
def test_property_the_range_is_outward_and_the_approximate_mean_is_inside_it(low, spread, share, n):
    high = low + spread
    mean = min(max(low + spread * share, low), high)
    figures = precision.significant_figures(n)
    lower, upper = precision.approximate_range(low, high, figures)
    assert lower <= low and upper >= high  # the stated range always contains every observed value
    approximate = precision.approximate_value(mean, n, lower=lower, upper=upper)
    assert lower <= approximate <= upper


# --- the tool results carry both blocks -----------------------------------------------------------------------------------------


def _view(start: str, end: str, n: int, mean: float, low: float, high: float, flags: tuple[str, ...] = (), below: int = 0) -> dict[str, Any]:
    return {
        "start": start, "end": end, "months_in_period": 12, "n_samples": n, "n_unit": "samples", "n_months_with_data": 6,
        "mean": mean, "min": low, "max": high, "n_below_loq": below, "below_loq_share": below / (n + below) if n + below else 0.0,
        "meets_minimum_samples": True, "flags": list(flags), "assessment": {"status": "no-limit-regime"},
    }


def _payload(a: dict[str, Any], b: dict[str, Any], flags: tuple[str, ...] = ()) -> dict[str, Any]:
    absolute = round(b["mean"] - a["mean"], 6)
    return {
        "origin": "real-eea-waterbase", "source": "real-eea-waterbase", "attribution": "EEA Waterbase (synthetic test data)",
        "scope": {"type": "site", "id": "SYN-1", "name": "Synthetic site", "country": "IT"}, "parameter": "Nitrate", "group": "water-chemistry",
        "unit": "mg/L", "resolution": "monthly", "status": "ok", "min_samples_per_period": 3, "periods": {"a": a, "b": b},
        "change": {"absolute": absolute, "relative_percent": round(absolute / a["mean"] * 100, 4), "direction": "increased"},
        "crossed_limit": "no-limit", "data_range": {"first": "2021-01", "last": "2023-12"}, "flags": list(flags),
    }


# few samples, a partial period and a high below-detection share: every weakness at once
LOW = _payload(
    _view("2021-01", "2021-12", 3, 0.340954, 0.281234, 0.524411),
    _view("2023-01", "2023-12", 4, 0.612345, 0.5011, 0.78123, flags=("partial-period",), below=2),
)
# plenty of samples, nothing to flag
FINE = _payload(_view("2021-01", "2021-12", 24, 0.340954, 0.281234, 0.524411), _view("2023-01", "2023-12", 30, 0.612345, 0.5011, 0.78123))
ARGUMENTS = {
    "scope": "site", "id_or_country": "SYN-1", "parameter": "Nitrate",
    "a_from": "2021-01", "a_to": "2021-12", "b_from": "2023-01", "b_to": "2023-12",
}


def _ctx(payload: dict[str, Any]) -> ToolContext:
    return ToolContext(None, lambda: [], lambda: ([], 0), lambda _l: None, lambda *_a: None, lambda: {}, lambda: {}, compare_site=lambda *_a: payload)


def test_a_low_precision_site_result_has_the_exact_numbers_and_the_approximate_block():
    outcome = run_tool(_ctx(LOW), "compare_periods", ARGUMENTS, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None
    result = outcome.result
    assert result["period_a"]["mean"] == {"amount": 0.340954, "unit": "mg/L"}  # the exact numbers stay
    assert result["change"]["absolute"] == {"amount": 0.271391, "unit": "mg/L"}
    block = result["approximate"]
    assert block["low_precision"] is True and block["rounding"] == "two significant figures"
    assert block["reasons"] == ["few-samples-in-a-period", "high-below-detection-share", "partial-period"]
    assert block["period_a"]["mean"] == {"amount": 0.34, "unit": "mg/L"}
    assert block["period_a"]["observed_range"] == {"min": {"amount": 0.28, "unit": "mg/L"}, "max": {"amount": 0.53, "unit": "mg/L"}}
    assert block["period_b"]["mean"] == {"amount": 0.61, "unit": "mg/L"}
    assert block["change"] == {
        "absolute": {"amount": 0.27, "unit": "mg/L"}, "relative_percent": {"amount": 80.0, "unit": "%"}, "direction": "increased",
    }
    assert "not a statistical uncertainty" in block["basis"] and "not a confidence interval" in block["basis"]
    assert not any(ch.isdigit() for ch in block["basis"] + block["rounding"])  # no digit in a text field: it would be a number for the grounding check
    assert len(outcome.content) < MAX_TOOL_RESULT_CHARS


def test_a_result_with_enough_samples_is_not_low_precision_and_keeps_three_figures():
    block = run_tool(_ctx(FINE), "compare_periods", ARGUMENTS, ALL_TOOLS).result["approximate"]
    assert block["low_precision"] is False and block["reasons"] == [] and block["rounding"] == "three significant figures"
    assert block["period_a"]["mean"]["amount"] == 0.341 and block["change"]["absolute"]["amount"] == 0.271


def test_annual_only_data_and_a_period_without_a_mean_are_handled():
    annual = {**LOW, "flags": ["annual-only"], "periods": {"a": _view("2018-01", "2018-12", 1, 2.0, 2.0, 2.0), "b": _view("2019-01", "2019-12", 1, 3.0, 3.0, 3.0)}}
    block = compact_site_change(annual)["approximate"]
    assert block["low_precision"] is True and "annual-only-data" in block["reasons"] and "few-samples-in-a-period" in block["reasons"]
    empty = {**LOW, "periods": {"a": {"start": "2021-01", "end": "2021-12", "n_samples": 0, "flags": []}, "b": {"start": "2023-01", "end": "2023-12", "n_samples": 0, "flags": []}}}
    assert "approximate" not in compact_site_change(empty)  # no mean in either period: nothing to approximate


def test_a_nonzero_change_is_never_rounded_to_zero_and_a_decrease_stays_a_decrease():
    down = _payload(_view("2021-01", "2021-12", 3, 5.0, 4.0, 6.0), _view("2023-01", "2023-12", 3, 4.9999, 4.0, 6.0))
    down["change"] = {"absolute": -0.0001, "relative_percent": -0.002, "direction": "decreased"}
    block = compact_site_change(down)["approximate"]
    assert block["change"]["absolute"]["amount"] == -0.0001 and block["change"]["relative_percent"]["amount"] == -0.002
    assert block["change"]["direction"] == "decreased"


def _country_entry(n_a: int, n_b: int, paired: int, flags: tuple[str, ...]) -> dict[str, Any]:
    def period(start: str, end: str, n: int, mean: float) -> dict[str, Any]:
        return {"start": start, "end": end, "n_sites": paired, "n_samples": n, "mean_of_site_means": mean, "flags": []}

    return {
        "origin": "real-eea-waterbase", "source": "real-eea-waterbase", "attribution": "EEA Waterbase (synthetic)", "parameter": "Nitrate",
        "unit": "mg/L", "status": "ok", "few_sites_threshold": 5, "n_sites_paired": paired, "n_sites_excluded": 0,
        "periods": {"a": period("2021-01", "2021-12", n_a, 9.7345), "b": period("2023-01", "2023-12", n_b, 18.0123)},
        "change_of_site_means": {"absolute": 8.2778, "relative_percent": 85.2, "direction": "increased"},
        "median_site_relative_change_percent": 50.123, "flags": list(flags),
    }


def test_a_country_result_carries_the_block_with_few_paired_sites_as_a_reason():
    from oah.chat.tools import compact_country_change

    result = compact_country_change({"scope": {"type": "country", "code": "IT"}, "parameter": "Nitrate", "results": [_country_entry(60, 70, 3, ("few-sites",))]})
    block = result["results"][0]["approximate"]
    assert block["low_precision"] is True and block["reasons"] == ["few-paired-sites"]
    assert block["period_a"]["mean_of_site_means"] == {"amount": 9.7, "unit": "mg/L"}
    assert block["change_of_site_means"]["absolute"] == {"amount": 8.3, "unit": "mg/L"}
    assert block["median_site_relative_change"] == {"amount": 50.0, "unit": "%"}
    assert "observed_range" not in block["period_a"]  # a country result carries no minimum and maximum: none is invented
    enough = compact_country_change({"scope": {"type": "country", "code": "IT"}, "parameter": "Nitrate", "results": [_country_entry(60, 70, 8, ())]})
    assert enough["results"][0]["approximate"]["low_precision"] is False


def _records(count: int, *, n: int = 12) -> list[dict[str, Any]]:
    return [
        {
            "observation_id": f"SYN-{index:04d}|CAS_14797-55-8|W|{2000 + index}|mg{{NO3}}/L", "parameter": "Nitrate", "statistic": "mean",
            "value": 20.123456 + index, "unit": "mg/L", "min": 10.654321, "max": 30.987654 + index, "period_start": f"{2000 + index}-01-01",
            "period_end": f"{2000 + index}-12-31", "limit": 5.312060656685729, "limit_unit": "mg/L", "limit_type": "maximum",
            "limit_basis": "national: synthetic basis", "status": "exceeds-limit", "data_quality_flags": [], "year": 2000 + index, "n": n,
            "n_below_loq": 0, "matrix": "W", "group": "water-chemistry", "origin": "real-eea-waterbase", "limit_regime": "IT", "limit_country": "IT",
        }
        for index in range(count)
    ]


def _measurement_ctx(records: list[dict[str, Any]]) -> ToolContext:
    return ToolContext(None, lambda: [], lambda: ([], 0), lambda _l: None, lambda *_a: records, lambda: {}, lambda: {})


def test_measurement_records_carry_a_per_record_block_and_a_result_note():
    outcome = run_tool(_measurement_ctx(_records(3, n=3)), "get_site_measurements", {"location_id": "SYN-1"}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None
    first = outcome.result["records"][0]
    assert first["value"]["amount"] == 20.123456  # exact
    assert first["approximate"]["low_precision"] is True and first["approximate"]["reasons"] == ["few-samples-in-a-period"]
    assert first["approximate"]["value"] == {"amount": 20.0, "unit": "mg/L"}
    assert first["approximate"]["observed_range"] == {"min": {"amount": 10.0, "unit": "mg/L"}, "max": {"amount": 31.0, "unit": "mg/L"}}
    assert outcome.result["approximate"]["low_precision"] is True and "not a confidence interval" in outcome.result["approximate"]["basis"]
    assert outcome.result["approximate"]["reasons"] == ["few-samples-in-a-period"]
    plenty = run_tool(_measurement_ctx(_records(2, n=25)), "get_site_measurements", {"location_id": "SYN-1"}, ALL_TOOLS).result
    assert plenty is not None and "approximate" not in plenty["records"][0]  # not low precision: the exact value is enough, nothing added
    assert plenty["approximate"]["low_precision"] is False and plenty["approximate"]["reasons"] == []


def test_a_sandbox_record_without_a_count_is_annual_only_and_a_comparator_value_is_left_alone():
    sandbox = [{**_records(1)[0], "origin": "real-sandbox", "n": None, "n_below_loq": None, "min": None, "max": None}]
    result = run_tool(_measurement_ctx(sandbox), "get_site_measurements", {"location_id": "Loc-A"}, ALL_TOOLS).result
    assert result is not None and result["records"][0]["approximate"]["reasons"] == ["annual-only-data"]
    censored = [{**_records(1)[0], "comparator": "<"}]
    result = run_tool(_measurement_ctx(censored), "get_site_measurements", {"location_id": "SYN-1"}, ALL_TOOLS).result
    assert result is not None and "approximate" not in result["records"][0] and result["approximate"]["low_precision"] is False


def test_the_longest_measurement_result_still_fits_the_size_bound():
    outcome = run_tool(_measurement_ctx(_records(500)), "get_site_measurements", {"location_id": "SYN-1", "limit": 500}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None
    assert len(outcome.content) <= MAX_TOOL_RESULT_CHARS and outcome.result["truncated"] is True and outcome.result["returned"] > 10
    weak = run_tool(_measurement_ctx(_records(500, n=3)), "get_site_measurements", {"location_id": "SYN-1", "limit": 500}, ALL_TOOLS)
    assert weak.result is not None and len(weak.content) <= MAX_TOOL_RESULT_CHARS and weak.result["returned"] > 10
    assert all("approximate" in record for record in weak.result["records"])  # every low-precision record carries its block, within the bound


# --- bathing samples ------------------------------------------------------------------------------------------------------------------


@pytest.fixture()
def samples_store(tmp_path: Path, monkeypatch) -> Path:
    path = build_samples_store(tmp_path)
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(path))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "none.sqlite"))
    return path


def _app_ctx(country: str | None = None) -> ToolContext:
    return app_module._chat_tool_context(country)


def test_the_samples_summary_and_the_concentration_comparison_carry_the_block(samples_store):
    summary = run_tool(_app_ctx(), "get_bathing_samples", {"bathing_water_id": "ITSYN001"}, ALL_TOOLS)
    assert summary.ok and summary.result is not None
    exact = summary.result["summary"]["escherichia_coli"]
    block = summary.result["approximate"]["indicators"]["escherichia_coli"]
    assert exact["mean"]["amount"] == round(1607 / 9, 6)  # exact stays
    assert block["low_precision"] is False and block["mean"] == {"amount": 180.0, "unit": "cfu/100ml"}
    assert block["observed_range"] == {"min": {"amount": 7, "unit": "cfu/100ml"}, "max": {"amount": 900, "unit": "cfu/100ml"}}
    assert "not a statistical uncertainty" in summary.result["approximate"]["basis"]
    assert len(summary.content) <= MAX_TOOL_RESULT_CHARS
    periods = {"a_from": "2020-05", "a_to": "2020-08", "b_from": "2022-05", "b_to": "2022-08"}
    for scope, target in (("bathing_water", "ITSYN001"), ("country", "IT")):
        outcome = run_tool(_app_ctx(), "compare_bathing_concentrations", {"scope": scope, "id_or_country": target, **periods}, ALL_TOOLS)
        assert outcome.ok and outcome.result is not None and len(outcome.content) <= MAX_TOOL_RESULT_CHARS
        blocks = [entry["approximate"] for entry in outcome.result["indicators"].values() if "approximate" in entry]
        assert blocks, scope
        for item in blocks:
            assert {"low_precision", "reasons", "rounding", "basis"} <= set(item) and isinstance(item["low_precision"], bool)


def test_a_long_samples_list_with_the_block_stays_within_the_bound(tmp_path: Path, monkeypatch):
    rows = [raw_row(i, "ITBIG001", f"2021-{1 + i % 9:02d}-{1 + i % 27:02d}", (i + 100, None), (i + 200, None), sample_status="shortTermPollutionSample") for i in range(1, 151)]
    monkeypatch.setenv("OAH_BATHING_SAMPLES_STORE", str(build_samples_store(tmp_path, rows=rows)))
    monkeypatch.setenv("OAH_BATHING_WATER_STORE", str(tmp_path / "none.sqlite"))
    outcome = run_tool(_app_ctx(), "get_bathing_samples", {"bathing_water_id": "ITBIG001", "limit": 100}, ALL_TOOLS)
    assert outcome.ok and outcome.result is not None and len(outcome.content) <= MAX_TOOL_RESULT_CHARS
    assert outcome.result["approximate"]["indicators"]["escherichia_coli"]["rounding"] == "three significant figures"


# --- grounding stays strict, with the scripted model ---------------------------------------------------------------------------------


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
            if len(self.calls) == len(self.replies) + 1 and "was not shown because" in str(kwargs["messages"][-1]):
                return self.replies[-1]  # the one revision of a withheld answer: the scripted model repeats its last text
            return self.replies[len(self.calls) - 1]

        self.messages = SimpleNamespace(create=_create)


def _converse(payload: dict[str, Any], answer: str):
    blocks = lambda *items: SimpleNamespace(content=list(items), usage=SimpleNamespace(input_tokens=10, output_tokens=5))  # noqa: E731
    client = _Client([blocks(_ToolUse("t1", "compare_periods", ARGUMENTS)), blocks(_Text(answer))])
    return run_chat(
        "How did nitrate change at SYN-1?", None, None, [], client=client, ctx=_ctx(payload), model="fake",
        limits=ChatLimits(max_steps=4, timeout_seconds=30.0), reserve_model_call=lambda: True,
    )


LOW_ANSWER = (
    "Nitrate at SYN-1 rose from about 0.34 mg/L (n_samples 3, between 0.28 and 0.53 observed) in 2021 to about 0.61 mg/L "
    "(n_samples 4, between 0.5 and 0.79 observed) in 2023, an increase of about 0.27 mg/L or roughly 80%. The data are few, "
    "so the figures are approximate. This is a screening aid, not a compliance assessment."
)


def test_an_answer_with_approximate_values_and_the_observed_range_is_answered_and_grounded():
    result = _converse(LOW, LOW_ANSWER)
    assert result.status == "answered" and result.grounded is True and result.ungrounded_numbers == () and result.unit_mismatches == ()
    assert result.answer == LOW_ANSWER and result.evidence is None


def test_an_exact_answer_is_still_grounded_when_the_precision_is_fine():
    answer = (
        "Nitrate at SYN-1 rose from 0.340954 mg/L (n_samples 24) in 2021 to 0.612345 mg/L (n_samples 30) in 2023, an increase of "
        "0.271391 mg/L. This is a screening aid, not a compliance assessment."
    )
    result = _converse(FINE, answer)
    assert result.status == "answered" and result.grounded is True
    rounded = answer.replace("0.340954", "0.341").replace("0.612345", "0.612").replace("0.271391", "0.271")
    assert _converse(FINE, rounded).status == "answered"  # the three-figure form in the approximate block is accepted too


def test_an_invented_interval_is_flagged_and_the_answer_withheld():
    answer = LOW_ANSWER.replace("between 0.28 and 0.53 observed", "between 0.15 and 0.95 observed")
    result = _converse(LOW, answer)
    assert result.status == "withheld-ungrounded" and result.answer is None and result.grounded is False
    assert "0.15" in result.ungrounded_numbers and "0.95" in result.ungrounded_numbers


def test_a_wrongly_rounded_number_is_flagged_and_the_answer_withheld():
    result = _converse(LOW, LOW_ANSWER.replace("about 0.34 mg/L", "about 0.36 mg/L"))  # neither 0.340954 nor its approximation 0.34
    assert result.status == "withheld-ungrounded" and "0.36" in result.ungrounded_numbers
    assert _converse(LOW, LOW_ANSWER.replace("roughly 80%", "roughly 85%")).status == "withheld-ungrounded"


def test_the_grounding_module_is_not_loosened():
    import oah.explain.grounding as grounding

    source = Path(grounding.__file__).read_text(encoding="utf-8")
    assert "_SAFE_VALUES = frozenset({Decimal(0), Decimal(1), Decimal(100)})" in source  # the documented tolerance rules are unchanged
    assert "return abs(mention - evidence) <= _tolerance(decimals)" in source


def test_the_prompt_asks_for_about_the_observed_range_and_no_confidence_interval():
    for needle in (
        "APPROXIMATE FIGURES", "approximate block", "low_precision", "about or roughly", "observed range", "state n",
        "never state an interval that is not an observed range", "confidence interval", "screening aid, not a compliance assessment",
        "presentation rounding, not a statistical uncertainty",
    ):
        assert needle in CHAT_PRECISION_FACTS, needle
    assert CHAT_PRECISION_FACTS in CHAT_SYSTEM_PROMPT and CHAT_PRECISION_FACTS not in CHAT_LEAK_CHECK_PARTS
    assert all(CHAT_PRECISION_FACTS not in part for part in CHAT_LEAK_CHECK_PARTS)  # the leak check does not compare with it


# --- translation keeps the numbers ----------------------------------------------------------------------------------------------------


class _Translator:
    def __init__(self, text: str) -> None:
        self.text, self.calls = text, 0
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **_kwargs: Any) -> Any:
        self.calls += 1
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.text)], usage=SimpleNamespace(input_tokens=200, output_tokens=90), stop_reason="end_turn"
        )


ES = (
    "El nitrato en SYN-1 subió de unos 0.34 mg/L (n_samples 3, entre 0.28 y 0.53 observado) en 2021 a unos 0.61 mg/L "
    "(n_samples 4, entre 0.5 y 0.79 observado) en 2023, un aumento de unos 0.27 mg/L o aproximadamente 80%. Los datos son pocos, "
    "así que las cifras son aproximadas. Esto es una ayuda de cribado, no una evaluación de cumplimiento."
)


def test_an_answer_with_approximate_values_and_a_range_translates_and_verifies():
    ok = tr.translate(LOW_ANSWER, "es-MX", client=_Translator(ES), model="fake", extra_leak_parts=CHAT_LEAK_CHECK_PARTS)
    assert ok.status == "ok" and ok.translated is True and ok.text == ES
    changed = tr.translate(LOW_ANSWER, "es-MX", client=_Translator(ES.replace("0.28", "0.29")), model="fake", extra_leak_parts=CHAT_LEAK_CHECK_PARTS)
    assert changed.status == "rejected" and changed.text == LOW_ANSWER  # a number changed by the translation: the English answer is kept
