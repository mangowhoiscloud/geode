"""Tests for PR-R6 — Hermes-style fresh read at session boundary.

The v0.99.52 post-merge smoke surfaced a CLI ↔ daemon model-state drift:
``_apply_model`` in the CLI process writes ``GEODE_MODEL`` to ``.env`` and
``primary_model`` to ``config.toml``, but the daemon's pydantic ``Settings``
singleton keeps its boot-time snapshot — PR-DRIFT-CUT removed the per-turn
auto-revert that had been silently masking the gap. ``reload_settings_from_disk``
gives ``services.py`` an explicit Hermes-style boundary read.

These tests pin three contracts:
  1. The function mutates the live singleton in place (identity preserved).
  2. Fresh disk values overlay the stale in-memory snapshot.
  3. Idempotent — repeated calls are safe (no exceptions, settled state).
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip ``GEODE_*`` env vars so each test has a clean slate."""
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
    from core.server.supervised.services import SessionMode, build_shared_services

    services = build_shared_services()
    monkeypatch.setenv("GEODE_AGENTIC_EFFORT", "low")
    _, loop_low = services.create_session(SessionMode.DAEMON)
    assert loop_low._effort == "low"

    monkeypatch.setenv("GEODE_AGENTIC_EFFORT", "high")
    _, loop_high = services.create_session(SessionMode.DAEMON)
    assert loop_high._effort == "high"
    # Prior loop preserved its captured value (no auto-revert side effect).
    assert loop_low._effort == "low"
