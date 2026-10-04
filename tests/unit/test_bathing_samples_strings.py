"""The four fixed strings of the bathing-water SAMPLES answers, in English and in the 25 machine-drafted translations.

The generic checks (digest, placeholders, numbers, no markup) are in ``test_i18n_strings``; these tests pin what is specific to
the new notices: they exist everywhere, keep the unit's number, never call a value safe or unsafe, and are never English text
copied into another language by mistake.
"""

from __future__ import annotations

import pytest

from oah.chat.prompts import CHAT_LEAK_CHECK_PARTS, CHAT_ROLE_PROMPT
from oah.explain.safety import guard_output
from oah.i18n.languages import LANGUAGES
from oah.i18n.strings import ENGLISH, all_strings, english_digest, load_strings
from oah.i18n.translate_check import numeric_tokens

NEW_KEYS = ("bathing_samples_notice", "bathing_no_threshold_notice", "bathing_flagged_values_note", "bathing_samples_change_notice")


def test_the_english_source_has_the_four_notices_and_they_make_no_safety_judgement():
    for key in NEW_KEYS:
        assert key in ENGLISH and ENGLISH[key].strip() and len(ENGLISH[key]) <= 600
        lowered = ENGLISH[key].lower()
        assert " safe" not in lowered and "unsafe" not in lowered, key  # no wording that could be quoted as a verdict
    assert "colony-forming units per 100 ml" in ENGLISH["bathing_samples_notice"] and "not a classification" in ENGLISH["bathing_samples_notice"]
    assert "No threshold or limit is applied" in ENGLISH["bathing_no_threshold_notice"] and "competent authority" in ENGLISH["bathing_no_threshold_notice"]
    assert "below the limit of detection" in ENGLISH["bathing_flagged_values_note"] and "Confirmed high values are included" in ENGLISH["bathing_flagged_values_note"]
    assert "No significance is tested" in ENGLISH["bathing_samples_change_notice"] and "no limit crossing" in ENGLISH["bathing_samples_change_notice"]


def test_every_language_has_the_four_notices_validated_and_machine_drafted():
    loaded = all_strings()
    assert len(loaded) == 26
    for code, strings in loaded.items():
        for key in NEW_KEYS:
            assert strings.strings[key].strip(), (code, key)
        if code != "en":
            assert strings.review_status == "machine-draft"


@pytest.mark.parametrize("code", [code for code in LANGUAGES if code != "en"])
def test_a_translation_keeps_the_unit_number_and_adds_no_markup_or_other_numbers(code: str):
    strings = load_strings(code)
    for key in NEW_KEYS:
        text = strings.strings[key]
        assert numeric_tokens(text) == numeric_tokens(ENGLISH[key]), (code, key)
        assert text != ENGLISH[key], (code, key)  # a translation, not the English text under another name
        assert "<" not in text and ">" not in text and "http" not in text.lower(), (code, key)
    assert "100" in strings.strings["bathing_samples_notice"]


def test_every_translation_file_carries_the_current_english_digest():
    import json

    from oah.paths import source_path

    for code in LANGUAGES:
        if code == "en":
            continue
        data = json.loads(source_path("i18n", "strings", f"{code}.json").read_text(encoding="utf-8"))
        assert data["source_sha256"] == english_digest() and data["review_status"] == "machine-draft", code
        assert set(NEW_KEYS) <= set(data["strings"]), code


def test_a_correct_refusal_is_not_taken_for_a_leak_but_the_role_prompt_still_is():
    refusal = "I cannot make a health or regulatory determination; please ask the competent authority or an accredited laboratory."
    assert guard_output(refusal, "describe", CHAT_LEAK_CHECK_PARTS) == ()
    assert "leaks-instructions" in guard_output(CHAT_ROLE_PROMPT[:400], "describe", CHAT_LEAK_CHECK_PARTS)
