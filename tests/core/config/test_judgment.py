"""Credential gating and the single persisted LLM/Jev operator selection."""

from pathlib import Path

import pytest
from core import config
from core.config import Settings, explain
from core.config.judgment import configure_judgment, judgment_status, resolve_judgment_route
from pydantic import SecretStr


@pytest.fixture
def judgment_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(tmp_path / "config.toml"))
    for name in (
        "GEODE_JUDGMENT_ENGINE",
        "GEODE_JEV_PROVIDER",
        "TYPESAFE_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    for field in ("GLOBAL_ENV_FILE", "PROJECT_ENV_FILE", "PROJECT_CONFIG_PATH"):
        monkeypatch.setattr(explain, field, tmp_path / field)
    settings = Settings(_env_file=None, typesafe_api_key="", openrouter_api_key="")
    monkeypatch.setitem(config.__dict__, "settings", settings)
    return settings


def test_key_does_not_enable_jev_and_missing_key_retains_llm(judgment_config: Settings) -> None:
    judgment_config.typesafe_api_key = SecretStr("test-typesafe-credential")
    assert resolve_judgment_route(judgment_config) is None
    judgment_config.judgment_engine = "jev"
    assert resolve_judgment_route(judgment_config)[0] == "typesafe"
    judgment_config.typesafe_api_key = SecretStr("")
    assert judgment_status()["effective_engine"] == "llm"
    assert judgment_status()["reason"] == "missing_jev_key"
    with pytest.raises(ValueError, match="requires"):
        configure_judgment("jev")


def test_provider_preference_and_secret_free_status(judgment_config: Settings) -> None:
    judgment_config.judgment_engine = "jev"
    judgment_config.typesafe_api_key = SecretStr("test-typesafe-credential")
    judgment_config.openrouter_api_key = "test-openrouter-credential"
    assert resolve_judgment_route(judgment_config)[0] == "typesafe"
    judgment_config.jev_provider = "openrouter"
    assert resolve_judgment_route(judgment_config)[0] == "openrouter"
    assert "credential" not in str(judgment_status())
    judgment_config.openrouter_api_key = ""
    assert resolve_judgment_route(judgment_config) is None


def test_persist_switch_without_changing_root_or_effort(
    judgment_config: Settings, tmp_path: Path
) -> None:
    import tomllib

    judgment_config.typesafe_api_key = SecretStr("test-typesafe-credential")
    root = judgment_config.model
    effort = judgment_config.agentic_effort
    result = configure_judgment("jev", provider="typesafe")
    assert result["effective_engine"] == "jev"
    saved = tomllib.loads((tmp_path / "config.toml").read_text())
    assert saved == {"judgment": {"engine": "jev", "provider": "typesafe"}}
    assert judgment_config.model == root
    assert judgment_config.agentic_effort == effort
    assert configure_judgment("llm")["effective_engine"] == "llm"


def test_masking_and_failed_write_do_not_change_memory(
    judgment_config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.config.toml_edit as writer

    judgment_config.typesafe_api_key = SecretStr("test-typesafe-credential")
    monkeypatch.setenv("GEODE_JUDGMENT_ENGINE", "llm")
    with pytest.raises(ValueError, match=r"controlled by os\.environ"):
        configure_judgment("jev")
    monkeypatch.delenv("GEODE_JUDGMENT_ENGINE")

    def failed_write(*args: object, **kwargs: object) -> None:
        raise OSError("read-only destination")

    monkeypatch.setattr(writer, "persist_toml_section", failed_write)
    with pytest.raises(OSError):
        configure_judgment("jev")
    assert judgment_config.judgment_engine == "llm"


def test_cli_and_natural_language_share_selection(judgment_config: Settings) -> None:
    from core.cli.commands.judgment import cmd_judgment
    from core.cli.tool_handlers.system import _build_system_handlers

    judgment_config.typesafe_api_key = SecretStr("test-typesafe-credential")
    assert cmd_judgment("typesafe", interactive=False)["effective_engine"] == "jev"
    handlers = dict(_build_system_handlers(None, False, None))
    result = handlers["switch_model"](model_hint="llm", role="judgment")
    assert result["action"] == "judgment"
    assert result["effective_engine"] == "llm"
    assert cmd_judgment("invalid", interactive=False)["status"] == "error"
