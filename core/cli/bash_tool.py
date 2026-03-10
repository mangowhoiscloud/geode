"""BashTool — execute shell commands with HITL approval gate.

Provides a safe shell execution interface for the agentic loop.
Dangerous patterns are blocked outright; all other commands require
explicit user approval before execution.
"""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)

# Max output sizes to prevent flooding
_MAX_STDOUT = 10_000
_MAX_STDERR = 5_000
_DEFAULT_TIMEOUT = 30


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
    re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
    re.compile(r"sudo\s+", re.IGNORECASE),
    re.compile(r">\s*/etc/", re.IGNORECASE),
    re.compile(r"curl.*\|\s*(?:ba)?sh", re.IGNORECASE),
    re.compile(r"wget.*\|\s*(?:ba)?sh", re.IGNORECASE),
    re.compile(r"mkfs\.", re.IGNORECASE),
    re.compile(r"dd\s+if=.*of=/dev/", re.IGNORECASE),
    re.compile(r"chmod\s+-R\s+777\s+/", re.IGNORECASE),
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
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self._working_dir,
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
        """Convert BashResult to a dict suitable for LLM tool_result."""
        if result.blocked:
            return {"error": result.error, "blocked": True}
        if result.denied:
            return {"error": "User denied execution", "denied": True}
        if result.error:
            return {"error": result.error, "returncode": result.returncode}

        out: dict[str, Any] = {"returncode": result.returncode}
        if result.stdout:
            out["stdout"] = result.stdout
        if result.stderr:
            out["stderr"] = result.stderr
        return out


# Tool definition exposed to the LLM
BASH_TOOL_DEFINITION: dict[str, Any] = {
    "name": "run_bash",
    "description": (
        "Execute a shell command on the user's local machine. "
        "REQUIRES user approval before execution. "
        "Use for: file operations, system checks, data processing. "
        "DO NOT use for: destructive operations, privilege escalation."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute",
            },
            "reason": {
                "type": "string",
                "description": "Why this command is needed",
            },
        },
        "required": ["command", "reason"],
    },
}
