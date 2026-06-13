#!/usr/bin/env python3
"""CI ratchet: reject repo-shape regressions.

Checks
------
- Dangling symlinks (target does not exist).
- Absolute symlinks (path leaks to a specific machine).
- Orphan worktrees (.claude/worktrees/<name>/ missing .owner).
- Petri bundle file-count ratchet — guards docs/self-improving/petri-bundle/logs/*.eval
  against accidental deletion during non-petri refactors. The PR that
  drops bundle archives must also lower the floor here, making the
  removal explicit (Karpathy P4 Ratchet).

Usage:
    python scripts/check_repo_hygiene.py

Exits 0 if clean, 1 on violations (details on stderr).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Lower bound for archive files under docs/self-improving/petri-bundle/logs/. Pinned to
# the count present on main (9 .eval archives, see audits PR #1130). Raise
# this number when adding archives; lowering it requires explicit review.
PETRI_EVAL_FLOOR = 9
PETRI_LOGS_DIR = Path("docs/self-improving/petri-bundle/logs")

# Absolute home paths with a REAL username (``/Users/<u>/`` or ``/home/<u>/``)
# are a machine-specific PII leak: they break portability AND expose the
# operator's home dir on the public GitHub-Pages site when they ride along in
# published run artifacts (docs/self-improving/**). Most enter via the
# state/ -> docs/ hub sync, which copies run_dir / candidate_path / transcript
# strings verbatim. This ratchet (Karpathy P4) rejects them so a re-sync must
# anonymize the prefix (the reconcile precedent already writes bundle-relative
# paths for survivors.json). Generic placeholder usernames used in docs/tests
# (``/Users/<name>``, ``/home/user``, ``foo`` ...) are allowed.
# Scoped to POSIX paths (macOS / Linux). The username segment need NOT be
# followed by ``/`` — a bare ``/Users/<name>`` at the end of a token still
# leaks the prefix (Codex review). Case-insensitive so a capitalised
# ``/Users/<Name>`` is caught; the allow-list comparison lower-cases the
# capture. Windows ``C:\\Users\\`` is intentionally out of scope (POSIX-only).
_HOME_PATH_RE = re.compile(r"/(?:Users|home)/([A-Za-z][A-Za-z0-9_.-]*)")
_PLACEHOLDER_USERS: frozenset[str] = frozenset(
    {
        "user",
        "users",
        "dev",
        "somebody",
        "foo",
        "bar",
        "name",
        "example",
        "test",
        "runner",
        "u",
        "ci",
        "root",
        "alice",
        "bob",
        "jane",
        "home",
        "shared",  # /Users/Shared — macOS system dir, not a username
    }
)

EXCLUDED_DIRS: frozenset[tuple[str, ...]] = frozenset(
    {
        (".git",),
        (".venv",),
        (".release-venv",),
        ("node_modules",),
        (".claude", "worktrees"),
    }
)


def is_excluded_for_symlink_scan(rel: Path) -> bool:
    """True if `rel` lives under any excluded directory."""
    parts = rel.parts
    for prefix in EXCLUDED_DIRS:
        if len(parts) >= len(prefix) and parts[: len(prefix)] == prefix:
            return True
    return False


# Called once per symlink check so each finder stays independently testable;
# the repo is small enough that the duplicate walk is a non-concern.
def _iter_symlinks(root: Path) -> list[Path]:
    """Return every symlink under `root`, pruning excluded subtrees."""
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_current = current.relative_to(root)
        dirnames[:] = [d for d in dirnames if not is_excluded_for_symlink_scan(rel_current / d)]
        for name in filenames + dirnames:
            candidate = current / name
            if candidate.is_symlink():
                found.append(candidate)
    return found


def find_dangling_symlinks(root: Path) -> list[tuple[Path, str]]:
    """Return (path, target) for each symlink whose target does not exist."""
    result: list[tuple[Path, str]] = []
    for link in _iter_symlinks(root):
        target = os.readlink(link)
        if not link.exists():
            result.append((link, target))
    return result


def find_absolute_symlinks(root: Path) -> list[tuple[Path, str]]:
    """Return (path, target) for each symlink whose target is an absolute path."""
    result: list[tuple[Path, str]] = []
    for link in _iter_symlinks(root):
        target = os.readlink(link)
        if target.startswith("/"):
            result.append((link, target))
    return result


def find_home_path_leaks(root: Path) -> list[tuple[str, int, str]]:
    """Return (relpath, lineno, username) for each tracked file embedding an
    absolute home path with a real (non-placeholder) username.

    Scans tracked files only (``git grep`` respects .gitignore + skips binary
    with ``-I``); ``*.lock`` is excluded because the editable self-reference
    legitimately carries the absolute checkout path. Placeholder usernames in
    :data:`_PLACEHOLDER_USERS` (and angle-bracket forms like ``/Users/<name>``,
    which the leading-``[a-z]`` anchor already rejects) are allowed."""
    git = shutil.which("git")
    if git is None:
        return []  # git unavailable — nothing to assert
    try:
        proc = subprocess.run(  # noqa: S603 — resolved git path, fixed argv + constant regex
            [git, "grep", "-nIE", r"/(Users|home)/[A-Za-z]", "--", ":!*.lock"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []  # not a git checkout — nothing to assert
    leaks: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        path, _, rest = line.partition(":")
        lineno_s, _, content = rest.partition(":")
        if not lineno_s.isdigit():
            continue
        for match in _HOME_PATH_RE.finditer(content):
            username = match.group(1)
            if username.lower() not in _PLACEHOLDER_USERS:
                leaks.append((path, int(lineno_s), username))
                break  # one finding per line is enough to flag it
    return leaks


def check_petri_eval_floor(root: Path) -> tuple[int, int] | None:
    """Return (found, floor) when below the petri archive floor, else None.

    Returns None if the bundle directory is absent (fresh clones for unrelated
    work shouldn't fail). The validator script enforces correctness when the
    bundle is present; this ratchet only catches deletions.
    """
    logs_dir = root / PETRI_LOGS_DIR
    if not logs_dir.is_dir():
        return None
    count = sum(1 for entry in logs_dir.iterdir() if entry.is_file() and entry.suffix == ".eval")
    if count < PETRI_EVAL_FLOOR:
        return (count, PETRI_EVAL_FLOOR)
    return None


def find_orphan_worktrees(root: Path) -> list[Path]:
    """Return each .claude/worktrees/<name>/ directory missing an `.owner` file."""
    worktrees_dir = root / ".claude" / "worktrees"
    if not worktrees_dir.is_dir():
        return []
    orphans: list[Path] = []
    for entry in sorted(worktrees_dir.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / ".owner").is_file():
            orphans.append(entry)
    return orphans


def format_report(
    root: Path,
    dangling: list[tuple[Path, str]],
    absolute: list[tuple[Path, str]],
    orphans: list[Path],
    petri_shortfall: tuple[int, int] | None,
    home_leaks: list[tuple[str, int, str]],
) -> str:
    total = (
        len(dangling)
        + len(absolute)
        + len(orphans)
        + (1 if petri_shortfall else 0)
        + len(home_leaks)
    )
    if total == 0:
        return ""
    lines = [f"Repo hygiene check: {total} issues", ""]
    if dangling:
        lines.append("[dangling symlink]")
        for path, target in dangling:
            lines.append(f"  {path.relative_to(root)} -> {target}")
        lines.append("")
    if absolute:
        lines.append("[absolute symlink]")
        for path, target in absolute:
            lines.append(f"  {path.relative_to(root)} -> {target}")
            lines.append("    hint: use relative path (ln -sr)")
        lines.append("")
    if orphans:
        lines.append("[orphan worktree]")
        for path in orphans:
            lines.append(f"  {path.relative_to(root)}/")
            lines.append("    hint: missing .owner file; remove worktree or add .owner")
        lines.append("")
    if petri_shortfall:
        found, floor = petri_shortfall
        lines.append("[petri bundle deletion]")
        lines.append(
            f"  {PETRI_LOGS_DIR}/ has {found} .eval archive(s); floor is {floor}.",
        )
        lines.append(
            "    hint: dropping archives must lower PETRI_EVAL_FLOOR in this script "
            "in the same PR (explicit-action ratchet).",
        )
        lines.append("")
    if home_leaks:
        lines.append("[hardcoded home path]")
        for path, lineno, username in home_leaks:
            lines.append(f"  {path}:{lineno} -> /Users|home/{username}/...")
        lines.append(
            "    hint: anonymize the home prefix (~/...) — a real username path "
            "leaks the operator's machine and breaks portability. If this is a "
            "placeholder, add the username to _PLACEHOLDER_USERS.",
        )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    root = Path.cwd()
    dangling = find_dangling_symlinks(root)
    absolute = find_absolute_symlinks(root)
    orphans = find_orphan_worktrees(root)
    petri_shortfall = check_petri_eval_floor(root)
    home_leaks = find_home_path_leaks(root)
    report = format_report(root, dangling, absolute, orphans, petri_shortfall, home_leaks)
    if report:
        print(report, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
