from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from core.agent.tool_executor import ToolExecutor
from core.agent.tool_executor.executor import ResourceLockPool
from core.agent.tool_executor.processor import ToolCallProcessor
from core.hooks import HookAction, HookDecision, HookName, HookRegistry, MiddlewareRegistry
from core.hooks.middleware import ToolCallRequest
from core.tools.base import ToolContext
from core.tools.plan import (
    ApprovalPolicy,
    DataClassification,
    ExecutionBinding,
    PersistenceRule,
    SafetyPolicy,
    ToolEffect,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


class _SecondReservationPool(ResourceLockPool):
    def __init__(self, second_reserved: threading.Event) -> None:
        super().__init__()
        self._second_reserved = second_reserved
        self._reservations = 0

    def _reserve(self, key: str):
        entry = super()._reserve(key)
        self._reservations += 1
        if self._reservations == 2:
            self._second_reserved.set()
        return entry


def _bound(
    policies: dict[str, SafetyPolicy],
    handlers: dict[str, Any],
    *,
    resource_names: frozenset[str] = frozenset(),
):
    specs = tuple(
        (ToolSpec(name, name, {"type": "object"}), f"test[{index}]")
        for index, name in enumerate(policies)
    )
    bindings = tuple(
        ExecutionBinding(
            name,
            "test",
            resource_strategy="test-resource" if name in resource_names else "none",
        )
        for name in policies
    )
    plan = compile_tool_plan(specs, bindings, safety=policies)
    resolvers = {name: lambda arguments: (str(arguments["resource"]),) for name in resource_names}
    return bind_tool_plan(plan, handlers, resolvers)


def test_per_invocation_consent_ignores_cached_and_open_hitl() -> None:
    approvals: list[str] = []
    handler = MagicMock(return_value={"ok": True})
    bound = _bound(
        {
            "private_read": SafetyPolicy(
                data_class=DataClassification.PERSONAL,
                persistence=PersistenceRule.REDACT,
                approval=ApprovalPolicy.PER_INVOCATION,
            )
        },
        {"private_read": handler},
    )
    executor = ToolExecutor(
        bound_tool_plan=bound,
        auto_approve=True,
        hitl_level=0,
        approval_callback=lambda *_args: approvals.append("asked") or "y",
    )
    executor._always_approved_categories.add("declared")
    executor._always_approved_tools.add("private_read")

    asyncio.run(executor.aexecute("private_read", {}))
    asyncio.run(executor.aexecute("private_read", {}))

    assert approvals == ["asked", "asked"]
    assert handler.call_count == 2


def test_cached_declared_approval_is_scoped_to_one_tool() -> None:
    responses = iter(("a", "y"))
    approvals: list[str] = []
    bound = _bound(
        {
            "first": SafetyPolicy(approval=ApprovalPolicy.CACHED),
            "second": SafetyPolicy(approval=ApprovalPolicy.CACHED),
        },
        {
            "first": MagicMock(return_value={"ok": True}),
            "second": MagicMock(return_value={"ok": True}),
        },
    )
    executor = ToolExecutor(
        bound_tool_plan=bound,
        approval_callback=lambda name, *_args: approvals.append(name) or next(responses),
    )

    asyncio.run(executor.aexecute("first", {}))
    asyncio.run(executor.aexecute("first", {}))
    asyncio.run(executor.aexecute("second", {}))

    assert approvals == ["first", "second"]


def test_final_rewrite_recomputes_plan_policy_and_privacy() -> None:
    class RewriteRequest:
        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            return ToolCallRequest(
                tool_name="private_write",
                arguments={"resource": "request"},
                context=request.context,
                correlation=request.correlation,
            )

    middleware = MiddlewareRegistry()
    middleware.register_tool_request(RewriteRequest())
    hooks = HookRegistry()
    hooks.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(
            action=HookAction.REWRITE,
            updates={"arguments": {"resource": "hook"}},
        ),
    )
    observed: list[str] = []
    bound = _bound(
        {
            "public_read": SafetyPolicy(),
            "private_write": SafetyPolicy(
                effect=ToolEffect.MUTATE,
                data_class=DataClassification.PERSONAL,
                persistence=PersistenceRule.REDACT,
                approval=ApprovalPolicy.PER_INVOCATION,
            ),
        },
        {
            "public_read": lambda **_kwargs: {"unexpected": True},
            "private_write": lambda resource: observed.append(resource) or {"ok": True},
        },
        resource_names=frozenset({"private_write"}),
    )
    approvals: list[str] = []
    executor = ToolExecutor(
        bound_tool_plan=bound,
        middleware_registry=middleware,
        hook_registry=hooks,
        hitl_level=0,
        approval_callback=lambda *_args: approvals.append("asked") or "y",
    )
    context = ToolContext()

    result = asyncio.run(executor.aexecute("public_read", {}, context=context))

    assert result == {"ok": True}
    assert approvals == ["asked"]
    assert observed == ["hook"]
    assert context.effective_tool_name == "private_write"
    assert context.contains_personal_data is True


def test_sync_handler_inherits_dispatch_contextvars() -> None:
    marker: ContextVar[str] = ContextVar("test_tool_dispatch_marker", default="missing")
    bound = _bound(
        {"read_marker": SafetyPolicy()},
        {"read_marker": lambda: {"marker": marker.get()}},
    )
    token = marker.set("session-value")
    try:
        result = asyncio.run(ToolExecutor(bound_tool_plan=bound).aexecute("read_marker", {}))
    finally:
        marker.reset(token)

    assert result == {"marker": "session-value"}


def test_personal_handler_exception_omits_secret_from_python_log(caplog) -> None:
    secret = "mailbox-secret-value"

    def fail() -> dict[str, Any]:
        raise ValueError(secret)

    bound = _bound(
        {
            "private_read": SafetyPolicy(
                data_class=DataClassification.PERSONAL,
                persistence=PersistenceRule.REDACT,
            )
        },
        {"private_read": fail},
    )

    result = asyncio.run(ToolExecutor(bound_tool_plan=bound).aexecute("private_read", {}))

    assert secret in result["error"]
    assert secret not in caplog.text
    assert "ValueError" in caplog.text


def test_personal_processor_exception_omits_secret_from_python_log(caplog) -> None:
    secret = "rewritten-private-value"
    bound = _bound(
        {
            "private_read": SafetyPolicy(
                data_class=DataClassification.PERSONAL,
                persistence=PersistenceRule.REDACT,
            )
        },
        {"private_read": lambda: {"ok": True}},
    )

    class EscapingExecutor(ToolExecutor):
        async def aexecute(self, *_args: Any, **kwargs: Any) -> dict[str, Any]:
            context = kwargs["context"]
            context.effective_tool_name = "private_read"
            context.contains_personal_data = True
            raise ValueError(secret)

    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    processor = ToolCallProcessor(
        executor=EscapingExecutor(bound_tool_plan=bound),
        op_logger=op_logger,
        error_recovery=MagicMock(),
    )
    block = SimpleNamespace(name="public_read", input={}, id="call")

    result = asyncio.run(processor._execute_single(block))

    assert secret in str(result)
    assert secret not in caplog.text
    assert "ValueError" in caplog.text


def test_personal_tool_failures_never_enter_automatic_recovery() -> None:
    handler = MagicMock(return_value={"error": "private failure", "recoverable": True})
    bound = _bound(
        {
            "private_read": SafetyPolicy(
                data_class=DataClassification.PERSONAL,
                persistence=PersistenceRule.REDACT,
                approval=ApprovalPolicy.PER_INVOCATION,
            )
        },
        {"private_read": handler},
    )
    recovery = MagicMock()
    recovery.arecover = AsyncMock()
    timeline = MagicMock()
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    processor = ToolCallProcessor(
        executor=ToolExecutor(
            bound_tool_plan=bound,
            approval_callback=lambda *_args: "y",
        ),
        op_logger=op_logger,
        error_recovery=recovery,
        timeline=timeline,
    )
    block = SimpleNamespace(
        name="private_read",
        input={"query": "private-query-value"},
        id="private-call",
    )

    for _ in range(3):
        asyncio.run(processor._execute_single(block))

    recovery.arecover.assert_not_awaited()
    assert handler.call_count == 3
    assert "private-query-value" not in repr(timeline.mock_calls)


def test_plan_runtime_availability_denies_headless_and_subagent_calls() -> None:
    handler = MagicMock(return_value={"ok": True})
    bound = _bound(
        {
            "restricted": SafetyPolicy(
                allow_headless=False,
                allow_subagents=False,
            )
        },
        {"restricted": handler},
    )

    headless = asyncio.run(
        ToolExecutor(bound_tool_plan=bound, interactive_approval=False).aexecute("restricted", {})
    )
    subagent = asyncio.run(
        ToolExecutor(bound_tool_plan=bound).aexecute(
            "restricted", {}, context=ToolContext(is_subagent=True)
        )
    )

    assert headless["error_type"] == "tool_policy_denied"
    assert subagent["error_type"] == "tool_policy_denied"
    handler.assert_not_called()


def test_legacy_gate_remains_for_plan_outside_compatibility() -> None:
    handler = MagicMock(return_value={"ok": True})
    executor = ToolExecutor(
        action_handlers={"memory_save": handler},
        approval_callback=lambda *_args: "n",
    )

    result = asyncio.run(executor.aexecute("memory_save", {"key": "k", "content": "x"}))

    assert result["denied"] is True
    handler.assert_not_called()


def test_hook_permission_cannot_be_bypassed_by_skip_or_cached_approval() -> None:
    from core.agent.safety import _skip_permissions_var

    hooks = HookRegistry()
    hooks.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(action=HookAction.REQUEST_PERMISSION),
    )
    handler = MagicMock(return_value={"ok": True})
    bound = _bound(
        {"guarded": SafetyPolicy(approval=ApprovalPolicy.CACHED)},
        {"guarded": handler},
    )
    approvals: list[str] = []
    executor = ToolExecutor(
        bound_tool_plan=bound,
        hook_registry=hooks,
        auto_approve=True,
        hitl_level=0,
        approval_callback=lambda *_args: approvals.append("asked") or "n",
    )
    executor._always_approved_categories.add("policy:cached")
    executor._always_approved_tools.add("guarded")
    token = _skip_permissions_var.set(True)
    try:
        result = asyncio.run(executor.aexecute("guarded", {}))
    finally:
        _skip_permissions_var.reset(token)

    assert result["denied"] is True
    assert approvals == ["asked"]
    handler.assert_not_called()


def test_hook_permission_grant_is_not_prompted_twice_by_legacy_gate() -> None:
    from core.agent.safety import _skip_permissions_var

    hooks = HookRegistry()
    hooks.register(
        HookName.PRE_TOOL_USE,
        lambda _invocation: HookDecision(action=HookAction.REQUEST_PERMISSION),
    )
    handler = MagicMock(return_value={"ok": True})
    approvals: list[str] = []
    executor = ToolExecutor(
        action_handlers={"memory_save": handler},
        hook_registry=hooks,
        hitl_level=0,
        approval_callback=lambda *_args: approvals.append("asked") or "y",
    )
    executor._always_approved_categories.add("write")
    executor._always_approved_tools.add("memory_save")
    token = _skip_permissions_var.set(True)
    try:
        result = asyncio.run(executor.aexecute("memory_save", {"key": "k", "content": "x"}))
    finally:
        _skip_permissions_var.reset(token)

    assert result == {"ok": True}
    assert approvals == ["asked"]
    handler.assert_called_once()


@pytest.mark.parametrize("stage", ["request", "hook"])
def test_rewrite_cannot_drop_per_invocation_approval(stage: str) -> None:
    class RewriteRequest:
        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            return replace(request, tool_name="weak")

    middleware = MiddlewareRegistry()
    hooks = HookRegistry()
    if stage == "request":
        middleware.register_tool_request(RewriteRequest())
    else:
        hooks.register(
            HookName.PRE_TOOL_USE,
            lambda _invocation: HookDecision(
                action=HookAction.REWRITE,
                updates={"tool_name": "weak"},
            ),
        )
    strict = MagicMock(return_value={"ok": True})
    weak = MagicMock(return_value={"ok": True})
    bound = _bound(
        {
            "strict": SafetyPolicy(approval=ApprovalPolicy.PER_INVOCATION),
            "weak": SafetyPolicy(),
        },
        {"strict": strict, "weak": weak},
    )
    executor = ToolExecutor(
        bound_tool_plan=bound,
        middleware_registry=middleware,
        hook_registry=hooks,
        auto_approve=True,
        hitl_level=0,
    )

    result = asyncio.run(executor.aexecute("strict", {}))

    assert result["error_type"] == "tool_policy_downgrade"
    strict.assert_not_called()
    weak.assert_not_called()


def test_rewrite_cannot_change_effect_domain_laterally() -> None:
    class RewriteRequest:
        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            return replace(request, tool_name="communicate")

    middleware = MiddlewareRegistry()
    middleware.register_tool_request(RewriteRequest())
    mutate = MagicMock(return_value={"ok": True})
    communicate = MagicMock(return_value={"ok": True})
    bound = _bound(
        {
            "mutate": SafetyPolicy(effect=ToolEffect.MUTATE),
            "communicate": SafetyPolicy(effect=ToolEffect.COMMUNICATE),
        },
        {"mutate": mutate, "communicate": communicate},
        resource_names=frozenset({"mutate", "communicate"}),
    )
    executor = ToolExecutor(bound_tool_plan=bound, middleware_registry=middleware)

    result = asyncio.run(executor.aexecute("mutate", {}))

    assert result["error_type"] == "tool_policy_downgrade"
    mutate.assert_not_called()
    communicate.assert_not_called()


def test_request_rewrite_cannot_drop_residual_dangerous_policy() -> None:
    class RewriteRequest:
        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            return replace(request, tool_name="weak")

    middleware = MiddlewareRegistry()
    middleware.register_tool_request(RewriteRequest())
    weak = MagicMock(return_value={"ok": True})
    computer = MagicMock(return_value={"ok": True})
    bound = _bound({"weak": SafetyPolicy()}, {"weak": weak})
    executor = ToolExecutor(
        bound_tool_plan=bound,
        transient_handlers={"computer": computer},
        middleware_registry=middleware,
        interactive_approval=False,
    )

    result = asyncio.run(executor.aexecute("computer", {}))

    assert result["error_type"] == "tool_policy_downgrade"
    computer.assert_not_called()
    weak.assert_not_called()


def test_request_rewrite_cannot_drop_residual_mcp_approval() -> None:
    class RewriteRequest:
        async def tool_request(self, request: ToolCallRequest) -> ToolCallRequest:
            return replace(request, tool_name="weak")

    middleware = MiddlewareRegistry()
    middleware.register_tool_request(RewriteRequest())
    weak = MagicMock(return_value={"ok": True})
    bound = _bound({"weak": SafetyPolicy()}, {"weak": weak})
    mcp = MagicMock()
    mcp.find_server_for_tool.return_value = "remote"
    executor = ToolExecutor(
        bound_tool_plan=bound,
        middleware_registry=middleware,
        mcp_manager=mcp,
    )
    executor._replace_bound_tool_scope({"remote_mutate"})

    result = asyncio.run(executor.aexecute("remote_mutate", {}))

    assert result["error_type"] == "tool_policy_downgrade"
    weak.assert_not_called()


def test_processor_parallelizes_distinct_resources_and_cleans_lock_pool() -> None:
    active_total = 0
    max_total = 0
    active_by_resource: dict[str, int] = {}
    max_by_resource: dict[str, int] = {}

    first_entries = {"a": asyncio.Event(), "b": asyncio.Event()}
    second_entries = {"a": asyncio.Event(), "b": asyncio.Event()}
    release = asyncio.Event()

    async def handler(resource: str, **_kwargs: Any) -> dict[str, bool]:
        nonlocal active_total, max_total
        active_total += 1
        active_by_resource[resource] = active_by_resource.get(resource, 0) + 1
        max_total = max(max_total, active_total)
        max_by_resource[resource] = max(
            max_by_resource.get(resource, 0), active_by_resource[resource]
        )
        entry = (
            first_entries[resource]
            if max_by_resource[resource] == 1 and not first_entries[resource].is_set()
            else second_entries[resource]
        )
        entry.set()
        await release.wait()
        active_by_resource[resource] -= 1
        active_total -= 1
        return {"ok": True}

    bound = _bound(
        {
            "memory_save": SafetyPolicy(
                effect=ToolEffect.MUTATE,
                approval=ApprovalPolicy.CACHED,
            )
        },
        {"memory_save": handler},
        resource_names=frozenset({"memory_save"}),
    )
    executor = ToolExecutor(
        bound_tool_plan=bound,
        approval_callback=lambda *_args: "y",
    )
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=op_logger,
        error_recovery=MagicMock(),
    )
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", name="memory_save", input={"resource": key}, id=i)
            for i, key in enumerate(("a", "a", "b", "b"))
        ]
    )

    async def exercise() -> list[dict[str, Any]]:
        task = asyncio.create_task(processor.process(response))
        await asyncio.wait_for(
            asyncio.gather(first_entries["a"].wait(), first_entries["b"].wait()),
            timeout=1,
        )
        assert second_entries["a"].is_set() is False
        assert second_entries["b"].is_set() is False
        release.set()
        return await task

    results = asyncio.run(exercise())

    assert len(results) == 4
    assert max_total == 2
    assert max_by_resource == {"a": 1, "b": 1}
    assert executor._resource_lock_pool.entry_count == 0


def test_processor_static_cost_tier_is_fallback_only_for_unbound_tools() -> None:
    approvals: list[str] = []
    handler = MagicMock(return_value={"ok": True})
    bound = _bound(
        {"petri_audit": SafetyPolicy()},
        {"petri_audit": handler},
    )
    executor = ToolExecutor(
        bound_tool_plan=bound,
        approval_callback=lambda *_args: approvals.append("asked") or "n",
    )
    op_logger = MagicMock()
    op_logger.log_tool_call.return_value = True
    processor = ToolCallProcessor(
        executor=executor,
        op_logger=op_logger,
        error_recovery=MagicMock(),
    )
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", name="petri_audit", input={}, id=str(index))
            for index in range(2)
        ]
    )

    results = asyncio.run(processor.process(response))

    assert len(results) == 2
    assert approvals == []
    assert handler.call_count == 2


def test_shared_resource_pool_serializes_two_executors() -> None:
    async def exercise() -> None:
        second_reserved = asyncio.Event()

        class ObservedPool(ResourceLockPool):
            def __init__(self) -> None:
                super().__init__()
                self.reservations = 0

            def _reserve(self, key: str):
                entry = super()._reserve(key)
                self.reservations += 1
                if self.reservations == 2:
                    second_reserved.set()
                return entry

        pool = ObservedPool()
        first_entered = asyncio.Event()
        second_entered = asyncio.Event()
        release = asyncio.Event()

        async def first_handler(resource: str) -> dict[str, bool]:
            first_entered.set()
            await release.wait()
            return {"ok": True}

        async def second_handler(resource: str) -> dict[str, bool]:
            second_entered.set()
            return {"ok": True}

        policy = SafetyPolicy(effect=ToolEffect.MUTATE)
        first = ToolExecutor(
            bound_tool_plan=_bound(
                {"mutate": policy},
                {"mutate": first_handler},
                resource_names=frozenset({"mutate"}),
            ),
            resource_lock_pool=pool,
        )
        second = ToolExecutor(
            bound_tool_plan=_bound(
                {"mutate": policy},
                {"mutate": second_handler},
                resource_names=frozenset({"mutate"}),
            ),
            resource_lock_pool=pool,
        )

        owner = asyncio.create_task(first.aexecute("mutate", {"resource": "same"}))
        await first_entered.wait()
        waiter = asyncio.create_task(second.aexecute("mutate", {"resource": "same"}))
        await second_reserved.wait()
        assert second_entered.is_set() is False
        release.set()
        await asyncio.gather(owner, waiter)
        assert second_entered.is_set() is True
        assert pool.entry_count == 0

    asyncio.run(exercise())


def test_timed_out_sync_mutation_holds_lock_until_thread_finishes(monkeypatch) -> None:
    from core.agent.tool_executor import executor as executor_module

    monkeypatch.setattr(executor_module, "_tool_deadline_s", lambda _name: 0.01)
    second_reserved = threading.Event()
    pool = _SecondReservationPool(second_reserved)
    first_entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()

    def first_handler(resource: str) -> dict[str, bool]:
        first_entered.set()
        release.wait()
        return {"ok": True}

    def second_handler(resource: str) -> dict[str, bool]:
        second_entered.set()
        return {"ok": True}

    policy = SafetyPolicy(effect=ToolEffect.MUTATE)
    first = ToolExecutor(
        bound_tool_plan=_bound(
            {"mutate": policy},
            {"mutate": first_handler},
            resource_names=frozenset({"mutate"}),
        ),
        resource_lock_pool=pool,
    )
    second = ToolExecutor(
        bound_tool_plan=_bound(
            {"mutate": policy},
            {"mutate": second_handler},
            resource_names=frozenset({"mutate"}),
        ),
        resource_lock_pool=pool,
    )

    async def exercise() -> None:
        try:
            first_result = await first.aexecute("mutate", {"resource": "same"})
            assert first_result["timeout"] is True
            assert first_entered.is_set()
            waiter = asyncio.create_task(second.aexecute("mutate", {"resource": "same"}))
            assert await asyncio.to_thread(second_reserved.wait, 1)
            assert second_entered.is_set() is False
            release.set()
            assert await waiter == {"ok": True}
            assert pool.entry_count == 0
        finally:
            release.set()

    asyncio.run(exercise())


def test_cancelled_sync_mutation_holds_lock_until_thread_finishes() -> None:
    second_reserved = threading.Event()
    pool = _SecondReservationPool(second_reserved)
    first_entered = threading.Event()
    second_entered = threading.Event()
    release = threading.Event()

    def first_handler(resource: str) -> dict[str, bool]:
        first_entered.set()
        release.wait()
        return {"ok": True}

    def second_handler(resource: str) -> dict[str, bool]:
        second_entered.set()
        return {"ok": True}

    policy = SafetyPolicy(effect=ToolEffect.MUTATE)
    first = ToolExecutor(
        bound_tool_plan=_bound(
            {"mutate": policy},
            {"mutate": first_handler},
            resource_names=frozenset({"mutate"}),
        ),
        resource_lock_pool=pool,
    )
    second = ToolExecutor(
        bound_tool_plan=_bound(
            {"mutate": policy},
            {"mutate": second_handler},
            resource_names=frozenset({"mutate"}),
        ),
        resource_lock_pool=pool,
    )

    async def exercise() -> None:
        try:
            owner = asyncio.create_task(first.aexecute("mutate", {"resource": "same"}))
            assert await asyncio.to_thread(first_entered.wait, 1)
            owner.cancel()
            with pytest.raises(asyncio.CancelledError):
                await owner
            waiter = asyncio.create_task(second.aexecute("mutate", {"resource": "same"}))
            assert await asyncio.to_thread(second_reserved.wait, 1)
            assert second_entered.is_set() is False
            release.set()
            assert await waiter == {"ok": True}
            assert pool.entry_count == 0
        finally:
            release.set()

    asyncio.run(exercise())


def test_cancelled_shared_resource_waiter_cleans_pool() -> None:
    async def exercise() -> None:
        second_reserved = asyncio.Event()
        idle = asyncio.Event()

        class ObservedPool(ResourceLockPool):
            def __init__(self) -> None:
                super().__init__()
                self.reservations = 0

            def _reserve(self, key: str):
                entry = super()._reserve(key)
                self.reservations += 1
                if self.reservations == 2:
                    second_reserved.set()
                return entry

            def _drop(self, key: str, entry: Any) -> None:
                super()._drop(key, entry)
                if self.entry_count == 0:
                    idle.set()

        pool = ObservedPool()
        owner_entered = asyncio.Event()
        cancelled_handler_entered = asyncio.Event()
        release = asyncio.Event()

        async def owner_handler(resource: str) -> dict[str, bool]:
            owner_entered.set()
            await release.wait()
            return {"ok": True}

        async def cancelled_handler(resource: str) -> dict[str, bool]:
            cancelled_handler_entered.set()
            return {"ok": True}

        policy = SafetyPolicy(effect=ToolEffect.MUTATE)
        owner_executor = ToolExecutor(
            bound_tool_plan=_bound(
                {"mutate": policy},
                {"mutate": owner_handler},
                resource_names=frozenset({"mutate"}),
            ),
            resource_lock_pool=pool,
        )
        waiter_executor = ToolExecutor(
            bound_tool_plan=_bound(
                {"mutate": policy},
                {"mutate": cancelled_handler},
                resource_names=frozenset({"mutate"}),
            ),
            resource_lock_pool=pool,
        )

        owner = asyncio.create_task(owner_executor.aexecute("mutate", {"resource": "same"}))
        await owner_entered.wait()
        waiter = asyncio.create_task(waiter_executor.aexecute("mutate", {"resource": "same"}))
        await second_reserved.wait()
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        release.set()
        await owner
        await asyncio.wait_for(idle.wait(), timeout=1)
        assert cancelled_handler_entered.is_set() is False
        assert pool.entry_count == 0

    asyncio.run(exercise())


def test_resource_resolution_failure_is_fail_closed() -> None:
    handler = MagicMock(return_value={"ok": True})
    bound = _bound(
        {
            "mutate": SafetyPolicy(
                effect=ToolEffect.MUTATE,
                approval=ApprovalPolicy.NONE,
            )
        },
        {"mutate": handler},
        resource_names=frozenset({"mutate"}),
    )
    executor = ToolExecutor(bound_tool_plan=bound)

    result = asyncio.run(executor.aexecute("mutate", {}))

    assert result["error_type"] == "resource_key_resolution"
    handler.assert_not_called()
    assert executor._resource_lock_pool.entry_count == 0


def test_resource_lock_pool_cleans_up_after_handler_failure() -> None:
    def fail(resource: str) -> dict[str, bool]:
        raise RuntimeError("boom")

    bound = _bound(
        {"mutate": SafetyPolicy(effect=ToolEffect.MUTATE)},
        {"mutate": fail},
        resource_names=frozenset({"mutate"}),
    )
    executor = ToolExecutor(bound_tool_plan=bound)

    result = asyncio.run(executor.aexecute("mutate", {"resource": "same"}))

    assert result["error_type"] == "internal"
    assert executor._resource_lock_pool.entry_count == 0
