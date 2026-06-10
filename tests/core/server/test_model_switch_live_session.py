"""Guard: /model switch lands in the SAME interactive session (v0.99.175).

The thin CLI relays a mid-session ``/model`` to the daemon, where
``cmd_model`` updates ``settings.model`` + config.toml but NOT the live
AgenticLoop the session runs on (its docstring says "applies to *new*
sessions"). Operator-reported "fable 5로 바꿔도 opus-4-8로 동작" — the
thin-CLI ↔ daemon model gap. ``CLIPoller._sync_live_loop_to_settings``
re-points the live loop after a ``/model`` command lands.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from core.server.ipc_server.poller import CLIPoller


class _FakeLoop:
    def __init__(self) -> None:
        self.model = "claude-opus-4-8"
        self._provider = "anthropic"
        self._tool_processor = type("_TP", (), {"_model": "claude-opus-4-8"})()
        self._new_adapter = None
        self._prompt_dirty = False
        self._effort = "high"
        self.adapted_to: str | None = None

    def _adapt_context_for_model(self, target: str) -> None:
        self.adapted_to = target


class _FakeSettings:
    model = "claude-fable-5"
    agentic_effort = "xhigh"


@pytest.fixture()
def poller(monkeypatch) -> CLIPoller:
    # The identity breadcrumb touches loop.context internals covered by the
    # _model_switching tests; stub it here so these guards isolate the
    # model/effort re-point behaviour.
    monkeypatch.setattr(
        "core.agent.loop._model_switching._inject_model_switch_breadcrumb",
        lambda *_a, **_k: 0,
    )
    return CLIPoller.__new__(CLIPoller)  # bypass __init__ — only the method is under test


def test_sync_repoints_live_loop_model(poller: CLIPoller, monkeypatch) -> None:
    monkeypatch.setattr("core.config.settings", _FakeSettings(), raising=False)
    loop = _FakeLoop()
    poller._sync_live_loop_to_settings(loop)
    assert loop.model == "claude-fable-5"
    assert loop._provider == "anthropic"
    assert loop.adapted_to == "claude-fable-5"


def test_sync_repoints_effort(poller: CLIPoller, monkeypatch) -> None:
    monkeypatch.setattr("core.config.settings", _FakeSettings(), raising=False)
    loop = _FakeLoop()
    poller._sync_live_loop_to_settings(loop)
    assert loop._effort == "xhigh"


def test_sync_noop_when_already_current(poller: CLIPoller, monkeypatch) -> None:
    class _SameSettings:
        model = "claude-opus-4-8"
        agentic_effort = "high"

    monkeypatch.setattr("core.config.settings", _SameSettings(), raising=False)
    loop = _FakeLoop()
    poller._sync_live_loop_to_settings(loop)
    # unchanged model → no context re-adapt fired
    assert loop.adapted_to is None
    assert loop.model == "claude-opus-4-8"


def test_handle_command_on_server_syncs_after_model(poller: CLIPoller, monkeypatch) -> None:
    """The /model command path must call the live-loop sync; other commands
    must not."""
    source = inspect.getsource(CLIPoller._handle_command_on_server)
    assert 'cmd == "/model"' in source
    assert "_sync_live_loop_to_settings(loop)" in source


def test_sync_survives_apply_failure(poller: CLIPoller, monkeypatch) -> None:
    """A swap failure must not crash command handling — effort still syncs."""

    def _boom(*_a: Any, **_k: Any) -> tuple[str, bool]:
        raise RuntimeError("adapter resolution failed")

    monkeypatch.setattr("core.config.settings", _FakeSettings(), raising=False)
    monkeypatch.setattr("core.agent.loop._model_switching._apply_model_update", _boom)
    loop = _FakeLoop()
    poller._sync_live_loop_to_settings(loop)  # must not raise
    assert loop._effort == "xhigh"  # effort axis still applied
