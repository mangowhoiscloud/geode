"""Regression pin for the ``repo_root`` computation used by

``SelfImprovingLoopRunner.apply_proposal`` when it invokes the
autoresearch re-audit subprocess.

The call site derives ``repo_root`` from
``MUTATION_AUDIT_LOG_PATH.resolve().parents[N]`` and then passes it as
``cwd`` to ``_run_autoresearch_subprocess``. The argv inside that
subprocess is ``["uv", "run", "python", "-m", "core.self_improving.train"]``,
so the cwd MUST be the repo root — otherwise ``python -m`` cannot resolve
the ``core`` package and the subprocess exits with a ``ModuleNotFoundError``
before any audit work happens.

Latent bug history: PR-G5b (2026-05-20) moved the audit log from
``<repo>/state/mutations.jsonl`` to ``<repo>/autoresearch/state/mutations.jsonl``.
The ``parents[3]`` arithmetic at the two call sites was not updated and the bug
slept because (a) tests mocked the subprocess and (b) live runs
went through ``geode audit-seeds generate`` / ``train`` directly
rather than the inner-loop runner. This test fails on a regression
by asserting the resolved repo root actually contains
``core/self_improving/train.py`` (the audit module's source file).
PR-SELF-IMPROVING-UMBRELLA (2026-05-31) moved the audit runner from
``autoresearch/train.py`` to ``core/self_improving/train.py`` and the
spawn from a relative path to ``-m core.self_improving.train``.
PR-STATE-SELF-IMPROVING-RENAME (2026-06-01) moved the audit log again to
``<repo>/state/autoresearch/mutations.jsonl`` — the repo-root invariant is
STILL ``parents[2]`` (mutations.jsonl → self_improving → state → repo) because
the depth below repo root is unchanged (two dirs); ``python -m`` still resolves
the package against the ``cwd``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.paths import MUTATION_AUDIT_LOG_PATH


@pytest.fixture
def audit_log_path() -> Path:
    return Path(MUTATION_AUDIT_LOG_PATH)


def test_mutation_audit_log_lives_three_levels_below_repo_root(
    audit_log_path: Path,
) -> None:
    """``parents[3]`` of the audit log path is the repo root.

    Pin (post PR-STATE-SOT-RUNTIME-SPLIT): ``MUTATION_AUDIT_LOG_PATH`` =
    ``<repo>/core/self_improving/state/mutations.jsonl`` → ``parents[3]``
    is the repo root containing ``core/self_improving/train.py`` (the move
    in-repo deepened it one level, 2 → 3).
    """
    repo_root = audit_log_path.resolve().parents[3]
    assert (repo_root / "core" / "self_improving" / "train.py").is_file(), (
        f"repo_root={repo_root!r} does not contain core/self_improving/train.py — "
        f"the parents[3] offset is wrong or the audit log path moved again."
    )


def test_parents_two_is_not_repo_root(
    audit_log_path: Path,
) -> None:
    """``parents[2]`` points at ``<repo>/core``, not the repo root.

    Negative pin: if a future refactor flips back to ``parents[2]``, the
    git ``cwd`` becomes ``<repo>/core`` and the ``-m core.self_improving.train``
    spawn cannot find the ``core`` package (which lives at the repo root). This
    asserts ``parents[2]`` does NOT contain ``core/self_improving/train.py`` so
    the wrong cwd cannot silently pass.
    """
    wrong_root = audit_log_path.resolve().parents[2]
    wrong_path = wrong_root / "core" / "self_improving" / "train.py"
    assert not wrong_path.exists(), (
        f"Unexpected: {wrong_path!r} exists — runner.py uses parents[3] (not "
        f"parents[2]) because parents[2] resolves to <repo>/core, not the repo root."
    )


def test_runner_apply_proposal_uses_correct_parents_offset() -> None:
    """The two ``parents[N]`` call sites in ``runner.py`` must use ``parents[3]``.

    Source-level pin: greps the runner module so a regression to ``parents[2]``
    on either call site fails before any subprocess spawn. The audit log moved
    in-repo to ``core/self_improving/state/`` (PR-STATE-SOT-RUNTIME-SPLIT), one
    level deeper, so the git-cwd derivation is now ``parents[3]``.
    """
    from core.self_improving.loop.mutate import runner

    source = Path(runner.__file__).read_text(encoding="utf-8")
    forbidden = [
        "log_path.resolve().parents[2]",
        "MUTATION_AUDIT_LOG_PATH).resolve().parents[2]",
    ]
    for needle in forbidden:
        assert needle not in source, (
            f"runner.py still contains {needle!r} — re-introducing the off-by-one "
            f"bug. The audit log is now 3 levels below repo root; use parents[3]."
        )
