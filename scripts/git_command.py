"""Small, shell-free boundary for repository maintenance scripts."""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path


class GitExecutableNotFoundError(RuntimeError):
    """Raised when a maintenance script cannot resolve the Git executable."""


def run_git(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a fixed Git subcommand as an argv sequence and capture its result."""
    executable = shutil.which("git")
    if executable is None:
        raise GitExecutableNotFoundError
    return subprocess.run(  # noqa: S603 - resolved executable; shell interpretation is disabled
        [executable, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
