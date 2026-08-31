from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from core.agent.tool_executor import ToolExecutor
from core.memory.effect_receipts import (
    EffectAdmissionKind,
    EffectReceiptStore,
    effect_operation_id,
)
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
    operation_id = effect_operation_id("s-test", "call-1")
    assert operation_id and operation_id != "call-1"
    return ToolContext(
        session_id="s-test",
        tool_call_id="call-1",
        operation_id=operation_id,
    )


def test_receipt_admission_replays_committed_and_quarantines_unfinished(tmp_path) -> None:
    store = EffectReceiptStore(tmp_path / "sessions.db")
    common = {
        "session_id": "s-test",
        "tool_call_id": "call-1",
        "tool_name": "send_message",
        "effect": "communicate",
        "arguments": {"recipient": "person@example.com", "body": "private body"},
        "personal_data": True,
    }

    first = store.admit(operation_id="op-first", **common)
    assert first.kind is EffectAdmissionKind.NEW
    restarted = EffectReceiptStore(tmp_path / "sessions.db")
    assert restarted.admit(operation_id="op-first", **common).kind is EffectAdmissionKind.UNCERTAIN

    store.commit("op-first", {"_personal_data_omitted": True, "tool_name": "send_message"})
    replay = restarted.admit(operation_id="op-first", **common)
    assert replay.kind is EffectAdmissionKind.REPLAY
    assert replay.result == {"_personal_data_omitted": True, "tool_name": "send_message"}

    conflict = store.admit(
        operation_id="op-first",
        **{**common, "arguments": {"recipient": "other@example.com"}},
    )
    assert conflict.kind is EffectAdmissionKind.CONFLICT

    raw = (
        sqlite3.connect(tmp_path / "sessions.db")
        .execute("SELECT * FROM effect_receipts WHERE operation_id = 'op-first'")
        .fetchone()
    )
    assert raw is not None
    encoded = repr(raw)
    assert "person@example.com" not in encoded
    assert "private body" not in encoded


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
        owner = asyncio.create_task(first.aexecute("action", {"value": 1}, context=_context()))
        await entered.wait()
        duplicate = await second.aexecute("action", {"value": 1}, context=_context())
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
