"""Config precedence regression — env / .env outranks project/global TOML.

Pins the fix for the 2026-06-09 incident where a project ``.env``
``GEODE_MODEL`` was silently overridden by ``[llm] primary_model``. The
documented chain is CLI > env > project ``.geode/config.toml`` > global
``~/.geode/config.toml`` > routing default; the env layer includes BOTH a
real ``GEODE_*`` env var AND a ``.env`` file value. ``_apply_toml_overlay``
used to skip only on ``os.environ`` membership, which missed ``.env``-file
values (pydantic loads them onto the instance, not ``os.environ``), inverting
env > TOML. The fix keys the skip on ``model_fields_set`` instead.

These tests exercise the overlay decision directly (deterministic — no cwd /
``.env``-relative-path / module-reload coupling, which is environment-dependent
under xdist). The full ``.env`` → ``model_fields_set`` → reload path is covered
by the live socket E2E in the PR.
"""

from __future__ import annotations

from pathlib import Path

import core.config as cfg
import pytest
from core.config._settings import Settings


def test_overlay_skips_field_set_by_env_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A field in ``env_set_fields`` (env var OR ``.env`` — both land in
    pydantic's ``model_fields_set``) must NOT be overwritten by the TOML
    overlay: env layer outranks project/global TOML."""
    monkeypatch.setattr(cfg, "_load_toml_config", lambda **_k: {"model": "claude-opus-4-8"})
    s = Settings()
    object.__setattr__(s, "model", "gpt-5.4")  # value pydantic read from env / .env

    cfg._apply_toml_overlay(s, env_set_fields={"model"})

    assert s.model == "gpt-5.4"


def test_overlay_applies_toml_when_field_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """With the field NOT env/.env-set, the TOML overlay drives it."""
    monkeypatch.setattr(cfg, "_load_toml_config", lambda **_k: {"model": "claude-opus-4-8"})
    s = Settings()
    object.__setattr__(s, "model", "sentinel-code-default")

    cfg._apply_toml_overlay(s, env_set_fields=set())

    assert s.model == "claude-opus-4-8"


def test_dotenv_value_lands_in_model_fields_set(tmp_path: Path) -> None:
    """Pin the premise of the fix: a ``.env`` ``GEODE_MODEL`` is captured in
    ``model_fields_set`` (same as a real env var), so the overlay skip can
    rely on it. Uses an explicit absolute ``_env_file`` — no cwd coupling."""
    (tmp_path / ".env").write_text("GEODE_MODEL=gpt-5.4\n", encoding="utf-8")
    s = Settings(_env_file=str(tmp_path / ".env"))
    assert s.model == "gpt-5.4"
    assert "model" in s.model_fields_set
