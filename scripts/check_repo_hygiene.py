#!/usr/bin/env python3
"""CI ratchet: reject repo-shape regressions.

Checks
------
- Dangling symlinks (target does not exist).
- Absolute symlinks (path leaks to a specific machine).
- Orphan worktrees (.claude/worktrees/<name>/ missing .owner).
- Petri bundle file-count ratchet — guards docs/petri-bundle/logs/*.eval
  against accidental deletion during non-petri refactors. The PR that
  drops bundle archives must also lower the floor here, making the
  removal explicit (Karpathy P4 Ratchet).

Usage:
    python scripts/check_repo_hygiene.py

Exits 0 if clean, 1 on violations (details on stderr).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Lower bound for archive files under docs/petri-bundle/logs/. Pinned to
# the count present on main (9 .eval archives, see audits PR #1130). Raise
# this number when adding archives; lowering it requires explicit review.
PETRI_EVAL_FLOOR = 9
PETRI_LOGS_DIR = Path("docs/petri-bundle/logs")

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
) -> str:
    total = len(dangling) + len(absolute) + len(orphans) + (1 if petri_shortfall else 0)
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
    return "\n".join(lines)


def main() -> int:
    root = Path.cwd()
    dangling = find_dangling_symlinks(root)
    absolute = find_absolute_symlinks(root)
    orphans = find_orphan_worktrees(root)
    petri_shortfall = check_petri_eval_floor(root)
    report = format_report(root, dangling, absolute, orphans, petri_shortfall)
    if report:
        print(report, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
