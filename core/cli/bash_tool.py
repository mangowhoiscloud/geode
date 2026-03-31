"""BashTool — execute shell commands with HITL approval gate.

Provides a safe shell execution interface for the agentic loop.
Dangerous patterns are blocked outright; all other commands require
explicit user approval before execution.

Sandbox hardening (v0.22.0):
- preexec_fn with resource.setrlimit for CPU/FSIZE/NPROC caps
- Secret redaction on stdout/stderr before returning to LLM context
"""

from __future__ import annotations

import logging
import os
import re
import resource
import subprocess  # nosec B404 — intentional: BashTool requires shell execution
from dataclasses import dataclass
from typing import Any

from core.tools.base import load_tool_definition

log = logging.getLogger(__name__)

# Max output sizes to prevent flooding
_MAX_STDOUT = 10_000
_MAX_STDERR = 5_000
_DEFAULT_TIMEOUT = 30

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


@dataclass
class BashResult:
    """Result of a shell command execution."""

    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    blocked: bool = False
    needs_approval: bool = False
    denied: bool = False
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

    def execute(self, command: str, *, timeout: int = _DEFAULT_TIMEOUT) -> BashResult:
        """Execute a shell command (caller must ensure approval)."""
        # Final safety check
        blocked = self.validate(command)
        if blocked:
            return blocked

        try:
            result = subprocess.run(  # nosec B602 — HITL approval gate + blocked patterns
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._working_dir,
                preexec_fn=_set_resource_limits if os.name != "nt" else None,
            )

            return BashResult(
                stdout=result.stdout[:_MAX_STDOUT],
                stderr=result.stderr[:_MAX_STDERR],
                returncode=result.returncode,
                command=command,
            )

        except subprocess.TimeoutExpired:
            log.warning("Command timed out after %ds: %s", timeout, command[:100])
            return BashResult(
                error=f"Timeout after {timeout}s",
                returncode=-1,
                command=command,
            )
        except OSError as exc:
            log.error("Command execution failed: %s", exc)
            return BashResult(
                error=str(exc),
                returncode=-1,
                command=command,
            )

    def to_tool_result(self, result: BashResult) -> dict[str, Any]:
        """Convert BashResult to a dict suitable for LLM tool_result.

        Applies secret redaction to stdout/stderr before returning
        to prevent API keys from leaking into LLM context.
        """
        from core.cli.redaction import redact_secrets

        if result.blocked:
            return {"error": result.error, "blocked": True}
        if result.denied:
            return {"error": "User denied execution", "denied": True}
        if result.error:
            return {"error": redact_secrets(result.error), "returncode": result.returncode}

        out: dict[str, Any] = {"returncode": result.returncode}
        if result.stdout:
            out["stdout"] = redact_secrets(result.stdout)
        if result.stderr:
            out["stderr"] = redact_secrets(result.stderr)
        return out


BASH_TOOL_DEFINITION: dict[str, Any] = load_tool_definition("run_bash")
