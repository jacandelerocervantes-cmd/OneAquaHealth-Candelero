"""``GET /languages``: the answer languages."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from oah.api.schemas import LanguageEntry, LanguagesResponse
from oah.config import load_settings
from oah.i18n.languages import LANGUAGES, SOURCE_LANGUAGE
from oah.i18n.localize import translation_checks_level
from oah.i18n.strings import load_strings

router = APIRouter()


@router.get("/languages", response_model=LanguagesResponse)
def languages() -> dict[str, Any]:
    """The answer languages: the 24 official EU languages (Spanish as es-MX and es-ES) and Norwegian Bokmal.

    Every language except English is a machine translation of the validated English answer (see docs/language_support.md).
    """
    entries = [
        LanguageEntry(
            code=language.code,
            name=language.name,
            endonym=language.endonym,
            status=language.status,
            script=language.script,
            direction=language.direction,
            tier=language.tier,
            fixed_strings_review_status="source" if language.code == SOURCE_LANGUAGE else "machine-draft",
            translation_checks=translation_checks_level(language.code),
        )
        for language in LANGUAGES.values()
    ]
    return {
        "default_language": load_settings().default_language,
        "source_language": SOURCE_LANGUAGE,
        "languages": entries,
        "note": load_strings(SOURCE_LANGUAGE).get("machine_translation_notice"),
    }
