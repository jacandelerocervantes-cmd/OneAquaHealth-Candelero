"""Adversarial harness for the numeric-grounding check (all data synthetic, no network)."""
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from oah.explain.grounding import _mentions, check_grounding
from oah.explain.grounding_cases import (
    INDEX_EVIDENCE,
    QUANTITY_EVIDENCE,
    REVIEW_EVIDENCE,
    all_cases,
    curated_cases,
    generated_cases,
    holdout_cases,
)


def _ids(cases):
    return [f"{kind}:{category}:{index}" for index, (kind, category, _t, _e) in enumerate(cases)]


def _of(kind, cases):
    return [c for c in cases if c[0] == kind]


CASES = all_cases()
MUST_ACCEPT = _of("valid", CASES) + _of("valid", holdout_cases())
MUST_FLAG = _of("adversarial", CASES) + _of("adversarial", holdout_cases())


def test_the_harness_is_large_enough_to_mean_something():
    assert len(_of("valid", CASES)) >= 50 and len(_of("adversarial", CASES)) >= 50
    assert len(_of("valid", holdout_cases())) >= 15 and len(_of("adversarial", holdout_cases())) >= 15
    assert len({(c[2], repr(c[3])) for c in CASES}) == len(CASES), "duplicate cases inflate the rates"


@pytest.mark.parametrize("case", MUST_ACCEPT, ids=_ids(MUST_ACCEPT))
def test_faithful_renderings_are_accepted(case):
    _kind, _category, text, evidence = case
    result = check_grounding(text, evidence)
    assert result.grounded, (text, result)


@pytest.mark.parametrize("case", MUST_FLAG, ids=_ids(MUST_FLAG))
def test_fabricated_or_distorted_numbers_and_units_are_flagged(case):
    _kind, _category, text, evidence = case
    assert not check_grounding(text, evidence).grounded, text


@pytest.mark.parametrize("case", _of("limitation-miss", curated_cases()), ids=lambda c: c[1])
def test_documented_blind_spots_are_not_detected_by_design(case):
    """A number check cannot see a right number on the wrong claim. If this ever fails, the check got
    smarter: update docs/math_registry.md and move the case to ``adversarial``."""
    assert check_grounding(case[2], case[3]).grounded


@pytest.mark.parametrize("case", _of("limitation-alarm", curated_cases()), ids=lambda c: c[1])
def test_derived_numbers_are_flagged_on_purpose(case):
    assert not check_grounding(case[2], case[3]).grounded


def test_generated_adversarial_cases_are_never_faithful_roundings():
    """The generator's own oracle: a case labelled adversarial must not be a legitimate rounding."""
    for _kind, category, text, evidence in _of("adversarial", generated_cases()):
        rendered = text.rsplit(" ", 1)[1].rstrip(".")
        value = Decimal(str(evidence["reported_value"]))
        decimals = len(rendered.partition(".")[2])
        assert abs(Decimal(rendered) - value) > Decimal("0.5") * Decimal(10) ** -decimals or "e" in rendered, (category, text)


# --- mechanics ----------------------------------------------------------------------------------


def _values(text):
    return [(m.raw, m.value, m.unit) for m in _mentions(text)]


def test_ranges_are_not_negative_numbers_but_real_minus_signs_are():
    assert [v for _r, v, _u in _values("Data cover 2013-2015.")] == [2013, 2015]
    assert [v for _r, v, _u in _values("Between 19.9-20.5.")] == [Decimal("19.9"), Decimal("20.5")]
    assert [v for _r, v, _u in _values("A change of -2.5 and (−3).")] == [Decimal("-2.5"), -3]
    assert [v for _r, v, _u in _values("Sample pm2-5 and SPEC-7.")] == [2, 5, 7]


def test_units_are_recognised_across_spaces_and_only_at_word_boundaries():
    assert _values("0.5 ug/L against a limit")[0][2] == "ug/L"
    assert _values("0.5ug/L")[0][2] == "ug/L"
    assert _values("18.5 °C")[0][2] == "Cel"
    assert _values("0.5 mg/Lx")[0][2] is None
    assert _values("55 percent")[0][2] == "%"
    assert _values("2500 µS/cm")[0][2] == "uS/cm"


def test_spelled_numbers_are_parsed_including_compounds_and_decimals():
    values = {r.lower(): v for r, v, _u in _values("Nineteen, twenty-five, eighty-seven point five and a hundred.")}
    assert values["nineteen"] == 19 and values["twenty-five"] == 25 and values["hundred"] == 100
    assert any(v == Decimal("87.5") for _r, v, _u in _values("Eighty-seven point five is high."))


def test_record_size_is_not_a_number_but_list_length_and_distribution_size_are():
    nine_keys = {f"k{n}": "text" for n in range(9)}
    assert not check_grounding("Nine measurements.", nine_keys).grounded
    assert check_grounding("Two candidates.", {"candidates": ["a", "b"]}).grounded
    assert check_grounding("Two classes.", {"probabilities": {"a": 0.6, "b": 0.4}}).grounded
    assert not check_grounding("Two classes.", {"record": {"a": "x", "b": "y", "c": 1}}).grounded


def test_booleans_and_none_are_not_numbers_in_the_evidence():
    assert not check_grounding("The value is 1.7.", {"flag": True, "none": None}).grounded


def test_percent_rules():
    fractions = {"p": 0.55}
    assert check_grounding("55%", fractions).grounded
    assert not check_grounding("0.55%", fractions).grounded
    assert not check_grounding("5.5%", fractions).grounded
    assert check_grounding("55%", {"share": 55}).grounded, "an evidence value above 1 is already a percentage"
    assert check_grounding("0.55%", {"share": {"value": 0.55, "unit": "%"}}).grounded


def test_unit_mismatch_is_reported_separately_from_missing_numbers():
    result = check_grounding("Ammonium was 0.5 ug/L.", QUANTITY_EVIDENCE)
    assert result.ungrounded_numbers == () and len(result.unit_mismatches) == 1 and "mg/L" in result.unit_mismatches[0]
    assert check_grounding("Ammonium was 0.5 mg/L.", QUANTITY_EVIDENCE).unit_mismatches == ()
    assert check_grounding("The value is 0.5 ug/L.", {"v": 0.5}).grounded, "no evidence unit, nothing to contradict"


def test_result_lists_are_sorted_and_deterministic():
    result = check_grounding("Values 9.9, 7.7 and 8.8.", {"n": "x"})
    assert result.ungrounded_numbers == ("7.7", "8.8", "9.9")
    assert result == check_grounding("Values 9.9, 7.7 and 8.8.", {"n": "x"})


def test_tolerance_is_inclusive_half_a_unit_of_the_last_digit():
    assert check_grounding("The value is 4.", {"x": 4.5}).grounded
    assert check_grounding("The value is 5.", {"x": 4.5}).grounded
    assert not check_grounding("The value is 6.", {"x": 4.5}).grounded
    assert check_grounding("The value is 19.92.", {"x": 19.928}).grounded is False, "truncation is not accepted"


@pytest.mark.parametrize("evidence", [INDEX_EVIDENCE, REVIEW_EVIDENCE, QUANTITY_EVIDENCE])
def test_text_without_numbers_is_always_grounded(evidence):
    assert check_grounding("Follow up with the site team next week.", evidence).grounded


# --- properties ---------------------------------------------------------------------------------


@given(st.decimals(min_value=Decimal("-100000"), max_value=Decimal("100000"), places=4), st.integers(0, 4))
@settings(max_examples=300, deadline=None)
def test_any_half_up_rounding_of_an_evidence_value_is_accepted(value, digits):
    rendered = str(value.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))
    assert check_grounding(f"The value is {rendered}.", {"v": float(value)}).grounded


@given(st.decimals(min_value=Decimal("0.0001"), max_value=Decimal("0.9999"), places=4), st.integers(0, 2))
@settings(max_examples=200, deadline=None)
def test_a_fraction_rendered_as_a_percentage_is_accepted(value, digits):
    percent = (value * 100).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    assert check_grounding(f"Probability {percent}%.", {"p": float(value)}).grounded


@given(st.decimals(min_value=Decimal("2"), max_value=Decimal("5000"), places=3))
@settings(max_examples=200, deadline=None)
def test_an_order_of_magnitude_error_is_always_flagged(value):
    wrong = value * 10
    assume(abs(wrong - value) > 1 and wrong not in (0, 1, 100))
    assert not check_grounding(f"The value is {wrong}.", {"v": float(value)}).grounded


def test_enumerators_number_the_writers_points_but_never_data_nouns():
    assert check_grounding("Two points for your decision.", {"n": "x"}).grounded
    assert check_grounding("There are 3 reasons and four steps.", {"n": "x"}).grounded
    assert not check_grounding("Two measurements failed.", {"n": "x"}).grounded
    assert not check_grounding("Twenty points were recorded.", {"n": "x"}).grounded, "only counts of 2-10 are exempt"
    assert not check_grounding("Two points of 87.5 were recorded.", {"n": "x"}).grounded, "the exemption is per number"


def test_structural_nouns_that_introduce_the_answers_own_list_are_enumerators_but_data_counts_are_still_checked():
    for sentence in ("This data holds two kinds of information.", "There are three types of records.", "It has four parts and 5 sections."):
        assert check_grounding(sentence, {"n": "x"}).grounded, sentence
    for sentence in ("Two sites exceeded the value.", "Three bathing waters were classified.", "It has four sources.", "Two groups differ."):
        assert not check_grounding(sentence, {"n": "x"}).grounded, sentence
