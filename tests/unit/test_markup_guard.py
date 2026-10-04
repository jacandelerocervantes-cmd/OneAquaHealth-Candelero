"""The markup guard of ``guard_output`` flags ANY tag-like text and every markdown link form, and leaves ordinary scientific
text alone (security audit F7). The translation checks reuse the same guard, so they are pinned here too."""
import pytest
from hypothesis import given
from hypothesis import strategies as st

from oah.explain.safety import guard_output
from oah.i18n.strings import _FORBIDDEN
from oah.i18n.translate_check import check_translation


def flags(text: str) -> tuple[str, ...]:
    return guard_output(text, "describe", ())


# --- tags the old allow-list let through ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "<details open ontoggle=alert(1)>x</details>",
        "<button onclick=x()>Click</button>",
        "<font color=red>x</font>",
        "<center>x</center>",
        "<video src=x onerror=y>",
        "<audio controls>",
        "<math><mi>x</mi></math>",
        "<template><script>1</script></template>",
        "<marquee>x</marquee>",
        "<custom-element>x</custom-element>",
        "<Œuvre>x</Œuvre>",  # any letter, not only ASCII
        "closing only: </p>",
        "closing only: </anything>",
        "<!-- a comment -->",
        "<!DOCTYPE html>",
        "<?xml version='1.0'?>",
        "a<b",  # a "<" directly before a letter opens a tag
        "text <https://example.org> text",
        "text <mailto:someone@example.org> text",
        "＜script＞",  # the fullwidth form folds to "<script>"
    ],
)
def test_any_tag_like_text_is_flagged(text):
    assert "contains-html" in flags(text), text


@pytest.mark.parametrize(
    "text",
    [
        "[text](https://example.org)",
        "[text](javascript:alert(1))",
        "[text](/relative/path)",
        "[text]()",
        "![alt](x.png)",
        "![alt][logo]",
        "![alt]",
        "[text][ref]",
        "[text] [ref]\n\n[ref]: https://example.org",
        "intro\n[ref]: https://example.org/path\nmore",
        "   [ref]:   target",
        "[1][2]",
        "［text］（https://example.org）",  # fullwidth brackets fold to a link
    ],
)
def test_every_markdown_link_or_reference_form_is_flagged(text):
    assert "contains-markdown-link" in flags(text), text


# --- ordinary scientific text is not touched -------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "Nitrate is below <5 mg/L at this site.",
        "The value was <0.5 mg/L (below the quantification limit).",
        "x < y and y <= z, so x < z.",
        "If pH < 6.5 or pH > 9.5 the range is exceeded.",
        "Ammonium 0.1 mg/L < limit 0.5 mg/L.",
        "n < 3 samples, so the period is flagged.",
        "A -> B and B => C are not markup.",
        "Values 1 < 2 < 3.",
        "The result was <1 (censored).",
        "Concentrations <= 10 and >= 2 were kept.",
        "See table [1] and note [mg/L] for the units.",
        "The ratio [0.5] is shown in brackets.",
        "Parameter list (nitrate, nitrite) and range [6.5, 9.5].",
        "Sample IDs [A-12] and [B-7] were used.",
    ],
)
def test_ordinary_scientific_text_is_not_flagged(text):
    assert flags(text) == (), text


@given(st.text(alphabet=st.sampled_from(list("abc ,.;:()0123456789mgL/%-=+")), max_size=60))
def test_text_without_angle_or_square_brackets_never_triggers_the_markup_flags(text):
    assert "contains-html" not in flags(text) and "contains-markdown-link" not in flags(text)


@given(st.text(alphabet=st.sampled_from(list("abcxyz")), min_size=1, max_size=8), st.text(max_size=20))
def test_a_less_than_sign_before_a_letter_is_always_flagged(word, tail):
    assert "contains-html" in flags(f"{tail} <{word} {tail}")


@given(st.sampled_from(["0", "1", "5", "9"]), st.text(alphabet=st.sampled_from(list("0123456789. mgL/")), max_size=12))
def test_a_less_than_sign_before_a_digit_or_a_space_is_never_flagged(digit, tail):
    assert "contains-html" not in flags(f"below <{digit}{tail}")
    assert "contains-html" not in flags(f"x < {digit}{tail}")


# --- the checks that reuse the guard stay consistent --------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("translation", "reason"),
    [
        ("Texto <details>oculto</details> aquí.", "contains-html"),
        ("Texto <button>x</button> aquí.", "contains-html"),
        ("Texto [enlace][ref] aquí.", "contains-markdown-link"),
        ("Texto ![imagen] aquí.", "contains-markdown-link"),
    ],
)
def test_the_translation_checks_reject_the_same_forms(translation, reason):
    result = check_translation("Text with no markup here.", translation)
    assert reason in result.reasons and not result.ok


def test_the_translation_checks_accept_scientific_less_than():
    result = check_translation("Nitrate is below <5 mg/L here.", "El nitrato está por debajo de <5 mg/L aquí.")
    assert result.ok, result.reasons


@pytest.mark.parametrize("value", ["<details>", "x</p>", "[a][b]", "![x]", "see [t](u)", "<!--", "<?php"])
def test_the_fixed_strings_validator_forbids_the_same_constructs(value):
    assert _FORBIDDEN.search(value), value
