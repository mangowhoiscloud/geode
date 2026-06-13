"""`--dangerously-skip-permissions` — bypass all HITL gates + the plan stop.

The flag flows: thin CLI ``--dangerously-skip-permissions`` → env +
``client_capability`` handshake → daemon ``_adopt_skip_permissions`` (sets env
+ in-memory ``settings``) → ``create_session`` forces ``hitl_level=0`` +
``auto_approve`` → plan handler auto-executes (no approve_plan stop).
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from core.config import reload_settings_from_disk, settings
from core.server.supervised.services import SessionMode, SharedServices

_ENV = "GEODE_DANGEROUSLY_SKIP_PERMISSIONS"


@pytest.fixture(autouse=True)
def _reset_skip() -> Iterator[None]:
    """Guarantee no skip-state leaks into other tests (process-global singleton)."""
    yield
    os.environ.pop(_ENV, None)
    settings.dangerously_skip_permissions = False


def _services() -> SharedServices:
    return SharedServices(
        mcp_manager=MagicMock(),
        skill_registry=MagicMock(),
        hook_system=MagicMock(),
        tool_handlers={"test_tool": lambda **kw: {"ok": True}},
        _cost_budget=1.0,
    )


def _enable(monkeypatch: pytest.MonkeyPatch, on: bool) -> None:
    monkeypatch.setenv(_ENV, "1" if on else "0")
    reload_settings_from_disk()


class TestSettingField:
    def test_env_backed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, True)
        assert settings.dangerously_skip_permissions is True
        _enable(monkeypatch, False)
        assert settings.dangerously_skip_permissions is False


class TestCreateSessionOverride:
    def test_skip_forces_hitl_0_and_auto_approve_in_repl(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REPL is hitl=2 by default; the flag must force it to 0 + auto-approve."""
        _enable(monkeypatch, True)
        executor, _ = _services().create_session(SessionMode.REPL)
        assert executor._hitl_level == 0
        assert executor._auto_approve is True

    def test_skip_forces_hitl_0_in_ipc(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, True)
        executor, _ = _services().create_session(SessionMode.IPC)
        assert executor._hitl_level == 0
        assert executor._auto_approve is True

    def test_no_skip_keeps_mode_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _enable(monkeypatch, False)
        executor, _ = _services().create_session(SessionMode.REPL)
        assert executor._hitl_level == 2
        assert executor._auto_approve is False


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
