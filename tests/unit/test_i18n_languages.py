"""The language registry and its input parsing (docs/language_support.md)."""
import pytest

from oah.i18n import languages as lang

EU_OFFICIAL = {
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu", "ga", "it", "lv", "lt", "mt", "pl",
    "pt", "ro", "sk", "sl", "es", "sv",
}


def test_registry_covers_the_24_eu_languages_plus_bokmal_with_two_spanish_variants():
    families = {entry.family for entry in lang.LANGUAGES.values()}
    assert families == EU_OFFICIAL | {"nb"}
    assert len(lang.LANGUAGES) == 26  # 23 non-Spanish EU languages + es-MX + es-ES + nb
    assert {"es-MX", "es-ES"} <= set(lang.LANGUAGES) and "es" not in lang.LANGUAGES


def test_every_entry_is_complete_and_only_english_is_the_source():
    for code, entry in lang.LANGUAGES.items():
        assert entry.code == code
        assert entry.name.strip() and entry.endonym.strip() and entry.script in {"Latin", "Cyrillic", "Greek"}
        assert entry.direction == "ltr"
        assert entry.tier in (1, 2)
        assert entry.status == ("source" if code == "en" else "translated-by-model")
    assert lang.LANGUAGES["bg"].script == "Cyrillic" and lang.LANGUAGES["el"].script == "Greek"


def test_tier_one_matches_the_planned_rollout():
    tier_one = {code for code, entry in lang.LANGUAGES.items() if entry.tier == 1}
    assert tier_one == {"en", "es-MX", "es-ES", "it", "el", "nb", "fr", "de", "pt"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("en", "en"), ("EN", "en"), (" fr ", "fr"), ("en\n", "en"), ("es-MX", "es-MX"), ("es_MX", "es-MX"), ("ES-mx", "es-MX"),
        ("es-es", "es-ES"), ("es_ES", "es-ES"), ("es", "es-MX"), ("ES", "es-MX"),
        ("el", "el"), ("EL", "el"), ("el-GR", "el"), ("no", "nb"), ("nb", "nb"), ("nb_NO", "nb"),
        ("en-GB", "en"), ("pt-PT", "pt"), ("de-DE", "de"),
    ],
)
def test_normalisation_of_case_underscores_and_documented_aliases(value, expected):
    assert lang.normalize_code(value) == expected
    assert lang.parse_language(value).code == expected


def test_el_as_a_language_is_greek_and_never_a_country_code():
    # "EL" is the EU country code for Greece; as a language value it can only mean Greek (el), and a country
    # selector never goes through this parser (the project's country code for Greece is GR).
    assert lang.parse_language("EL").name == "Greek"
    assert lang.normalize_code("GR") is None  # the country code of Greece is not a language
    assert lang.normalize_code("Greek") is None


@pytest.mark.parametrize(
    "value",
    [
        None, 5, b"en", [], "", "  ", "x", "english", "Greek", "gr", "xx", "nn", "pt-BR", "es-419", "es-MX-x", "en;fr",
        "en,fr", "es MX", "../en", "en\x00", "e\nn", "e" * 40, "еn", "ｅｎ", "zz-ZZ", "es--MX",
    ],
)
def test_unknown_or_hostile_codes_are_rejected(value):
    assert lang.normalize_code(value) is None
    assert lang.is_supported(value) is False
    with pytest.raises(lang.UnsupportedLanguageError) as info:
        lang.parse_language(value)
    assert info.value.supported == lang.supported_codes()
    assert "es-MX" in str(info.value) and len(str(info.value)) < 400


def test_the_error_message_truncates_hostile_input():
    with pytest.raises(lang.UnsupportedLanguageError) as info:
        lang.parse_language("<script>" * 50)
    assert "<script><script><script>" not in str(info.value)


def test_default_and_source_language_are_english():
    assert lang.DEFAULT_LANGUAGE == lang.SOURCE_LANGUAGE == "en"
    assert lang.parse_language(lang.DEFAULT_LANGUAGE).status == "source"


def test_spanish_variants_differ_in_prompt_style_but_share_a_family():
    mexico, spain = lang.LANGUAGES["es-MX"], lang.LANGUAGES["es-ES"]
    assert mexico.family == spain.family == "es"
    assert "Mexican" in mexico.style_note and "decimal point" in mexico.style_note
    assert "peninsular" in spain.style_note and "decimal point" in spain.style_note


def test_listing_has_the_public_fields_only():
    rows = lang.language_listing()
    assert len(rows) == 26 and rows[0].keys() == {"code", "name", "endonym", "status"}
    assert {row["status"] for row in rows} == {"source", "translated-by-model"}
