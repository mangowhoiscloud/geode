"""`--dangerously-skip-permissions` — bypass all HITL gates + the plan stop.

The flag flows: thin CLI ``--dangerously-skip-permissions`` → env +
``client_capability`` handshake → daemon ``_adopt_skip_permissions`` (sets env
+ in-memory ``settings``) → ``create_session`` forces ``hitl_level=0`` +
``auto_approve`` → plan handler auto-executes (no approve_plan stop).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from core.config import reload_settings_from_disk, settings

_ENV = "GEODE_DANGEROUSLY_SKIP_PERMISSIONS"


@pytest.fixture(autouse=True)
def _reset_skip() -> Iterator[None]:
    """Guarantee no skip-state leaks into other tests (process-global singleton)."""
    yield
    os.environ.pop(_ENV, None)
    settings.dangerously_skip_permissions = False


def _enable(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    monkeypatch.setenv(_ENV, "1" if on else "0")
    reload_settings_from_disk()


class TestSettingField:
    def test_env_backed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, True)
        assert settings.dangerously_skip_permissions is True
        _enable(monkeypatch, False)
        assert settings.dangerously_skip_permissions is False


class TestApprovalGatesBypass:
    """The flag is read DYNAMICALLY by each HITL gate (not cached at executor
    construction) — so a full-HITL (hitl_level=2) executor still bypasses once
    the flag is set, and resets when it clears. This is what makes a running
    daemon honour the per-connection capability without a sticky-on next
    session."""

    def _workflow(self):  # hitl_level=2 = full HITL (would otherwise prompt)
        from core.agent.approval import ApprovalWorkflow

        return ApprovalWorkflow(hitl_level=2)

    def test_write_gate_bypassed_when_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, True)
        rejection, approved = self._workflow().apply_safety_gates(
            "edit_file", {"path": "x", "content": "y"}
        )
        assert rejection is None
        assert approved is True

    def test_write_gate_not_bypassed_without_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sanity: with skip off + hitl=2 the write gate does NOT auto-approve
        (it would prompt) — confirms the bypass is the flag, not a test artifact."""
        _enable(monkeypatch, False)
        wf = self._workflow()
        # auto-deny path returns a rejection without prompting (3+ denials).
        for _ in range(3):
            wf.track_decision("edit_file", "n")
        rejection, approved = wf.apply_safety_gates("edit_file", {"path": "x"})
        assert approved is False

    def test_bash_auto_approved_when_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, True)
        assert self._workflow().is_bash_auto_approved("rm -rf /tmp/x") is True

    def test_bash_not_auto_approved_without_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, False)
        # a write (non-read-only) command at hitl=2 needs approval
        assert self._workflow().is_bash_auto_approved("rm -rf /tmp/x") is False

    def test_mcp_auto_approved_when_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, True)
        assert self._workflow().is_mcp_approved("some-server") is True

    def test_batch_cost_bypassed_when_skip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import asyncio

        _enable(monkeypatch, True)
        assert asyncio.run(self._workflow().batch_cost_approval([])) is True


class TestAdoptHelper:
    def test_adopt_true_sets_env_and_settings(self) -> None:
        from core.server.ipc_server.poller import _adopt_skip_permissions

        _adopt_skip_permissions({"dangerously_skip_permissions": True})
        assert settings.dangerously_skip_permissions is True
        assert os.environ[_ENV] == "1"

    def test_adopt_false_resets_no_sticky(self) -> None:
        from core.server.ipc_server.poller import _adopt_skip_permissions

        _adopt_skip_permissions({"dangerously_skip_permissions": True})
        _adopt_skip_permissions({"dangerously_skip_permissions": False})
        assert settings.dangerously_skip_permissions is False
        assert os.environ[_ENV] == "0"

    def test_adopt_missing_field_is_false(self) -> None:
        from core.server.ipc_server.poller import _adopt_skip_permissions

        _adopt_skip_permissions({"dangerously_skip_permissions": True})
        _adopt_skip_permissions({})  # a normal client sends no field
        assert settings.dangerously_skip_permissions is False


class TestCapabilityAdvertise:
    def test_client_capability_includes_flag_when_env_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from core.cli.ipc_client import IPCClient

        monkeypatch.setenv(_ENV, "1")
        client = IPCClient()
        sent: dict = {}
        monkeypatch.setattr(client, "_send", lambda payload: sent.update(payload))
        client._send_client_capability()
        assert sent["type"] == "client_capability"
        assert sent["dangerously_skip_permissions"] is True

    def test_client_capability_flag_false_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from core.cli.ipc_client import IPCClient

        monkeypatch.delenv(_ENV, raising=False)
        client = IPCClient()
        sent: dict = {}
        monkeypatch.setattr(client, "_send", lambda payload: sent.update(payload))
        client._send_client_capability()
        assert sent["dangerously_skip_permissions"] is False
