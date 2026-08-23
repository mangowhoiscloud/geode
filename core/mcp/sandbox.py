"""Deny-default OS sandbox argv for capability-confined MCP servers."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path, PurePosixPath

from core.tools.bash_sandbox import sandbox_binary_status

_SYSTEM_ROOTS = ("/System", "/usr", "/bin", "/sbin", "/lib", "/lib64")
_SANDBOX_TMP = str(PurePosixPath("/") / "tmp")
_TRUSTED_BWRAP_PATHS = frozenset({"/usr/bin/bwrap", "/usr/local/bin/bwrap", "/bin/bwrap"})

_MACOS_PROFILE = """(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow signal (target same-sandbox))
(allow process-info* (target same-sandbox))
(allow sysctl-read)
(allow mach-lookup
  (global-name "com.apple.system.opendirectoryd.libinfo")
  (global-name "com.apple.cfprefsd.daemon"))
(allow file-test-existence)
(allow file-read* (subpath (param "SCRATCH")))
(allow file-write* (subpath (param "SCRATCH")))
(allow file-read* (literal (param "COMMAND")))
(allow file-read* (subpath "/System"))
(allow file-read* (subpath "/usr"))
(allow file-read* (subpath "/bin"))
(allow file-read* (subpath "/sbin"))
"""


def resolve_mcp_sandbox_argv(
    command: str,
    args: list[str],
    *,
    scratch: Path,
) -> tuple[list[str] | None, str | None]:
    """Return strict sandbox argv or a reason the server must not launch."""
    resolved = shutil.which(command)
    if resolved is None:
        return None, f"MCP command not found: {command}"
    resolved = os.path.realpath(resolved)
    binary_name, sandbox = sandbox_binary_status()
    if sandbox is None:
        return None, f"{binary_name} unavailable for brokered MCP execution"

    platform = str(sys.platform)
    if platform == "darwin":
        return (
            [
                sandbox,
                "-p",
                _MACOS_PROFILE,
                "-D",
                f"SCRATCH={scratch}",
                "-D",
                f"COMMAND={resolved}",
                "--",
                resolved,
                *args,
            ],
            None,
        )

    if platform.startswith("linux"):
        sandbox = os.path.realpath(sandbox)
        if sandbox not in _TRUSTED_BWRAP_PATHS:
            return None, f"untrusted bwrap path: {sandbox}"
        allowed_root = next(
            (root for root in _SYSTEM_ROOTS if Path(resolved).is_relative_to(root)),
            None,
        )
        if allowed_root is None:
            return None, f"brokered MCP command is outside system roots: {resolved}"
        argv = [
            sandbox,
            "--unshare-all",
            "--new-session",
            "--die-with-parent",
        ]
        for root in _SYSTEM_ROOTS:
            if os.path.exists(root):
                argv.extend(("--ro-bind", root, root))
        argv.extend(
            (
                "--tmpfs",
                _SANDBOX_TMP,
                "--dir",
                "/work",
                "--chdir",
                "/work",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--",
                resolved,
                *args,
            )
        )
        return argv, None

    return None, f"platform {platform} has no brokered MCP sandbox"


__all__ = ["resolve_mcp_sandbox_argv"]
