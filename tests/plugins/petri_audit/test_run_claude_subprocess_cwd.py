"""PR-RESUME-NO-PERSIST-FIX (B2) — ``_run_claude_subprocess``
forwards ``cwd`` to ``asyncio.create_subprocess_exec``.

Verifies the lowest-level subprocess invocation receives the cwd
override. Without this propagation the adapter-level wiring would
be a no-op.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch


def _build_fake_proc(stdout: bytes = b"", stderr: bytes = b"", rc: int = 0) -> Any:
    """Minimal asyncio.subprocess.Process stub used by both tests."""

    class _Proc:
        returncode = rc

        async def communicate(self, _stdin: bytes) -> tuple[bytes, bytes]:
            return (stdout, stderr)

        def kill(self) -> None:
            pass

        async def wait(self) -> int:
            return rc

    return _Proc()


def test_run_subprocess_forwards_cwd_when_set() -> None:
    from plugins.petri_audit.claude_cli_provider import _run_claude_subprocess

    captured: dict[str, Any] = {}

    async def _fake_create(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return _build_fake_proc()

    with patch("asyncio.create_subprocess_exec", _fake_create):
        asyncio.run(
            _run_claude_subprocess(
                ["/fake/claude", "--print"],
                stdin_text="",
                timeout_s=10.0,
                cwd="/tmp/per-task-test-cwd",  # noqa: S108 — propagation probe
            )
        )

    assert captured.get("cwd") == "/tmp/per-task-test-cwd"  # noqa: S108


def test_run_subprocess_omits_cwd_default_inherits() -> None:
    """When no cwd is passed, ``asyncio.create_subprocess_exec``
    receives ``cwd=None`` (its own default = inherit caller's cwd).
    Confirms back-compat for direct callers that pre-date the B2
    fix (inspect_ai audit lane, one-shot diagnostic scripts)."""
    from plugins.petri_audit.claude_cli_provider import _run_claude_subprocess

    captured: dict[str, Any] = {}

    async def _fake_create(*args: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return _build_fake_proc()

    with patch("asyncio.create_subprocess_exec", _fake_create):
        asyncio.run(
            _run_claude_subprocess(
                ["/fake/claude", "--print"],
                stdin_text="",
                timeout_s=10.0,
            )
        )

    # ``cwd`` key is in captured kwargs with value None.
    assert "cwd" in captured
    assert captured["cwd"] is None
