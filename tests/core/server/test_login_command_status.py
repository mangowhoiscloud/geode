"""Daemon /login results carry the command outcome, not only captured text."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from core.server.ipc_server.poller import CLIPoller


def _poller() -> CLIPoller:
    # Command dispatch reads only the injected handler and shared services.
    from core.cli.dispatcher import _handle_command

    poller = object.__new__(CLIPoller)
    poller._command_handler = _handle_command  # type: ignore[attr-defined]
    poller._scheduler_service = None  # type: ignore[attr-defined]
    poller._services = SimpleNamespace(  # type: ignore[attr-defined]
        command_registry=None, skill_registry=None, mcp_manager=None
    )
    return poller


@pytest.mark.parametrize(
    ("args", "status", "text"),
    [
        ("remove ghost-plan", "error", "Plan not found: ghost-plan"),
        ("refresh", "ok", "nothing to reload"),
        ("help", "ok", "credentials & subscription plans"),
    ],
)
def test_login_command_reports_its_outcome(args: str, status: str, text: str) -> None:
    result = asyncio.run(_poller()._handle_command_on_server({"cmd": "/login", "args": args}, None))

    assert result["status"] == status
    assert text in (result.get("message", "") if status == "error" else result["output"])
