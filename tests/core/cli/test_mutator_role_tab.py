"""PR-G2 — mutator role-tab in ``/model`` picker.

Pins:
- ``mutator`` role registered in ``AGENT_ROLES``.
- The role has ``settings_field=""`` (sentinel — mutator lives in
  ``MutatorConfig.default_model``, not Settings).
- ``toml_section="self_improving_loop.autoresearch.mutator"`` / ``toml_key="default_model"``
  matches the runner's lazy ``load_self_improving_loop_config()`` reader.
- ``_current_model_for_role(mutator)`` reads the toml value (or empty
  when unset, signalling inherit-Settings.model).
- ``_apply_model(..., role="mutator")`` writes to env + toml only,
  NOT to Settings (which has no such attribute).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_mutator_role_registered() -> None:
    """``mutator`` joins ``primary`` + ``reflection`` in AGENT_ROLES."""
    from core.cli.commands._state import AGENT_ROLES, role_by_name

    names = [r.name for r in AGENT_ROLES]
    assert "mutator" in names
    role = role_by_name("mutator")
    assert role.label == "Mutator"


def test_mutator_role_has_empty_settings_field() -> None:
    """The mutator model lives in MutatorConfig (toml), not Settings,
    so ``settings_field`` is the empty-string sentinel."""
    from core.cli.commands._state import role_by_name

    role = role_by_name("mutator")
    assert role.settings_field == ""
    # toml routing points at the self-improving-loop section
    assert role.toml_section == "self_improving_loop.autoresearch.mutator"
    assert role.toml_key == "default_model"
    # No effort axis on the mutator role
    assert role.has_effort is False


def test_current_model_for_mutator_reads_toml_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When ``settings_field=""`` the reader must consult the toml,
    not raise ``AttributeError`` on Settings."""
    from core.cli.commands import model as model_mod
    from core.cli.commands._state import role_by_name

    fake_toml = tmp_path / "config.toml"
    fake_toml.write_text(
        '[self_improving_loop.autoresearch.mutator]\ndefault_model = "claude-haiku-4-5-20251001"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    role = role_by_name("mutator")
    assert model_mod._current_model_for_role(role) == "claude-haiku-4-5-20251001"


def test_current_model_for_mutator_returns_empty_when_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing toml key → empty string (signals inherit-Settings.model
    per PR-MINIMAL-2 G1a)."""
    from core.cli.commands import model as model_mod
    from core.cli.commands._state import role_by_name

    fake_toml = tmp_path / "config.toml"
    fake_toml.write_text("[other_section]\nkey = 'value'\n", encoding="utf-8")
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    role = role_by_name("mutator")
    assert model_mod._current_model_for_role(role) == ""


def test_current_model_for_mutator_returns_empty_when_toml_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Missing config.toml → empty (fresh-install fallback)."""
    from core.cli.commands import model as model_mod
    from core.cli.commands._state import role_by_name

    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", tmp_path / "absent.toml")
    role = role_by_name("mutator")
    assert model_mod._current_model_for_role(role) == ""


def test_read_toml_value_handles_malformed_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Truncated / malformed config.toml → empty rather than raise."""
    from core.cli.commands import model as model_mod

    fake_toml = tmp_path / "config.toml"
    fake_toml.write_text("[broken section\nkey = value\n", encoding="utf-8")
    monkeypatch.setattr("core.paths.GLOBAL_CONFIG_TOML", fake_toml)
    assert (
        model_mod._read_toml_value("self_improving_loop.autoresearch.mutator", "default_model")
        == ""
    )


def test_apply_model_for_mutator_skips_settings_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Roles with ``settings_field=""`` must NOT trigger
    ``object.__setattr__(settings, ...)`` — Settings has no mutator
    field, the call would silently create a stray attr. Persistence
    runs through env + toml only."""
    import inspect

    from core.cli.commands import model as model_mod

    src = inspect.getsource(model_mod._apply_model)
    # The guard must check role_def.settings_field truthy before the
    # __setattr__ call. Anti-deception pin.
    assert "if role_def.settings_field:" in src
    # C-2 (2026-06-11) — the durable write is toml-only now; the env write
    # was removed (hazards H3/H4/H6) and stale lines are cleaned up.
    assert "upsert_config_toml(role_def.toml_section" in src
    assert "remove_env(role_def.env_var)" in src
    assert "upsert_config_toml(role_def.toml_section, role_def.toml_key" in src
