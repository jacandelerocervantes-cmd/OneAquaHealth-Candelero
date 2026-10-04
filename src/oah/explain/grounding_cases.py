"""Curated and generated test cases for the numeric-grounding check (test fixture, no runtime use).

Every case is ``(kind, category, text, evidence)`` where ``kind`` is one of

* ``valid``               a faithful rendering that the check MUST accept;
* ``adversarial``         a fabricated or distorted number/unit that the check MUST flag;
* ``limitation-miss``     an error the check cannot detect BY DESIGN (it is a number/unit check, not a
                          semantic one); documented so the limit is measured, not implied;
* ``limitation-alarm``    a faithful but DERIVED number (e.g. 3 of 15 written as 20 %) that the check flags
                          on purpose, because an unsupported number and a derived one are indistinguishable.

All data is synthetic. Generation is deterministic.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

Case = tuple[str, str, str, dict[str, Any]]

INDEX_EVIDENCE: dict[str, Any] = {
    "location_ref": "Location/Loc-Almyros",
    "ccme_wqi": 19.928374,
    "ccme_class": "Poor",
    "confidence": "low_confidence",
    "evaluable_measurements": 15,
    "failed_measurements": 3,
    "distinct_parameters_count": 5,
    "worst_parameter_excursion": 5.0,
    "veto_parameters": [{"parameter": "Nitrate", "worst_excursion": 5.0}],
}
REVIEW_EVIDENCE: dict[str, Any] = {
    "specimen_id": "SPEC-7",
    "prediction_set": ["Baetidae", "Perlidae"],
    "probabilities": {"Baetidae": 0.55, "Perlidae": 0.45},
}
QUANTITY_EVIDENCE: dict[str, Any] = {
    "parameter": "Ammonium",
    "value": 0.5,
    "unit": "mg/L",
    "limit": 0.5,
    "observations": 1256,
    "period": "2013-2015",
    "temperature": {"value": 18.5, "unit": "Cel"},
    "conductivity": {"value": 2500, "unit": "uS/cm"},
    "delta": -2.5,
    "half": 4.5,
    "tie": 2.5,
}


def _half_up(value: float, digits: int) -> str:
    return str(Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP))


def _is_legitimate_rounding(rendered: str, value: float) -> bool:
    """Independent oracle: ``rendered`` equals ``value`` rounded to its own number of decimals (half either way)."""
    decimals = len(rendered.partition(".")[2])
    return abs(Decimal(rendered) - Decimal(str(value))) <= Decimal("0.5") * Decimal(10) ** -decimals


def _fullwidth(text: str) -> str:
    return "".join(chr(ord(c) - ord("0") + 0xFF10) if c.isdigit() else c for c in text)


def curated_cases() -> list[Case]:
    i, r, q = INDEX_EVIDENCE, REVIEW_EVIDENCE, QUANTITY_EVIDENCE
    valid = [
        ("exact", "The index is 19.928374, class Poor.", i),
        ("round-2", "The index is 19.93, class Poor.", i),
        ("round-1", "The index is about 19.9.", i),
        ("round-0", "The index is roughly 20.", i),
        ("counts", "15 evaluable measurements, 3 failed, across 5 distinct parameters.", i),
        ("excursion", "The worst excursion is 5 for Nitrate.", i),
        ("percent-of-fraction", "Baetidae has a 55% probability and Perlidae 45%.", r),
        ("fraction", "Probabilities are 0.55 and 0.45.", r),
        ("round-half-up", "The rounded value is 5.", {"x": 4.5}),
        ("round-half-up-2", "The rounded value is 3.", {"x": 2.5}),
        ("thousands-separator", "There were 1,256 observations.", q),
        ("hyphen-range", "Data cover 2013-2015.", q),
        ("en-dash-range", "Data cover 2013–2015.", q),
        ("unit-match", "Ammonium was 0.5 mg/L against a limit of 0.5 mg/L.", q),
        ("unit-alias-celsius", "The temperature was 18.5 °C.", q),
        ("unit-alias-micro", "Conductivity was 2500 µS/cm.", q),
        ("scientific", "Conductivity was 2.5e3 uS/cm.", q),
        ("unicode-minus", "A change of −2.5 was recorded.", q),
        ("fullwidth-digits", f"The index is {_fullwidth('19.9')}.", i),
        ("cardinality", "Two candidate families remain.", r),
        ("cardinality-digit", "2 candidate families remain.", r),
        ("number-word-grounded", "Three measurements failed.", i),
        ("safe-numbers", "There is 1 finding out of 100 possible, and 0 are critical.", {"note": "none"}),
        ("no-numbers", "The site needs a follow-up visit.", i),
        ("identifier-digits", "Specimen SPEC-7 is ambiguous.", r),
        ("enumerator-real-output", "Two points for your decision: the item is flagged as synthetic.", r),
        ("enumerator-digit", "There are 3 reasons to review this.", i),
        ("enumerator-steps", "Suggested next steps: two options follow.", i),
    ]
    adversarial = [
        ("invented", "The index is 87.5, a very high score.", i),
        ("decimal-shift-up", "The index is 199.28.", i),
        ("decimal-shift-down", "The index is 1.99.", i),
        ("digit-transposition", "The index is 19.29.", i),
        ("wrong-rounding", "The index is about 19.5.", i),
        ("sign-flip", "The index is -19.9.", i),
        ("invented-count", "Nine measurements failed.", i),
        ("invented-count-digit", "9 measurements failed.", i),
        ("number-word-invented", "Nineteen measurements failed.", i),
        ("compound-number-word", "Twenty-five percent of tests failed.", i),
        ("decimal-number-word", "The index is eighty-seven point five.", i),
        ("fullwidth-invented", f"The index is {_fullwidth('87.5')}.", i),
        ("scientific-invented", "Conductivity was 1.9e2 uS/cm.", q),
        ("thousands-invented", "There were 2,256 observations.", q),
        ("percent-decimal-shift", "Baetidae has a 5.5% probability.", r),
        ("percent-of-fraction-misuse", "Baetidae has a 0.55% probability.", r),
        ("percent-invented", "Baetidae has a 75% probability.", r),
        ("unit-swap-mass", "Ammonium was 0.5 ug/L against a limit of 0.5 mg/L.", q),
        ("unit-swap-limit", "Ammonium was 0.5 mg/L against a limit of 0.5 ug/L.", q),
        ("unit-swap-temperature", "The temperature was 18.5 °F.", q),
        ("unit-swap-conductivity", "Conductivity was 2500 mS/cm.", q),
        ("unit-swap-percent", "Ammonium was 0.5 % of the limit.", q),
        ("arithmetic-invented", "The index is 19.9, so 24.9 after adding 5.", i),
        ("range-invented", "Data cover 2013-2019.", q),
        ("year-shift", "Data were collected in 2014.", {"period": "2013-2015 sample"}),
    ]
    limitation_miss = [
        ("context-swap", "The limit was 18.5.", q),  # 18.5 is the temperature, not the limit
        ("label-swap", "Baetidae has a probability of 0.45.", r),  # 0.45 belongs to Perlidae
        ("wrong-claim-right-number", "A value of 5 parameters failed.", i),  # 5 is the parameter count
        ("unit-free-context", "The index is 15.", i),  # 15 is the measurement count
    ]
    limitation_alarm = [
        ("derived-average", "On average 0.2 failures occurred per test.", i),
        ("derived-sum", "In total 18 numbers were involved.", i),
        ("derived-factor", "Nitrate exceeds its limit by a factor of six.", i),
        ("decimal-comma", "The index is 19,93.", i),  # European decimal comma: read as 19 and 93
    ]
    return (
        [("valid", c, t, e) for c, t, e in valid]
        + [("adversarial", c, t, e) for c, t, e in adversarial]
        + [("limitation-miss", c, t, e) for c, t, e in limitation_miss]
        + [("limitation-alarm", c, t, e) for c, t, e in limitation_alarm]
    )


def holdout_cases() -> list[Case]:
    """Cases written AFTER the implementation and measured BEFORE any further change (never used for tuning).

    Same author as the rest, so this is still not independent of the authors' imagination: it shows
    the check does not merely memorise the curated list, not how real model output behaves.
    """
    i, r, q = INDEX_EVIDENCE, REVIEW_EVIDENCE, QUANTITY_EVIDENCE
    valid = [
        ("markdown-bold", "The index is **19.93** (Poor).", i),
        ("score-out-of-100", "A score of 19.9/100 indicates poor quality.", i),
        ("approx-symbol", "The index is ≈ 19.9.", i),
        ("percent-with-space", "Baetidae is at 55 % and Perlidae at 45 %.", r),
        ("percent-word", "Baetidae is at 55 percent.", r),
        ("parenthesised", "Baetidae is likely (0.55) versus Perlidae (0.45).", r),
        ("unit-no-space", "Ammonium reached 0.5mg/L.", q),
        ("unit-long-form", "Ammonium was 0.5 milligrams per liter.", q),
        ("times-sign", "Nitrate is 5× over the limit.", i),
        ("hundred-percent", "This is a one hundred percent grounded case.", {"n": "x"}),
        ("list-of-numbers", "Counts were 15, 3 and 5.", i),
        ("negative-parens", "The change (−2.5) was small.", q),
        ("range-en-dash", "Between 0.45–0.55.", r),
        ("ordinal-words", "This is the first of the second group.", i),
        ("two-of-them", "Both of the two candidates are plausible.", r),
        ("trailing-zero", "The worst excursion is 5.0.", i),
        ("plus-sign", "An excursion of +5 was seen.", i),
        ("upper-e-notation", "Conductivity was 2.5E3 uS/cm.", q),
    ]
    adversarial = [
        ("markdown-invented", "The index is **87.5**.", i),
        ("out-of-100-invented", "A score of 87.5/100.", i),
        ("split-thousands", "There were 1 256 observations and 9 999 extra.", q),
        ("word-percent-invented", "Sixty-eight percent of tests failed.", i),
        ("word-decimal-invented", "Nineteen point nine three is the index.", {"ccme_wqi": 54.0}),
        ("hundred-and-fifty", "A hundred and fifty tests were run.", i),
        ("unit-word-swap", "Ammonium was 0.5 micrograms per liter.", q),
        ("unit-no-space-swap", "Ammonium reached 0.5ug/L.", q),
        ("fahrenheit-word", "Water was 18.5 degrees Fahrenheit.", q),
        ("percent-word-misuse", "Baetidae is at 0.55 percent.", r),
        ("times-invented", "Nitrate is 8× over the limit.", i),
        ("plus-invented", "An excursion of +9 was seen.", i),
        ("range-invented-endash", "Between 0.35–0.65.", r),
        ("negative-invented", "The change (−8.5) was large.", q),
        ("year-invented", "Sampled in 2019.", q),
        ("data-count-not-an-enumerator", "Two measurements failed and two families remain.", {"n": "x"}),
        ("fraction-swap", "Baetidae has 0.54.", r),
        ("scale-mg-to-g", "Ammonium was 0.5 g/L.", q),
    ]
    return [("valid", c, t, e) for c, t, e in valid] + [("adversarial", c, t, e) for c, t, e in adversarial]


_GENERATED_VALUES = (19.928374, 0.55, 0.45, 5.0, 1256.0, 18.5, 2500.0, 0.0731, 42.42, 7.35)


def generated_cases() -> list[Case]:
    """Systematic renderings (valid) and systematic distortions (adversarial) of numeric evidence."""
    cases: list[Case] = []
    for value in _GENERATED_VALUES:
        evidence = {"reported_value": value}
        for digits in (0, 1, 2):
            if value != 0.55 and value != 0.45 or digits == 2:
                cases.append(("valid", f"gen-round-{digits}", f"The reported value is {_half_up(value, digits)}.", evidence))
        cases.append(("valid", "gen-exact", f"The reported value is {value}.", evidence))
        if 0 < value < 1:
            cases.append(("valid", "gen-percent", f"The reported value is {_half_up(value * 100, 0)}%.", evidence))
        if value >= 1000:
            cases.append(("valid", "gen-thousands", f"The reported value is {int(value):,}.", evidence))
        distorted = [(f"gen-{label}", f"{value * factor:g}") for factor, label in ((10.0, "shift-up"), (0.1, "shift-down"), (-1.0, "sign"))]
        distorted.append(("gen-offset", _half_up(value + 3.7, 2)))
        distorted.append(("gen-scaled", _half_up(value * 1.37, 1)))
        for label, rendered in distorted:
            if not _is_legitimate_rounding(rendered, value):  # never label a faithful rounding as adversarial
                cases.append(("adversarial", label, f"The reported value is {rendered}.", evidence))
    return cases


def all_cases() -> list[Case]:
    """Curated plus generated cases, without duplicates (a repeated case would inflate the rates)."""
    seen: set[tuple[str, str]] = set()
    unique: list[Case] = []
    for case in curated_cases() + generated_cases():
        key = (case[2], repr(sorted(case[3].items())))
        if key not in seen:
            seen.add(key)
            unique.append(case)
    return unique
