"""Tests for ``core.agent.task_isolation``.

PR-RESUME-NO-PERSIST-FIX (2026-05-25) — the sub-agent worker binds a
per-task cwd so claude-cli's cwd-keyed session cache pool is unique
per ``task_id``. This module is a thin ContextVar wrapper; tests
cover set/get semantics + None default + path coercion.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from core.agent.task_isolation import get_task_isolated_cwd, set_task_isolated_cwd

# Test fixtures use ``/tmp/...`` literals only as string-equality
# probes — nothing is actually created on disk. The per-line
# ``noqa`` suppression below keeps ruff's filesystem-security lint
# (S108) quiet without pulling in a tmp_path fixture that's overkill
# for the ContextVar round-trip checks here.
_FAKE_CWD_A = "/tmp/some-task-cwd"  # noqa: S108 — ContextVar value probe, not a real dir
_FAKE_CWD_B = "/tmp/another-task-cwd"  # noqa: S108
_FAKE_CWD_C = "/tmp/before-clear"  # noqa: S108
_FAKE_CWD_PARENT = "/tmp/parent-cwd"  # noqa: S108
_FAKE_CWD_CHILD_A = "/tmp/child-a"  # noqa: S108
_FAKE_CWD_CHILD_B = "/tmp/child-b"  # noqa: S108


def test_default_is_none() -> None:
    """Unbound ContextVar returns None — direct callers (audit lane,
    diagnostic scripts) get the caller's cwd via subprocess inherit."""
    set_task_isolated_cwd(None)
    assert get_task_isolated_cwd() is None


def test_set_and_get_string() -> None:
    set_task_isolated_cwd(_FAKE_CWD_A)
    try:
        assert get_task_isolated_cwd() == _FAKE_CWD_A
    finally:
        set_task_isolated_cwd(None)


def test_set_and_get_path() -> None:
    """``Path`` instances are coerced to ``str`` so the consumer
    (``asyncio.create_subprocess_exec(cwd=...)``) gets a value of the
    expected type without each call site stringifying."""
    set_task_isolated_cwd(Path(_FAKE_CWD_B))
    try:
        value = get_task_isolated_cwd()
        assert value == _FAKE_CWD_B
        assert isinstance(value, str)
    finally:
        set_task_isolated_cwd(None)


def test_none_clears_binding() -> None:
    set_task_isolated_cwd(_FAKE_CWD_C)
    set_task_isolated_cwd(None)
    assert get_task_isolated_cwd() is None


def test_contextvar_isolation_across_asyncio_tasks() -> None:
    """ContextVar copies bindings into spawned tasks but mutations
    in one task don't leak back to the parent — verifies the
    per-task isolation semantics hold under asyncio.gather. Critical
    for the sub-agent dispatch model where multiple sub-agents may
    run concurrently in the same parent process."""

    async def child(new_cwd: str) -> str | None:
        before = get_task_isolated_cwd()
        set_task_isolated_cwd(new_cwd)
        await asyncio.sleep(0)  # yield so other tasks interleave
        return before

    async def main() -> list[str | None]:
        set_task_isolated_cwd(_FAKE_CWD_PARENT)
        results = await asyncio.gather(
            child(_FAKE_CWD_CHILD_A),
            child(_FAKE_CWD_CHILD_B),
        )
        # Parent's binding must NOT have been mutated by children.
        assert get_task_isolated_cwd() == _FAKE_CWD_PARENT
        return results

    results = asyncio.run(main())
    # Each child inherited the parent's binding at spawn time.
    assert all(before == _FAKE_CWD_PARENT for before in results)
    set_task_isolated_cwd(None)
