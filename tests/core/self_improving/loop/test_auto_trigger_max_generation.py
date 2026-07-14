"""PR-MAX-GEN (2026-05-26) — auto_trigger max_generation cap.

Closes the audit finding from the 2026-05-26 autoresearch attribution
sprint Phase A (§5.6): ``auto_trigger_mutator`` only enforced a
``min_interval_minutes`` floor and had no hard cap on total fired
generations. A misconfigured operator could accumulate hundreds of
fires without any stop condition.

This file pins:

1. ``count_fired_generations`` correctly counts only ``state="fired"``
   rows (other states like ``interval_blocked`` ignored).
2. Empty / missing history file → count = 0.
3. ``max_generation=0`` (default) preserves legacy unbounded behaviour.
4. ``max_generation=N`` blocks the (N+1)-th fire with state
   ``max_generation_reached``.
5. The cap check fires BEFORE the lock acquisition (so a saturated
   history doesn't consume the lock for a no-op).
6. Malformed / non-dict / OSError reads degrade gracefully.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest


def _write_history_row(
    path: Path,
    *,
    state: str,
    ts: float | None = None,
    detail: str = "",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row: dict[str, Any] = {
        "ts": ts if ts is not None else time.time(),
        "state": state,
        "detail": detail,
        "trigger_id": "self_improving_loop_auto_trigger",
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# count_fired_generations
# ---------------------------------------------------------------------------


def test_count_fired_generations_missing_file_returns_zero(tmp_path: Path) -> None:
    from core.self_improving.loop.auto_trigger import count_fired_generations

    assert count_fired_generations(history_path=tmp_path / "missing.jsonl") == 0


def test_count_fired_generations_only_counts_fired_state(tmp_path: Path) -> None:
    """``interval_blocked`` / ``lock_busy`` / ``runner_error`` etc. are
    history rows too — they must NOT contribute to the fire count."""
    from core.self_improving.loop.auto_trigger import count_fired_generations

    history = tmp_path / "history.jsonl"
    _write_history_row(history, state="fired")
    _write_history_row(history, state="interval_blocked")
    _write_history_row(history, state="fired")
    _write_history_row(history, state="lock_busy")
    _write_history_row(history, state="runner_error")
    _write_history_row(history, state="parse_error")
    _write_history_row(history, state="fired")

    assert count_fired_generations(history_path=history) == 3


def test_count_fired_generations_skips_malformed_rows(tmp_path: Path) -> None:
    """Best-effort — malformed JSON / non-dict rows / blank lines all
    skipped silently without aborting the scan."""
    from core.self_improving.loop.auto_trigger import count_fired_generations

    history = tmp_path / "history.jsonl"
    _write_history_row(history, state="fired")
    with history.open("a", encoding="utf-8") as fh:
        fh.write("not-json\n")
        fh.write("\n")  # blank
        fh.write("[1, 2, 3]\n")  # non-dict
    _write_history_row(history, state="fired")

    assert count_fired_generations(history_path=history) == 2


def test_count_fired_generations_oserror_returns_partial(tmp_path: Path) -> None:
    """OSError mid-read returns the count accumulated so far (best-effort)."""
    from core.self_improving.loop.auto_trigger import count_fired_generations

    history = tmp_path / "history.jsonl"
    history.write_text("dummy\n", encoding="utf-8")

    with patch.object(Path, "open", side_effect=OSError("disk full")):
        n = count_fired_generations(history_path=history)
    assert n == 0


# ---------------------------------------------------------------------------
# auto_trigger_mutator — max_generation gate behaviour
# ---------------------------------------------------------------------------


def test_max_generation_zero_means_unlimited(tmp_path: Path) -> None:
    """``max_generation=0`` (default) → legacy unbounded behaviour: even
    with 100 prior fires the next call still proceeds past the cap
    check (it may still hit lock/interval/runner gates, but the cap
    itself doesn't block)."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    history = tmp_path / "history.jsonl"
    for _ in range(100):
        _write_history_row(history, state="fired")

    fake_runner_calls: list[None] = []

    class _FakeRunner:
        def run_once(self) -> object:
            fake_runner_calls.append(None)

            class _Mut:
                target_section = "role"

            return _Mut()

    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=0,
        max_generation=0,  # unlimited
        runner_factory=lambda: _FakeRunner(),
        lock_path=tmp_path / "lock",
        timestamp_path=tmp_path / "ts.txt",
        history_path=history,
    )

    assert status.state == "fired"
    assert len(fake_runner_calls) == 1


def test_max_generation_blocks_when_history_at_cap(tmp_path: Path) -> None:
    """``max_generation=3`` + history already has 3 fired rows → next
    call returns ``max_generation_reached`` without invoking runner."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    history = tmp_path / "history.jsonl"
    for _ in range(3):
        _write_history_row(history, state="fired")

    runner_calls: list[None] = []

    class _FakeRunner:
        def run_once(self) -> object:  # pragma: no cover — must not fire
            runner_calls.append(None)
            return object()

    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=0,
        max_generation=3,
        runner_factory=lambda: _FakeRunner(),
        lock_path=tmp_path / "lock",
        timestamp_path=tmp_path / "ts.txt",
        history_path=history,
    )

    assert status.state == "max_generation_reached"
    assert "3/3" in status.detail
    assert runner_calls == []


def test_max_generation_blocks_when_history_above_cap(tmp_path: Path) -> None:
    """Pre-existing history with 5 fires + cap=3 → still blocked. The
    ``>=`` comparison ensures the cap can't be re-entered after the
    operator raises and lowers it."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    history = tmp_path / "history.jsonl"
    for _ in range(5):
        _write_history_row(history, state="fired")

    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=0,
        max_generation=3,
        runner_factory=lambda: (_ for _ in ()).throw(  # pragma: no cover
            AssertionError("must not be called")
        ),
        lock_path=tmp_path / "lock",
        timestamp_path=tmp_path / "ts.txt",
        history_path=history,
    )

    assert status.state == "max_generation_reached"
    assert "5/3" in status.detail


def test_max_generation_allows_when_below_cap(tmp_path: Path) -> None:
    """``max_generation=3`` + history has 2 fired rows → next call
    proceeds (only 2 of 3 used)."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    history = tmp_path / "history.jsonl"
    _write_history_row(history, state="fired")
    _write_history_row(history, state="fired")

    class _FakeRunner:
        def run_once(self) -> object:
            class _Mut:
                target_section = "role"

            return _Mut()

    status = auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=0,
        max_generation=3,
        runner_factory=lambda: _FakeRunner(),
        lock_path=tmp_path / "lock",
        timestamp_path=tmp_path / "ts.txt",
        history_path=history,
    )

    assert status.state == "fired"


def test_max_generation_cap_evaluated_before_lock(tmp_path: Path) -> None:
    """The cap check must fire BEFORE the lock acquisition, otherwise a
    saturated history would still consume + release the lock on every
    cron tick (lock cost wasted)."""
    from core.self_improving.loop import auto_trigger as mod

    history = tmp_path / "history.jsonl"
    for _ in range(2):
        _write_history_row(history, state="fired")

    lock_acquire_calls: list[None] = []

    def fake_acquire(lock_path: Path | None = None) -> int | None:
        lock_acquire_calls.append(None)  # pragma: no cover — must not be reached
        return 1

    with patch.object(mod, "acquire_auto_trigger_lock", fake_acquire):
        status = mod.auto_trigger_mutator(
            enabled=True,
            min_interval_minutes=0,
            max_generation=2,
            runner_factory=lambda: object(),  # would crash if reached
            lock_path=tmp_path / "lock",
            timestamp_path=tmp_path / "ts.txt",
            history_path=history,
        )

    assert status.state == "max_generation_reached"
    assert lock_acquire_calls == []


def test_register_auto_trigger_forwards_max_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex MCP review #1 (FAIL must-fix #1) — pin that
    ``register_auto_trigger`` actually forwards ``max_generation``
    into the scheduler callback. Without this wiring, the new
    config knob was a dead parameter."""
    from core.self_improving.loop import auto_trigger as mod

    forwarded: dict[str, Any] = {}

    def fake_mutator(**kwargs: Any) -> mod.AutoTriggerStatus:
        forwarded.update(kwargs)
        return mod.AutoTriggerStatus(state="fired")

    monkeypatch.setattr(mod, "auto_trigger_mutator", fake_mutator)

    class _FakeTM:
        def __init__(self) -> None:
            self.registered: list[Any] = []

        def register(self, cfg: Any) -> None:
            self.registered.append(cfg)

    tm = _FakeTM()
    result = mod.register_auto_trigger(
        tm,
        enabled=True,
        cron="0 * * * *",
        min_interval_minutes=60,
        max_generation=42,
        runner_factory=lambda: object(),
        hooks=None,
    )

    assert result is True
    assert len(tm.registered) == 1
    # Invoke the registered callback to verify the forwarded knob.
    tm.registered[0].callback({})
    assert forwarded["max_generation"] == 42


def test_max_generation_stage_registered() -> None:
    """PR-HOOK-TAXONOMY D2 — ``max_generation_reached`` is a telemetry
    stage of the single ``SELF_IMPROVING_AUTO_TRIGGER`` event. Without
    the stage entry ``_emit_state_event`` silently skips telemetry."""
    from core.hooks import HookEvent
    from core.self_improving.loop.auto_trigger import AUTO_TRIGGER_TELEMETRY_STAGES

    assert "max_generation_reached" in AUTO_TRIGGER_TELEMETRY_STAGES
    assert HookEvent.SELF_IMPROVING_AUTO_TRIGGER.value == "self_improving_auto_trigger"


def test_max_generation_post_lock_recheck_blocks_overshoot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex MCP review #1 (FAIL must-fix #2) — pin that the post-lock
    cap re-check exists. Simulates the race: pre-lock count is below
    cap, but by the time the lock is acquired another process has
    bumped the count to/above cap. Without re-check both would fire."""
    from core.self_improving.loop import auto_trigger as mod

    history = tmp_path / "history.jsonl"
    # Pre-lock state: 2 fires, cap=3 → pre-lock check allows.
    _write_history_row(history, state="fired")
    _write_history_row(history, state="fired")

    # When the lock acquisition is requested, simulate that ANOTHER
    # process appended a fire between our pre-lock count and our
    # lock-acquire. We mutate the history file mid-flight.
    real_acquire = mod.acquire_auto_trigger_lock

    def fake_acquire(lock_path: Path | None = None) -> int | None:
        _write_history_row(history, state="fired")  # race: cap now reached
        return real_acquire(lock_path=lock_path)

    monkeypatch.setattr(mod, "acquire_auto_trigger_lock", fake_acquire)

    status = mod.auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=0,
        max_generation=3,
        runner_factory=lambda: (_ for _ in ()).throw(  # pragma: no cover
            AssertionError("post-lock re-check should have blocked")
        ),
        lock_path=tmp_path / "lock",
        timestamp_path=tmp_path / "ts.txt",
        history_path=history,
    )

    assert status.state == "max_generation_reached"
    assert "post-lock re-check" in status.detail


def test_max_generation_emits_hook_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Codex MCP review #2 (FAIL must-fix #3) — direct emission test.
    When the cap fires, the registered HookSystem must receive a
    ``SELF_IMPROVING_AUTO_TRIGGER`` event with the
    ``{trigger_id, ts, detail, stage}`` payload. Pins the wiring from
    ``_finalize_status`` → ``_emit_state_event`` →
    ``stage="max_generation_reached"``."""
    from core.hooks import HookEvent
    from core.self_improving.loop import auto_trigger as mod

    history = tmp_path / "history.jsonl"
    for _ in range(3):
        _write_history_row(history, state="fired")

    captured: list[tuple[HookEvent, dict[str, Any]]] = []

    class _FakeHooks:
        def trigger(self, event: HookEvent, payload: dict[str, Any]) -> None:
            captured.append((event, payload))

    status = mod.auto_trigger_mutator(
        enabled=True,
        min_interval_minutes=0,
        max_generation=3,
        runner_factory=lambda: (_ for _ in ()).throw(  # pragma: no cover
            AssertionError("runner must not fire")
        ),
        lock_path=tmp_path / "lock",
        timestamp_path=tmp_path / "ts.txt",
        history_path=history,
        hooks=_FakeHooks(),
    )

    assert status.state == "max_generation_reached"
    # Hook system received the cap-reached event with the canonical
    # auto-trigger payload schema.
    assert len(captured) == 1
    event, payload = captured[0]
    assert event is HookEvent.SELF_IMPROVING_AUTO_TRIGGER
    assert payload["stage"] == "max_generation_reached"
    assert payload["trigger_id"] == mod.AUTO_TRIGGER_TRIGGER_ID
    assert "ts" in payload
    assert "3/3" in payload["detail"]


def test_max_generation_disabled_state_short_circuits_before_cap(tmp_path: Path) -> None:
    """``enabled=False`` short-circuits BEFORE the cap check — disabled
    is a defensive guard that never touches disk."""
    from core.self_improving.loop.auto_trigger import auto_trigger_mutator

    history = tmp_path / "history.jsonl"
    for _ in range(5):
        _write_history_row(history, state="fired")

    status = auto_trigger_mutator(
        enabled=False,
        min_interval_minutes=0,
        max_generation=2,
        history_path=history,
    )

    assert status.state == "disabled"
