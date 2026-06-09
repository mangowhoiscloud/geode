"""Config precedence regression — env / .env outranks project/global TOML.

Pins the fix for the 2026-06-09 incident where a project ``.env``
``GEODE_MODEL`` was silently overridden by ``[llm] primary_model``. The
documented chain is CLI > env > project ``.geode/config.toml`` > global
``~/.geode/config.toml`` > routing default; the env layer includes BOTH a
real ``GEODE_*`` env var AND a ``.env`` file value. ``_apply_toml_overlay``
used to skip only on ``os.environ`` membership, which missed ``.env``-file
values (pydantic loads them onto the instance, not ``os.environ``), inverting
env > TOML. The fix keys the skip on ``model_fields_set`` instead.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest


def _project(tmp: Path, *, env_model: str | None, toml_model: str | None) -> None:
    if env_model is not None:
        (tmp / ".env").write_text(f"GEODE_MODEL={env_model}\n", encoding="utf-8")
    if toml_model is not None:
        (tmp / ".geode").mkdir(exist_ok=True)
        (tmp / ".geode" / "config.toml").write_text(
            f'[llm]\nprimary_model = "{toml_model}"\n', encoding="utf-8"
        )


def _resolved_model(tmp: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.chdir(tmp)
    monkeypatch.delenv("GEODE_MODEL", raising=False)
    import core.config as cfg

    importlib.reload(cfg)
    cfg.reload_settings_from_disk()
    return str(cfg.settings.model)


def test_project_dotenv_model_beats_project_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A project ``.env`` ``GEODE_MODEL`` (env layer) must win over the
    project ``[llm] primary_model`` (TOML layer)."""
    _project(tmp_path, env_model="gpt-5.4", toml_model="claude-opus-4-8")
    assert _resolved_model(tmp_path, monkeypatch) == "gpt-5.4"


def test_project_toml_wins_when_no_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no env/.env override, the project TOML drives the model."""
    _project(tmp_path, env_model=None, toml_model="claude-opus-4-8")
    assert _resolved_model(tmp_path, monkeypatch) == "claude-opus-4-8"


def test_reload_honours_dotenv_over_toml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``reload_settings_from_disk`` (daemon session boundary) must keep the
    same precedence — the pre-fix reload copied fresh *values* but checked the
    stale singleton's ``model_fields_set``, so the overlay used the wrong set."""
    _project(tmp_path, env_model="gpt-5.4", toml_model="claude-opus-4-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GEODE_MODEL", raising=False)
    import core.config as cfg

    importlib.reload(cfg)
    cfg.reload_settings_from_disk()
    assert cfg.settings.model == "gpt-5.4"
    # Drop the .env override → reload → project TOML now wins.
    (tmp_path / ".env").write_text("\n", encoding="utf-8")
    cfg.reload_settings_from_disk()
    assert cfg.settings.model == "claude-opus-4-8"
