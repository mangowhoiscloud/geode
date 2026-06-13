"""`--dangerously-skip-permissions` — bypass all HITL gates + the plan stop.

The flag flows: thin CLI ``--dangerously-skip-permissions`` → env →
``client_capability`` handshake → daemon ``_adopt_skip_permissions`` sets the
PER-SESSION ContextVar → the HITL gates + plan handler read it at call time.
Per-session isolation (a ContextVar, not a process-global) so a concurrent
skip session can't flip another session's gates.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator

import pytest
from core.agent.approval import ApprovalWorkflow
from core.agent.safety import (
    _skip_permissions_var,
    current_skip_permissions,
    set_skip_permissions,
)
from core.config import reload_settings_from_disk, settings

_ENV = "GEODE_DANGEROUSLY_SKIP_PERMISSIONS"


@pytest.fixture(autouse=True)
def _reset_skip() -> Iterator[None]:
    """Guarantee no skip-state leaks into other tests (ContextVar + env default)."""
    yield
    _skip_permissions_var.set(None)
    os.environ.pop(_ENV, None)
    settings.dangerously_skip_permissions = False


def _wf() -> ApprovalWorkflow:  # hitl_level=2 = full HITL (would otherwise prompt)
    return ApprovalWorkflow(hitl_level=2)


class TestResolution:
    def test_env_backed_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ContextVar unset → env-backed setting is the default (a daemon
        launched in skip mode applies daemon-wide)."""
        _skip_permissions_var.set(None)
        monkeypatch.setenv(_ENV, "1")
        reload_settings_from_disk()
        assert settings.dangerously_skip_permissions is True
        assert current_skip_permissions() is True
        monkeypatch.setenv(_ENV, "0")
        reload_settings_from_disk()
        assert current_skip_permissions() is False

    def test_contextvar_overrides_env_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A per-session value overrides a daemon-wide env default."""
        monkeypatch.setenv(_ENV, "1")
        reload_settings_from_disk()
        set_skip_permissions(False)
        assert current_skip_permissions() is False

    def test_per_session_isolation(self) -> None:
        """A skip session must NOT flip another concurrent session's flag — the
        Codex HIGH a process-global would reintroduce. Each ``copy_context``
        is an independent session context."""
        import contextvars

        set_skip_permissions(True)
        other = contextvars.copy_context()
        # Mutate THIS context; the snapshot taken before stays independent, and
        # a fresh context resolves to the (False) env default.
        fresh = contextvars.Context()
        assert fresh.run(current_skip_permissions) is False
        assert current_skip_permissions() is True
        assert other.run(current_skip_permissions) is True


class TestApprovalGatesBypass:
    """Each HITL gate reads the flag at call time, so a full-HITL (hitl=2)
    executor still bypasses when the session flag is set."""

    def test_write_gate_bypassed_when_skip(self) -> None:
        set_skip_permissions(True)
        rejection, approved = _wf().apply_safety_gates("edit_file", {"path": "x", "content": "y"})
        assert rejection is None
        assert approved is True

    def test_write_gate_denied_without_skip(self) -> None:
        """Sanity: skip off + hitl=2 does NOT auto-approve (bypass is the flag)."""
        wf = _wf()
        for _ in range(3):  # auto-deny path returns rejection without prompting
            wf.track_decision("edit_file", "n")
        _rejection, approved = wf.apply_safety_gates("edit_file", {"path": "x"})
        assert approved is False

    def test_bash_auto_approved_when_skip(self) -> None:
        set_skip_permissions(True)
        assert _wf().is_bash_auto_approved("rm -rf /tmp/x") is True

    def test_bash_not_auto_approved_without_skip(self) -> None:
        assert _wf().is_bash_auto_approved("rm -rf /tmp/x") is False

    def test_mcp_auto_approved_when_skip(self) -> None:
        set_skip_permissions(True)
        assert _wf().is_mcp_approved("some-server") is True

    def test_batch_cost_bypassed_when_skip(self) -> None:
        set_skip_permissions(True)
        assert asyncio.run(_wf().batch_cost_approval([])) is True


class TestAdoptHelper:
    """The IPC capability handler sets the per-session ContextVar."""

    def test_adopt_true(self) -> None:
        from core.server.ipc_server.poller import _adopt_skip_permissions

        _adopt_skip_permissions({"dangerously_skip_permissions": True})
        assert current_skip_permissions() is True

    def test_adopt_false_resets(self) -> None:
        from core.server.ipc_server.poller import _adopt_skip_permissions

        _adopt_skip_permissions({"dangerously_skip_permissions": True})
        _adopt_skip_permissions({"dangerously_skip_permissions": False})
        assert current_skip_permissions() is False

    def test_adopt_missing_field_is_false(self) -> None:
        from core.server.ipc_server.poller import _adopt_skip_permissions

        _adopt_skip_permissions({"dangerously_skip_permissions": True})
        _adopt_skip_permissions({})  # a normal client sends no field
        assert current_skip_permissions() is False


class TestCapabilityAdvertise:
    def test_includes_flag_when_env_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.cli.ipc_client import IPCClient

        monkeypatch.setenv(_ENV, "1")
        client = IPCClient()
        sent: dict = {}
        monkeypatch.setattr(client, "_send", lambda payload: sent.update(payload))
        client._send_client_capability()
        assert sent["type"] == "client_capability"
        assert sent["dangerously_skip_permissions"] is True

    def test_flag_false_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.cli.ipc_client import IPCClient

        monkeypatch.delenv(_ENV, raising=False)
        client = IPCClient()
        sent: dict = {}
        monkeypatch.setattr(client, "_send", lambda payload: sent.update(payload))
        client._send_client_capability()
        assert sent["dangerously_skip_permissions"] is False
