"""PR-SOT-REVERT-ON-AUDIT-FAIL (2026-05-26) — SoT rollback when
post-commit audit subprocess crashes or exits non-zero.

Closes the second silent leak from the 2026-05-26 autoresearch
attribution/wiring sprint Phase A audit (Section 5.2):

* ``SelfImprovingLoopRunner.apply_proposal`` (runner.py:1865) writes
  the mutation to the canonical SoT.
* ``_invoke_autoresearch`` (runner.py:1981-2004 pre-PR) spawned the
  audit subprocess but did not check ``returncode`` and only logged
  on Exception — never called ``_rollback_sot``.
* Result: a crashed audit left the SoT mutated and the baseline
  unchanged. The next cycle had no signal to attribute the
  regression to.

This file pins three behaviours:

1. ``_invoke_autoresearch`` calls ``_rollback_sot`` when the
   subprocess returns a non-zero ``returncode`` (and
   ``original_sections`` was forwarded).
2. ``_invoke_autoresearch`` calls ``_rollback_sot`` when the
   subprocess raises any Exception.
3. ``_invoke_autoresearch`` does NOT call ``_rollback_sot`` when the
   subprocess succeeds (returncode 0) — pinning we don't regress the
   happy path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from core.self_improving_loop.runner import Mutation, SelfImprovingLoopRunner


def _make_runner(tmp_path: Path) -> SelfImprovingLoopRunner:
    """Build a minimally-wired runner instance for unit testing."""
    return SelfImprovingLoopRunner(
        llm_call=lambda system, user: (
            '{"target_section": "role", "new_value": "x", "rationale": "y"}'
        ),
        rerun_enabled=True,
        commit_enabled=False,
        audit_log_path=tmp_path / "mutations.jsonl",
    )


def _make_mutation() -> Mutation:
    return Mutation(
        target_section="role",
        new_value="mutated-value",
        rationale="test mutation",
        target_kind="prompt",
        mutation_id="mut-test-1",
    )


def _completed_process(returncode: int, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["uv", "run", "python", "autoresearch/train.py"],
        returncode=returncode,
        stdout="",
        stderr=stderr,
    )


def test_audit_subprocess_returncode_zero_does_not_rollback(tmp_path: Path) -> None:
    """Happy path — when the audit subprocess exits 0, the canonical
    SoT mutation stays in place (no rollback) because the audit has
    accepted or rejected via its own promote-gate path and any
    rejection-side revert is handled in train.py (PR-SOT-REVERT-ON-REJECT)."""
    runner = _make_runner(tmp_path)
    mutation = _make_mutation()
    original_sections = {"role": "pre-mutation"}

    rollback_calls: list[Any] = []

    def fake_subprocess(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed_process(returncode=0)

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            fake_subprocess,
        ),
        patch.object(
            SelfImprovingLoopRunner,
            "_rollback_sot",
            staticmethod(lambda *a, **kw: rollback_calls.append((a, kw))),
        ),
    ):
        runner._invoke_autoresearch(
            tmp_path,
            audit_run_id="run-1",
            mutation=mutation,
            original_sections=original_sections,
        )

    assert rollback_calls == []


def test_audit_subprocess_nonzero_returncode_triggers_rollback(tmp_path: Path) -> None:
    """When the audit subprocess exits non-zero, rollback is called
    with the original_sections + mutation + a RuntimeError carrying
    the exit code in its message."""
    runner = _make_runner(tmp_path)
    mutation = _make_mutation()
    original_sections = {"role": "pre-mutation"}

    rollback_calls: list[Any] = []

    def fake_subprocess(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed_process(returncode=2, stderr="something went wrong")

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            fake_subprocess,
        ),
        patch.object(
            SelfImprovingLoopRunner,
            "_rollback_sot",
            staticmethod(lambda *a, **kw: rollback_calls.append((a, kw))),
        ),
    ):
        runner._invoke_autoresearch(
            tmp_path,
            audit_run_id="run-1",
            mutation=mutation,
            original_sections=original_sections,
        )

    assert len(rollback_calls) == 1
    args, kwargs = rollback_calls[0]
    # First positional arg: original_sections
    assert args == (original_sections,)
    assert kwargs["mutation"] is mutation
    assert isinstance(kwargs["exc"], RuntimeError)
    assert "exit code 2" in str(kwargs["exc"])


def test_audit_subprocess_exception_triggers_rollback(tmp_path: Path) -> None:
    """When the subprocess invocation itself raises (e.g. OSError on
    fork failure, timeout), rollback is called with the captured
    exception."""
    runner = _make_runner(tmp_path)
    mutation = _make_mutation()
    original_sections = {"role": "pre-mutation"}

    rollback_calls: list[Any] = []

    def fake_subprocess(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise OSError("simulated fork failure")

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            fake_subprocess,
        ),
        patch.object(
            SelfImprovingLoopRunner,
            "_rollback_sot",
            staticmethod(lambda *a, **kw: rollback_calls.append((a, kw))),
        ),
    ):
        runner._invoke_autoresearch(
            tmp_path,
            audit_run_id="run-1",
            mutation=mutation,
            original_sections=original_sections,
        )

    assert len(rollback_calls) == 1
    args, kwargs = rollback_calls[0]
    assert args == (original_sections,)
    assert isinstance(kwargs["exc"], OSError)
    assert "simulated fork failure" in str(kwargs["exc"])


def test_rollback_skipped_when_original_sections_not_forwarded(tmp_path: Path) -> None:
    """Backward-compat: when ``original_sections`` is None (a caller
    that didn't migrate to the new signature), the legacy graceful-
    log behaviour is preserved — no rollback call, no crash."""
    runner = _make_runner(tmp_path)
    mutation = _make_mutation()

    rollback_calls: list[Any] = []

    def fake_subprocess(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed_process(returncode=99)

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            fake_subprocess,
        ),
        patch.object(
            SelfImprovingLoopRunner,
            "_rollback_sot",
            staticmethod(lambda *a, **kw: rollback_calls.append((a, kw))),
        ),
    ):
        runner._invoke_autoresearch(
            tmp_path,
            audit_run_id="run-1",
            mutation=mutation,
            original_sections=None,
        )

    assert rollback_calls == []


def test_rollback_skipped_when_mutation_is_none(tmp_path: Path) -> None:
    """Defensive — when mutation is None we cannot meaningfully rollback
    (don't know which SoT to restore), so the legacy log-only behaviour
    is preserved."""
    runner = _make_runner(tmp_path)
    original_sections = {"role": "pre-mutation"}

    rollback_calls: list[Any] = []

    def fake_subprocess(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise RuntimeError("fail")

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            fake_subprocess,
        ),
        patch.object(
            SelfImprovingLoopRunner,
            "_rollback_sot",
            staticmethod(lambda *a, **kw: rollback_calls.append((a, kw))),
        ),
    ):
        runner._invoke_autoresearch(
            tmp_path,
            audit_run_id="run-1",
            mutation=None,
            original_sections=original_sections,
        )

    assert rollback_calls == []


def test_rollback_sot_accepts_runtimerror_after_pr(tmp_path: Path) -> None:
    """Pin: the ``exc`` parameter type widening from OSError to
    BaseException — _rollback_sot must accept any exception subclass
    so the audit-fail rollback path (RuntimeError) works at type
    check time. Smoke-runs the static dispatch."""
    mutation = _make_mutation()
    original_sections = {"role": "pre-mutation"}

    write_calls: list[Any] = []

    def fake_write_wrapper(sections: dict[str, str]) -> None:
        write_calls.append(sections)

    with patch("autoresearch.train.write_wrapper_prompt_sections", fake_write_wrapper):
        # RuntimeError used to fail mypy on the OSError-typed parameter;
        # post-PR this is accepted.
        SelfImprovingLoopRunner._rollback_sot(
            original_sections,
            mutation=mutation,
            exc=RuntimeError("audit subprocess exit code 2"),
        )

    assert write_calls == [original_sections]


def test_apply_proposal_forwards_original_sections_and_rolls_back_on_nonzero(
    tmp_path: Path,
) -> None:
    """End-to-end pin: when ``apply_proposal`` is called with a
    runner-driven cycle (``rerun_enabled=True``) and the audit
    subprocess exits non-zero, the canonical SoT is restored from
    ``proposal.original_sections``. This pins the entire wiring chain:
    apply_proposal → _invoke_autoresearch → _rollback_sot → write
    back the pre-mutation sections.

    Codex MCP review #2 (CONDITIONAL_PASS, must-fix #1) — the unit
    tests above patch ``_rollback_sot`` so they don't prove the
    actual restoration. This test patches the *writers* instead so
    the rollback path's actual SoT write is observed."""
    from core.self_improving_loop.runner import Proposal

    runner = _make_runner(tmp_path)
    mutation = _make_mutation()
    original_sections = {"role": "ORIGINAL", "shell_caution": "untouched"}

    proposal = Proposal(
        mutation=mutation,
        target_sections=dict(original_sections),
        original_sections=dict(original_sections),
    )

    # Track the SoT state via writer/reader patches.
    sot_state = dict(original_sections)

    def fake_load_wrapper() -> dict[str, str]:
        return dict(sot_state)

    def fake_write_wrapper(sections: dict[str, str]) -> None:
        sot_state.clear()
        sot_state.update(sections)

    def failing_subprocess(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed_process(returncode=2, stderr="audit crashed")

    with (
        patch("autoresearch.train.load_wrapper_prompt_sections", fake_load_wrapper),
        patch("autoresearch.train.write_wrapper_prompt_sections", fake_write_wrapper),
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            failing_subprocess,
        ),
        # Skip the git commit step (commit_enabled=False already, but
        # be explicit about not invoking git in test).
        patch(
            "core.self_improving_loop.runner._git_commit_audit_log",
            lambda *a, **kw: None,
        ),
    ):
        result = runner.apply_proposal(proposal)

    # apply_proposal returns the mutation regardless — the rollback
    # is silent (logged but not raised).
    assert result is mutation
    # CRITICAL invariant: SoT was first mutated by apply_mutation then
    # restored by the rollback path. End state must equal the
    # pre-mutation original_sections.
    assert sot_state == original_sections
    assert sot_state["role"] == "ORIGINAL"


@pytest.mark.parametrize("returncode", [1, 2, 124, 137])
def test_rollback_triggers_across_failure_returncodes(tmp_path: Path, returncode: int) -> None:
    """Pin that any non-zero returncode triggers rollback — not just
    a magic value. Covers timeout (124), OOM kill (137), and generic
    failures (1, 2)."""
    runner = _make_runner(tmp_path)
    mutation = _make_mutation()
    original_sections = {"role": "pre-mutation"}

    rollback_calls: list[Any] = []

    def fake_subprocess(**kwargs: Any) -> subprocess.CompletedProcess[str]:
        return _completed_process(returncode=returncode)

    with (
        patch(
            "core.self_improving_loop.runner._run_autoresearch_subprocess",
            fake_subprocess,
        ),
        patch.object(
            SelfImprovingLoopRunner,
            "_rollback_sot",
            staticmethod(lambda *a, **kw: rollback_calls.append((a, kw))),
        ),
    ):
        runner._invoke_autoresearch(
            tmp_path,
            audit_run_id=f"run-rc{returncode}",
            mutation=mutation,
            original_sections=original_sections,
        )

    assert len(rollback_calls) == 1
    _, kwargs = rollback_calls[0]
    assert f"exit code {returncode}" in str(kwargs["exc"])
