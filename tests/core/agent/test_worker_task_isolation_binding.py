"""PR-RESUME-NO-PERSIST-FIX (B2) + PR-CLEANUP-WORKER-REQUEST-RUN-DIR —
sub-agent worker binds per-task cwd at startup by reading the live
run_dir SoT (``core.observability.run_dir.get_active_run_dir``),
NOT the dead ``WorkerRequest.run_dir`` field.

Tests mirror the exact bind sequence ``_run_agentic`` uses so the
suite stays in lockstep with the production path. Coverage:

* ContextVar-bound run_dir → per-task cwd materialised + ContextVar set.
* Different task_ids → disjoint cwd pools (cross-sub-agent isolation
  invariant the whole PR exists to enforce).
* Idempotent re-bind (crash + retry).
* Unbound ContextVar (no orchestrator) → no per-task cwd created,
  no ContextVar set (legacy callers unaffected).
"""

from __future__ import annotations

from pathlib import Path

from core.agent.task_isolation import get_task_isolated_cwd, set_task_isolated_cwd
from core.observability.run_dir import get_active_run_dir, set_active_run_dir


def _bind_like_worker(task_id: str) -> Path | None:
    """Mirror the bind sequence in ``core/agent/worker.py:_run_agentic``.

    Reads ``get_active_run_dir()`` (the live SoT — populated by
    ``worker.main()`` from the ``GEODE_RUN_DIR`` env var on entry).
    Returns the bound cwd path, or ``None`` when no orchestrator
    has set a run_dir (the legacy direct-call surface).
    """
    active_run_dir = get_active_run_dir()
    if active_run_dir is None or not task_id:
        return None
    task_cwd_path = active_run_dir / "sub_agents" / task_id / "cwd"
    task_cwd_path.mkdir(parents=True, exist_ok=True)
    set_task_isolated_cwd(task_cwd_path)
    return task_cwd_path


def test_worker_bind_creates_directory_and_sets_contextvar(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Happy path — orchestrator set ``_active_run_dir``, worker
    binding materialises the cwd + sets the per-task ContextVar."""
    set_active_run_dir(tmp_path)
    try:
        task_id = "gen-gen1-000-abc12345"
        bound_path = _bind_like_worker(task_id)

        expected_path = tmp_path / "sub_agents" / task_id / "cwd"
        assert bound_path == expected_path
        assert expected_path.is_dir()

        value = get_task_isolated_cwd()
        assert value == str(expected_path)
        assert isinstance(value, str)
    finally:
        set_task_isolated_cwd(None)
        set_active_run_dir(None)


def test_worker_bind_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Same task_id binding twice (e.g. crash + retry path) must
    not error on the mkdir or overwrite a stale binding with a
    different path."""
    set_active_run_dir(tmp_path)
    try:
        task_id = "evolve-gen1-001-xyz67890"
        first = _bind_like_worker(task_id)
        second = _bind_like_worker(task_id)

        assert first == second
        assert get_task_isolated_cwd() == str(second)
    finally:
        set_task_isolated_cwd(None)
        set_active_run_dir(None)


def test_per_task_cwd_pools_are_disjoint(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Two different task_ids in the same run_dir get different
    cwds — cross-sub-agent cwd-cache isolation invariant."""
    set_active_run_dir(tmp_path)
    try:
        cwd_a = _bind_like_worker("gen-gen1-000-aaaa")
        cwd_b = _bind_like_worker("gen-gen1-001-bbbb")
        assert cwd_a is not None and cwd_b is not None

        assert cwd_a != cwd_b
        # Different cwd → different hash → different
        # ~/.claude/projects/<hash>/sessions/ pool.
        assert cwd_a.name == "cwd"
        assert cwd_b.name == "cwd"
        assert cwd_a.parent.name == "gen-gen1-000-aaaa"
        assert cwd_b.parent.name == "gen-gen1-001-bbbb"
    finally:
        set_task_isolated_cwd(None)
        set_active_run_dir(None)


def test_worker_bind_noop_when_no_active_run_dir() -> None:
    """Direct-call surface (gateway, REPL, ad-hoc CLI, tests) —
    no orchestrator has bound a run_dir, so the worker skips the
    per-task cwd setup and the ContextVar stays at its default
    ``None``. This preserves the legacy behaviour callers outside
    seed-generation depend on."""
    set_active_run_dir(None)  # explicit clear
    set_task_isolated_cwd(None)
    bound = _bind_like_worker("gen-gen1-000-no-orchestrator")
    assert bound is None
    assert get_task_isolated_cwd() is None


def test_worker_bind_noop_when_task_id_empty(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Symmetric guard — run_dir is bound but the request carries
    an empty task_id (unexpected, but the binding must not raise)."""
    set_active_run_dir(tmp_path)
    set_task_isolated_cwd(None)
    try:
        bound = _bind_like_worker("")
        assert bound is None
        assert get_task_isolated_cwd() is None
    finally:
        set_active_run_dir(None)
