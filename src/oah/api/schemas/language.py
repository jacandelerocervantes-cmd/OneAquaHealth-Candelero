"""Answer-language models: the fields shared by explanation and chat responses, and ``GET /languages``."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


TranslationStatus = Literal["not-needed", "ok", "rejected", "failed"]
TranslationChecks = Literal["neutral-and-denylist", "neutral-only"]


class LanguageFields(BaseModel):
    """The answer-language fields shared by the explanation and chat responses (docs/language_support.md).

    The grounding and unsafe flags always describe the ENGLISH answer. ``answer_en`` is that validated English answer
    (null when English was requested, or when nothing is shown). ``translation_status``: ``ok`` the text is the model's
    verified translation; ``rejected`` a check failed and the English text is shown; ``failed`` the translation could not
    be made (provider error, timeout, budget) and the English text is shown; ``not-needed`` English was requested, the
    text is a localised fixed string, or the English answer was unsafe and is never translated.
    """

    language: str  # canonical code of the answer language, one of GET /languages
    answer_en: str | None = None
    translation_status: TranslationStatus
    translated: bool  # true only for a model translation that passed the checks
    translation_reasons: list[str]  # why a translation was rejected or not made; codes, never text
    notices: dict[str, str]  # fixed notices in the answer language (interpretation, machine translation, fallback, ...)
    # How far a translation into this language is verified: ``neutral-and-denylist`` (numbers, links and markup, length, copied
    # instructions and a best-effort list of potability and safety words) or ``neutral-only`` (the same without the word list);
    # null for English. A client labels any translated text "machine translation" and shows ``answer_en``; for ``neutral-only``
    # it should also say the translation is unverified. Neither level proves the meaning is preserved.
    translation_checks: TranslationChecks | None = None


class LanguageEntry(BaseModel):
    code: str  # BCP-47 tag as accepted by the ``language`` parameter, for example es-MX
    name: str  # English name
    endonym: str  # name in the language itself
    status: Literal["source", "translated-by-model"]  # English is the source; every other answer is machine-translated
    script: str
    direction: Literal["ltr", "rtl"]
    tier: Literal[1, 2]  # 1: best-effort denylist and first in line for native-speaker review
    fixed_strings_review_status: Literal["source", "machine-draft"]  # the fixed notices are never human-reviewed yet
    translation_checks: TranslationChecks | None = None  # the verification level of a translation into it; null for English


class LanguagesResponse(BaseModel):
    """The answer languages (docs/language_support.md)."""

    default_language: str  # used when a request names none (OAH_DEFAULT_LANGUAGE)
    source_language: str
    languages: list[LanguageEntry]
    note: str
