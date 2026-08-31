from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from core.agent.loop import _guards, _phases
from core.agent.tool_executor import ToolExecutor
from core.hooks import HookAction, HookDecision, HookName, HookRegistry, MiddlewareRegistry
from core.llm.agentic_response import AgenticResponse, ToolUseBlock
from core.memory.effect_receipts import (
    EffectAdmissionKind,
    EffectReceiptStore,
    effect_operation_id,
)
from core.memory.session_checkpoint import SessionCheckpoint, SessionState
from core.memory.session_manager import SessionManager
from core.tools.base import ToolContext
from core.tools.plan import (
    ExecutionBinding,
    SafetyPolicy,
    ToolEffect,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


def _bound(effect: ToolEffect, handler: Any):
    side_effecting = effect is not ToolEffect.READ
    plan = compile_tool_plan(
        ((ToolSpec("action", "action", {"type": "object"}), "test"),),
        (
            ExecutionBinding(
                "action",
                "test",
                resource_strategy="test" if side_effecting else "none",
            ),
        ),
        safety={"action": SafetyPolicy(effect=effect)},
    )
    resolvers = {"action": lambda _arguments: ("test-resource",)} if side_effecting else None
    return bind_tool_plan(plan, {"action": handler}, resolvers)


def _context() -> ToolContext:
    operation_id = effect_operation_id()
    assert operation_id and operation_id != "call-1"
    return ToolContext(
        session_id="s-test",
        step_id="step-1",
        tool_call_id="call-1",
        operation_id=operation_id,
    )


def test_logical_operation_id_is_not_provider_call_correlation() -> None:
    first = effect_operation_id()
    second = effect_operation_id()

    assert first.startswith("op-")
    assert first != second
    assert "call-1" not in first


def test_tool_checkpoint_binds_provider_call_to_logical_operation() -> None:
    processor = SimpleNamespace(
        _step_snapshot=SimpleNamespace(step_id="step-1"),
        operation_id_for=lambda _tool_call_id: "op-1",
    )
    loop = SimpleNamespace(
        _tool_processor=processor,
        _serialize_content=lambda content: [
            {
                "type": block.type,
                "id": block.id,
                "name": block.name,
                "input": block.input,
            }
            for block in content
        ],
    )

    message = _guards._tool_round_assistant_message(
        loop,
        AgenticResponse(
            content=[ToolUseBlock(id="call-1", name="action", input={"value": 1})],
            stop_reason="tool_use",
        ),
    )

    assert message["metadata"]["effect_operations"] == {
        "call-1": {"operation_id": "op-1", "step_id": "step-1"}
    }


def test_receipt_admission_replays_committed_and_quarantines_unfinished(tmp_path) -> None:
    store = EffectReceiptStore(tmp_path / "sessions.db")
    common = {
        "session_id": "s-test",
        "step_id": "step-1",
        "tool_call_id": "call-1",
        "tool_name": "send_message",
        "effect": "communicate",
        "arguments": {"recipient": "person@example.com", "body": "private body"},
        "personal_data": True,
    }

    first = store.admit(operation_id="op-first", **common)
    assert first.kind is EffectAdmissionKind.NEW
    restarted = EffectReceiptStore(tmp_path / "sessions.db")
    assert restarted.admit(operation_id="op-first", **common).kind is EffectAdmissionKind.CONFLICT

    store.commit("op-first", {"_personal_data_omitted": True, "tool_name": "send_message"})
    replay = restarted.admit(operation_id="op-first", **common)
    assert replay.kind is EffectAdmissionKind.CONFLICT
    recovered = restarted.recover(
        operation_id="op-first",
        session_id="s-test",
        step_id="step-1",
        tool_call_id="call-1",
        tool_name="send_message",
        arguments={"_personal_data_omitted": True},
    )
    assert recovered is not None
    assert recovered.kind is EffectAdmissionKind.REPLAY

    replay_with_changed_personal_input = store.admit(
        operation_id="op-first",
        **{**common, "arguments": {"recipient": "other@example.com"}},
    )
    assert replay_with_changed_personal_input.kind is EffectAdmissionKind.CONFLICT

    raw = (
        sqlite3.connect(tmp_path / "sessions.db")
        .execute("SELECT * FROM effect_receipts WHERE operation_id = 'op-first'")
        .fetchone()
    )
    assert raw is not None
    encoded = repr(raw)
    assert "person@example.com" not in encoded
    assert "private body" not in encoded
    raw_payload = json.dumps(
        {"tool_name": "send_message", "arguments": common["arguments"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert hashlib.sha256(raw_payload.encode()).hexdigest() not in encoded


def test_prior_step_uncertainty_blocks_new_effect_until_operator_resolves(tmp_path) -> None:
    store = EffectReceiptStore(tmp_path / "sessions.db")
    common = {
        "session_id": "s-test",
        "tool_call_id": "call-1",
        "tool_name": "action",
        "effect": "mutate",
        "arguments": {"value": 1},
        "personal_data": False,
    }
    assert (
        store.admit(operation_id="op-1", step_id="step-1", **common).kind is EffectAdmissionKind.NEW
    )
    blocked = store.admit(
        operation_id="op-2",
        step_id="step-2",
        **{**common, "tool_call_id": "call-2"},
    )
    assert blocked.kind is EffectAdmissionKind.UNCERTAIN
    assert store.resolve("op-1", applied=False)
    reconciled = store.recover(
        operation_id="op-1",
        session_id="s-test",
        step_id="step-1",
        tool_call_id="call-1",
        tool_name="action",
        arguments={"value": 1},
    )
    assert reconciled is not None
    assert reconciled.kind is EffectAdmissionKind.REPLAY
    assert reconciled.result == {
        "external_effect_applied": False,
        "reconciled_by_operator": True,
    }
    retried = store.admit(
        operation_id="op-2",
        step_id="step-2",
        **{**common, "tool_call_id": "call-2"},
    )
    assert retried.kind is EffectAdmissionKind.NEW


def test_executor_suppresses_duplicate_effect_and_rejects_conflict(tmp_path) -> None:
    handler = MagicMock(return_value={"ok": True})
    db_path = tmp_path / "sessions.db"
    executor = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=EffectReceiptStore(db_path),
    )
    context = _context()

    first = asyncio.run(executor.aexecute("action", {"value": 1}, context=context))
    restarted = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=EffectReceiptStore(db_path),
    )
    replay = asyncio.run(restarted.aexecute("action", {"value": 1}, context=context))
    conflict = asyncio.run(restarted.aexecute("action", {"value": 2}, context=context))

    assert first == replay == {"ok": True}
    assert conflict["error_type"] == "effect_operation_conflict"
    assert handler.call_count == 1
    assert handler.call_args.kwargs["value"] == 1


def test_admission_failure_never_dispatches_effect() -> None:
    handler = MagicMock(return_value={"ok": True})
    receipts = MagicMock(spec=EffectReceiptStore)
    receipts.admit.side_effect = OSError("database unavailable")
    executor = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=receipts,
    )

    result = asyncio.run(executor.aexecute("action", {"value": 1}, context=_context()))

    assert result["error_type"] == "effect_receipt_unavailable"
    handler.assert_not_called()


def test_agent_loop_effect_requires_checkpoint_authority(tmp_path) -> None:
    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=EffectReceiptStore(tmp_path / "sessions.db"),
    )
    context = _context()
    context.agent_loop = SimpleNamespace(_checkpoint=None)

    result = asyncio.run(executor.aexecute("action", {"value": 1}, context=context))

    assert result["error_type"] == "effect_checkpoint_unavailable"
    handler.assert_not_called()


def test_post_effect_commit_failure_stays_uncertain_without_replay(tmp_path) -> None:
    class FailingCommitStore(EffectReceiptStore):
        def commit(self, operation_id: str, result: dict[str, Any]) -> None:
            raise OSError("simulated crash window")

    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.COMMUNICATE, handler),
        effect_receipts=FailingCommitStore(tmp_path / "sessions.db"),
    )
    context = _context()

    first = asyncio.run(executor.aexecute("action", {"value": 1}, context=context))
    restarted = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.COMMUNICATE, handler),
        effect_receipts=EffectReceiptStore(tmp_path / "sessions.db"),
    )
    second = asyncio.run(restarted.aexecute("action", {"value": 1}, context=context))

    assert first["error_type"] == second["error_type"] == "effect_outcome_uncertain"
    assert first["outcome_uncertain"] is second["outcome_uncertain"] is True
    assert handler.call_count == 1
    assert handler.call_args.kwargs["value"] == 1


def test_effect_handler_error_stays_uncertain_without_replay(tmp_path) -> None:
    handler = MagicMock(return_value={"error": "connection closed after request"})
    executor = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.ADMINISTRATIVE, handler),
        effect_receipts=EffectReceiptStore(tmp_path / "sessions.db"),
    )
    context = _context()

    first = asyncio.run(executor.aexecute("action", {"value": 1}, context=context))
    second = asyncio.run(executor.aexecute("action", {"value": 1}, context=context))

    assert first["error_type"] == second["error_type"] == "effect_outcome_uncertain"
    assert handler.call_count == 1


def test_concurrent_duplicate_never_reaches_second_handler(tmp_path) -> None:
    async def exercise() -> None:
        entered = asyncio.Event()
        release = asyncio.Event()
        calls = 0

        async def handler(**_kwargs: Any) -> dict[str, bool]:
            nonlocal calls
            calls += 1
            entered.set()
            await release.wait()
            return {"ok": True}

        db_path = tmp_path / "sessions.db"
        first = ToolExecutor(
            bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
            effect_receipts=EffectReceiptStore(db_path),
        )
        second = ToolExecutor(
            bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
            effect_receipts=EffectReceiptStore(db_path),
        )
        context = _context()
        owner = asyncio.create_task(first.aexecute("action", {"value": 1}, context=context))
        await entered.wait()
        duplicate = await second.aexecute("action", {"value": 1}, context=context)
        release.set()

        assert duplicate["error_type"] == "effect_outcome_uncertain"
        assert await owner == {"ok": True}
        assert calls == 1

    asyncio.run(exercise())


def test_read_effect_bypasses_receipt_rail(tmp_path) -> None:
    handler = MagicMock(return_value={"ok": True})
    receipts = MagicMock(spec=EffectReceiptStore)
    executor = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.READ, handler),
        effect_receipts=receipts,
    )

    assert asyncio.run(executor.aexecute("action", {}, context=_context())) == {"ok": True}
    receipts.admit.assert_not_called()
    assert handler.call_count == 1


def test_post_tool_policy_is_committed_and_not_reapplied_on_replay(tmp_path) -> None:
    handler = MagicMock(return_value={"ok": True})
    hooks = HookRegistry()
    hook = MagicMock(return_value=HookDecision(action=HookAction.BLOCK))
    hooks.register(HookName.POST_TOOL_USE, hook)
    db_path = tmp_path / "sessions.db"
    first = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=EffectReceiptStore(db_path),
        hook_registry=hooks,
    )
    context = _context()
    result = asyncio.run(first.aexecute("action", {"value": 1}, context=context))

    replay = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=EffectReceiptStore(db_path),
    )
    replayed = asyncio.run(replay.aexecute("action", {"value": 1}, context=context))

    assert result == replayed
    assert replayed["error_type"] == "hook_blocked"
    assert handler.call_count == hook.call_count == 1


def test_replay_result_cannot_be_transformed_twice_by_execution_middleware(tmp_path) -> None:
    class AddOne:
        async def tool_execution(self, request: Any, next_call: Any) -> dict[str, Any]:
            result = await next_call(request)
            result["nested"]["value"] += 1
            return result

    middleware = MiddlewareRegistry()
    middleware.register_tool_execution(AddOne(), name="add-one")
    handler = MagicMock(return_value={"nested": {"value": 1}})
    db_path = tmp_path / "sessions.db"
    context = _context()
    first = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=EffectReceiptStore(db_path),
        middleware_registry=middleware,
    )
    restarted = ToolExecutor(
        bound_tool_plan=_bound(ToolEffect.MUTATE, handler),
        effect_receipts=EffectReceiptStore(db_path),
        middleware_registry=middleware,
    )

    assert asyncio.run(first.aexecute("action", {}, context=context)) == {"nested": {"value": 2}}
    assert asyncio.run(restarted.aexecute("action", {}, context=context)) == {
        "nested": {"value": 2}
    }
    assert handler.call_count == 1


def test_strict_checkpoint_rejects_stale_sqlite_message_sot(tmp_path, monkeypatch) -> None:
    checkpoint = SessionCheckpoint(tmp_path)
    checkpoint.save(SessionState(session_id="s", messages=[{"role": "user", "content": "old"}]))
    monkeypatch.setattr(
        SessionManager,
        "upsert_messages",
        MagicMock(side_effect=OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        checkpoint.save(
            SessionState(session_id="s", messages=[{"role": "user", "content": "new"}]),
            strict_messages=True,
        )

    restored = checkpoint.load("s")
    assert restored is not None
    assert [(item["role"], item["content"]) for item in restored.messages] == [("user", "old")]


def test_restart_repairs_committed_tool_call_without_redispatch(tmp_path) -> None:
    store = EffectReceiptStore(tmp_path / "sessions.db")
    store.admit(
        operation_id="op-1",
        session_id="s-test",
        step_id="step-1",
        tool_call_id="call-1",
        tool_name="action",
        effect="mutate",
        arguments={"value": 1},
        personal_data=False,
    )
    store.commit("op-1", {"ok": True})
    context = SimpleNamespace(
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "action",
                        "input": {"value": 1},
                    }
                ],
                "metadata": {
                    "effect_operations": {"call-1": {"operation_id": "op-1", "step_id": "step-1"}}
                },
            }
        ]
    )
    context.get_messages = lambda: list(context.messages)
    saved: list[bool] = []
    executor = SimpleNamespace(_effect_receipts=store)
    loop = SimpleNamespace(
        context=context,
        _session_id="s-test",
        _checkpoint=object(),
        _tool_processor=SimpleNamespace(_executor=executor),
        _save_checkpoint=lambda *_args, **kwargs: (
            saved.append(bool(kwargs.get("strict_messages"))) or True
        ),
    )

    _phases._repair_incomplete_tool_round(loop, "resume")

    assert [message["role"] for message in context.messages] == ["assistant", "user"]
    result = json.loads(context.messages[-1]["content"][0]["content"])
    assert result == {"ok": True}
    assert saved == [True]


def test_restart_never_recovers_by_reused_provider_call_id(tmp_path) -> None:
    store = EffectReceiptStore(tmp_path / "sessions.db")
    store.admit(
        operation_id="op-old",
        session_id="s-test",
        step_id="step-old",
        tool_call_id="call-reused",
        tool_name="action",
        effect="mutate",
        arguments={"value": 1},
        personal_data=False,
    )
    store.commit("op-old", {"old": True})
    context = SimpleNamespace(
        messages=[
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-reused",
                        "name": "action",
                        "input": {"value": 2},
                    }
                ],
                "metadata": {
                    "effect_operations": {
                        "call-reused": {"operation_id": "op-new", "step_id": "step-new"}
                    }
                },
            }
        ]
    )
    context.get_messages = lambda: list(context.messages)
    loop = SimpleNamespace(
        context=context,
        _session_id="s-test",
        _checkpoint=object(),
        _tool_processor=SimpleNamespace(_executor=SimpleNamespace(_effect_receipts=store)),
        _save_checkpoint=lambda *_args, **_kwargs: True,
    )

    _phases._repair_incomplete_tool_round(loop, "resume")

    result = json.loads(context.messages[-1]["content"][0]["content"])
    assert result["error_type"] == "tool_execution_interrupted"
    assert result.get("old") is None


def test_checkpoint_round_trip_preserves_effect_operation_anchor(tmp_path) -> None:
    checkpoint = SessionCheckpoint(tmp_path)
    anchor = {"call-1": {"operation_id": "op-1", "step_id": "step-1"}}
    checkpoint.save(
        SessionState(
            session_id="s",
            messages=[
                {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "call-1", "name": "action", "input": {}}
                    ],
                    "metadata": {"effect_operations": anchor},
                }
            ],
        ),
        strict_messages=True,
    )

    restored = checkpoint.load("s")

    assert restored is not None
    assert restored.messages[0]["metadata"]["effect_operations"] == anchor
