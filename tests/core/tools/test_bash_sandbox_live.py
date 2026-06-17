"""Live isolation E2E for the run_bash sandbox (Phase F) — macOS Seatbelt.

These exercise REAL ``/usr/bin/sandbox-exec`` isolation through the full
``BashTool.aexecute`` path: a normal in-cwd command succeeds, a write outside
the working directory is blocked, and a network connection is blocked. They
auto-skip off macOS (Linux bwrap isolation needs userns and is verified
separately; CI runs ubuntu so these skip there). No API cost — pure OS sandbox.

macOS path live-verified 2026-06-18.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
from core.tools.bash_tool import BashResult, BashTool

_MACOS_SANDBOX = sys.platform == "darwin" and os.path.exists("/usr/bin/sandbox-exec")
pytestmark = pytest.mark.skipif(not _MACOS_SANDBOX, reason="macOS /usr/bin/sandbox-exec only")


def _run(tool: BashTool, cmd: str) -> BashResult:
    return asyncio.run(tool.aexecute(cmd, timeout=20))


@pytest.fixture
def sandboxed_tool(tmp_path, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "bash_sandbox", "on", raising=False)
    return BashTool(working_dir=str(tmp_path))


def test_normal_in_cwd_command_succeeds(sandboxed_tool, tmp_path) -> None:
    """A normal command that writes inside the working dir must still work."""
    result = _run(sandboxed_tool, "echo hello-sandbox > out.txt && cat out.txt")
    assert result.returncode == 0, result.stderr
    assert "hello-sandbox" in result.stdout
    assert (tmp_path / "out.txt").read_text().strip() == "hello-sandbox"


def test_write_outside_cwd_is_blocked(sandboxed_tool) -> None:
    """Writing outside the working dir (here: $HOME) must be denied by Seatbelt."""
    target = os.path.expanduser("~/.geode-bash-sandbox-escape-probe")
    if os.path.exists(target):  # pragma: no cover - hygiene
        os.remove(target)
    try:
        result = _run(sandboxed_tool, f"echo escaped > {target!r}")
        assert result.returncode != 0, "write outside cwd should have been blocked"
        assert not os.path.exists(target), "sandbox failed to block the out-of-cwd write"
    finally:
        if os.path.exists(target):
            os.remove(target)


def test_network_egress_is_blocked(sandboxed_tool) -> None:
    """An outbound TCP connection must be denied (no network rule → deny default)."""
    probe = (
        "python3 -c "
        "'import socket,sys; "
        's=socket.create_connection(("1.1.1.1",443),timeout=5); '
        "s.close(); sys.exit(0)'"
    )
    result = _run(sandboxed_tool, probe)
    assert result.returncode != 0, "network egress should have been blocked by the sandbox"
