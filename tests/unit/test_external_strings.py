"""The fixed notices of the external context: present in all 25 translations, short enough for the chat sanitiser, honest."""
from __future__ import annotations

import re

import pytest

from oah.external import constants as c
from oah.external.service import NOTICE_KEYS, UNAVAILABLE_NOTICE_KEY
from oah.i18n import strings as s
from oah.i18n.languages import LANGUAGES, SOURCE_LANGUAGE
from oah.explain.safety import MAX_STRING_CHARS

EXTERNAL_KEYS = (
    "external_context_notice", "external_reanalysis_notice", "external_discharge_notice", "external_occurrence_notice",
    "external_licence_notice", "external_no_causation_notice", "external_unavailable_notice",
)
TRANSLATED = [code for code in LANGUAGES if code != SOURCE_LANGUAGE]


def test_every_notice_key_the_service_names_exists() -> None:
    used = {key for keys in NOTICE_KEYS.values() for key in keys} | {UNAVAILABLE_NOTICE_KEY}
    assert used == set(EXTERNAL_KEYS)
    assert set(EXTERNAL_KEYS) <= set(s.KEYS)


def test_english_notices_fit_the_chat_sanitiser_cut_and_state_the_rules() -> None:
    for key in EXTERNAL_KEYS:
        assert len(s.ENGLISH[key]) <= MAX_STRING_CHARS, key  # the chat sanitiser cuts longer strings at 200 characters
    text = {key: s.ENGLISH[key].lower() for key in EXTERNAL_KEYS}
    assert "not a measurement" in text["external_context_notice"] and "orientation" in text["external_context_notice"]
    assert "modelled" in text["external_reanalysis_notice"] and "not measurements" in text["external_reanalysis_notice"]
    assert "modelled" in text["external_discharge_notice"] and "not measured at a gauge" in text["external_discharge_notice"]
    assert "opportunistic" in text["external_occurrence_notice"] and "not monitoring" in text["external_occurrence_notice"]
    assert "absent" in text["external_occurrence_notice"] and "licence" in text["external_licence_notice"]
    assert "non-commercial" in text["external_licence_notice"]
    assert "context only" in text["external_no_causation_notice"] and "caused" in text["external_no_causation_notice"]
    assert "nothing was estimated" in text["external_unavailable_notice"]


@pytest.mark.parametrize("code", TRANSLATED)
def test_every_translation_has_every_notice_as_a_machine_draft(code: str) -> None:
    loaded = s.load_strings(code)
    assert loaded.review_status == "machine-draft"
    for key in EXTERNAL_KEYS:
        value = loaded.strings[key]
        assert value and value != s.ENGLISH[key], (code, key)  # translated, not copied
        assert not re.search(r"\d", value), (code, key)  # the notices carry no number
        assert "reviewed" not in value.lower()
        assert len(value) <= 600


def test_no_notice_says_safe_or_unsafe_or_a_health_claim() -> None:
    forbidden = re.compile(r"(?i)\b(?:safe|unsafe|potable|drinkable|contaminated|harmful|healthy|toxic)\b")
    for key in EXTERNAL_KEYS:
        assert not forbidden.search(s.ENGLISH[key]), key


def test_the_attribution_text_is_the_required_link_text_and_is_never_translated() -> None:
    assert c.OPEN_METEO_ATTRIBUTION == "Weather data by Open-Meteo.com"
    assert c.OPEN_METEO_URL == "https://open-meteo.com/"
    for code in TRANSLATED:
        assert all("Open-Meteo" not in value for value in s.load_strings(code).strings.values())  # it comes from the data, as written
    for provider in c.PROVIDERS:
        assert len(c.PROVIDER_INFO[provider].data_note) <= MAX_STRING_CHARS
        assert len(c.PROVIDER_INFO[provider].attribution) <= MAX_STRING_CHARS
        assert len(c.PROVIDER_INFO[provider].licence) <= MAX_STRING_CHARS
    assert c.PROVIDER_INFO[c.PROVIDER_DISCHARGE].attribution_verified is False
    assert c.PROVIDER_INFO[c.PROVIDER_GBIF].attribution_verified is False
    assert c.PROVIDER_INFO[c.PROVIDER_WEATHER].attribution_verified is True
