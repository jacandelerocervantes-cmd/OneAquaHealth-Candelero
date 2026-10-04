"""Deterministic post-hoc grounding check for LLM-generated explanations.

The LLM call in ``oah.explain.explainer`` is not trusted on its own. Every number the model writes
must trace back to a number in the evidence it was given, and a number written with a unit must not
carry a different unit than the evidence gives it. A failure is reported, never hidden.

What it checks
* Numbers: digits (ASCII or full-width, ``1,256``, ``2.5e3``, ``-2.5``/``−2.5``, ranges such as
  ``2013-2015``) and spelled-out numbers (``nineteen``, ``twenty-five``, ``eighty-seven point five``).
* Rounding: a number written with ``d`` decimals matches an evidence value ``e`` when
  ``|t - e| <= 0.5 * 10**-d`` (exact decimal arithmetic), i.e. any reasonable round-half-up or
  round-half-down. Truncation beyond half a unit is NOT accepted.
* Percentages: ``55%`` matches an evidence fraction ``0.55``; ``0.55%`` does not. A number followed by ``%``
  also matches an evidence value above 1 (already a percentage) or one whose unit is ``%``.
* Units: when the evidence gives a number a unit (a dict with a ``unit`` key), the same number written in the
  text with a different known unit (``ug/L`` for ``mg/L``, ``°F`` for ``Cel``) is a ``unit_mismatch``.
* Discourse counts: 2-10 directly before ``points``, ``things``, ``reasons``, ``steps``, ``options``, ``caveats``,
  ``notes`` or ``questions`` numbers the writer's own remarks, not the data (``two points for your decision``).
* Counts: the length of any list, and of a nested object whose values are all numbers (a distribution), is
  an allowed number (``two candidates`` for a two-item prediction set). The size of a record itself is not.

What it cannot check (measured in ``oah.explain.grounding_cases`` and docs/math_registry.md)
* A correct number attached to the wrong claim (``limit 18.5`` when 18.5 is the temperature) or a swapped label.
* Derived numbers (3 of 15 written as ``20%``) are flagged on purpose: an unsupported number and a derived
  one cannot be told apart syntactically.
* Fractions written as words (``half``, ``a third``), numbers in other languages, and spelled numbers above a million.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

_NUMBER = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?")
_SAFE_VALUES = frozenset({Decimal(0), Decimal(1), Decimal(100)})

# canonical unit -> aliases (normalised: lower case, no spaces, u for micro)
_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "mg/L": ("mg/l", "milligramperliter", "milligramsperliter", "milligramperlitre"),
    "ug/L": ("ug/l", "microgramperliter", "microgramsperliter", "microgramperlitre"),
    "ng/L": ("ng/l",),
    "g/L": ("g/l",),
    "uS/cm": ("us/cm",),
    "mS/cm": ("ms/cm",),
    "ug/m3": ("ug/m3",),
    "mg/m3": ("mg/m3",),
    "Cel": ("cel", "°c", "celsius", "degreescelsius", "degc"),
    "degF": ("°f", "fahrenheit", "degreesfahrenheit", "degf"),
    "%": ("%", "percent", "percentage", "percentagepoints"),
    "NTU": ("ntu",),
}
_ALIAS_TO_UNIT = {alias: unit for unit, aliases in _UNIT_ALIASES.items() for alias in aliases}
_ALIASES_LONGEST_FIRST = sorted(_ALIAS_TO_UNIT, key=len, reverse=True)

_UNITS_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS_WORDS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_WORD = re.compile(
    r"\b(?:(?:" + "|".join(sorted({**_UNITS_WORDS, **_TENS_WORDS}, key=len, reverse=True)) + r")"
    r"(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?|hundred|thousand|million)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GroundingResult:
    grounded: bool
    ungrounded_numbers: tuple[str, ...]
    unit_mismatches: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Evidence:
    value: Decimal
    unit: str | None  # canonical unit, or None when the evidence gives none


@dataclass(frozen=True)
class _Mention:
    raw: str
    value: Decimal
    decimals: int
    unit: str | None
    is_word: bool
    enumerator: bool = False  # a small count that numbers the reviewer's own points ("two points"), not a data claim


# Discourse nouns a writer uses to number their own remarks. A spelled or digit count of 2-10 directly before one of
# them is not a claim about the data ("Two points for your decision"). Data nouns ("measurements", "families",
# "observations") are deliberately absent, so an invented count of those is still flagged.
_ENUMERATOR_NOUNS = frozenset({"points", "things", "reasons", "steps", "options", "caveats", "notes", "questions"})
_NEXT_WORD = re.compile(r"\s+([A-Za-z]+)")


def _enumerates(text: str, end: int) -> bool:
    match = _NEXT_WORD.match(text, end)
    return match is not None and match.group(1).lower() in _ENUMERATOR_NOUNS


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    return text.replace("−", "-").replace("µ", "u").replace("μ", "u").replace("³", "3")


def _canonical_unit(text: str) -> str | None:
    return _ALIAS_TO_UNIT.get(re.sub(r"\s+", "", _normalise(text).lower()))


def _parse(token: str) -> tuple[Decimal, int] | None:
    """Exact value of a numeric token and the number of decimals it was written with."""
    cleaned = token.replace(",", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    mantissa, _, exponent = cleaned.lower().partition("e")
    decimals = len(mantissa.partition(".")[2]) - (int(exponent) if exponent else 0)
    return value, max(0, decimals)


def _tolerance(decimals: int) -> Decimal:
    return Decimal("0.5") * Decimal(10) ** -decimals


def _matches(mention: Decimal, decimals: int, evidence: Decimal) -> bool:
    return abs(mention - evidence) <= _tolerance(decimals)


def _unit_after(text: str, end: int) -> str | None:
    """Canonical unit written right after a number, matching aliases across optional spaces.

    The word boundary is checked in the ORIGINAL text, so ``ug/L against`` is a unit followed by a
    word, while ``mg/Lx`` is not a unit.
    """
    rest = _normalise(text[end : end + 40]).lower()
    compact: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(rest):
        if not char.isspace():
            compact.append(char)
            origin.append(index)
    joined = "".join(compact)
    for alias in _ALIASES_LONGEST_FIRST:
        if joined.startswith(alias):
            follower = rest[origin[len(alias) - 1] + 1 : origin[len(alias) - 1] + 2]  # char right after the alias
            if not (alias[-1].isalnum() and follower.isalnum()):
                return _ALIAS_TO_UNIT[alias]
    return None


def _word_value(phrase: str) -> Decimal:
    words = re.split(r"[- ]", phrase.lower())
    total = Decimal(0)
    for word in words:
        if word in _UNITS_WORDS:
            total += _UNITS_WORDS[word]
        elif word in _TENS_WORDS:
            total += _TENS_WORDS[word]
    return total


def _mentions(text: str) -> list[_Mention]:
    text = _normalise(text)
    found: list[_Mention] = []
    for match in _NUMBER.finditer(text):
        parsed = _parse(match.group())
        if parsed is None:
            continue
        value, decimals = parsed
        before = text[: match.start()]
        if before.endswith("-") and not (len(before) > 1 and (before[-2].isalnum() or before[-2] in "_)")):
            value = -value
        raw = ("-" if value < 0 else "") + match.group()
        found.append(_Mention(raw, value, decimals, _unit_after(text, match.end()), False, _enumerates(text, match.end())))
    taken = [(m.start(), m.end()) for m in _NUMBER.finditer(text)]
    lowered = text
    for match in _WORD.finditer(lowered):
        if any(start <= match.start() < end for start, end in taken):
            continue
        phrase = match.group()
        base = phrase.lower()
        if base in ("hundred", "thousand", "million"):
            value = Decimal({"hundred": 100, "thousand": 1000, "million": 1_000_000}[base])
        else:
            value = _word_value(phrase)
            tail = re.match(r"\s+point((?:\s+(?:zero|one|two|three|four|five|six|seven|eight|nine))+)\b", lowered[match.end() :], re.IGNORECASE)
            decimals = 0
            if tail:
                digits = [str(_UNITS_WORDS[w]) for w in tail.group(1).split()]
                value = Decimal(f"{value}.{''.join(digits)}")
                decimals = len(digits)
                found.append(_Mention(phrase + tail.group(0), value, decimals, _unit_after(lowered, match.end() + len(tail.group(0))), True))
                continue
        found.append(_Mention(phrase, value, 0, _unit_after(lowered, match.end()), True, _enumerates(lowered, match.end())))
    return found


def _collect(node: Any, unit: str | None, out: list[_Evidence], counts: set[int], root: bool = False) -> None:
    if isinstance(node, bool) or node is None:
        return
    if isinstance(node, (int, float, Decimal)):
        out.append(_Evidence(Decimal(str(node)), unit))
    elif isinstance(node, str):
        for match in _NUMBER.finditer(_normalise(node)):
            parsed = _parse(match.group())
            if parsed:
                out.append(_Evidence(parsed[0], None))
    elif isinstance(node, Mapping):
        if not root and node and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in node.values()):
            counts.add(len(node))  # a distribution over classes is countable; a record's schema size is not
        declared = node.get("unit")
        scope = _canonical_unit(declared) if isinstance(declared, str) else None
        for key, value in node.items():
            _collect(str(key), None, out, counts)
            _collect(value, scope if scope else unit, out, counts)
    elif isinstance(node, (list, tuple, set)):
        counts.add(len(node))
        for item in node:
            _collect(item, unit, out, counts)


def check_grounding(explanation_text: str, evidence: Mapping[str, Any]) -> GroundingResult:
    """Verify every number (and unit) in ``explanation_text`` traces back to ``evidence``."""
    facts: list[_Evidence] = []
    counts: set[int] = set()
    _collect(json.loads(json.dumps(evidence, default=str)), None, facts, counts, root=True)
    allowed_counts = {Decimal(n) for n in counts}

    ungrounded: set[str] = set()
    mismatches: set[str] = set()
    for mention in _mentions(explanation_text):
        value, unit = mention.value, mention.unit
        if value in _SAFE_VALUES or value in allowed_counts and value == value.to_integral_value():
            continue
        if mention.enumerator and Decimal(2) <= value <= Decimal(10) and value == value.to_integral_value():
            continue
        if unit == "%":
            candidates = [
                f for f in facts
                if (f.unit == "%" and _matches(value, mention.decimals, f.value))
                or (f.unit is None and 0 <= f.value <= 1 and _matches(value, mention.decimals, f.value * 100))
                or (f.unit is None and f.value > 1 and _matches(value, mention.decimals, f.value))
            ]
            if not candidates:
                ungrounded.add(mention.raw + "%")
            continue
        matched = [f for f in facts if _matches(value, mention.decimals, f.value)]
        if not matched:
            ungrounded.add(mention.raw)
        elif unit is not None and not any(f.unit is None or f.unit == unit for f in matched):
            expected = sorted({f.unit for f in matched if f.unit})
            mismatches.add(f"{mention.raw} {unit} (evidence unit: {', '.join(expected)})")
    return GroundingResult(not ungrounded and not mismatches, tuple(sorted(ungrounded)), tuple(sorted(mismatches)))
