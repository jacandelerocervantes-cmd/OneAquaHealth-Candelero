"""Language-neutral verification of a machine translation of an already validated English answer.

The English guards (``oah.explain.safety.guard_output``, ``oah.explain.grounding.check_grounding``) were written for
English and run on the English text before it is translated. A translation is never checked by pattern lists in the
target language (that would need a reliable pack for 26 languages). It is checked only by properties that do not
depend on the language:

* the multiset of numeric tokens equals the source (digits with their own decimal point and separators, written
  exactly as in the source: a decimal comma, a regrouped thousands separator, an added or a dropped number all
  change the multiset);
* non-ASCII numeral characters (Arabic-Indic or fullwidth digits, superscripts, roman-numeral characters) appear
  only as often as in the source (a unit such as km2 written with a superscript is kept, a new numeral system is not);
* no invisible or control characters (zero-width characters, bidi controls, soft hyphens, tag characters);
* no URL, HTML tag, markdown link or code fence, and no copy of the instructions of the translation call (the neutral
  flags of ``guard_output``; its English claim and format flags are not applied to a translation);
* length within ``MIN_LENGTH_RATIO`` to ``MAX_LENGTH_RATIO`` of the source and at most ``MAX_TRANSLATION_CHARS``;
* an OPTIONAL best-effort denylist of obvious potability and safety words for the tier-1 languages
  (``oah.i18n.denylist``), never the only protection.

A translation that is identical to the source is accepted (a text made only of codes and numbers stays as it is).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from oah.explain.safety import guard_output

MIN_LENGTH_RATIO = 0.4
MAX_LENGTH_RATIO = 3.0
MAX_TRANSLATION_CHARS = 6_000
MAX_SOURCE_CHARS = 3_000  # the same bound as the English output guard

# Flags of guard_output that do not depend on the language of the text.
NEUTRAL_GUARD_FLAGS = frozenset(
    {"contains-url", "contains-html", "contains-markdown-link", "contains-code-block", "leaks-instructions"}
)

# ASCII digits only (a bare ``\d`` would also match every Unicode digit): digits joined by single "." or ","
# characters stay one token, so "1,234.5" is one token and "1.234,5" or "1 234.5" is a different one.
_NUMBER = re.compile(r"[0-9]+(?:[.,][0-9]+)*")
_NUMERAL_CATEGORIES = frozenset({"Nd", "Nl", "No"})
_INVISIBLE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    reasons: tuple[str, ...]


def numeric_tokens(text: str) -> Counter[str]:
    """The multiset of ASCII numeric tokens of ``text``."""
    return Counter(_NUMBER.findall(text))


def non_ascii_numerals(text: str) -> Counter[str]:
    """The multiset of numeral characters that are not ASCII digits (category Nd, Nl or No)."""
    return Counter(ch for ch in text if ord(ch) > 127 and unicodedata.category(ch) in _NUMERAL_CATEGORIES)


def invisible_characters(text: str) -> tuple[str, ...]:
    """Control and invisible characters other than ordinary whitespace (``\\n`` and ``\\t`` are allowed)."""
    return tuple(
        sorted({f"U+{ord(ch):04X}" for ch in text if unicodedata.category(ch) in _INVISIBLE_CATEGORIES and ch not in "\n\t"})
    )


def _squash(token: str) -> str:
    return re.sub(r"[.,]", "", token)


def number_reasons(source: str, translation: str) -> list[str]:
    """Reasons the numbers of ``translation`` differ from ``source`` (empty when they are identical)."""
    reasons: list[str] = []
    wanted, got = numeric_tokens(source), numeric_tokens(translation)
    if wanted != got:
        added, missing = got - wanted, wanted - got
        reformatted = {_squash(token) for token in added} & {_squash(token) for token in missing}
        if reformatted:
            reasons.append("numeral-format-changed")  # the same digits written with other separators
        if any(_squash(token) not in reformatted for token in added):
            reasons.append("number-added")
        if any(_squash(token) not in reformatted for token in missing):
            reasons.append("number-missing")
    if non_ascii_numerals(source) != non_ascii_numerals(translation):
        reasons.append("non-ascii-numeral")
    return reasons


def _shingles(text: str, size: int = 6) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(words[i : i + size]) for i in range(max(0, len(words) - size + 1))}


def leaks_instructions(source: str, translation: str, leak_sources: Sequence[str]) -> bool:
    """True when the translation repeats a run of six words of one of ``leak_sources`` (the instructions of the
    translation call and, optionally, of the chat). Runs that the English source itself contains are not counted: the
    source was already checked, and a faithful copy of it is not a leak."""
    fresh = _shingles(translation) - _shingles(source)
    return any(fresh & _shingles(prompt) for prompt in leak_sources)


def forbidden_constructs(source: str, translation: str, leak_sources: Sequence[str]) -> list[str]:
    """Neutral checks: URL, HTML, markdown link, code fence (flags of ``guard_output``) and copied instructions."""
    flags = guard_output(translation, "describe", ())
    reasons = [flag for flag in flags if flag in NEUTRAL_GUARD_FLAGS]
    if leaks_instructions(source, translation, leak_sources):
        reasons.append("leaks-instructions")
    return reasons


def length_reasons(source: str, translation: str, *, min_ratio: float = MIN_LENGTH_RATIO, max_ratio: float = MAX_LENGTH_RATIO) -> list[str]:
    """``too-short`` / ``too-long`` when the length ratio (in characters) leaves the bounded range."""
    reasons: list[str] = []
    ratio = len(translation) / max(1, len(source))
    if ratio < min_ratio:
        reasons.append("too-short")
    if ratio > max_ratio or len(translation) > MAX_TRANSLATION_CHARS:
        reasons.append("too-long")
    return reasons


def check_translation(
    source: str,
    translation: str,
    *,
    leak_sources: Sequence[str] = (),
    denylist_patterns: Sequence[re.Pattern[str]] = (),
    min_ratio: float = MIN_LENGTH_RATIO,
    max_ratio: float = MAX_LENGTH_RATIO,
) -> CheckResult:
    """Verify ``translation`` against the validated English ``source``; every failed check adds one reason."""
    if not translation.strip():
        return CheckResult(False, ("empty",))
    reasons: list[str] = []
    if invisible_characters(translation):
        reasons.append("invisible-characters")
    reasons.extend(number_reasons(source, translation))
    reasons.extend(forbidden_constructs(source, translation, leak_sources))
    reasons.extend(length_reasons(source, translation, min_ratio=min_ratio, max_ratio=max_ratio))
    folded = unicodedata.normalize("NFKC", translation)
    if any(pattern.search(folded) for pattern in denylist_patterns):
        reasons.append("denylist-term")
    return CheckResult(not reasons, tuple(dict.fromkeys(reasons)))
