"""The language fields of an API response, built from a validated English answer and an optional translation.

Pure functions, no I/O beyond the packaged strings: ``oah.api.services`` decides when a model call is made (spend
guard, cache, audit) and passes the outcome here. The rules (docs/language_support.md):

* English requested: the answer is the English text, ``answer_en`` is null, status ``not-needed``.
* Another language and a translation that passed the checks: the translated text, ``answer_en`` the English original,
  status ``ok``, ``translated`` true. A translation that failed a check or could not be made falls back to the English
  text with status ``rejected`` or ``failed`` and the fallback notice.
* An unsafe English answer is never translated and never returned (status ``not-needed``, reason
  ``english-answer-unsafe``, no text): the chat and the explanation routes both show the flags and the fixed withheld notice.
* An English answer that is not grounded (a number or unit that cannot be traced to the data) is withheld the same way
  (reason ``english-answer-ungrounded``, notice ``withheld_ungrounded_notice``): no text, no translation.
* The fixed texts of the chat (budget exceeded, no answer) are not model output: they come from the strings files in
  the requested language, ``answer_en`` is the English original, status ``not-needed``.
* ``translation_checks`` says how far a translation into the language is verified (``translation_checks_level``).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from oah.i18n.denylist import has_denylist
from oah.i18n.languages import LANGUAGES, SOURCE_LANGUAGE
from oah.i18n.strings import ENGLISH, load_strings
from oah.i18n.translator import TranslationResult, TranslationStatus

UNSAFE_REASON = "english-answer-unsafe"
UNGROUNDED_REASON = "english-answer-ungrounded"

ChecksLevel = Literal["neutral-and-denylist", "neutral-only"]
CHECKS_NEUTRAL_AND_DENYLIST: ChecksLevel = "neutral-and-denylist"
CHECKS_NEUTRAL_ONLY: ChecksLevel = "neutral-only"


def translation_checks_level(code: str) -> ChecksLevel | None:
    """How far a machine translation into ``code`` is verified: ``neutral-and-denylist`` (numbers, links and markup, length,
    copied instructions, plus a best-effort list of potability and safety words) for the languages that have a denylist,
    ``neutral-only`` (the same, without the word list) for the others, null for English (nothing is translated).

    Neither level proves the meaning is preserved: a client labels any translated text as machine translation and shows
    ``answer_en`` next to it; ``neutral-only`` is the weaker level and should be labelled as unverified.
    """
    if code == SOURCE_LANGUAGE:
        return None
    return CHECKS_NEUTRAL_AND_DENYLIST if has_denylist(LANGUAGES[code].family) else CHECKS_NEUTRAL_ONLY


@dataclass(frozen=True)
class Localization:
    language: str
    text: str | None  # what to show: the translation, the English fallback, a localised fixed text, or nothing
    answer_en: str | None  # the validated English original; null when English was requested or nothing is shown
    translation_status: TranslationStatus
    translated: bool
    translation_reasons: tuple[str, ...]
    notices: dict[str, str]
    disclaimer: str
    translation_checks: ChecksLevel | None = None


def notices_for(
    code: str, *, translation_status: str, unsafe: bool, grounded: bool, withheld_ungrounded: bool = False,
    with_evidence: bool = False,
) -> dict[str, str]:
    """The fixed notices that apply to a response, in the requested language (never model output)."""
    strings = load_strings(code)
    notices = {"interpretation_notice": strings.get("interpretation_notice")}
    if translation_status == "ok":
        notices["machine_translation_notice"] = strings.get("machine_translation_notice")
    elif translation_status in ("rejected", "failed"):
        notices["translation_fallback_notice"] = strings.get("translation_fallback_notice", language=LANGUAGES[code].endonym)
    if unsafe:
        notices["withheld_notice"] = strings.get("withheld_notice")
    elif withheld_ungrounded:
        notices["withheld_ungrounded_notice"] = strings.get("withheld_ungrounded_notice")
    elif not grounded:
        notices["ungrounded_notice"] = strings.get("ungrounded_notice")
    if with_evidence:
        notices["evidence_notice"] = strings.get("evidence_notice")  # the response carries an evidence summary of the data consulted
    return notices


def build_localization(
    code: str,
    english_text: str | None,
    translation: TranslationResult | None = None,
    *,
    fixed_key: str | None = None,
    unsafe: bool = False,
    grounded: bool = True,
    withheld_ungrounded: bool = False,
    with_evidence: bool = False,
) -> Localization:
    """Combine the English answer, the translation outcome and the requested language into response fields.

    ``fixed_key`` names a string of ``oah.i18n.strings`` that replaces the answer (chat budget and no-answer texts).
    An unsafe answer, and one withheld as not grounded (``withheld_ungrounded``), have NO text in any language.
    ``with_evidence`` adds the fixed ``evidence_notice`` (the chat response carries a summary of the data consulted).
    """
    strings = load_strings(code)
    disclaimer = strings.get("disclaimer")
    reasons: tuple[str, ...] = ()
    withheld = unsafe or withheld_ungrounded
    if code == SOURCE_LANGUAGE:
        status: TranslationStatus = "not-needed"
        text = None if withheld else english_text
        answer_en = None
    elif fixed_key is not None:
        status, text, answer_en = "not-needed", strings.get(fixed_key), ENGLISH[fixed_key]
    elif withheld or english_text is None:
        status, reasons = "not-needed", (UNGROUNDED_REASON if (withheld_ungrounded and not unsafe) else UNSAFE_REASON,)
        text = None
        answer_en = None
    elif translation is None:
        raise ValueError("a translation outcome is required for a safe answer in a language other than English")
    else:
        status, reasons = translation.status, translation.reasons
        text, answer_en = translation.text, english_text
    translated = status == "ok" and code != SOURCE_LANGUAGE
    return Localization(
        language=code,
        text=text,
        answer_en=answer_en,
        translation_status=status,
        translated=translated,
        translation_reasons=reasons,
        notices=notices_for(
            code, translation_status=status, unsafe=unsafe, grounded=grounded, withheld_ungrounded=withheld_ungrounded,
            with_evidence=with_evidence,
        ),
        disclaimer=disclaimer,
        translation_checks=translation_checks_level(code),
    )
