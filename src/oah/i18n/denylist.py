"""Optional best-effort denylist of obvious potability and safety words for the tier-1 languages.

BEST EFFORT, never the only protection: the English text was already guarded before translation, the translation is
checked by language-neutral properties (``oah.i18n.translate_check``), and the translation prompt forbids these
words. This hook only catches the obvious cases where a translator introduces a claim word that the English source
did not contain ("potable", "safe to drink", "contaminated", "toxic", "harmful" and their usual inflections). Patterns
are data (``src/oah/i18n/denylist/<family>.json``), one file per language family, written for the languages whose
vocabulary the maintainer could review first: es, it, el, fr, de, pt, nb. Spanish variants share the ``es`` file.

Matching is done on the NFKC form of the translation, case-insensitively, with word boundaries. The noun forms
(for example the Spanish or Italian word for "potability") are not listed on purpose: the English guard allows the
word "potability", and a faithful translation of "this is not a potability determination" must not be rejected.
Unlisted inflections and synonyms are a known gap.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from oah.paths import source_path

MAX_PATTERNS = 60
MAX_PATTERN_CHARS = 200
DENYLIST_FAMILIES = ("de", "el", "es", "fr", "it", "nb", "pt")


class DenylistError(ValueError):
    """A denylist data file is malformed."""


@lru_cache(maxsize=None)
def denylist_patterns(family: str) -> tuple[re.Pattern[str], ...]:
    """The compiled patterns of one language family; empty when the family has no denylist."""
    if family not in DENYLIST_FAMILIES:
        return ()
    path = source_path("i18n", "denylist", f"{family}.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    patterns = data.get("patterns") if isinstance(data, dict) else None
    if (
        not isinstance(data, dict)
        or data.get("language") != family
        or data.get("best_effort") is not True
        or not isinstance(patterns, list)
        or not 0 < len(patterns) <= MAX_PATTERNS
    ):
        raise DenylistError(f"{path.name}: expected an object with language, best_effort true and 1 to {MAX_PATTERNS} patterns.")
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > MAX_PATTERN_CHARS:
            raise DenylistError(f"{path.name}: every pattern must be a non-empty string of at most {MAX_PATTERN_CHARS} characters.")
        compiled.append(re.compile(pattern, re.IGNORECASE))
    return tuple(compiled)


def has_denylist(family: str) -> bool:
    return family in DENYLIST_FAMILIES
