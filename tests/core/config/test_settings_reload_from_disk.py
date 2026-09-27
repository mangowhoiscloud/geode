"""Tests for PR-R6 — Hermes-style fresh read at session boundary.

The v0.99.52 post-merge smoke surfaced a CLI ↔ daemon model-state drift:
``_apply_model`` in the CLI process writes ``GEODE_MODEL`` to ``.env`` and
``primary_model`` to ``config.toml``, but the daemon's pydantic ``Settings``
singleton keeps its boot-time snapshot — PR-DRIFT-CUT removed the per-turn
auto-revert that had been silently masking the gap. ``reload_settings_from_disk``
gives ``services.py`` an explicit Hermes-style boundary read.

These tests pin the reload contracts:
  1. The function mutates the live singleton in place (identity preserved).
  2. Fresh disk values overlay the stale in-memory snapshot.
  3. Idempotent — repeated calls are safe (no exceptions, settled state).
  4. Failed preparation preserves the previous settings; a corrected reload recovers.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate ``GEODE_*`` environment overrides."""
    for key in list(os.environ):
        if key.startswith("GEODE_"):
            monkeypatch.delenv(key, raising=False)


def test_singleton_identity_preserved_across_reload() -> None:
    """``from core.config import settings`` references must keep working
    after a reload. Replacing the singleton would leave every captured
    reference stale; mutating in place keeps callers in sync.
    """
    from core.config import reload_settings_from_disk, settings

    pre = settings
    reload_settings_from_disk()
    post_from_module = __import__("core.config", fromlist=["settings"]).settings
    assert pre is post_from_module, (
        "reload_settings_from_disk replaced the singleton; existing references "
        "would now be stale. Must mutate in place."
    )


def test_reload_picks_up_env_var_change(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of R6 — when ``GEODE_MODEL`` changes between two
    reads of ``settings.model``, the second read must see the new value.

    Pre-PR the CLI would write ``GEODE_MODEL=gpt-5.5`` to ``.env`` + invoke
    ``_apply_model`` (which only mutates the CLI process's Settings), and
    the daemon's session-start ``settings.model`` would still resolve to its
    boot-time value. ``reload_settings_from_disk`` closes that gap by
    re-running pydantic's env/`.env` resolution on the live singleton.
    """
    from core.config import reload_settings_from_disk, settings

    monkeypatch.setenv("GEODE_MODEL", "gpt-5.5")
    reload_settings_from_disk()
    assert settings.model == "gpt-5.5"

    monkeypatch.setenv("GEODE_MODEL", "claude-sonnet-4-6")
    reload_settings_from_disk()
    assert settings.model == "claude-sonnet-4-6"


def test_reload_is_idempotent_on_unchanged_disk() -> None:
    """Calling twice in a row with no disk change must leave settings
    untouched. Catches accidental side effects (e.g. resetting fields to
    defaults, double-applying TOML overlay).
    """
    from core.config import reload_settings_from_disk, settings

    reload_settings_from_disk()
    snapshot = {
        "model": settings.model,
        "act_model": getattr(settings, "act_model", ""),
        "ensemble_mode": getattr(settings, "ensemble_mode", ""),
    }
    reload_settings_from_disk()
    assert settings.model == snapshot["model"]
    assert getattr(settings, "act_model", "") == snapshot["act_model"]
    assert getattr(settings, "ensemble_mode", "") == snapshot["ensemble_mode"]


def test_reload_handles_fresh_process_call() -> None:
    """First call in a fresh process must initialise the singleton via
    ``_get_settings`` (not crash on ``None``). The singleton is then
    in-place-mutated rather than instantiated twice.
    """
    from core.config import reload_settings_from_disk, settings

    # The fixture stripped GEODE_*; the singleton may or may not exist yet
    # depending on test ordering. The call must succeed either way.
    reload_settings_from_disk()
    # Field access proves the singleton is valid after the call.
    assert isinstance(settings.model, str)


def test_invalid_toml_preserves_live_settings_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import core.config as cfg
    from core.config._settings import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    toml_path = tmp_path / "config.toml"
    monkeypatch.setenv("GEODE_CONFIG_TOML", str(toml_path))
    monkeypatch.setattr(cfg, "PROJECT_CONFIG_PATH", tmp_path / "absent.toml")
    current = Settings(model="previous-model", agentic_effort="low")
    monkeypatch.setattr(cfg, "_settings_instance", current)
    before = current.model_dump()
    before_fields_set = set(current.model_fields_set)
    routing_calls: list[str] = []
    monkeypatch.setattr(cfg, "reload_routing_constants", lambda: routing_calls.append("reload"))
    monkeypatch.setenv("GEODE_MODEL", "new-env-model")
    toml_path.write_text('[agentic]\neffort = "invalid"\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="agentic_effort"):
        cfg.reload_settings_from_disk()

    assert cfg.settings is current
    assert current.model_dump() == before
    assert current.model_fields_set == before_fields_set
    assert routing_calls == []

    toml_path.write_text('[llm]\nprimary_model = "toml-model"\n[agentic]\neffort = "high"\n')
    cfg.reload_settings_from_disk()
    assert cfg.settings is current
    assert current.model == "new-env-model"
    assert "model" in current.model_fields_set
    assert current.agentic_effort == "high"
    assert routing_calls == ["reload"]

    monkeypatch.delenv("GEODE_MODEL")
    cfg.reload_settings_from_disk()
    assert current.model == "toml-model"
    assert "model" not in current.model_fields_set


def test_invalid_env_preserves_live_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.config as cfg
    from core.config._settings import Settings

    current = Settings(_env_file=None, model="previous-model", agentic_effort="low")
    monkeypatch.setattr(cfg, "_settings_instance", current)
    before = current.model_dump()
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setenv("GEODE_AGENTIC_EFFORT", "invalid")

    with pytest.raises(ValidationError, match="agentic_effort"):
        cfg.reload_settings_from_disk()

    assert cfg.settings is current
    assert current.model_dump() == before


def test_routing_reload_failure_preserves_live_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    import core.config as cfg
    from core.config._settings import Settings

    current = Settings(_env_file=None, model="previous-model", agentic_effort="low")
    monkeypatch.setattr(cfg, "_settings_instance", current)
    before = current.model_dump()
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    monkeypatch.setattr(cfg, "_load_toml_config", lambda: {})
    monkeypatch.setenv("GEODE_MODEL", "new-env-model")

    def fail_routing_reload() -> None:
        raise ValueError("invalid routing manifest")

    monkeypatch.setattr(cfg, "reload_routing_constants", fail_routing_reload)
    with pytest.raises(ValueError, match="invalid routing manifest"):
        cfg.reload_settings_from_disk()

    assert cfg.settings is current
    assert current.model_dump() == before


def test_create_session_bridges_effort_to_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """PR-R6 — operator's effort choice must reach the live ``AgenticLoop``.

    Pre-PR ``services.create_session`` constructed ``AgenticLoop(...)`` with
    only ``model=`` from settings — the ``effort`` axis fell through to the
    constructor's ``"high"`` default regardless of operator selection. The
    ``/model`` picker writes ``GEODE_AGENTIC_EFFORT`` to disk + mutates
    ``settings.agentic_effort``, ``reload_settings_from_disk`` correctly
    picks it back up on the next session, but the missing constructor arg
    meant the loop never observed the change. This test pins both ends of
    the wire: ``settings.agentic_effort`` change → ``loop._effort`` reflects.
    """
    from core.server.supervised.services import SessionMode
    from core.wiring.runtime import build_shared_services

    services = build_shared_services()
    monkeypatch.setenv("GEODE_AGENTIC_EFFORT", "low")
    _, loop_low = services.create_session(SessionMode.DAEMON)
    assert loop_low._effort == "low"

    monkeypatch.setenv("GEODE_AGENTIC_EFFORT", "high")
    _, loop_high = services.create_session(SessionMode.DAEMON)
    assert loop_high._effort == "high"
    # Prior loop preserved its captured value (no auto-revert side effect).
    assert loop_low._effort == "low"


def test_monkeypatch_undo_pins_lazy_settings_export() -> None:
    """Arrange the next test: undo rebinds the PEP 562 export to its old object."""
    import core.config as cfg

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("core.config.settings", object())
    # Bool-only asserts: a Settings repr would print credential fields on failure.
    pinned = "settings" in vars(cfg)
    assert pinned, "monkeypatch undo no longer rebinds the lazy export"


def test_lazy_settings_export_follows_authority_reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """The root conftest drops the inherited binding before this test's fixtures."""
    import core.config as cfg

    monkeypatch.setattr(cfg, "_settings_instance", None)
    live = cfg.settings is cfg._get_settings()
    assert live, "core.config.settings kept a binding from an earlier test"
