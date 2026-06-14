"""The mutation ledger (tracked SoT) must enter git history; runtime scratch must not.

History: G5b.fix1 (2026-05-20) — a Codex MCP LLM-as-Judge audit found
``.gitignore`` swept the ledger under a broad ``state/autoresearch/*`` glob, so
the runner's ``git add`` silently no-op'd and the CHANGELOG's "git-tracked audit
log" claim was false. The fix was a ``!...mutations.jsonl`` negation re-including
it.

PR-STATE-SOT-RUNTIME-SPLIT (2026-06-14) retired that whole negation dance. The
tracked SoT (``mutations.jsonl`` / ``baseline_archive.jsonl`` / ``results.*`` /
``policies/``) moved IN-REPO to ``core/self_improving/state/`` — under ``core/``,
which nothing ignores, so it is *naturally* git-tracked with no negation. The
RUNTIME scratch (``baseline.json``, ``run.log``, per-run ``seed_generation/``)
moved OUT of the repo to ``~/.geode/self-improving/`` — so it is structurally
impossible to commit, no gitignore rule required.

These tests pin both halves of that split:
1. the tracked ledger really is not ignored (behavioural ``git check-ignore``),
2. the runtime baseline lives outside the repo tree (structural).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

# tests/core/self_improving/loop/test_audit_log_gitignored.py → parents[4] = repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]


def _check_ignore(repo_relative: str) -> subprocess.CompletedProcess[str] | None:
    """Run ``git check-ignore`` from the repo root; None if git is unavailable."""
    try:
        return subprocess.run(  # noqa: S603  # nosec B603 — argv hard-coded
            ["git", "check-ignore", repo_relative],  # noqa: S607  # nosec B607
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None


def test_gitignore_no_longer_carries_state_negation_dance() -> None:
    """The retired negation dance must be GONE from ``.gitignore``.

    Architecture pin: after the SoT moved under ``core/`` the old
    ``state/autoresearch/*`` ignore + ``!...mutations.jsonl`` negation are dead.
    Their reappearance would mean someone re-created a top-level ``state/`` home
    and re-introduced the silent-ignore footgun the split removed.
    """
    text = (_REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "state/autoresearch/*" not in text, (
        "The retired `state/autoresearch/*` ignore glob is back in .gitignore — "
        "the tracked SoT now lives under core/self_improving/state/ and must not "
        "be re-homed at a top-level state/ that needs a negation dance."
    )
    assert "!state/autoresearch/mutations.jsonl" not in text, (
        "The retired mutations.jsonl negation is back — it only existed to undo "
        "the broad state/ glob, which no longer exists."
    )


@pytest.mark.parametrize(
    "constant_name",
    [
        "MUTATION_AUDIT_LOG_PATH",
        "BASELINE_ARCHIVE_PATH",
        "RESULTS_TSV_PATH",
        "RESULTS_JSONL_PATH",
        "AUTORESEARCH_TOOL_POLICY_PATH",
    ],
)
def test_tracked_sot_not_gitignored(constant_name: str) -> None:
    """Every tracked-SoT path must be git-tracked (``check-ignore`` exit 1).

    Derives the path from ``core.paths`` so a future relocation that re-ignores
    the SoT fails here regardless of the literal path.
    """
    from core import paths

    target = Path(getattr(paths, constant_name)).resolve()
    repo_relative = str(target.relative_to(_REPO_ROOT))
    result = _check_ignore(repo_relative)
    if result is None:
        pytest.skip("git binary not available in test environment")
    assert result.returncode == 1, (
        f"git check-ignore considers {repo_relative} ignored "
        f"(exit={result.returncode}, stdout={result.stdout!r}). The tracked SoT "
        f"under core/self_improving/state/ must enter git history — a later glob "
        f"(`*.jsonl`?) may have re-ignored it."
    )


def test_runtime_baseline_lives_outside_repo() -> None:
    """The runtime ``baseline.json`` must resolve OUTSIDE the repo tree.

    Replaces the old "baseline.json is gitignored" sanity check. Runtime scratch
    now lives at ``~/.geode/self-improving/`` (out of repo), so it is
    structurally uncommittable — no gitignore rule can regress.
    """
    from core import paths

    baseline = Path(paths.BASELINE_JSON_PATH).resolve()
    assert not baseline.is_relative_to(_REPO_ROOT), (
        f"BASELINE_JSON_PATH={baseline} resolved INSIDE the repo tree "
        f"({_REPO_ROOT}). Runtime baseline must live under GEODE_HOME "
        f"(~/.geode/self-improving/) so it cannot be committed."
    )
