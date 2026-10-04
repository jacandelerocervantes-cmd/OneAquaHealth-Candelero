"""Settings of the answer-language package: OAH_TRANSLATION_MODEL, OAH_TRANSLATION_TIMEOUT_SECONDS, OAH_DEFAULT_LANGUAGE."""
import pytest

from oah import config


def test_defaults():
    settings = config.load_settings({})
    assert settings.default_language == "en"
    assert settings.translation_timeout_seconds == 30.0
    assert settings.translation_model == "" and settings.translation_model_id == settings.llm_model == config.DEFAULT_LLM_MODEL


def test_the_translation_model_defaults_to_the_explanation_model_and_follows_it():
    assert config.load_settings({"OAH_LLM_MODEL": "model-x"}).translation_model_id == "model-x"
    both = config.load_settings({"OAH_LLM_MODEL": "model-x", "OAH_TRANSLATION_MODEL": "model-y"})
    assert both.translation_model_id == "model-y" and both.llm_model == "model-x"
    assert config.load_settings({"OAH_TRANSLATION_MODEL": "   "}).translation_model_id == config.DEFAULT_LLM_MODEL


@pytest.mark.parametrize("bad", ["bad model", "m;rm", "-lead", "m/../x", "x" * 101, "m\x00n"])
def test_a_malformed_translation_model_is_refused(bad):
    with pytest.raises(ValueError, match="OAH_TRANSLATION_MODEL"):
        config.load_settings({"OAH_TRANSLATION_MODEL": bad})


def test_the_timeout_is_validated_and_has_a_ceiling():
    assert config.load_settings({"OAH_TRANSLATION_TIMEOUT_SECONDS": "12.5"}).translation_timeout_seconds == 12.5
    assert config.load_settings({"OAH_TRANSLATION_TIMEOUT_SECONDS": "9999"}).translation_timeout_seconds == 60.0
    for bad in ("0", "-3", "soon"):
        with pytest.raises(ValueError, match="OAH_TRANSLATION_TIMEOUT_SECONDS"):
            config.load_settings({"OAH_TRANSLATION_TIMEOUT_SECONDS": bad})


def test_the_default_language_is_validated_and_normalised():
    assert config.load_settings({"OAH_DEFAULT_LANGUAGE": "ES"}).default_language == "es-MX"
    assert config.load_settings({"OAH_DEFAULT_LANGUAGE": " el "}).default_language == "el"
    assert config.load_settings({"OAH_DEFAULT_LANGUAGE": ""}).default_language == "en"
    for bad in ("xx", "pt-BR", "Greek"):
        with pytest.raises(ValueError, match="OAH_DEFAULT_LANGUAGE"):
            config.load_settings({"OAH_DEFAULT_LANGUAGE": bad})


def test_the_timeout_ceiling_matches_the_translator():
    from oah.i18n.translator import DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS

    assert config.TRANSLATION_TIMEOUT_CEILING_SECONDS == MAX_TIMEOUT_SECONDS
    assert config.DEFAULT_TRANSLATION_TIMEOUT_SECONDS == DEFAULT_TIMEOUT_SECONDS


def test_settings_repr_still_hides_secrets():
    text = repr(config.load_settings({"ANTHROPIC_API_KEY": "sk-ant-secret", "OAH_API_KEY": "k-secret"}))
    assert "sk-ant-secret" not in text and "k-secret" not in text
