"""Resource ownership and dispatch invariants for HookSystem."""

from __future__ import annotations

import asyncio
import time
import weakref
from pathlib import Path

import pytest
from core.agent.tool_executor import ToolExecutor
from core.hooks import (
    DuplicateHookRegistrationError,
    HookAction,
    HookDecision,
    HookDispatch,
    HookEvent,
    HookName,
    HookRegistry,
    HookSystem,
)


# Dispatch stamps ``schema_version`` on every payload (core.hooks.catalog
# OBSERVER_SCHEMA_VERSION). These cases assert delivery, isolation and timeout —
# not the literal key set — so the system field is dropped before comparing.
def _emitted(data):
    return {k: v for k, v in (data or {}).items() if k != "schema_version"}


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

    assert [_emitted(d) for d in observed] == [{"session_id": "s-1"}]
    assert original == {"session_id": "s-1"}


def test_nested_observer_payload_isolated_from_source_handlers_and_sinks() -> None:
    hooks = HookSystem()
    seen: list[str] = []
    sink_seen: list[str] = []

    def mutate(_event: HookEvent, data: dict) -> None:
        data["tool_input"]["path"] = "changed"

    hooks.register(HookEvent.TOOL_EXEC_STARTED, mutate, name="mutate", priority=1)
    hooks.register(
        HookEvent.TOOL_EXEC_STARTED,
        lambda _event, data: seen.append(data["tool_input"]["path"]),
        name="observe",
        priority=2,
    )
    hooks.register_sink(
        lambda dispatch: sink_seen.append(dispatch.data["tool_input"]["path"]),
        name="sink",
    )
    original = {"tool_name": "probe", "tool_input": {"path": "approved"}}
    hooks.trigger(HookEvent.TOOL_EXEC_STARTED, original)

    assert original["tool_input"]["path"] == "approved"
    assert seen == ["approved"]
    assert sink_seen == ["approved"]

    async def run_async() -> None:
        async def async_mutate(_event: HookEvent, data: dict) -> None:
            data["tool_input"]["path"] = "async-changed"

        hooks.clear(HookEvent.TOOL_EXEC_STARTED)
        hooks.register(HookEvent.TOOL_EXEC_STARTED, async_mutate, name="async-mutate", priority=1)
        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            lambda _event, data: seen.append(data["tool_input"]["path"]),
            name="async-observe",
            priority=2,
        )
        await hooks.trigger_async(HookEvent.TOOL_EXEC_STARTED, original)

    asyncio.run(run_async())
    assert original["tool_input"]["path"] == "approved"
    assert seen == ["approved", "approved"]


def test_runtime_observer_cannot_change_approved_tool_arguments() -> None:
    events = HookSystem()
    public_hooks = HookRegistry(events=events)
    admitted: list[str] = []
    dispatched: list[str] = []

    def admit(invocation) -> HookDecision:
        admitted.append(invocation.payload["arguments"]["value"])
        return HookDecision(action=HookAction.CONTINUE)

    def mutate(_event: HookEvent, data: dict) -> None:
        data["tool_input"]["value"] = "observer-changed"

    async def probe(**kwargs: str) -> dict[str, str]:
        dispatched.append(kwargs["value"])
        return {"seen": kwargs["value"]}

    public_hooks.register(HookName.PRE_TOOL_USE, admit)
    events.register(HookEvent.TOOL_EXEC_STARTED, mutate, name="observer")
    executor = ToolExecutor(
        action_handlers={"local_probe": probe},
        hooks=events,
        hook_registry=public_hooks,
        interactive_approval=False,
    )
    result = asyncio.run(executor.aexecute("local_probe", {"value": "approved"}))

    assert admitted == ["approved"]
    assert dispatched == ["approved"]
    assert result == {"seen": "approved"}


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
    assert _emitted(data) == {}
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


@pytest.mark.parametrize("operation", ["close", "replace", "unregister", "cancel"])
def test_sink_close_failure_remains_visible_to_final_exporters(
    operation: str, caplog: pytest.LogCaptureFixture
) -> None:
    hooks = HookSystem()
    closed: list[str] = []

    class _Sink:
        def __call__(self, _dispatch: HookDispatch) -> None:
            return None

        def close(self) -> None:
            closed.append("failed")
            raise OSError("private buffered content")

    subscription = hooks.register_sink(_Sink(), name="buffered")
    assert hooks.has_sink_failures is False
    if operation == "replace":
        hooks.register_sink(lambda _dispatch: None, name="buffered", replace=True)
    elif operation == "unregister":
        assert hooks.unregister_sink("buffered") is True
    elif operation == "cancel":
        assert subscription.cancel() is True
    else:
        hooks.close()
    assert hooks.has_sink_failures is True
    hooks.close()
    assert closed == ["failed"]
    assert hooks.has_sink_failures is True
    assert "OSError" in caplog.text
    assert "private buffered content" not in caplog.text


@pytest.mark.parametrize("failing_owner", ["sink", "cleanup"])
def test_cancelled_close_drains_remaining_owners_then_preserves_cancellation(
    failing_owner: str, caplog: pytest.LogCaptureFixture
) -> None:
    hooks = HookSystem()
    closed: list[str] = []
    original = asyncio.CancelledError("private cancellation")

    class _Sink:
        def __call__(self, _dispatch: HookDispatch) -> None:
            return None

        def close(self) -> None:
            closed.append("good")

    class _CancelledSink(_Sink):
        def close(self) -> None:
            closed.append("cancelled")
            raise original

    hooks.register_sink(_Sink(), name="good")
    if failing_owner == "sink":
        hooks.register_sink(_CancelledSink(), name="cancelled")
    else:
        hooks.add_cleanup("cancelled", _CancelledSink().close)
    with pytest.raises(asyncio.CancelledError) as error:
        hooks.close()
    assert error.value is original
    assert closed == ["cancelled", "good"]
    assert hooks.has_sink_failures is True
    hooks.close()
    assert closed == ["cancelled", "good"]
    assert "private cancellation" not in caplog.text


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
