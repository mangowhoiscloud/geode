"""Context recovery through the real turn, adapter, compactor, and hook owners."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from core.agent.context_manager import ContextWindowManager
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig, AgenticResult, _phases
from core.agent.tool_executor import ToolExecutor
from core.config import settings
from core.hooks import HookAction, HookDecision, HookName, HookRegistry
from core.llm.adapters.base import AdapterCallRequest, AdapterCallResult, UsageSummary
from core.llm.adapters.openrouter_payg import OpenRouterPaygAdapter
from core.orchestration.context_monitor import check_context
from openai import BadRequestError


def _history(count=20, chars=1500):
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"fact-{i}: " + "x" * chars}
        for i in range(count)
    ]


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("persistent_rejection", [False, True])
def test_actual_input_rejection_recovers_below_local_threshold(
    strict, persistent_rejection, monkeypatch
):
    """SDK rejection survives both error modes; the next wire request is smaller."""
    monkeypatch.setenv("GEODE_LLM_FAIL_FAST_ON_ADAPTER_ERROR", "1" if strict else "0")
    monkeypatch.setattr(settings, "replan_enabled", False)
    registry = HookRegistry()
    events = []

    async def observe(invocation):
        events.append((invocation.name, dict(invocation.payload)))
        return HookDecision()

    registry.register(HookName.PRE_COMPACT, observe, name="capture-pre")
    registry.register(HookName.POST_COMPACT, observe, name="capture-post")
    context = ConversationContext(messages=_history())
    loop = AgenticLoop(
        context,
        ToolExecutor(action_handlers={}, hook_registry=registry),
        config=AgenticLoopConfig(
            source="payg",
            max_rounds=4,
            allowed_tool_names=set(),
            system_prompt_override="Offline context recovery test.",
        ),
        model="openrouter/openai/gpt-6-sol",
        provider="openrouter",
        quiet=True,
    )
    adapter = OpenRouterPaygAdapter()
    loop._new_adapter = adapter
    calls = []
    error = BadRequestError(
        "maximum context length exceeded",
        response=httpx.Response(400, request=httpx.Request("POST", "https://offline.invalid")),
        body={"error": {"code": "context_length_exceeded"}},
    )

    async def create(**kwargs):
        calls.append(deepcopy(kwargs))
        if len(calls) == 1 or persistent_rejection:
            raise error
        text = (
            "Recovered candidate."
            if len(calls) == 2
            else (
                '{"passed":true,"score":1.0,"reflection":{"observation":"Fixture accepted",'
                '"lesson":"Preserve evidence","next_check":"none"}}'
            )
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=10),
        )

    transport = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(adapter, "_get_client", lambda model="": transport)
    summary = AsyncMock(side_effect=["Earlier findings. " + "z" * 12_000, "Earlier facts."])
    monkeypatch.setattr("core.orchestration.compaction._call_summarize", summary)
    assert not check_context(context.messages, loop.model).is_warning

    result = asyncio.run(loop.arun("Preserve this current request exactly."))

    assert result.termination_reason == ("context_exhausted" if persistent_rejection else "natural")
    if not persistent_rejection:
        assert result.text == "Recovered candidate."
    assert len(calls) == 3  # finite rejection, or rejected + retry + final verification
    assert len(str(calls[1]["messages"])) < len(str(calls[0]["messages"]))
    assert str(calls[1]["messages"]).count("Preserve this current request exactly.") == 1
    assert summary.await_count == (2 if persistent_rejection else 1)
    assert summary.await_args.kwargs["source"] == "payg"
    assert [name for name, _ in events] == [
        HookName.PRE_COMPACT,
        HookName.POST_COMPACT,
    ] * summary.await_count
    assert events[0][1]["trigger"] == "provider_overflow"
    assert events[0][1]["hard"] is True
    assert (
        sum(
            message.get("content") == "Preserve this current request exactly."
            for message in context.messages
        )
        == 1
    )


def test_equal_count_compaction_is_progress(monkeypatch):
    messages = _history(count=8, chars=10_000)
    before = check_context(messages, "gpt-6-sol").estimated_tokens
    monkeypatch.setattr(settings, "compact_keep_recent", 8)
    monkeypatch.setattr(
        "core.orchestration.compaction._call_summarize", AsyncMock(return_value="Facts.")
    )
    manager = ContextWindowManager(hooks=None, quiet=True, source_provider=lambda: "payg")

    result = asyncio.run(
        manager.aggressive_context_recovery(
            "",
            messages,
            "gpt-6-sol",
            "openai",
            provider_rejected=True,
        )
    )

    assert result.status == "changed"
    assert result.original_count == result.new_count == 8
    assert check_context(messages, "gpt-6-sol").estimated_tokens < before


@pytest.mark.parametrize("hard", [False, True])
def test_failed_checkpoint_does_not_fall_through_to_pruning(hard, monkeypatch):
    messages = _history()
    original = deepcopy(messages)
    monkeypatch.setattr(
        "core.orchestration.compaction._call_summarize", AsyncMock(return_value="Facts.")
    )
    calls = []

    def failed_commit():
        calls.append(deepcopy(messages))
        raise OSError("checkpoint storage unavailable")

    manager = ContextWindowManager(hooks=None, quiet=True)
    result = asyncio.run(
        manager._apply_overflow_strategy(
            {"strategy": "compact", "keep_recent": 4, "hard": hard},
            messages,
            settings,
            "gpt-6-sol",
            "openai",
            commit=failed_commit,
        )
    )

    assert result.status == "failed"
    assert result.action == "compact"
    assert messages == original
    assert len(calls) == 1


def test_precompact_reentry_is_deferred_without_second_summary(monkeypatch):
    messages = _history()
    registry = HookRegistry()
    manager = ContextWindowManager(hooks=None, hook_registry=registry, quiet=True)
    inner = []

    async def reenter(_invocation):
        inner.append(await manager.compact(messages, "gpt-6-sol", "openai", keep_recent=4))
        return HookDecision(action=HookAction.CONTINUE)

    registry.register(HookName.PRE_COMPACT, reenter, name="reentry")
    summarize = AsyncMock(return_value="Facts.")
    monkeypatch.setattr("core.orchestration.compaction._call_summarize", summarize)

    result = asyncio.run(manager.compact(messages, "gpt-6-sol", "openai", keep_recent=4))

    assert result.status == "changed"
    assert [item.status for item in inner] == ["deferred"]
    summarize.assert_awaited_once()


@pytest.mark.parametrize("cancel_at", [HookName.PRE_COMPACT, HookName.POST_COMPACT])
def test_hook_cancellation_respects_commit_boundary(cancel_at, monkeypatch):
    messages = _history()
    original = deepcopy(messages)
    registry = HookRegistry()

    async def cancel(_invocation):
        raise asyncio.CancelledError()

    registry.register(cancel_at, cancel, name="cancel")
    manager = ContextWindowManager(hooks=None, hook_registry=registry, quiet=True)
    summary = AsyncMock(return_value="Facts.")
    monkeypatch.setattr("core.orchestration.compaction._call_summarize", summary)
    commits = []
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            manager.compact(
                messages,
                "gpt-6-sol",
                "openai",
                keep_recent=4,
                commit=lambda: commits.append(deepcopy(messages)),
            )
        )

    assert summary.await_count == (0 if cancel_at is HookName.PRE_COMPACT else 1)
    if cancel_at is HookName.PRE_COMPACT:
        assert messages == original
        assert commits == []
    else:
        assert messages == commits[0] and messages != original
    assert manager._compacting is False


@pytest.mark.parametrize(
    "provider,model,native",
    [
        ("anthropic", "claude-fable-5", True),
        ("openai", "gpt-6-sol", False),
    ],
)
def test_soft_ceiling_uses_route_strategy(provider, model, native, monkeypatch):
    from core.orchestration.context_budget import resolve_context_budget_policy

    policy = resolve_context_budget_policy(model, provider=provider, source="payg")
    messages = _history(chars=40_000)
    original = deepcopy(messages)
    metrics = check_context(messages, model, policy=policy)
    assert metrics.is_ceiling_exceeded and not metrics.is_warning
    summarize = AsyncMock(return_value="Facts.")
    monkeypatch.setattr("core.orchestration.compaction._call_summarize", summarize)
    manager = ContextWindowManager(hooks=None, quiet=True)

    asyncio.run(manager.check_context_overflow("", messages, model, provider, policy=policy))

    assert summarize.await_count == (0 if native else 1)
    assert (messages == original) is native


def test_one_soft_maintenance_pass_for_root_and_auxiliary_requests(monkeypatch):
    from core.orchestration.context_budget import resolve_request_context_budget
    from core.orchestration.context_monitor import CHARS_PER_TOKEN

    model = "gpt-5.6-sol"
    policy = resolve_request_context_budget(
        AdapterCallRequest(model=model, messages=(), max_tokens=32_768),
        provider="openai",
        source="payg",
    )
    target = (policy.warning_tokens + policy.critical_tokens) // 2
    messages = _history(chars=int(target / policy.safety_margin) * CHARS_PER_TOKEN // 20)
    registry = HookRegistry()
    events = []

    async def defer(invocation):
        events.append(invocation)
        return HookDecision(action=HookAction.DEFER, reason="Keep this soft-maintenance candidate")

    registry.register(HookName.PRE_COMPACT, defer, name="defer")
    loop = AgenticLoop(
        ConversationContext(messages=deepcopy(messages)),
        ToolExecutor(action_handlers={}, hook_registry=registry),
        config=AgenticLoopConfig(
            source="payg",
            allowed_tool_names=set(),
            system_prompt_override="Offline deferred compaction test.",
        ),
        model=model,
        provider="openai",
        quiet=True,
    )
    complete = AsyncMock(
        return_value=AdapterCallResult(
            text="Candidate.", usage=UsageSummary(), stop_reason="end_turn"
        )
    )
    loop._new_adapter = SimpleNamespace(
        provider="openai", source="payg", name="fake", acomplete=complete
    )

    async def stop_after_response(_loop, turn, response, _round_idx, **_kwargs):
        assert turn.messages[:-1] == messages
        return AgenticResult(text=response.text, termination_reason="natural")

    # This oracle ends at root dispatch; the full recovery test above covers
    # final verification. Its auxiliary call has its own unchanged history.
    monkeypatch.setattr(_phases, "process_tool_calls", stop_after_response)
    monkeypatch.setattr(settings, "replan_enabled", False)
    result = asyncio.run(loop._arun_once("Continue."))
    assert result.text == "Candidate."
    assert complete.await_count == len(events) == 1

    auxiliary = deepcopy(messages)
    asyncio.run(loop._call_llm("Auxiliary task.", auxiliary, allow_tools=False))
    assert complete.await_count == len(events) == 2
    assert auxiliary == messages
