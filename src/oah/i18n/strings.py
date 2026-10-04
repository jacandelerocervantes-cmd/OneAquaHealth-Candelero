"""Fixed user-facing strings, localised (docs/language_support.md).

English is the source of truth and lives here, in code. Every other language is one JSON file in
``src/oah/i18n/strings/<code>.json`` with the same keys and the same placeholders. The files are model-drafted
translations and say so (``"review_status": "machine-draft"``); none was reviewed by a human. These strings are the
only translated text that is NOT produced at run time: model-generated answers go through ``oah.i18n.translator``.

Each file carries ``source_sha256``, the digest of the English text it was translated from, so a change of an English
string makes every translation visibly stale (``StringsError``) instead of silently showing an old wording.

Loading is strict: every key present, no key missing or extra, no empty value, the same ``{placeholders}`` as English,
the same numbers as English, and no HTML, URL, markdown link, code fence or control characters.
"""
from __future__ import annotations

import hashlib
import json
import re
import string
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from oah.i18n.languages import DEFAULT_LANGUAGE, LANGUAGES, SOURCE_LANGUAGE, normalize_code
from oah.i18n.translate_check import numeric_tokens
from oah.paths import source_path

MAX_STRING_CHARS = 600
MACHINE_DRAFT = "machine-draft"
SOURCE_STATUS = "source"

ENGLISH: dict[str, str] = {
    "disclaimer": "AI-generated decision support. Not verified, and not a potability, health or regulatory determination.",
    "interpretation_notice": (
        "Reference values, not a legal compliance determination: a failed measurement means the reference "
        "value used was exceeded, not a legal exceedance. See limit_basis for each parameter's source."
    ),
    "budget_exceeded": (
        "I could not answer within the step budget for this question. Try a narrower question: one site, one "
        "parameter and a date window."
    ),
    "no_answer": "The assistant returned no answer. Try rephrasing the question.",
    "not_available": "Not available in this data.",
    "machine_translation_notice": (
        "Machine-translated from the English original. Numbers, units, names and codes are unchanged."
    ),
    "translation_fallback_notice": "The answer could not be translated into {language} safely, so the English original is shown.",
    "withheld_notice": "The answer was withheld because it did not pass the safety checks.",
    "ungrounded_notice": "Some numbers in this answer could not be traced to the data.",
    "withheld_ungrounded_notice": (
        "The answer was withheld because some of its numbers or units could not be traced to the data. The data that "
        "were consulted are still shown."
    ),
    # Chat evidence summary (a withheld answer still shows the data consulted): no digits, so every translation carries none.
    "evidence_notice": (
        "Data the assistant consulted, copied from the data tools. A short list shows every value. A longer one shows how "
        "many values there are, the lowest and highest value seen, and the first and last period. An observed range is not "
        "a confidence interval."
    ),
    "bathing_water_classification_notice": (
        "Bathing-water status is a classification under Directive 2006/7/EC. It is not a concentration and not a "
        "statement of legal compliance."
    ),
    "measurement_only_notice": (
        "This project has no limit regime for these parameters. Values are shown without a limit comparison."
    ),
    "bathing_change_notice": (
        "Seasons are compared only by the order of the four classes excellent, good, sufficient and poor. Bathing "
        "waters with the class not classified, or good or sufficient, in either season cannot be compared and are "
        "counted separately. No concentration or threshold is involved."
    ),
    # Bathing-water SAMPLES (backend package 6, docs/bathing_samples_store.md): individual E. coli and enterococci results.
    "bathing_samples_notice": (
        "These are individual sample results of E. coli and intestinal enterococci reported under the Bathing Water "
        "Directive, in colony-forming units per 100 ml. They are not a classification and not a compliance assessment."
    ),
    "bathing_no_threshold_notice": (
        "No threshold or limit is applied to these values. This project has none for these bacteria, so a value is "
        "never labelled good, bad or compliant here. For advice on bathing, ask the competent authority."
    ),
    "bathing_flagged_values_note": (
        "Values that the source flags as below the limit of detection, missing or of an unrecognised status are counted "
        "apart and are not in the minimum, maximum, mean or median. Confirmed high values are included and counted."
    ),
    "bathing_samples_change_notice": (
        "Periods are compared by the mean and the median of individual sample results. No significance is tested, and "
        "because no limit exists for these bacteria no limit crossing is reported. A country comparison uses only the "
        "bathing waters with enough samples in both periods."
    ),
    # EXTERNAL context (backend package 7, docs/external_context.md): weather, river discharge and species records from
    # public providers. Modelled or opportunistic, never the site's own data, never evidence of causation.
    "external_context_notice": (
        "External context from a public data provider: it is not a measurement made at this site and is not part of "
        "the site's own data. It is shown for orientation only."
    ),
    "external_reanalysis_notice": (
        "Weather values are modelled reanalysis for a coarse grid cell, not measurements at the site. The most recent "
        "days may be missing."
    ),
    "external_discharge_notice": (
        "River discharge is modelled for the nearest river cell of a coarse grid, not measured at a gauge, and that "
        "cell may not be the river of this site."
    ),
    "external_occurrence_notice": (
        "Species records are opportunistic observations published to GBIF, not monitoring. Having no record does not "
        "mean a species is absent."
    ),
    "external_licence_notice": "Each record keeps its own licence and some allow non-commercial use only.",
    "external_no_causation_notice": (
        "Weather and river flow are context only. Nothing here shows that they caused any water-quality value."
    ),
    "external_unavailable_notice": (
        "The external data provider could not be used just now (switched off, over its call budget, or not "
        "answering). Nothing was estimated in its place."
    ),
    # Reasons an index of the sidebar catalogue does not apply to a country (GET /catalog, docs/indices_catalog.md).
    "catalog_reason_no_data": "No data for this country.",
    "catalog_reason_not_loaded": "Data not loaded.",
    "catalog_reason_provider_off": "This external provider is switched off.",
    "catalog_reason_no_site": "No site with coordinates in this country.",
    "catalog_reason_no_river_site": "No river site with coordinates in this country.",
    # Final wording (package 5, the period comparison): replaces the provisional text of the language package.
    "approximation_notice": (
        "Screening aid, not a compliance assessment: each period is summarised by its mean, which is compared with "
        "the limit. National aggregation rules such as LIMeco or HWQI are not reproduced."
    ),
    "status_answered": "Answered",
    "status_withheld": "Withheld",
    "status_withheld_ungrounded": "Withheld, not grounded",
    "status_budget_exceeded": "Budget exceeded",
    "status_no_answer": "No answer",
    "translation_status_not_needed": "Original language",
    "translation_status_ok": "Machine translation",
    "translation_status_rejected": "Translation rejected, original shown",
    "translation_status_failed": "Translation failed, original shown",
}

KEYS: tuple[str, ...] = tuple(ENGLISH)

_PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
_FORBIDDEN = re.compile(
    r"(?i)</?[a-z][^>]*>|\b(?:https?|ftp|javascript):|\bwww\.|!\[|\[[^\]]*\][(\[]|```|[<>]"
)


class StringsError(ValueError):
    """A strings file is malformed, incomplete or stale."""


def english_digest() -> str:
    """Digest of the English text; every translation file must carry it."""
    return hashlib.sha256(json.dumps(ENGLISH, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def placeholders(text: str) -> frozenset[str]:
    """The ``{name}`` placeholders of ``text``; raises ``StringsError`` for a malformed format string."""
    try:
        names = {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}
    except ValueError as error:
        raise StringsError(f"malformed placeholder syntax: {error}") from error
    bad = {name for name in names if not _PLACEHOLDER.fullmatch("{" + name + "}")}
    if bad:
        raise StringsError(f"unsupported placeholder names {sorted(bad)}")
    return frozenset(names)


@dataclass(frozen=True)
class LocalizedStrings:
    code: str
    review_status: str
    strings: dict[str, str]
    fallback: bool = False  # True when English was served because the requested language is unknown

    def get(self, key: str, **values: str) -> str:
        if key not in self.strings:
            raise KeyError(key)
        text = self.strings[key]
        return text.format(**values) if values or "{" in text else text


def validate_strings(code: str, data: Any) -> LocalizedStrings:
    """Validate a parsed strings file for language ``code``; returns it or raises ``StringsError``."""
    if not isinstance(data, dict):
        raise StringsError(f"{code}: the file must hold a JSON object")
    if data.get("language") != code:
        raise StringsError(f"{code}: 'language' must be {code!r}")
    if data.get("review_status") != MACHINE_DRAFT:
        raise StringsError(f"{code}: 'review_status' must be {MACHINE_DRAFT!r}; human review is never claimed here")
    if data.get("source_sha256") != english_digest():
        raise StringsError(f"{code}: stale; the English strings changed since this file was translated")
    values = data.get("strings")
    if not isinstance(values, dict):
        raise StringsError(f"{code}: 'strings' must be an object")
    missing, extra = set(KEYS) - set(values), set(values) - set(KEYS)
    if missing or extra:
        raise StringsError(f"{code}: missing keys {sorted(missing)}, unknown keys {sorted(extra)}")
    for key in KEYS:
        value = values[key]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise StringsError(f"{code}.{key}: must be a non-empty string without surrounding whitespace")
        if len(value) > MAX_STRING_CHARS:
            raise StringsError(f"{code}.{key}: longer than {MAX_STRING_CHARS} characters")
        if any(unicodedata.category(ch) in {"Cc", "Cf", "Cs", "Co", "Cn"} for ch in value):
            raise StringsError(f"{code}.{key}: control or invisible characters")
        if _FORBIDDEN.search(value):
            raise StringsError(f"{code}.{key}: HTML, URL, link, code fence or angle bracket")
        if placeholders(value) != placeholders(ENGLISH[key]):
            raise StringsError(f"{code}.{key}: placeholders differ from English")
        if numeric_tokens(value) != numeric_tokens(ENGLISH[key]):
            raise StringsError(f"{code}.{key}: numbers differ from English")
    return LocalizedStrings(code, MACHINE_DRAFT, {key: values[key] for key in KEYS})


@lru_cache(maxsize=None)
def _load(code: str) -> LocalizedStrings:
    if code == SOURCE_LANGUAGE:
        return LocalizedStrings(code, SOURCE_STATUS, dict(ENGLISH))
    path = source_path("i18n", "strings", f"{code}.json")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StringsError(f"{code}: cannot read the strings file ({type(error).__name__})") from error
    return validate_strings(code, data)


def load_strings(language: object) -> LocalizedStrings:
    """The strings of ``language``. An unknown language yields the English strings with ``fallback=True``."""
    code = normalize_code(language)
    if code is None:
        english = _load(DEFAULT_LANGUAGE)
        return LocalizedStrings(english.code, english.review_status, english.strings, fallback=True)
    return _load(code)


def all_strings() -> dict[str, LocalizedStrings]:
    """Every registered language, validated (used by tests and by the start-up self-check)."""
    return {code: _load(code) for code in LANGUAGES}
