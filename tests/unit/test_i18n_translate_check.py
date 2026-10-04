"""Language-neutral verification of translations, including hostile cases and properties."""
import random
import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from oah.i18n import translate_check as tc
from oah.i18n.denylist import DENYLIST_FAMILIES, DenylistError, denylist_patterns, has_denylist

SOURCE = "The nitrate value is 3.5 mg/L at Loc-Almyros in 2021, with a reference limit of 50 mg/L."
GOOD = "El valor de nitrato es 3.5 mg/L en Loc-Almyros en 2021, con un límite de referencia de 50 mg/L."


def reasons(translation: str, source: str = SOURCE, **kwargs) -> tuple[str, ...]:
    return tc.check_translation(source, translation, **kwargs).reasons


def test_a_faithful_translation_passes():
    result = tc.check_translation(SOURCE, GOOD)
    assert result.ok and result.reasons == ()


def test_a_translation_identical_to_the_source_is_accepted():
    assert tc.check_translation(SOURCE, SOURCE).ok
    assert tc.check_translation("pH 7.2", "pH 7.2").ok  # only codes and numbers


def test_numeric_tokens_keep_separators_and_ignore_other_scripts():
    assert tc.numeric_tokens("a 3.5 b 1,234.5 c 2021-05-14 d 7.") == {"3.5": 1, "1,234.5": 1, "2021": 1, "05": 1, "14": 1, "7": 1}
    assert tc.numeric_tokens("٣٫٥ ３") == {}  # Arabic-Indic and fullwidth digits are not ASCII tokens
    assert tc.numeric_tokens("5, 6") == {"5": 1, "6": 1}


def test_a_decimal_comma_is_rejected():
    assert "numeral-format-changed" in reasons(GOOD.replace("3.5", "3,5"))


def test_a_regrouped_thousands_separator_is_rejected():
    source = "There were 1,234 samples and 5.5 mg/L."
    assert not tc.check_translation(source, "Hubo 1 234 muestras y 5.5 mg/L.").ok
    assert not tc.check_translation(source, "Hubo 1.234 muestras y 5.5 mg/L.").ok
    assert "numeral-format-changed" in tc.check_translation(source, "Hubo 1.234 muestras y 5.5 mg/L.").reasons
    assert tc.check_translation(source, "Hubo 1,234 muestras y 5.5 mg/L.").ok


def test_an_added_number_is_rejected():
    result = reasons(GOOD + " Medido en 7 sitios.")
    assert "number-added" in result and "number-missing" not in result


def test_a_changed_number_is_both_added_and_missing():
    result = reasons(GOOD.replace("50 mg/L", "51 mg/L"))
    assert "number-added" in result and "number-missing" in result


def test_a_dropped_number_is_rejected():
    result = reasons(GOOD.replace(" en 2021", ""))
    assert "number-missing" in result and "number-added" not in result


def test_a_duplicate_number_is_counted_as_a_multiset():
    assert "number-missing" in reasons(GOOD.replace("de referencia de 50 mg/L", "de referencia"))
    assert "number-added" in reasons(GOOD + " 50")


def test_a_number_written_in_words_counts_as_dropped():
    assert "number-missing" in reasons("El valor de nitrato es tres punto cinco mg/L en Loc-Almyros en 2021, con un límite de 50 mg/L.")


@pytest.mark.parametrize(
    "digits",
    ["٢٠٢١", "۲۰۲۱", "２０２１", "२०२१", "๒๐๒๑"],
)
def test_digits_of_other_numeral_systems_are_rejected(digits):
    result = reasons(GOOD.replace("2021", digits))
    assert "non-ascii-numeral" in result and "number-missing" in result


def test_numerals_that_the_source_has_may_stay_but_new_ones_may_not():
    source = "The catchment is 5 km² wide."
    assert tc.check_translation(source, "La cuenca mide 5 km² de ancho.").ok
    assert "non-ascii-numeral" in tc.check_translation(source, "La cuenca mide 5 km de ancho.").reasons
    assert "non-ascii-numeral" in tc.check_translation(source, "La cuenca mide 5 km³ de ancho.").reasons
    assert "non-ascii-numeral" in tc.check_translation("There are 2 sites.", "Hay 2 sitios Ⅶ.").reasons  # roman numeral character
    assert "non-ascii-numeral" in tc.check_translation("There are 2 sites.", "Hay 2 sitios ½.").reasons


@pytest.mark.parametrize("char", ["​", "‌", "‍", "⁠", "﻿", "­", "‮", "⁦", "\x00", "\x1b", "\U000e0041"])
def test_invisible_and_control_characters_are_rejected(char):
    assert "invisible-characters" in reasons(GOOD.replace("mg/L", f"mg/{char}L", 1))
    assert tc.invisible_characters(f"a{char}b")


def test_ordinary_whitespace_is_allowed():
    assert tc.check_translation(SOURCE, GOOD.replace(", con", ",\ncon").replace("de nitrato", "de\tnitrato")).ok
    assert tc.invisible_characters("a b\nc\td") == ()


@pytest.mark.parametrize(
    ("addition", "flag"),
    [
        (" Ver https://example.org/x", "contains-url"),
        (" Ver www.example.org", "contains-url"),
        (" Ver javascript:alert(1)", "contains-url"),
        (" <b>negrita</b>", "contains-html"),
        (" <script>x</script>", "contains-html"),
        (" [aquí](http://x.y)", "contains-markdown-link"),
        (" ![img](x.png)", "contains-markdown-link"),
        ("\n```\ncode\n```", "contains-code-block"),
    ],
)
def test_forbidden_constructs_are_rejected(addition, flag):
    assert flag in reasons(GOOD + addition)


def test_the_english_claim_patterns_are_not_applied_to_a_translation():
    # They belong to the English text, which is guarded before translation; a translation is not judged by them.
    assert tc.forbidden_constructs("The water is potable.", "The water is potable.", ()) == []


def test_instruction_leak_is_detected_against_the_given_prompts():
    prompt = "You are a translation component of a water-data service and must keep every number as written"
    leak = "Hola. You are a translation component of a water-data service and must keep"
    assert "leaks-instructions" in reasons(GOOD + " " + leak, leak_sources=(prompt,))
    assert "leaks-instructions" not in reasons(GOOD, leak_sources=(prompt,))


def test_a_run_of_words_that_the_source_itself_contains_is_not_a_leak():
    source = SOURCE + " This is a reference value and not a legal limit."
    prompt = "Keep the meaning: this is a reference value and not a legal limit, or cannot be determined."
    translation = GOOD + " This is a reference value and not a legal limit."
    assert "leaks-instructions" not in reasons(translation, source=source, leak_sources=(prompt,))


def test_length_ratio_bounds():
    assert "too-short" in reasons("El valor es 3.5 mg/L 2021 50 50")
    assert "too-long" in reasons(GOOD + " " + "texto " * 100)
    assert tc.length_reasons("x" * 100, "y" * 40) == []
    assert tc.length_reasons("x" * 100, "y" * 39) == ["too-short"]
    assert tc.length_reasons("x" * 100, "y" * 300) == []
    assert tc.length_reasons("x" * 100, "y" * 301) == ["too-long"]
    assert tc.length_reasons("x", "y" * (tc.MAX_TRANSLATION_CHARS + 1)) == ["too-long"]
    assert tc.length_reasons("", "") == ["too-short"]  # an empty text is never a faithful translation


def test_empty_translation_is_rejected():
    for blank in ("", "   ", "\n\t"):
        assert tc.check_translation(SOURCE, blank).reasons == ("empty",)


def test_denylist_hook_is_applied_when_patterns_are_supplied():
    patterns = denylist_patterns("es")
    bad = GOOD + " El agua es potable."
    assert "denylist-term" in reasons(bad, denylist_patterns=patterns)
    assert "denylist-term" not in reasons(bad)  # no hook, no check


def test_reasons_are_unique_and_ordered():
    result = reasons("​" + GOOD.replace("3.5", "3,5") + " https://x.y", leak_sources=())
    assert len(result) == len(set(result))
    assert result[0] == "invisible-characters"


# --- denylist data -----------------------------------------------------------------------------------------------


def test_denylist_covers_the_tier_one_families_only():
    assert set(DENYLIST_FAMILIES) == {"es", "it", "el", "fr", "de", "pt", "nb"}
    assert all(has_denylist(family) for family in DENYLIST_FAMILIES) and not has_denylist("bg") and not has_denylist("en")
    assert denylist_patterns("bg") == ()


@pytest.mark.parametrize(
    ("family", "text"),
    [
        ("es", "El agua es potable."), ("es", "No es segura para beber."), ("es", "El agua está contaminada."),
        ("it", "L'acqua non è potabile."), ("it", "L'acqua è contaminata."), ("it", "Non è sicura da bere."),
        ("fr", "L'eau est potable."), ("fr", "L'eau est contaminée."), ("fr", "Elle est sûre pour boire."),
        ("de", "Das Wasser ist nicht trinkbar."), ("de", "Das Wasser ist giftig."), ("de", "Es ist sicher zum Trinken."),
        ("pt", "A água é potável."), ("pt", "A água está contaminada."), ("pt", "Segura para beber."),
        ("nb", "Vannet er ikke drikkbart."), ("nb", "Vannet er forurenset."), ("nb", "Det er trygt å drikke."),
        ("el", "Το νερό είναι μη πόσιμο."),
        ("el", "Το νερό είναι μολυσμένο."),
    ],
)
def test_denylist_catches_the_obvious_claim_words(family, text):
    assert any(pattern.search(text) for pattern in denylist_patterns(family)), text


@pytest.mark.parametrize(
    ("family", "text"),
    [
        ("es", "Esto no es una determinación de potabilidad."), ("it", "Non è una determinazione di potabilità."),
        ("fr", "Ce n'est pas une détermination de potabilité."), ("de", "Grenzwerte der Trinkwasserverordnung."),
        ("pt", "Valores de referência do consumo humano."), ("nb", "Referanseverdier for drikkevann."),
        ("el", "Τιμές αναφοράς για πόσιμο νερό."),
    ],
)
def test_denylist_does_not_reject_the_faithful_noun_or_drinking_water_references(family, text):
    assert not any(pattern.search(text) for pattern in denylist_patterns(family)), text


def test_spanish_variants_share_the_es_denylist():
    from oah.i18n.languages import LANGUAGES

    assert LANGUAGES["es-MX"].family == LANGUAGES["es-ES"].family == "es"


def test_denylist_files_are_validated(monkeypatch, tmp_path):
    import json

    from oah.i18n import denylist as dl

    def fake_path(*parts):
        return tmp_path / parts[-1]

    monkeypatch.setattr(dl, "source_path", fake_path)
    for bad in (
        {"language": "es", "best_effort": False, "patterns": ["x"]},
        {"language": "fr", "best_effort": True, "patterns": ["x"]},
        {"language": "es", "best_effort": True, "patterns": []},
        {"language": "es", "best_effort": True, "patterns": [""]},
        {"language": "es", "best_effort": True, "patterns": ["x" * 300]},
        {"language": "es", "best_effort": True, "patterns": [5]},
        ["not an object"],
    ):
        (tmp_path / "es.json").write_text(json.dumps(bad), encoding="utf-8")
        dl.denylist_patterns.cache_clear()
        with pytest.raises(DenylistError):
            dl.denylist_patterns("es")
    dl.denylist_patterns.cache_clear()


# --- properties --------------------------------------------------------------------------------------------------

_WORD = st.text(alphabet=st.characters(min_codepoint=0x61, max_codepoint=0x7a), min_size=1, max_size=8)
_NUMBER = st.one_of(
    st.integers(0, 10**6).map(str),
    st.tuples(st.integers(0, 999), st.integers(0, 999)).map(lambda pair: f"{pair[0]}.{pair[1]}"),
)
_PIECES = st.lists(st.one_of(_WORD, _NUMBER), min_size=1, max_size=25)


@settings(max_examples=150)
@given(st.text())
def test_property_a_text_never_differs_from_itself(text):
    assert tc.number_reasons(text, text) == []


@settings(max_examples=100)
@given(st.text())
def test_property_checking_arbitrary_text_never_raises(text):
    result = tc.check_translation(SOURCE, text)
    assert isinstance(result.ok, bool) and result.ok == (result.reasons == ())


@settings(max_examples=150)
@given(_PIECES, st.integers(0, 10**6))
def test_property_reordering_words_keeps_the_numeric_multiset(pieces, seed):
    shuffled = list(pieces)
    random.Random(seed).shuffle(shuffled)
    assert tc.number_reasons(" ".join(pieces), " ".join(shuffled)) == []


@settings(max_examples=150)
@given(_PIECES, _NUMBER)
def test_property_adding_a_number_is_always_detected(pieces, extra):
    source = " ".join(pieces)
    assert "number-added" in tc.number_reasons(source, f"{source} {extra}")
    assert "number-missing" in tc.number_reasons(f"{source} {extra}", source)


@settings(max_examples=150)
@given(st.lists(_WORD, min_size=0, max_size=6), st.integers(0, 999), st.integers(0, 999), st.lists(_WORD, min_size=0, max_size=6))
def test_property_a_decimal_comma_is_always_detected(before, whole, frac, after):
    source = " ".join([*before, f"{whole}.{frac}", *after])
    translation = " ".join([*before, f"{whole},{frac}", *after])
    assert "numeral-format-changed" in tc.number_reasons(source, translation)


@settings(max_examples=150)
@given(
    st.lists(_WORD, min_size=1, max_size=8),
    st.sampled_from(["​", "‌", "‍", "⁠", "﻿", "­", "‮", "⁦", "\x00", "\x07"]),
    st.integers(0, 10_000),
)
def test_property_an_inserted_invisible_character_is_always_rejected(words, char, position):
    text = " ".join(words)
    at = position % (len(text) + 1)
    assert "invisible-characters" in tc.check_translation(text, text[:at] + char + text[at:]).reasons


@settings(max_examples=150)
@given(st.integers(1, 10**9))
def test_property_foreign_digits_never_replace_ascii_digits(value):
    ascii_text = f"The value is {value} mg/L."
    for zero in (0x0660, 0x06F0, 0xFF10, 0x0966):
        foreign = "".join(chr(zero + int(ch)) for ch in str(value))
        result = tc.check_translation(ascii_text, f"El valor es {foreign} mg/L.")
        assert not result.ok and "number-missing" in result.reasons and "non-ascii-numeral" in result.reasons


@settings(max_examples=100)
@given(st.lists(_WORD, min_size=3, max_size=30))
def test_property_text_without_digits_has_no_number_reasons_and_keeps_the_ratio_check_meaningful(words):
    text = " ".join(words)
    assert tc.number_reasons(text, text) == []
    assert tc.length_reasons(text, text) == []
    assert not re.search(r"[0-9]", text)
