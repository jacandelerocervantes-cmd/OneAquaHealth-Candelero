"""Registry of the answer languages (docs/language_support.md).

The registry lists the 24 official EU languages (Spanish is offered as two variants, es-MX and es-ES) plus Norwegian
Bokmal (Norway is covered by the data although it is an EEA, not an EU, country). English is the source language:
every answer is produced in English first and, when another language is requested, translated by a second,
constrained model call and verified (``oah.i18n.translator``). So every language except English has the status
``translated-by-model``.

Codes are BCP-47 language tags as written here. The language code ``el`` (Greek) is NOT the country code ``EL``
that the EU institutions use for Greece (the EEA Waterbase file uses ``EL``; this project's country parameter uses
``GR``): a ``language`` value is always parsed against this registry only, case-insensitively, so ``EL``, ``el``
and ``Greek`` are never confused with a country selector (``Greek`` is rejected: only codes are accepted).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

DEFAULT_LANGUAGE = "en"
SOURCE_LANGUAGE = "en"
MAX_CODE_CHARS = 12

LanguageStatus = Literal["source", "translated-by-model"]
Tier = Literal[1, 2]


class UnsupportedLanguageError(ValueError):
    """The requested language code is not in the registry. ``supported`` lists the accepted codes."""

    def __init__(self, value: object, supported: tuple[str, ...]) -> None:
        super().__init__(f"Unsupported language {str(value)[:20]!r}; supported: {', '.join(supported)}.")
        self.supported = supported


@dataclass(frozen=True)
class Language:
    code: str  # BCP-47 tag as listed, for example "es-MX"
    name: str  # English name
    endonym: str  # name in the language itself
    script: str
    status: LanguageStatus
    tier: Tier  # 1: a denylist hook exists and priority review is planned; 2: the rest
    family: str  # primary language subtag; Spanish variants share "es"
    style_note: str = ""  # extra instruction for the translation prompt (English), empty for most languages
    direction: Literal["ltr", "rtl"] = "ltr"  # all languages here are left to right


_ES_COMMON = (
    "Use international numerals exactly as in the source (decimal point, never a decimal comma). "
)


def _lang(code: str, name: str, endonym: str, script: str = "Latin", tier: Tier = 2, style: str = "") -> Language:
    family = code.split("-")[0]
    status: LanguageStatus = "source" if code == SOURCE_LANGUAGE else "translated-by-model"
    return Language(code, name, endonym, script, status, tier, family, style)


_LANGUAGES: tuple[Language, ...] = (
    _lang("bg", "Bulgarian", "Български", "Cyrillic"),
    _lang("hr", "Croatian", "Hrvatski"),
    _lang("cs", "Czech", "Čeština"),
    _lang("da", "Danish", "Dansk"),
    _lang("nl", "Dutch", "Nederlands"),
    _lang("en", "English", "English", tier=1),
    _lang("et", "Estonian", "Eesti"),
    _lang("fi", "Finnish", "Suomi"),
    _lang("fr", "French", "Français", tier=1),
    _lang("de", "German", "Deutsch", tier=1),
    _lang("el", "Greek", "Ελληνικά", "Greek", tier=1),
    _lang("hu", "Hungarian", "Magyar"),
    _lang("ga", "Irish", "Gaeilge"),
    _lang("it", "Italian", "Italiano", tier=1),
    _lang("lv", "Latvian", "Latviešu"),
    _lang("lt", "Lithuanian", "Lietuvių"),
    _lang("mt", "Maltese", "Malti"),
    _lang("nb", "Norwegian Bokmål", "Norsk bokmål", tier=1),
    _lang("pl", "Polish", "Polski"),
    _lang("pt", "Portuguese", "Português", tier=1),
    _lang("ro", "Romanian", "Română"),
    _lang("sk", "Slovak", "Slovenčina"),
    _lang("sl", "Slovenian", "Slovenščina"),
    _lang(
        "es-MX", "Spanish (Mexico)", "Español (México)", tier=1,
        style=(
            "Write Mexican Spanish (es-MX): Mexican vocabulary and the form 'usted' where a form of address is "
            "needed. " + _ES_COMMON
        ),
    ),
    _lang(
        "es-ES", "Spanish (Spain)", "Español (España)", tier=1,
        style=("Write peninsular Spanish (es-ES). " + _ES_COMMON),
    ),
    _lang("sv", "Swedish", "Svenska"),
)

LANGUAGES: dict[str, Language] = {language.code: language for language in _LANGUAGES}

# Inputs accepted besides the exact codes (case-insensitive, underscore or hyphen). A bare "es" is the Mexican
# variant (maintainer decision, 2026-10-02); "no" is the macrolanguage code people type for Bokmal.
ALIASES: dict[str, str] = {
    "es": "es-MX",
    "no": "nb",
    "nb-no": "nb",
    "en-gb": "en",
    "en-us": "en",
    "pt-pt": "pt",
    "el-gr": "el",
    "fr-fr": "fr",
    "de-de": "de",
    "it-it": "it",
}

_SHAPE = re.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,4})?$")
_LOOKUP: dict[str, str] = {code.lower(): code for code in LANGUAGES}
_LOOKUP.update(ALIASES)


def supported_codes() -> tuple[str, ...]:
    """The accepted language codes, in registry order (alphabetical by English name, English included)."""
    return tuple(LANGUAGES)


def normalize_code(value: object) -> str | None:
    """The canonical code for ``value`` (case, underscore and the documented aliases normalised), else ``None``."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > MAX_CODE_CHARS or not _SHAPE.fullmatch(text):
        return None
    return _LOOKUP.get(text.replace("_", "-").lower())


def parse_language(value: object) -> Language:
    """The registry entry for ``value``; raises ``UnsupportedLanguageError`` (with the supported codes) otherwise."""
    code = normalize_code(value)
    if code is None:
        raise UnsupportedLanguageError(value, supported_codes())
    return LANGUAGES[code]


def is_supported(value: object) -> bool:
    return normalize_code(value) is not None


def language_listing() -> list[dict[str, str]]:
    """Rows for ``GET /languages``: code, English name, endonym, status."""
    return [
        {"code": language.code, "name": language.name, "endonym": language.endonym, "status": language.status}
        for language in LANGUAGES.values()
    ]
