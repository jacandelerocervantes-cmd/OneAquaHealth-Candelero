"""The fixed localised strings: strict loading, completeness and sync with the English text used by the API."""
import copy
import json

import pytest

from oah.i18n import strings as s
from oah.i18n.languages import LANGUAGES
from oah.paths import source_path


def _raw(code: str) -> dict:
    return json.loads(source_path("i18n", "strings", f"{code}.json").read_text(encoding="utf-8"))


def test_every_language_has_one_file_and_nothing_else_is_there():
    present = {path.stem for path in source_path("i18n", "strings").glob("*.json")}
    assert present == set(LANGUAGES) - {"en"}  # English is in code


def test_every_language_loads_with_every_key_and_the_same_placeholders():
    loaded = s.all_strings()
    assert set(loaded) == set(LANGUAGES)
    for code, entry in loaded.items():
        assert tuple(entry.strings) == s.KEYS
        for key in s.KEYS:
            assert entry.strings[key].strip()
            assert s.placeholders(entry.strings[key]) == s.placeholders(s.ENGLISH[key]), (code, key)


def test_files_are_labelled_machine_draft_and_never_human_reviewed():
    for code in LANGUAGES:
        if code == "en":
            assert s.load_strings("en").review_status == "source"
            continue
        raw = _raw(code)
        assert raw["review_status"] == "machine-draft" and raw["language"] == code
        assert "reviewed" not in json.dumps(raw).lower()  # no claim of human review in any file
        assert s.load_strings(code).review_status == "machine-draft"


def test_translations_are_actually_translated_not_copies_of_english():
    for code in LANGUAGES:
        if code == "en":
            continue
        values = s.load_strings(code).strings
        same = [key for key in s.KEYS if values[key] == s.ENGLISH[key]]
        assert len(same) <= 1, (code, same)  # at most a word that is identical across languages


def test_the_english_text_matches_what_the_api_uses_today():
    from oah.api.services import EXPLANATION_DISCLAIMER
    from oah.chat.prompts import BUDGET_EXCEEDED_ANSWER, NO_ANSWER_TEXT
    from oah.indices.regimes import INTERPRETATION_NOTICE

    assert s.ENGLISH["disclaimer"] == EXPLANATION_DISCLAIMER
    assert s.ENGLISH["interpretation_notice"] == INTERPRETATION_NOTICE
    assert s.ENGLISH["budget_exceeded"] == BUDGET_EXCEEDED_ANSWER
    assert s.ENGLISH["no_answer"] == NO_ANSWER_TEXT


def test_the_disclaimer_keeps_its_meaning_in_every_language_by_construction_of_the_english_digest():
    # Every file carries the digest of the English text it was translated from.
    assert {_raw(code)["source_sha256"] for code in LANGUAGES if code != "en"} == {s.english_digest()}


def test_mexican_and_peninsular_spanish_are_separate_files():
    mexico, spain = s.load_strings("es-MX"), s.load_strings("es-ES")
    assert mexico.code == "es-MX" and spain.code == "es-ES"
    assert mexico.strings != spain.strings
    assert "{language}" in mexico.strings["translation_fallback_notice"]
    assert "Consulte limit_basis" in mexico.strings["interpretation_notice"]


def test_unknown_language_falls_back_to_english_with_a_flag():
    fallback = s.load_strings("xx")
    assert fallback.fallback is True and fallback.code == "en" and fallback.strings == s.ENGLISH
    assert s.load_strings(None).fallback is True
    assert s.load_strings("fr").fallback is False and s.load_strings("en").fallback is False


def test_aliases_and_case_resolve_before_loading():
    assert s.load_strings("ES").code == "es-MX"
    assert s.load_strings("es_es").code == "es-ES"
    assert s.load_strings("EL").code == "el"


def test_get_formats_placeholders():
    text = s.load_strings("de").get("translation_fallback_notice", language="Deutsch")
    assert "Deutsch" in text and "{" not in text
    assert s.load_strings("en").get("not_available") == "Not available in this data."
    with pytest.raises(KeyError):
        s.load_strings("en").get("no_such_key")


@pytest.fixture
def good() -> dict:
    return copy.deepcopy(_raw("fr"))


def test_validate_accepts_a_good_file(good):
    assert s.validate_strings("fr", good).code == "fr"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(language="de"), "'language'"),
        (lambda d: d.update(review_status="human-reviewed"), "review_status"),
        (lambda d: d.pop("review_status"), "review_status"),
        (lambda d: d.update(source_sha256="0" * 64), "stale"),
        (lambda d: d.update(strings=[]), "'strings'"),
        (lambda d: d["strings"].pop("disclaimer"), "missing keys"),
        (lambda d: d["strings"].update(extra="x"), "unknown keys"),
        (lambda d: d["strings"].update(disclaimer=""), "non-empty"),
        (lambda d: d["strings"].update(disclaimer="   "), "non-empty"),
        (lambda d: d["strings"].update(disclaimer=" padded "), "non-empty"),
        (lambda d: d["strings"].update(disclaimer=5), "non-empty"),
        (lambda d: d["strings"].update(disclaimer="x" * 700), "longer"),
        (lambda d: d["strings"].update(disclaimer="a​b"), "invisible"),
        (lambda d: d["strings"].update(disclaimer="a\x00b"), "invisible"),
        (lambda d: d["strings"].update(disclaimer="see https://example.org now"), "HTML, URL"),
        (lambda d: d["strings"].update(disclaimer="see www.example.org now"), "HTML, URL"),
        (lambda d: d["strings"].update(disclaimer="a <b>bold</b> text"), "HTML, URL"),
        (lambda d: d["strings"].update(disclaimer="a [link](x) text"), "HTML, URL"),
        (lambda d: d["strings"].update(disclaimer="a ```code``` text"), "HTML, URL"),
        (lambda d: d["strings"].update(disclaimer="a > b"), "HTML, URL"),
        (lambda d: d["strings"].update(translation_fallback_notice="sans variable"), "placeholders"),
        (lambda d: d["strings"].update(translation_fallback_notice="{language} {other}"), "placeholders"),
        (lambda d: d["strings"].update(translation_fallback_notice="{language"), "placeholder"),
        (lambda d: d["strings"].update(bathing_water_classification_notice="Directive 2006/8/EC"), "numbers differ"),
        (lambda d: d["strings"].update(bathing_water_classification_notice="Directive 2006,7/EC"), "numbers differ"),
        (lambda d: d["strings"].update(bathing_water_classification_notice="Directive"), "numbers differ"),
    ],
)
def test_validate_rejects_malformed_files(good, mutate, message):
    mutate(good)
    with pytest.raises(s.StringsError, match=message):
        s.validate_strings("fr", good)


def test_validate_rejects_a_non_object():
    with pytest.raises(s.StringsError):
        s.validate_strings("fr", ["not", "an", "object"])


def test_placeholders_helper_rejects_positional_and_attribute_forms():
    assert s.placeholders("a {language} b") == frozenset({"language"})
    for bad in ("{0}", "{}", "{language.__class__}", "{a[0]}"):
        with pytest.raises(s.StringsError):
            s.placeholders(bad)


def test_a_missing_file_is_a_clear_error(monkeypatch):
    s._load.cache_clear()
    monkeypatch.setattr(s, "source_path", lambda *parts: source_path("i18n", "nowhere", *parts[2:]))
    try:
        with pytest.raises(s.StringsError, match="cannot read"):
            s.load_strings("fr")
    finally:
        s._load.cache_clear()
