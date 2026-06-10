"""C-2 env=secrets-only guards (2026-06-11).

Pins: model/effort/credential_source picks persist to config.toml ONLY
(no .env writes — hazards H3/H4/H6), stale env lines are cleaned up by
the writers, the credential_source toml rows are read back (H7 closed),
and API-key writes legitimately stay on the .env layer.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from core.config.env_io import remove_env, upsert_env


@pytest.fixture()
def cwd_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path / ".env"


def test_remove_env_deletes_line_and_process_env(
    cwd_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    upsert_env("GEODE_MODEL", "claude-sonnet-4-6")
    assert "GEODE_MODEL" in cwd_env.read_text()
    assert os.environ["GEODE_MODEL"] == "claude-sonnet-4-6"

    assert remove_env("GEODE_MODEL") is True
    assert "GEODE_MODEL" not in cwd_env.read_text()
    assert "GEODE_MODEL" not in os.environ
    assert remove_env("GEODE_MODEL") is False  # idempotent


def test_remove_env_keeps_other_lines(cwd_env: Path) -> None:
    upsert_env("ANTHROPIC_API_KEY", "sk-test")
    upsert_env("GEODE_MODEL", "x")
    remove_env("GEODE_MODEL")
    content = cwd_env.read_text()
    assert "ANTHROPIC_API_KEY=sk-test" in content
    assert "GEODE_MODEL" not in content


def test_model_picker_source_has_no_env_write() -> None:
    """Source pin — the picker's persistence block must not regrow the
    env write (config.toml is the only durable layer for model picks)."""
    src = (
        Path(__file__).resolve().parents[3] / "core" / "cli" / "commands" / "model.py"
    ).read_text(encoding="utf-8")
    assert "_upsert_env(role_def.env_var" not in src
    assert '_upsert_env("GEODE_AGENTIC_EFFORT"' not in src
    assert "remove_env(role_def.env_var)" in src  # stale-mask cleanup present


def test_login_source_is_toml_only() -> None:
    src = (
        Path(__file__).resolve().parents[3] / "core" / "cli" / "commands" / "login.py"
    ).read_text(encoding="utf-8")
    assert "_upsert_env(env_var, source)" not in src
    # API-key write (secrets) must REMAIN on the env layer
    assert "_upsert_env(env_var, key)" in src


def test_credential_source_toml_rows_are_read_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H7 closed — the rows /login source writes now flow through the cascade."""
    import core.config as config_mod
    from core.config import _load_toml_config

    global_toml = tmp_path / "config.toml"
    global_toml.write_text('[llm]\nanthropic_credential_source = "subscription"\n')
    monkeypatch.setattr(config_mod, "GLOBAL_CONFIG_PATH", global_toml)
    monkeypatch.setattr(config_mod, "PROJECT_CONFIG_PATH", tmp_path / "absent.toml")
    values = _load_toml_config()
    assert values.get("anthropic_credential_source") == "subscription"
