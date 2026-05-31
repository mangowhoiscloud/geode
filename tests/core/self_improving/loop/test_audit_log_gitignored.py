"""G5b.fix1 (2026-05-20) — mutations.jsonl must NOT be git-ignored.

The G5b self-improving-loop runner appends every applied wrapper-prompt
mutation to ``autoresearch/state/mutations.jsonl`` and calls
``_git_commit_audit_log`` to stage + commit the row. The Codex MCP
LLM-as-Judge audit on 2026-05-20 found that ``.gitignore`` matched
``autoresearch/state/*`` and silently ignored the ledger; the runner's
``git add`` then no-op'd, and the CHANGELOG's "git-tracked audit log"
claim was false.

These tests pin the negation in ``.gitignore`` so the ledger really
enters git history.

Test strategy: two independent checks.

1. **File-content guard** — read the repo ``.gitignore`` and assert
   the negation line is present. Cheap, runs in <1ms.
2. **Behavioural guard** — shell out to ``git check-ignore`` (when
   git is available in the test env) and assert the exit code is 1
   (= not ignored). Costlier but catches subtler regressions like a
   later ``*.jsonl`` glob that re-ignores the ledger.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# tests/core/self_improving/loop/test_audit_log_gitignored.py → parents[4] = repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _read_gitignore() -> str:
    return (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")


def test_gitignore_has_mutations_negation() -> None:
    """``.gitignore`` carries the explicit negation for the mutation ledger."""
    text = _read_gitignore()
    assert "!autoresearch/state/mutations.jsonl" in text, (
        "G5b.fix1 regression: the mutation audit log negation is missing from "
        ".gitignore — `git add autoresearch/state/mutations.jsonl` would fail "
        "silently and the runner's git-as-optimiser ledger would never enter "
        "history. Add `!autoresearch/state/mutations.jsonl` AFTER the "
        "`autoresearch/state/*` line."
    )


def test_gitignore_state_glob_still_present() -> None:
    """The base ignore of ``autoresearch/state/*`` is preserved.

    The negation should be additive, not a wholesale removal of the
    ignore (which would leak run logs, baseline.json snapshots, etc.).
    """
    text = _read_gitignore()
    assert "autoresearch/state/*" in text, (
        "The base ignore rule for `autoresearch/state/*` is missing. The "
        "G5b.fix1 negation must coexist with the base ignore; otherwise "
        "stale run.log / audit_logs/ / baseline.json files leak into commits."
    )


def test_git_check_ignore_says_mutations_not_ignored() -> None:
    """Behavioural check via ``git check-ignore`` — exit 1 = not ignored."""
    try:
        result = subprocess.run(  # nosec B603 — argv hard-coded
            ["git", "check-ignore", "autoresearch/state/mutations.jsonl"],  # noqa: S607  # nosec B607
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("git binary not available in test environment")
    assert result.returncode == 1, (
        "git check-ignore considers autoresearch/state/mutations.jsonl "
        f"ignored (exit={result.returncode}, stdout={result.stdout!r}). "
        "The G5b.fix1 negation in .gitignore is not effective — perhaps a "
        "later glob (`*.jsonl`?) re-ignores it."
    )


def test_git_check_ignore_still_ignores_baseline() -> None:
    """Sanity: baseline.json (and other state/ artifacts) still ignored."""
    try:
        result = subprocess.run(  # nosec B603 — argv hard-coded
            ["git", "check-ignore", "autoresearch/state/baseline.json"],  # noqa: S607  # nosec B607
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        pytest.skip("git binary not available in test environment")
    assert result.returncode == 0, (
        "Sanity check failed: autoresearch/state/baseline.json should still "
        "be ignored (exit 0 from `git check-ignore`), but got "
        f"exit={result.returncode}. The G5b.fix1 negation may have leaked "
        "into a too-broad rule."
    )
