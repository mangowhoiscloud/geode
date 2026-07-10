"""Resource ownership and dispatch invariants for HookSystem."""

from __future__ import annotations

import asyncio
import time
import weakref
from pathlib import Path

import pytest
from core.hooks import (
    DuplicateHookRegistrationError,
    HookDispatch,
    HookEvent,
    HookSystem,
)


def test_subscription_cancel_is_idempotent() -> None:
    hooks = HookSystem()
    calls: list[str] = []
    subscription = hooks.register(
        HookEvent.SESSION_STARTED,
        lambda _event, _data: calls.append("called"),
        name="listener",
    )

    assert subscription.cancel() is True
    assert subscription.cancel() is False
    hooks.trigger(HookEvent.SESSION_STARTED)
    assert calls == []


def test_sink_receives_exactly_one_completed_dispatch_per_trigger_mode() -> None:
    hooks = HookSystem()
    dispatches: list[HookDispatch] = []
    hooks.register_sink(dispatches.append, name="capture")

    hooks.trigger(HookEvent.SESSION_STARTED)
    hooks.trigger_with_result(HookEvent.SESSION_ENDED)
    hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED)
    asyncio.run(hooks.trigger_async(HookEvent.SESSION_STARTED))
    asyncio.run(hooks.trigger_with_result_async(HookEvent.SESSION_ENDED))
    asyncio.run(hooks.trigger_interceptor_async(HookEvent.USER_INPUT_RECEIVED))

    assert len(dispatches) == 6


def test_observer_top_level_mutation_does_not_bleed_to_later_handlers() -> None:
    hooks = HookSystem()
    observed: list[dict] = []

    def _mutate(_event: HookEvent, data: dict) -> None:
        data["changed"] = True

    hooks.register(HookEvent.SESSION_STARTED, _mutate, name="mutate", priority=1)
    hooks.register(
        HookEvent.SESSION_STARTED,
        lambda _event, data: observed.append(data),
        name="observe",
        priority=2,
    )
    original = {"session_id": "s-1"}
    hooks.trigger(HookEvent.SESSION_STARTED, original)

    assert observed == [{"session_id": "s-1"}]
    assert original == {"session_id": "s-1"}


def test_overlapping_name_collision_with_different_handlers_fails_loud() -> None:
    hooks = HookSystem()
    hooks.register_prefix("SESSION", lambda _e, _d: None, name="same")

    with pytest.raises(DuplicateHookRegistrationError, match="overlaps"):
        hooks.register(HookEvent.SESSION_STARTED, lambda _e, _d: None, name="same")


def test_async_timeout_cancels_handler_without_waiting_for_full_delay() -> None:
    hooks = HookSystem()
    cancelled = asyncio.Event()

    async def _slow(_event: HookEvent, _data: dict) -> dict:
        try:
            await asyncio.sleep(5)
        finally:
            cancelled.set()
        return {"modify": {"late": True}}

    hooks.register(HookEvent.USER_INPUT_RECEIVED, _slow, name="slow")

    async def _run() -> tuple[float, dict]:
        started = time.monotonic()
        result = await hooks.trigger_interceptor_async(
            HookEvent.USER_INPUT_RECEIVED,
            {},
            timeout_s=0.01,
        )
        return time.monotonic() - started, result.data

    elapsed, data = asyncio.run(_run())
    assert elapsed < 0.5
    assert data == {}
    assert cancelled.is_set()


def test_close_runs_cleanup_and_closes_sink_once() -> None:
    hooks = HookSystem()
    calls: list[str] = []

    class _Sink:
        def __call__(self, _dispatch: HookDispatch) -> None:
            return None

        def close(self) -> None:
            calls.append("sink")

    hooks.add_cleanup("cleanup", lambda: calls.append("cleanup"))
    hooks.register_sink(_Sink(), name="sink")
    hooks.close()
    hooks.close()

    assert calls == ["cleanup", "sink"]
    assert hooks.list_hooks() == {}
    assert hooks.list_sinks() == []


def test_owner_cleanup_does_not_create_a_self_cycle() -> None:
    hooks = HookSystem()
    owner_ref = weakref.ref(hooks)
    hooks.add_owner_cleanup("binding", lambda _owner: None)

    del hooks

    assert owner_ref() is None


def test_replacing_or_cancelling_sink_releases_previous_resource() -> None:
    hooks = HookSystem()
    closed: list[str] = []

    class _Sink:
        def __init__(self, name: str) -> None:
            self.name = name

        def __call__(self, _dispatch: HookDispatch) -> None:
            return None

        def close(self) -> None:
            closed.append(self.name)

    stale_subscription = hooks.register_sink(_Sink("first"), name="sink")
    subscription = hooks.register_sink(_Sink("second"), name="sink", replace=True)
    assert closed == ["first"]
    assert stale_subscription.cancel() is False
    assert hooks.list_sinks() == ["sink"]
    assert subscription.cancel() is True
    assert closed == ["first", "second"]


def test_closing_older_bootstrap_does_not_clear_newer_global_binding(tmp_path: Path) -> None:
    from core.llm.router import _hooks as router_hooks
    from core.wiring.bootstrap import build_hooks

    older, _, _ = build_hooks(
        session_key="older",
        run_id="run-1",
        log_dir=tmp_path / "older",
    )
    newer, _, _ = build_hooks(
        session_key="newer",
        run_id="run-2",
        log_dir=tmp_path / "newer",
    )
    assert router_hooks._hooks_ctx is newer

    older.close()
    assert router_hooks._hooks_ctx is newer
    newer.close()
    assert router_hooks._hooks_ctx is None


def test_replaced_bootstrap_can_release_owned_sqlite_resources(tmp_path: Path) -> None:
    from core.wiring.bootstrap import build_hooks

    older, _, _ = build_hooks(
        session_key="older",
        run_id="run-1",
        log_dir=tmp_path / "older",
    )
    older_ref = weakref.ref(older)
    newer, _, _ = build_hooks(
        session_key="newer",
        run_id="run-2",
        log_dir=tmp_path / "newer",
    )

    del older

    assert older_ref() is None
    newer.close()
