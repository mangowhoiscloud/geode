"""BashTool — execute shell commands with HITL approval gate.

Provides a safe shell execution interface for the agentic loop.
Dangerous patterns are blocked outright; all other commands require
explicit user approval before execution.

Sandbox hardening (v0.22.0):
- preexec_fn with resource.setrlimit for CPU/FSIZE/NPROC caps
- Secret redaction on stdout/stderr before returning to LLM context
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import resource
import signal
from dataclasses import dataclass
from typing import Any

from core.tools.base import load_tool_definition

log = logging.getLogger(__name__)

# Max output sizes to prevent flooding
_MAX_STDOUT = 10_000
_MAX_STDERR = 5_000
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 600
_TERMINATE_GRACE_S = 2.0

# --- Resource limits for child processes (sandbox hardening) ---
_BASH_CPU_LIMIT_S = 30  # CPU time hard cap (seconds)
_BASH_FSIZE_LIMIT_B = 50 * 1024 * 1024  # Max output file size (50 MB)
_BASH_NPROC_LIMIT = 64  # Max child processes


def _set_resource_limits() -> None:
    """preexec_fn for subprocess: apply hard resource limits.

    Called in the child process after fork, before exec.
    Note: RLIMIT_NPROC is intentionally NOT set. On macOS it caps the
    user's *total* process count (not per-subprocess), causing fork()
    failures when many MCP/serve processes are running.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (_BASH_CPU_LIMIT_S, _BASH_CPU_LIMIT_S))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_BASH_FSIZE_LIMIT_B, _BASH_FSIZE_LIMIT_B))


def _prepare_child_process() -> None:
    """Create a process group and apply resource limits before shell exec."""
    os.setsid()
    _set_resource_limits()


@dataclass
class BashResult:
    """Result of a shell command execution."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    blocked: bool = False
    needs_approval: bool = False
    denied: bool = False
    timed_out: bool = False
    interrupted: bool = False
    error: str = ""
    command: str = ""


# Patterns that are always blocked (never executed regardless of approval)
_BLOCKED_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"rm\s+-rf\s+/\s*$", re.IGNORECASE),  # root only, not /tmp etc.
    re.compile(r"sudo\s+", re.IGNORECASE),
    re.compile(r">\s*/etc/", re.IGNORECASE),
    re.compile(r"curl.*\|\s*(?:ba)?sh", re.IGNORECASE),
    re.compile(r"wget.*\|\s*(?:ba)?sh", re.IGNORECASE),
    re.compile(r"mkfs\.", re.IGNORECASE),
    re.compile(r"dd\s+if=.*of=/dev/", re.IGNORECASE),
    re.compile(r"chmod\s+-R\s+777\s+/\s*$", re.IGNORECASE),  # root only
    re.compile(r":\(\)\s*\{.*\|.*&\s*\}", re.IGNORECASE),  # fork bomb
]


class BashTool:
    """Execute shell commands with safety checks and HITL approval."""

    def __init__(self, *, working_dir: str | None = None) -> None:
        if working_dir is None:
            from core.paths import get_project_root

            working_dir = str(get_project_root())
        self._working_dir = working_dir

    def validate(self, command: str) -> BashResult | None:
        """Check if a command is blocked. Returns BashResult if blocked, None if OK."""
        for pattern in _BLOCKED_PATTERNS:
            if pattern.search(command):
                log.warning("Blocked dangerous command: %s", command[:100])
                return BashResult(
                    blocked=True,
                    error=f"Blocked: matches dangerous pattern ({pattern.pattern})",
                    command=command,
                )
        return None

    async def aexecute(
        self,
        command: str,
        *,
        timeout: int = _DEFAULT_TIMEOUT,
        cancellation: asyncio.Event | None = None,
    ) -> BashResult:
        """Execute a shell command asynchronously (caller must ensure approval)."""
        blocked = self.validate(command)
        if blocked:
            return blocked
        if cancellation is not None and cancellation.is_set():
            return BashResult(
                interrupted=True,
                error="Interrupted before execution",
                returncode=-1,
                command=command,
            )

        timeout = max(1, min(int(timeout), _MAX_TIMEOUT))

        process: asyncio.subprocess.Process | None = None
        communicate_task: asyncio.Task[tuple[bytes, bytes]] | None = None
        cancel_task: asyncio.Task[bool] | None = None
        try:
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._working_dir,
                preexec_fn=_prepare_child_process if os.name != "nt" else None,
            )
            communicate_task = asyncio.create_task(process.communicate())
            wait_tasks: set[asyncio.Task[Any]] = {communicate_task}
            if cancellation is not None:
                cancel_task = asyncio.create_task(cancellation.wait())
                wait_tasks.add(cancel_task)

            done, pending = await asyncio.wait(
                wait_tasks,
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if communicate_task in done:
                stdout_raw, stderr_raw = communicate_task.result()
            elif cancel_task is not None and cancel_task in done:
                await self._terminate_process_tree(process)
                self._cancel_pending(communicate_task, *pending)
                return BashResult(
                    error="Interrupted",
                    returncode=-1,
                    interrupted=True,
                    command=command,
                )
            else:
                await self._terminate_process_tree(process)
                self._cancel_pending(communicate_task, *pending)
                log.warning("Command timed out after %ds: %s", timeout, command[:100])
                return BashResult(
                    error=f"Timeout after {timeout}s",
                    returncode=-1,
                    timed_out=True,
                    command=command,
                )

            for task in pending:
                task.cancel()
            stdout = stdout_raw.decode("utf-8", errors="replace") if stdout_raw else ""
            stderr = stderr_raw.decode("utf-8", errors="replace") if stderr_raw else ""
            return BashResult(
                stdout=stdout[:_MAX_STDOUT],
                stderr=stderr[:_MAX_STDERR],
                returncode=process.returncode or 0,
                command=command,
            )
        except TimeoutError:
            if process is not None:
                await self._terminate_process_tree(process)
            log.warning("Command timed out after %ds: %s", timeout, command[:100])
            return BashResult(
                error=f"Timeout after {timeout}s",
                returncode=-1,
                timed_out=True,
                command=command,
            )
        except OSError as exc:
            log.error("Command execution failed: %s", exc)
            return BashResult(
                error=str(exc),
                returncode=-1,
                command=command,
            )
        finally:
            if cancel_task is not None and not cancel_task.done():
                cancel_task.cancel()

    @staticmethod
    def _cancel_pending(*tasks: asyncio.Task[Any]) -> None:
        for task in tasks:
            if not task.done():
                task.cancel()

    async def _terminate_process_tree(self, process: asyncio.subprocess.Process) -> None:
        """Terminate the shell process group, then force kill if it lingers."""
        if process.returncode is not None:
            return
        if os.name != "nt":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=_TERMINATE_GRACE_S)
            return
        except TimeoutError:
            pass
        if os.name != "nt":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()

    def to_tool_result(self, result: BashResult) -> dict[str, Any]:
        """Convert BashResult to a dict suitable for LLM tool_result.

        Applies secret redaction to stdout/stderr before returning
        to prevent API keys from leaking into LLM context.
        """
        from core.utils.redaction import redact_secrets

        if result.blocked:
            return {"error": result.error, "blocked": True}
        if result.denied:
            return {"error": "User denied execution", "denied": True}
        if result.interrupted:
            return {"error": redact_secrets(result.error or "Interrupted"), "interrupted": True}
        if result.timed_out:
            return {
                "error": redact_secrets(result.error or "Timed out"),
                "returncode": result.returncode,
                "timed_out": True,
            }
        if result.error:
            return {"error": redact_secrets(result.error), "returncode": result.returncode}

        out: dict[str, Any] = {"returncode": result.returncode}
        if result.stdout:
            out["stdout"] = redact_secrets(result.stdout)
        if result.stderr:
            out["stderr"] = redact_secrets(result.stderr)
        return out


BASH_TOOL_DEFINITION: dict[str, Any] = load_tool_definition("run_bash")
