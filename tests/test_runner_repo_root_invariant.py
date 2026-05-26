"""Regression pin for the ``repo_root`` computation used by

``SelfImprovingLoopRunner.apply_proposal`` and
``apply_group_proposals`` when they invoke the autoresearch
re-audit subprocess.

Both call sites derive ``repo_root`` from
``MUTATION_AUDIT_LOG_PATH.resolve().parents[N]`` and then pass it as
``cwd`` to ``_run_autoresearch_subprocess``. The argv inside that
subprocess is ``["uv", "run", "python", "autoresearch/train.py"]``,
so the cwd MUST be the repo root — otherwise the relative path
resolves to ``<wrong-root>/autoresearch/train.py`` and the
subprocess exits with ``[Errno 2]`` before any audit work happens.

Latent bug history: PR-G5b (2026-05-20) moved the audit log from
``<repo>/state/mutations.jsonl`` to
``<repo>/autoresearch/state/mutations.jsonl``. The ``parents[1]``
arithmetic at the two call sites was not updated and the bug
slept because (a) tests mocked the subprocess and (b) live runs
went through ``geode audit-seeds generate`` / ``train.py`` directly
rather than the inner-loop runner. This test fails on a regression
by asserting the resolved repo root actually contains
``autoresearch/train.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.paths import MUTATION_AUDIT_LOG_PATH


@pytest.fixture
def audit_log_path() -> Path:
    return Path(MUTATION_AUDIT_LOG_PATH)


def test_mutation_audit_log_lives_two_levels_below_repo_root(
    audit_log_path: Path,
) -> None:
    """``parents[2]`` of the audit log path is the repo root.

    Pin: ``MUTATION_AUDIT_LOG_PATH`` =
    ``<repo>/autoresearch/state/mutations.jsonl`` → ``parents[2]``
    is the directory containing ``autoresearch/train.py``.
    """
    repo_root = audit_log_path.resolve().parents[2]
    assert (repo_root / "autoresearch" / "train.py").is_file(), (
        f"repo_root={repo_root!r} does not contain autoresearch/train.py — "
        f"the parents[2] offset is wrong or the audit log path moved again."
    )


def test_parents_one_is_not_repo_root(
    audit_log_path: Path,
) -> None:
    """``parents[1]`` points at ``autoresearch/`` not the repo root.

    Direct negative pin: if some future refactor flips back to
    ``parents[1]``, the subprocess argv ``autoresearch/train.py``
    against this cwd resolves to ``autoresearch/autoresearch/train.py``
    which does not exist. This test asserts that exact non-existence
    so the wrong cwd cannot silently pass.
    """
    wrong_root = audit_log_path.resolve().parents[1]
    wrong_path = wrong_root / "autoresearch" / "train.py"
    assert not wrong_path.exists(), (
        f"Unexpected: {wrong_path!r} exists — runner.py's parents[2] arithmetic "
        f"was chosen against parents[1] precisely because parents[1] "
        f"resolves to the autoresearch/ subdirectory, not the repo root."
    )


def test_runner_apply_proposal_uses_correct_parents_offset() -> None:
    """The two ``parents[N]`` call sites in ``runner.py`` must use ``parents[2]``.

    Source-level pin: greps the runner module so a regression to
    ``parents[1]`` on either call site fails before any subprocess
    spawn. Catches the off-by-one bug introduced after PR-G5b
    moved the audit log under ``autoresearch/state/``.
    """
    from core.self_improving_loop import runner

    source = Path(runner.__file__).read_text(encoding="utf-8")
    # Both call sites should now read parents[2]; parents[1] must not
    # appear in any repo_root computation downstream of MUTATION_AUDIT_LOG_PATH
    # / self.audit_log_path / log_path. We guard with a substring scan rather
    # than AST parsing because the patterns are unambiguous and the file is
    # already line-stable here.
    forbidden = [
        "log_path.resolve().parents[1]",
        "MUTATION_AUDIT_LOG_PATH).resolve().parents[1]",
    ]
    for needle in forbidden:
        assert needle not in source, (
            f"runner.py still contains {needle!r} — re-introducing the "
            f"off-by-one bug. Replace with parents[2]."
        )
