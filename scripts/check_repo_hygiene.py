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
    python scripts/check_repo_hygiene.py free-merged-worktree --pr N --worktree PATH

Exits 0 if clean, 1 on violations (details on stderr).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
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
        "redacted",  # /Users/REDACTED — the artifact masker's anonymized home sentinel
        # Single-letter / second-person placeholders (a real docstring example
        # ``/Users/x/dev`` tripped the ratchet on PR #2468):
        "x",
        "y",
        "you",
        "yourname",
        "username",
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
    try:
        proc = _run(
            ["git", "grep", "-nIE", r"/(Users|home)/[A-Za-z]", "--", ":!*.lock"],
            cwd=root,
            check=False,
        )
    except CleanupError:
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
        for leak_path, lineno, username in home_leaks:
            lines.append(f"  {leak_path}:{lineno} -> /Users|home/{username}/...")
        lines.append(
            "    hint: anonymize the home prefix (~/...) — a real username path "
            "leaks the operator's machine and breaks portability. If this is a "
            "placeholder, add the username to _PLACEHOLDER_USERS.",
        )
        lines.append("")
    return "\n".join(lines)


class CleanupError(RuntimeError):
    """The requested worktree is not safe to remove."""


def _run(
    argv: list[str],
    *,
    cwd: Path,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which(argv[0])
    if executable is None:
        raise CleanupError(f"required command is unavailable: {argv[0]}")
    try:
        result = subprocess.run(  # noqa: S603 - executable is resolved; argv is not shell-expanded
            [executable, *argv[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CleanupError(f"{' '.join(argv)} failed: {exc}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise CleanupError(f"{' '.join(argv)} failed: {detail}")
    return result


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=root, check=check)


def _registered_branch(root: Path, target: Path) -> str:
    blocks = _git(root, "worktree", "list", "--porcelain").stdout.strip().split("\n\n")
    target_resolved = target.resolve()
    for block in blocks:
        values = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
        worktree = values.get("worktree")
        branch = values.get("branch", "")
        if worktree and Path(worktree).resolve() == target_resolved:
            prefix = "refs/heads/"
            if not branch.startswith(prefix):
                raise CleanupError("detached worktrees are not eligible for automatic cleanup")
            return branch.removeprefix(prefix)
    raise CleanupError(f"not a registered worktree: {target}")


def _owner_metadata(target: Path) -> dict[str, str]:
    owner_file = target / ".owner"
    if not owner_file.is_file():
        raise CleanupError(f"missing ownership record: {owner_file}")
    metadata: dict[str, str] = {}
    for token in shlex.split(owner_file.read_text(encoding="utf-8")):
        key, separator, value = token.partition("=")
        if separator:
            metadata[key] = value
    if metadata.get("task_id") != target.name:
        raise CleanupError(
            "owner task_id does not match worktree name: "
            f"{metadata.get('task_id')!r} != {target.name!r}"
        )
    return metadata


def _pr_details(root: Path, pr_number: int) -> dict[str, object]:
    result = _run(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "state,headRefName,headRefOid,mergeCommit,url",
        ],
        cwd=root,
    )
    try:
        parsed: object = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CleanupError("gh returned invalid PR metadata") from exc
    if not isinstance(parsed, dict) or not all(isinstance(key, str) for key in parsed):
        raise CleanupError("gh returned invalid PR metadata")
    return {str(key): value for key, value in parsed.items()}


def _remote_head(root: Path, branch: str) -> str | None:
    result = _git(root, "ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if not result.stdout.strip():
        return None
    return result.stdout.split(maxsplit=1)[0]


def free_merged_worktree(*, root: Path, target: Path, pr_number: int, dry_run: bool) -> None:
    """Verify and remove a feature worktree whose PR was squash-merged."""
    root = root.resolve()
    target = target.resolve()
    if Path.cwd().resolve().is_relative_to(target):
        raise CleanupError("run cleanup from outside the target worktree")

    branch = _registered_branch(root, target)
    if branch in {"main", "develop"}:
        raise CleanupError(f"protected branch worktree cannot be freed: {branch}")
    owner = _owner_metadata(target)
    if _git(target, "status", "--porcelain", "--untracked-files=all").stdout.strip():
        raise CleanupError("target worktree has tracked or untracked changes")

    details = _pr_details(root, pr_number)
    if details.get("state") != "MERGED":
        raise CleanupError(f"PR #{pr_number} is not merged")
    if details.get("headRefName") != branch:
        raise CleanupError(
            f"PR head does not match worktree branch: {details.get('headRefName')!r} != {branch!r}"
        )
    merge_commit = details.get("mergeCommit")
    if not isinstance(merge_commit, dict):
        raise CleanupError("PR metadata is missing merge commit")
    merge_oid = merge_commit.get("oid")
    expected_head_oid = details.get("headRefOid")
    if not isinstance(merge_oid, str) or not isinstance(expected_head_oid, str):
        raise CleanupError("PR metadata is missing merge or head commit")

    _git(root, "fetch", "origin", "--prune")
    temporary_ref = f"refs/geode/cleanup/pr-{pr_number}-head"
    try:
        _git(
            root,
            "fetch",
            "--quiet",
            "origin",
            f"+refs/pull/{pr_number}/head:{temporary_ref}",
        )
        fetched_head_oid = _git(root, "rev-parse", temporary_ref).stdout.strip()
        if fetched_head_oid != expected_head_oid:
            raise CleanupError("GitHub PR head changed while cleanup was being verified")
        head_tree = _git(root, "rev-parse", f"{temporary_ref}^{{tree}}").stdout.strip()
        merge_tree = _git(root, "rev-parse", f"{merge_oid}^{{tree}}").stdout.strip()
        if head_tree != merge_tree:
            raise CleanupError("merged PR tree differs from its final feature head")

        local_oid = _git(root, "rev-parse", branch).stdout.strip()
        ancestry = _git(
            root,
            "merge-base",
            "--is-ancestor",
            local_oid,
            fetched_head_oid,
            check=False,
        )
        if ancestry.returncode != 0:
            raise CleanupError("local branch contains commits outside the merged PR head")

        remote_oid = _remote_head(root, branch)
        if remote_oid is not None and remote_oid != fetched_head_oid:
            raise CleanupError("remote branch advanced beyond the merged PR head")

        summary = (
            f"verified PR #{pr_number}: branch={branch} "
            f"owner={owner.get('session', 'unknown')} worktree={target}"
        )
        if dry_run:
            print(f"dry-run: {summary}")
            return

        if remote_oid is not None:
            _git(
                root,
                "push",
                f"--force-with-lease=refs/heads/{branch}:{fetched_head_oid}",
                "origin",
                "--delete",
                branch,
            )
        _git(root, "worktree", "remove", str(target))
        _git(root, "update-ref", "-d", f"refs/heads/{branch}", local_oid)
        _git(root, "fetch", "origin", "--prune")
        _git(root, "worktree", "prune")
        print(f"freed: {summary}")
    finally:
        _git(root, "update-ref", "-d", temporary_ref, check=False)


def _free_worktree_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=free_merged_worktree.__doc__)
    parser.add_argument("--pr", type=int, required=True, help="merged feature PR number")
    parser.add_argument("--worktree", type=Path, required=True, help="target worktree path")
    parser.add_argument("--dry-run", action="store_true", help="verify without deleting anything")
    args = parser.parse_args(argv)
    try:
        common_dir = Path(
            _git(
                Path.cwd(),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ).stdout.strip()
        )
        root = common_dir.resolve().parent
        target = args.worktree if args.worktree.is_absolute() else root / args.worktree
        free_merged_worktree(
            root=root,
            target=target,
            pr_number=args.pr,
            dry_run=args.dry_run,
        )
    except CleanupError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        if argv[0] == "free-merged-worktree":
            return _free_worktree_main(argv[1:])
        print(f"unknown command: {argv[0]}", file=sys.stderr)
        return 2

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
