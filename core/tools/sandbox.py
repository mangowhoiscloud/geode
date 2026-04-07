"""Centralized path validation for file tools — Claude Code parity.

Provides multi-layer security validation following Claude Code patterns:
  1. Shell expansion syntax blocking (TOCTOU prevention)
  2. Symlink chain resolution with intermediate validation
  3. macOS path normalization (/private/var ↔ /var)
  4. Dangerous file/directory blocking
  5. Glob pattern blocking in write operations
  6. Containment check against allowed working directories

All file tools (Glob, Grep, Edit, Write, ReadDocument) delegate to
``validate_path()`` instead of implementing inline sandbox checks.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from core.paths import get_project_root

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Claude Code filesystem.ts parity
# ---------------------------------------------------------------------------

DANGEROUS_FILES: frozenset[str] = frozenset(
    {
        ".gitconfig",
        ".gitmodules",
        ".bashrc",
        ".bash_profile",
        ".zshrc",
        ".zprofile",
        ".profile",
        ".ripgreprc",
        ".mcp.json",
        ".claude.json",
    }
)

DANGEROUS_DIRECTORIES: frozenset[str] = frozenset(
    {
        ".git",
        ".vscode",
        ".idea",
        ".claude",
    }
)

_MAX_SYMLINK_DEPTH = 40  # SYMLOOP_MAX

# Shell expansion patterns — block before Path construction
_SHELL_EXPANSION_CHARS = re.compile(r"[$%]")
_ZSH_EQUALS_PREFIX = re.compile(r"^=\w")
_TILDE_VARIANT = re.compile(r"^~[^/\\]")  # ~user, ~+, ~-, ~N (only ~ and ~/ allowed)

# Glob characters blocked in write paths
_GLOB_CHARS = re.compile(r"[*?\[\]{}]")

# macOS /private normalization
_PRIVATE_VAR_RE = re.compile(r"^/private/var/")
_PRIVATE_TMP_RE = re.compile(r"^/private/tmp(/|$)")

# ---------------------------------------------------------------------------
# Session-scoped additional working directories (G1 — Phase 3 wires this)
# ---------------------------------------------------------------------------

_additional_dirs: list[Path] = []


def add_working_directory(path: Path) -> None:
    """Add a session-scoped working directory to the sandbox allowlist."""
    resolved = path.resolve()
    if resolved not in _additional_dirs:
        _additional_dirs.append(resolved)
        log.info("Sandbox: added working directory %s", resolved)


def remove_working_directory(path: Path) -> None:
    """Remove a session-scoped working directory from the sandbox allowlist."""
    resolved = path.resolve()
    if resolved in _additional_dirs:
        _additional_dirs.remove(resolved)
        log.info("Sandbox: removed working directory %s", resolved)


def get_all_working_directories() -> list[Path]:
    """Return all allowed working directories (project root + additional)."""
    return [get_project_root(), *_additional_dirs]


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def normalize_macos_path(path_str: str) -> str:
    """Normalize macOS symlink aliases: /private/var → /var, /private/tmp → /tmp.

    Applied bilaterally (to both input paths and working directories) to ensure
    symmetric comparison.  Follows Claude Code filesystem.ts pathInWorkingPath().
    """
    result = _PRIVATE_VAR_RE.sub("/var/", path_str)
    result = _PRIVATE_TMP_RE.sub(lambda m: f"/tmp{m.group(1)}", result)  # noqa: S108  # nosec B108 — intentional macOS normalization
    return result


def check_shell_expansion(path_str: str) -> dict[str, Any] | None:
    """Block paths containing shell expansion syntax (TOCTOU prevention).

    Rejects: $VAR, ${VAR}, $(cmd), %VAR%, =cmd (Zsh), ~user, ~+, ~-.
    Only bare ~ and ~/ are allowed (expanded by Python, not shell).
    """
    from core.tools.base import tool_error

    if _SHELL_EXPANSION_CHARS.search(path_str):
        return tool_error(
            f"Shell expansion syntax not allowed in path: {path_str!r}",
            error_type="permission",
            recoverable=False,
            hint="Use a literal path without $, %, or shell variables.",
        )
    if _ZSH_EQUALS_PREFIX.match(path_str):
        return tool_error(
            f"Zsh equals expansion not allowed in path: {path_str!r}",
            error_type="permission",
            recoverable=False,
            hint="Use the full path instead of =command syntax.",
        )
    if _TILDE_VARIANT.match(path_str):
        return tool_error(
            f"Tilde expansion variant not allowed: {path_str!r}",
            error_type="permission",
            recoverable=False,
            hint="Only ~ and ~/ are supported.  Use the full path.",
        )
    return None


def check_dangerous_path(path: Path, *, write: bool) -> dict[str, Any] | None:
    """Block writes to dangerous files and directories.

    Read access is allowed; only write/edit operations are blocked.
    Matches Claude Code's DANGEROUS_FILES and DANGEROUS_DIRECTORIES.
    """
    if not write:
        return None

    from core.tools.base import tool_error

    # Check filename
    if path.name.lower() in {f.lower() for f in DANGEROUS_FILES}:
        return tool_error(
            f"Write access denied to dangerous file: {path.name}",
            error_type="permission",
            recoverable=False,
            hint=(
                f"Files like {path.name} can alter system behavior.  "
                "Read access is allowed but writes are blocked."
            ),
        )

    # Check directory components
    for part in path.parts:
        if part.lower() in {d.lower() for d in DANGEROUS_DIRECTORIES}:
            return tool_error(
                f"Write access denied to dangerous directory: {part}/",
                error_type="permission",
                recoverable=False,
                hint=(
                    f"The {part}/ directory is protected.  "
                    "Read access is allowed but writes are blocked."
                ),
            )

    return None


def check_glob_in_write(path_str: str) -> dict[str, Any] | None:
    """Block glob characters in write operation paths."""
    from core.tools.base import tool_error

    if _GLOB_CHARS.search(path_str):
        return tool_error(
            f"Glob patterns not allowed in write path: {path_str!r}",
            error_type="validation",
            recoverable=False,
            hint="Specify an exact file path without *, ?, [, ], {{, }}.",
        )
    return None


@lru_cache(maxsize=1024)
def _resolve_symlink_cached(path_str: str) -> tuple[str, str | None]:
    """Resolve a symlink path and return (resolved_str, error_msg_or_none).

    Cached to avoid repeated filesystem calls for the same path.
    """
    path = Path(path_str)
    if not path.exists() and not path.is_symlink():
        return (path_str, None)  # Non-existent — let caller handle

    visited: set[str] = set()
    current = path

    for _depth in range(_MAX_SYMLINK_DEPTH):
        current_str = str(current)
        if current_str in visited:
            return ("", f"Circular symlink detected: {path_str}")
        visited.add(current_str)

        if not current.is_symlink():
            break

        try:
            target = current.resolve()
        except (RuntimeError, OSError):
            return ("", f"Circular symlink detected: {path_str}")
        current = target
    else:
        return ("", f"Symlink chain too deep (>{_MAX_SYMLINK_DEPTH}): {path_str}")

    return (str(current.resolve()), None)


def resolve_symlink_chain(
    path: Path,
    allowed_roots: list[Path],
) -> Path | dict[str, Any]:
    """Resolve symlink chain and validate each intermediate is within allowed roots.

    Returns resolved Path on success, or tool_error dict on failure.
    """
    from core.tools.base import tool_error

    resolved_str, err = _resolve_symlink_cached(str(path))
    if err:
        return tool_error(
            err,
            error_type="permission",
            recoverable=False,
            hint="Resolve circular or overly deep symlinks manually.",
        )

    resolved = Path(resolved_str)

    # Validate resolved path is within at least one allowed root
    if not _path_in_allowed_roots(resolved, allowed_roots):
        return tool_error(
            f"Symlink resolves outside sandbox: {path} -> {resolved}",
            error_type="permission",
            recoverable=False,
            hint="The symlink target must be within the project directory.",
        )

    return resolved


def _path_in_allowed_roots(path: Path, allowed_roots: list[Path]) -> bool:
    """Check if a path is contained within any of the allowed roots.

    Uses macOS normalization for bilateral comparison.
    """
    normalized_path = normalize_macos_path(str(path)).lower()

    for root in allowed_roots:
        normalized_root = normalize_macos_path(str(root)).lower()
        # Check: path starts with root (with trailing separator for safety)
        if normalized_path == normalized_root:
            return True
        if normalized_path.startswith(normalized_root + "/"):
            return True

    return False


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def validate_path(
    path_str: str,
    *,
    write: bool = False,
    allowed_roots: list[Path] | None = None,
) -> Path | dict[str, Any]:
    """Validate and resolve a file path through the full security pipeline.

    Returns a resolved Path on success, or a tool_error dict on failure.

    Pipeline order (Claude Code parity):
      1. Shell expansion blocking
      2. Glob-in-write blocking
      3. Path construction + symlink resolution
      4. macOS normalization + containment check
      5. Dangerous file/directory blocking

    Args:
        path_str: Raw path string from tool input.
        write: True for write/edit operations, False for read-only.
        allowed_roots: Working directories for containment check.
            Defaults to ``get_all_working_directories()``.
    """
    from core.tools.base import tool_error

    roots = allowed_roots if allowed_roots is not None else get_all_working_directories()

    # 1. Shell expansion blocking
    err = check_shell_expansion(path_str)
    if err:
        return err

    # 2. Glob-in-write blocking
    if write:
        err = check_glob_in_write(path_str)
        if err:
            return err

    # 3. Construct path — resolve relative to project root
    path = Path(path_str)
    if not path.is_absolute():
        path = get_project_root() / path

    # 4. Symlink resolution + containment
    if path.is_symlink():
        result = resolve_symlink_chain(path, roots)
        if isinstance(result, dict):
            return result
        resolved = result
    else:
        resolved = path.resolve()
        if not _path_in_allowed_roots(resolved, roots):
            return tool_error(
                f"Access denied: path outside project directory ({roots[0]})",
                error_type="permission",
                recoverable=False,
                hint=(
                    "All file tools are sandboxed to the project directory.  "
                    "Use a relative path or omit the path parameter."
                ),
            )

    # 5. Dangerous file/directory blocking (writes only)
    err = check_dangerous_path(resolved, write=write)
    if err:
        return err

    return resolved
