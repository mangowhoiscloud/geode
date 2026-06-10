"""OL-A1.5 — auto-trigger HookEvent + audit log JSONL invariants.

Pins:
- 5 new HookEvent variants exist (one per terminal state, except ``disabled``).
- ``STATE_TO_HOOK_EVENT`` maps each state correctly + does NOT include ``disabled``.
- ``append_history_entry`` writes one JSONL row per call, round-trips.
- ``append_history_entry`` graceful on OSError (returns False, no raise).
- ``auto_trigger_mutator`` emits the right HookEvent + appends one
  history row for every terminal state EXCEPT ``disabled``.
- ``hooks=None`` short-circuits hook emit (audit log still writes).
- Multi-call history log is append-only (entry count grows).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def trigger_paths(tmp_path: Path) -> Iterator[tuple[Path, Path, Path]]:
    lock = tmp_path / "auto_trigger.lock"
    ts = tmp_path / "auto_trigger_last_run.txt"
    hist = tmp_path / "auto_trigger_history.jsonl"
    yield lock, ts, hist


class _FakeRunner:
    def __init__(self, *, raises: Exception | None = None, target_section: str = "sec") -> None:
        self._raises = raises
        self._target_section = target_section
        self.run_once_count = 0

    def run_once(self) -> Any:
        self.run_once_count += 1
        if self._raises is not None:
            raise self._raises

        class _M:
            target_section = self._target_section

        _M.target_section = self._target_section  # type: ignore[misc]
        return _M()


class _CapturingHooks:
    """Records every HookEvent.trigger call for assertion."""

    def __init__(self) -> None:
        self.emitted: list[tuple[Any, dict[str, Any]]] = []

    def trigger(self, event: Any, data: dict[str, Any]) -> None:
        self.emitted.append((event, data))


# ---------------------------------------------------------------------------
# HookEvent enum additions
# ---------------------------------------------------------------------------


def test_hook_event_has_auto_trigger_variants() -> None:
    """PR-MAX-GEN (2026-05-26) added a sixth auto-trigger variant:
    ``SELF_IMPROVING_AUTO_TRIGGER_MAX_GENERATION_REACHED``."""
    from core.hooks import HookEvent

    assert HookEvent.SELF_IMPROVING_AUTO_TRIGGER_FIRED.value == "self_improving_auto_trigger_fired"
    assert HookEvent.SELF_IMPROVING_AUTO_TRIGGER_LOCK_BUSY.value == (
        "self_improving_auto_trigger_lock_busy"
    )
    assert HookEvent.SELF_IMPROVING_AUTO_TRIGGER_INTERVAL_BLOCKED.value == (
        "self_improving_auto_trigger_interval_blocked"
    )
    assert HookEvent.SELF_IMPROVING_AUTO_TRIGGER_RUNNER_ERROR.value == (
        "self_improving_auto_trigger_runner_error"
    )
    assert HookEvent.SELF_IMPROVING_AUTO_TRIGGER_PARSE_ERROR.value == (
        "self_improving_auto_trigger_parse_error"
    )
    assert HookEvent.SELF_IMPROVING_AUTO_TRIGGER_MAX_GENERATION_REACHED.value == (
        "self_improving_auto_trigger_max_generation_reached"
    )


def test_state_to_hook_event_map_covers_terminal_states() -> None:
    """`disabled` is intentionally absent — see module docstring.
    PR-MAX-GEN (2026-05-26) added ``max_generation_reached`` for the
    generation-cap state, bringing the map to six entries."""
    from core.self_improving.loop.auto_trigger import STATE_TO_HOOK_EVENT

    assert set(STATE_TO_HOOK_EVENT) == {
        "fired",
        "lock_busy",
        "interval_blocked",
        "runner_error",
        "parse_error",
        "max_generation_reached",
    }
    assert "disabled" not in STATE_TO_HOOK_EVENT


def test_state_to_hook_event_values_resolve_via_getattr() -> None:
    """Each mapped string MUST resolve via `getattr(HookEvent, name)`."""
    from core.hooks import HookEvent
    from core.self_improving.loop.auto_trigger import STATE_TO_HOOK_EVENT

    for hook_name in STATE_TO_HOOK_EVENT.values():
        assert hasattr(HookEvent, hook_name), f"HookEvent missing {hook_name}"


# ---------------------------------------------------------------------------
# append_history_entry
# ---------------------------------------------------------------------------


def test_history_entry_writes_one_jsonl_row(trigger_paths: tuple[Path, Path, Path]) -> None:
    from core.self_improving.loop.auto_trigger import append_history_entry

    _, _, hist = trigger_paths
    ok = append_history_entry(
        state="fired",
        detail="target_section=wrapper.intro",
        ts=1234567890.0,
        trigger_id="test-trigger",
        history_path=hist,
    )
    assert ok is True
    lines = hist.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row == {
        "ts": 1234567890.0,
        "state": "fired",
        "detail": "target_section=wrapper.intro",
        "trigger_id": "test-trigger",
    }


def test_history_entry_appends_multiple_rows(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    from core.self_improving.loop.auto_trigger import append_history_entry

    _, _, hist = trigger_paths
    for i in range(3):
        append_history_entry(state="fired", detail=f"row{i}", ts=float(i), history_path=hist)
    lines = hist.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    rows = [json.loads(ln) for ln in lines]
    assert [r["detail"] for r in rows] == ["row0", "row1", "row2"]


def test_history_entry_creates_parent_dir(tmp_path: Path) -> None:
    from core.self_improving.loop.auto_trigger import append_history_entry

    nested = tmp_path / "deep" / "nested" / "history.jsonl"
    assert not nested.parent.exists()
    ok = append_history_entry(state="fired", detail="d", ts=1.0, history_path=nested)
    assert ok is True
    assert nested.is_file()


def test_history_entry_preserves_unicode_in_detail(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    """Korean / non-ASCII detail must not be escaped to ``\\uXXXX``."""
    from core.self_improving.loop.auto_trigger import append_history_entry

    _, _, hist = trigger_paths
    append_history_entry(
        state="fired",
        detail="target_section=섹션-한글",
        ts=1.0,
        history_path=hist,
    )
    raw = hist.read_text(encoding="utf-8")
    assert "섹션-한글" in raw
    assert "\\u" not in raw  # ensure_ascii=False applied


def test_history_entry_graceful_on_oserror(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Disk failure → returns False, does not raise."""
    from core.self_improving.loop import auto_trigger as at_module

    def _boom_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "mkdir", _boom_mkdir)
    target = tmp_path / "blocked" / "history.jsonl"
    ok = at_module.append_history_entry(state="fired", detail="d", ts=1.0, history_path=target)
    assert ok is False


# ---------------------------------------------------------------------------
# auto_trigger_mutator end-to-end with telemetry + history
# ---------------------------------------------------------------------------


def test_fired_emits_hook_and_appends_history(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    from core.hooks import HookEvent
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock, ts, hist = trigger_paths
    runner = _FakeRunner(target_section="wrapper.intro")
    hooks = _CapturingHooks()
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock,
        timestamp_path=ts,
        history_path=hist,
        hooks=hooks,
        now=2000000.0,
    )
    assert status.state == "fired"
    # Hook emitted exactly once with the FIRED variant
    assert len(hooks.emitted) == 1
    event, payload = hooks.emitted[0]
    assert event == HookEvent.SELF_IMPROVING_AUTO_TRIGGER_FIRED
    assert payload["ts"] == 2000000.0
    assert "wrapper.intro" in payload["detail"]
    # History appended exactly once
    lines = hist.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["state"] == "fired"


def test_lock_busy_emits_hook_and_appends_history(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    from core.hooks import HookEvent
    from core.self_improving.loop.auto_trigger import (
        acquire_auto_trigger_lock,
        auto_trigger_mutator,
        release_auto_trigger_lock,
    )

    lock, ts, hist = trigger_paths
    held = acquire_auto_trigger_lock(lock)
    assert held is not None
    try:
        hooks = _CapturingHooks()
        status = auto_trigger_mutator(
            enabled=True,
            min_interval_minutes=60,
            runner_factory=lambda: _FakeRunner(),
            lock_path=lock,
            timestamp_path=ts,
            history_path=hist,
            hooks=hooks,
        )
        assert status.state == "lock_busy"
        assert len(hooks.emitted) == 1
        assert hooks.emitted[0][0] == HookEvent.SELF_IMPROVING_AUTO_TRIGGER_LOCK_BUSY
        assert hist.read_text(encoding="utf-8").strip().splitlines()
    finally:
        release_auto_trigger_lock(held)


def test_interval_blocked_emits_hook_and_appends_history(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    from core.hooks import HookEvent
    from core.self_improving.loop.auto_trigger import (
        auto_trigger_mutator,
        write_last_run_timestamp,
    )

    lock, ts, hist = trigger_paths
    now = 1000000.0
    write_last_run_timestamp(now - 10 * 60, ts)  # 10 minutes ago
    hooks = _CapturingHooks()
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: _FakeRunner(),
        lock_path=lock,
        timestamp_path=ts,
        history_path=hist,
        hooks=hooks,
        now=now,
    )
    assert status.state == "interval_blocked"
    assert len(hooks.emitted) == 1
    assert hooks.emitted[0][0] == HookEvent.SELF_IMPROVING_AUTO_TRIGGER_INTERVAL_BLOCKED


def test_runner_error_emits_hook_and_appends_history(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    from core.hooks import HookEvent
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock, ts, hist = trigger_paths
    runner = _FakeRunner(raises=RuntimeError("boom"))
    hooks = _CapturingHooks()
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock,
        timestamp_path=ts,
        history_path=hist,
        hooks=hooks,
    )
    assert status.state == "runner_error"
    assert len(hooks.emitted) == 1
    assert hooks.emitted[0][0] == HookEvent.SELF_IMPROVING_AUTO_TRIGGER_RUNNER_ERROR


def test_parse_error_emits_hook_and_appends_history(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    from core.hooks import HookEvent
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock, ts, hist = trigger_paths
    runner = _FakeRunner(raises=ValueError("malformed mutation"))
    hooks = _CapturingHooks()
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock,
        timestamp_path=ts,
        history_path=hist,
        hooks=hooks,
    )
    assert status.state == "parse_error"
    assert len(hooks.emitted) == 1
    assert hooks.emitted[0][0] == HookEvent.SELF_IMPROVING_AUTO_TRIGGER_PARSE_ERROR


def test_disabled_skips_hook_and_history(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    """`disabled` is the only state that does NOT emit a hook OR
    append a row — see STATE_TO_HOOK_EVENT docstring for rationale.
    """
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock, ts, hist = trigger_paths
    hooks = _CapturingHooks()
    status = auto_trigger_mutator(
        enabled=False,
        min_interval_minutes=60,
        runner_factory=lambda: _FakeRunner(),
        lock_path=lock,
        timestamp_path=ts,
        history_path=hist,
        hooks=hooks,
    )
    assert status.state == "disabled"
    assert hooks.emitted == []
    assert not hist.exists()


def test_hooks_none_does_not_crash(trigger_paths: tuple[Path, Path, Path]) -> None:
    """Manual REPL / unit-test path: hooks=None must not raise."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock, ts, hist = trigger_paths
    runner = _FakeRunner()
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock,
        timestamp_path=ts,
        history_path=hist,
        hooks=None,
    )
    assert status.state == "fired"
    # History still written (telemetry sink-free is still loggable)
    assert hist.read_text(encoding="utf-8").strip().splitlines()


def test_multi_call_history_is_append_only(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    """Three sequential calls → three rows."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock, ts, hist = trigger_paths
    for i in range(3):
        runner = _FakeRunner(target_section=f"sec{i}")
        # Each call uses a unique ts; min_interval=0 effectively
        status = auto_trigger_mutator(
            enabled=True,
            min_interval_minutes=1,
            runner_factory=lambda r=runner: r,
            lock_path=lock,
            timestamp_path=ts,
            history_path=hist,
            now=1000.0 + i * 120.0,  # 2 minutes apart
        )
        assert status.state == "fired"
    lines = hist.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3


def test_hook_handler_exception_does_not_break_mutator(
    trigger_paths: tuple[Path, Path, Path],
) -> None:
    """A misbehaving hook subscriber must not crash the state machine."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    lock, ts, hist = trigger_paths

    class _BrokenHooks:
        def trigger(self, event: Any, data: dict[str, Any]) -> None:
            raise RuntimeError("hook handler broke")

    runner = _FakeRunner()
    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=60,
        runner_factory=lambda: runner,
        lock_path=lock,
        timestamp_path=ts,
        history_path=hist,
        hooks=_BrokenHooks(),
    )
    # State machine completed despite hook subscriber crash
    assert status.state == "fired"
    # History still written
    assert hist.read_text(encoding="utf-8").strip().splitlines()
