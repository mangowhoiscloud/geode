"""PR-RESUME-NO-PERSIST-FIX (B2) — sub-agent worker binds per-task
cwd at startup.

Tests verify the binding behavior in isolation by exercising the
``set_task_isolated_cwd`` call path that ``_run_agentic`` triggers
before the AgenticLoop is built. We don't run the full worker (it
needs the IPC subprocess scaffolding) — instead we replicate the
exact 3 lines from ``worker.py`` and assert the side effects
(ContextVar set + directory exists).
"""

from __future__ import annotations

from pathlib import Path

from core.agent.task_isolation import get_task_isolated_cwd, set_task_isolated_cwd


def _bind_like_worker(run_dir: str, task_id: str) -> Path:
    """Mirror the exact bind sequence in ``core/agent/worker.py:
    _run_agentic`` so the test stays in lockstep with the production
    path. If the production binding changes, this helper must
    change too."""
    task_cwd_path = Path(run_dir) / "sub_agents" / task_id / "cwd"
    task_cwd_path.mkdir(parents=True, exist_ok=True)
    set_task_isolated_cwd(task_cwd_path)
    return task_cwd_path


def test_worker_bind_creates_directory_and_sets_contextvar(tmp_path) -> None:  # type: ignore[no-untyped-def]
    run_dir = str(tmp_path)
    task_id = "gen-gen1-000-abc12345"

    bound_path = _bind_like_worker(run_dir, task_id)

    # 1. Directory exists on disk.
    expected_path = tmp_path / "sub_agents" / task_id / "cwd"
    assert expected_path.is_dir()
    assert bound_path == expected_path

    # 2. ContextVar carries the absolute path as a string.
    value = get_task_isolated_cwd()
    assert value == str(expected_path)
    assert isinstance(value, str)

    set_task_isolated_cwd(None)


def test_worker_bind_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Same task_id binding twice in a row (e.g. crash + retry path)
    must not error on the mkdir or overwrite a stale binding with a
    different path."""
    run_dir = str(tmp_path)
    task_id = "evolve-gen1-001-xyz67890"

    first = _bind_like_worker(run_dir, task_id)
    second = _bind_like_worker(run_dir, task_id)

    assert first == second
    assert get_task_isolated_cwd() == str(second)
    set_task_isolated_cwd(None)


def test_per_task_cwd_pools_are_disjoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Two different task_ids in the same run_dir get different
    cwds — verifies the cross-sub-agent cwd-cache isolation
    invariant the whole PR exists to enforce."""
    run_dir = str(tmp_path)

    cwd_a = _bind_like_worker(run_dir, "gen-gen1-000-aaaa")
    cwd_b = _bind_like_worker(run_dir, "gen-gen1-001-bbbb")

    assert cwd_a != cwd_b
    # Different cwd → different hash → different
    # ~/.claude/projects/<hash>/sessions/ pool.
    assert cwd_a.name == "cwd"
    assert cwd_b.name == "cwd"
    assert cwd_a.parent.name == "gen-gen1-000-aaaa"
    assert cwd_b.parent.name == "gen-gen1-001-bbbb"
    set_task_isolated_cwd(None)
