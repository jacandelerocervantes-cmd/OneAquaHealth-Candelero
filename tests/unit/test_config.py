"""Configuration must be explicit, portable, and side-effect free on import."""

from __future__ import annotations

from oah import config
from oah.paths import default_data_dir


def test_settings_uses_user_cache_when_data_dir_is_unset(monkeypatch) -> None:
    monkeypatch.setattr(config, "_dotenv_values", lambda: {"OAH_SANDBOX_URL": "https://dotenv.test"})
    settings = config.load_settings({"OAH_SANDBOX_URL": "https://example.test/fhir/"})
    assert settings.data_dir == default_data_dir()
    assert settings.sandbox_url == "https://example.test/fhir"
    assert settings.sources_root is None


def test_environment_values_override_dotenv_hermetically(monkeypatch) -> None:
    monkeypatch.setattr(
        config,
        "_dotenv_values",
        lambda: {
            "OAH_SANDBOX_URL": "https://dotenv.test/fhir",
            "OAH_DATA_DIR": "C" + ":" + "\\" + "dotenv-data",
        },
    )
    environment = {
        "OAH_SANDBOX_URL": "https://environment.test/fhir/",
        "OAH_DATA_DIR": "C" + ":" + "\\" + "environment-data",
    }
    settings = config.load_settings(environment)
    assert settings.sandbox_url == "https://environment.test/fhir"
    assert settings.data_dir.name == "environment-data"

def test_settings_uses_public_sandbox_default(monkeypatch) -> None:
    monkeypatch.setattr(config, "_dotenv_values", lambda: {})
    assert config.load_settings({}).sandbox_url == config.DEFAULT_SANDBOX_URL


def test_settings_defaults_llm_model_and_leaves_api_key_unset(monkeypatch) -> None:
    monkeypatch.setattr(config, "_dotenv_values", lambda: {})
    settings = config.load_settings({})
    assert settings.llm_model == config.DEFAULT_LLM_MODEL
    assert settings.anthropic_api_key is None


def test_settings_reads_llm_model_override_and_api_key(monkeypatch) -> None:
    monkeypatch.setattr(config, "_dotenv_values", lambda: {})
    settings = config.load_settings(
        {"OAH_LLM_MODEL": "claude-sonnet-5", "ANTHROPIC_API_KEY": "sk-ant-test-not-real"}
    )
    assert settings.llm_model == "claude-sonnet-5"
    assert settings.anthropic_api_key == "sk-ant-test-not-real"
