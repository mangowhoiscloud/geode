"""Tests for model switch context guard — hybrid adaptation.

Scenarios from research doc §5.3:
T1: Large context → small model → adapts (tool result summarize + prune)
T2: Small context → small model → no adaptation needed
T3: Huge context → small model → adapts to fit
T4: Small model → large model (upgrade) → no adaptation
T5: Escalation path — fallback triggers adaptation
T6: Failed text summary → original history and model retained
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, _model_switching
from core.agent.tool_executor import ToolExecutor
from core.hooks import HookAction, HookDecision, HookName
from core.orchestration.context_monitor import (
    check_context,
    summarize_tool_results,
)


def _make_tool_result_msg(content: str, tool_use_id: str = "tu_1") -> dict[str, Any]:
    return {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
    }


def _build_large_conversation(
    num_tool_results: int = 10,
    tool_result_chars: int = 50_000,
    num_text_msgs: int = 5,
) -> list[dict[str, Any]]:
    """Build a conversation with large tool results."""
    msgs: list[dict[str, Any]] = [{"role": "user", "content": "initial question"}]
    for i in range(num_tool_results):
        msgs.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": f"tu_{i}",
                        "name": "web_fetch",
                        "input": {"url": "http://example.com"},
                    }
                ],
            }
        )
        msgs.append(_make_tool_result_msg("x" * tool_result_chars, f"tu_{i}"))
    for i in range(num_text_msgs):
        msgs.append({"role": "user", "content": f"follow-up question {i}"})
        msgs.append({"role": "assistant", "content": f"response {i}"})
    return msgs


# ---------------------------------------------------------------------------
# T1: Opus(1M) → GLM-5(200K) — adaptation with tool result summarization
# ---------------------------------------------------------------------------


class TestT1LargeToSmall:
    def test_tool_results_summarized(self):
        msgs = _build_large_conversation(num_tool_results=20, tool_result_chars=50_000)
        # Before: ~250K tokens of tool results
        before_tokens = check_context(msgs, "glm-5").estimated_tokens
        assert before_tokens > 200_000  # exceeds GLM-5 200K window

        count, _tok_before, _tok_after = summarize_tool_results(msgs, target_window=200_000)
        assert count > 0

        after_tokens = check_context(msgs, "glm-5").estimated_tokens
        assert after_tokens < before_tokens

    def test_adapt_context_reduces_tokens(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation(num_tool_results=20, tool_result_chars=50_000)

        loop = _make_loop(ctx, model="claude-opus-4-6")
        before = check_context(ctx.messages, "glm-5").estimated_tokens

        asyncio.run(_model_switching.adapt_context_for_model(loop, "glm-5"))

        after = check_context(ctx.messages, "glm-5").estimated_tokens
        assert after < before

    def test_downshift_summarizes_without_pruning_when_summary_fits(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation(num_tool_results=20, tool_result_chars=50_000)
        original_count = len(ctx.messages)

        loop = _make_loop(ctx, model="claude-opus-4-6")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "glm-5"))

        after = check_context(ctx.messages, "glm-5")
        assert not after.is_critical
        assert len(ctx.messages) == original_count
        assert ctx.messages[0]["content"] == "initial question"
        assert "summarized from" in str(ctx.messages)


# ---------------------------------------------------------------------------
# T2: Small context → GLM-5 — no adaptation
# ---------------------------------------------------------------------------


class TestT2SmallContext:
    def test_no_adaptation_needed(self):
        ctx = ConversationContext()
        ctx.messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        original = list(ctx.messages)

        loop = _make_loop(ctx, model="claude-opus-4-6")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "glm-5"))

        # Messages unchanged
        assert ctx.messages == original


# ---------------------------------------------------------------------------
# T3: Huge context → still fits after adaptation
# ---------------------------------------------------------------------------


class TestT3HugeContext:
    def test_extreme_context_adapted(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation(num_tool_results=30, tool_result_chars=100_000)
        before = check_context(ctx.messages, "glm-5")
        assert before.usage_pct > 200  # way over

        loop = _make_loop(ctx, model="claude-opus-4-6")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "glm-5"))

        after = check_context(ctx.messages, "glm-5")
        assert after.estimated_tokens < before.estimated_tokens
        assert not after.is_critical


# ---------------------------------------------------------------------------
# T4: GLM-5 → Opus (upgrade) — no adaptation
# ---------------------------------------------------------------------------


class TestT4Upgrade:
    def test_upgrade_no_adaptation(self):
        ctx = ConversationContext()
        ctx.messages = [
            {"role": "user", "content": "x" * 50_000},
            {"role": "assistant", "content": "response"},
        ]
        original_count = len(ctx.messages)

        loop = _make_loop(ctx, model="glm-5")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "claude-opus-4-6"))

        # No changes — context fits easily in 1M window
        assert len(ctx.messages) == original_count

    def test_upgrade_from_small_to_large_does_not_force_compaction(self):
        ctx = ConversationContext()
        ctx.messages = [
            {"role": "user", "content": "x" * 120_000},
            {"role": "assistant", "content": "response"},
        ]
        original = list(ctx.messages)
        before_small = check_context(ctx.messages, "glm-5")
        assert not before_small.is_critical

        loop = _make_loop(ctx, model="glm-5")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "claude-opus-4-6"))

        after_large = check_context(ctx.messages, "claude-opus-4-6")
        assert ctx.messages == original
        assert not after_large.is_warning
        assert not after_large.is_ceiling_exceeded


# ---------------------------------------------------------------------------
# OpenAI internal downshift/upshift — 1.05M ↔ 400K / 200K
# ---------------------------------------------------------------------------


class TestOpenAIBidirectionalSwitch:
    def test_gpt55_to_gpt54_mini_downshift_adapts_to_400k_window(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation(num_tool_results=24, tool_result_chars=100_000)

        before = check_context(ctx.messages, "gpt-5.4-mini")
        assert before.context_window == 400_000
        assert before.is_critical

        loop = _make_loop(ctx, model="gpt-5.5")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "gpt-5.4-mini"))

        after = check_context(ctx.messages, "gpt-5.4-mini")
        assert after.estimated_tokens < before.estimated_tokens
        assert not after.is_critical

    def test_gpt55_to_o4_mini_downshift_adapts_to_200k_window(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation(num_tool_results=20, tool_result_chars=50_000)

        before = check_context(ctx.messages, "o4-mini")
        assert before.context_window == 200_000
        assert before.is_critical

        loop = _make_loop(ctx, model="gpt-5.5")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "o4-mini"))

        after = check_context(ctx.messages, "o4-mini")
        assert after.estimated_tokens < before.estimated_tokens
        assert not after.is_critical

    def test_gpt54_mini_to_gpt55_upshift_does_not_mutate_context(self):
        ctx = ConversationContext()
        ctx.messages = [
            {"role": "user", "content": "x" * 180_000},
            {"role": "assistant", "content": "response"},
        ]
        original = list(ctx.messages)

        before_large = check_context(ctx.messages, "gpt-5.5")
        assert before_large.context_window == 1_050_000
        assert not before_large.is_warning

        loop = _make_loop(ctx, model="gpt-5.4-mini")
        asyncio.run(_model_switching.adapt_context_for_model(loop, "gpt-5.5"))

        after_large = check_context(ctx.messages, "gpt-5.5")
        assert ctx.messages == original
        assert not after_large.is_warning
        assert not after_large.is_ceiling_exceeded


# ---------------------------------------------------------------------------
# T6: Failed client summary must not silently prune history
# ---------------------------------------------------------------------------


class TestT6PureText:
    def test_text_only_downshift_refused_without_client_summary(self, monkeypatch):
        from core.agent.loop import _ContextExhaustedError

        msgs = []
        for i in range(100):
            msgs.append({"role": "user", "content": f"{'y' * 5_000} q{i}"})
            msgs.append({"role": "assistant", "content": f"{'z' * 5_000} a{i}"})

        # Should exceed 200K context of GLM-5
        before = check_context(msgs, "glm-5")
        assert before.is_warning

        ctx = ConversationContext()
        ctx.messages = msgs
        original = deepcopy(msgs)

        loop = _make_loop(ctx, model="claude-opus-4-6")
        summary = AsyncMock(side_effect=RuntimeError("summary unavailable"))
        monkeypatch.setattr("core.orchestration.compaction._call_summarize", summary)
        with pytest.raises(_ContextExhaustedError, match="current model retained"):
            asyncio.run(_model_switching.adapt_context_for_model(loop, "glm-5"))
        assert ctx.messages == original
        summary.assert_awaited_once()


# ---------------------------------------------------------------------------
# update_model triggers adaptation
# ---------------------------------------------------------------------------


class TestUpdateModelIntegration:
    def test_update_model_calls_adapt(self):
        ctx = ConversationContext()
        ctx.messages = _build_large_conversation(num_tool_results=20, tool_result_chars=50_000)

        loop = _make_loop(ctx, model="claude-opus-4-6")
        before = check_context(ctx.messages, "glm-5").estimated_tokens

        with patch("core.ui.agentic_ui.update_session_model"):
            asyncio.run(loop.update_model_async("glm-5", "glm"))

        after = check_context(ctx.messages, "glm-5").estimated_tokens
        assert after < before

    def test_update_model_empty_context_no_crash(self):
        ctx = ConversationContext()  # empty

        loop = _make_loop(ctx, model="claude-opus-4-6")
        with patch("core.ui.agentic_ui.update_session_model"):
            asyncio.run(loop.update_model_async("glm-5", "zhipuai"))
        # No crash

    def test_explicit_selection_survives_defaults_change_at_next_model_call(self, monkeypatch):
        from core.agent.loop import _phases
        from core.agent.loop.models import TurnState
        from core.config import settings

        loop = _make_loop(ConversationContext(), model="claude-opus-4-6")

        async def scenario():
            await loop.update_model_async("claude-sonnet-5", "anthropic")
            selected = loop._model_settings
            adapter = loop._new_adapter
            assert loop._prompt_dirty
            monkeypatch.setattr(settings, "model", "gpt-6-sol")
            monkeypatch.setattr(settings, "act_model", "glm-5.3")
            monkeypatch.setattr(settings, "agentic_effort", "low")
            turn = _phases.PreparedTurn(
                user_input="keep the selected model",
                messages=[],
                turn_state=TurnState(turn_id="selected-model", messages=[]),
                system_prompt="outdated prompt",
                reflection_hint="retained reflection",
                verification_hint="retained verification",
                verification_continuation=False,
            )
            call = await _phases.prepare_model_call(loop, turn, 0)
            assert call.system_prompt == turn.system_prompt
            assert "<model_card>\nModel: claude-sonnet-5" in call.system_prompt
            assert "retained reflection" in call.system_prompt
            assert "retained verification" in call.system_prompt
            assert loop.model == "claude-sonnet-5"
            assert loop._model_settings == selected
            assert loop._new_adapter is adapter
            assert not loop._prompt_dirty

        with (
            patch("core.ui.agentic_ui.update_session_model"),
            patch("core.ui.agentic_ui.emit_model_switched"),
            patch("core.agent.loop._guards._maybe_replan_async", new=AsyncMock()),
            patch("core.agent.loop._phases.TextSpinner"),
        ):
            asyncio.run(scenario())


# ---------------------------------------------------------------------------
# usage_pct cap removed
# ---------------------------------------------------------------------------


class TestUsagePctNoCap:
    def test_exceeds_100_percent(self):
        huge_msg = "x" * 2_000_000  # ~500K tokens
        metrics = check_context([{"role": "user", "content": huge_msg}], "glm-5")
        # 500K / 200K = 250%
        assert metrics.usage_pct > 100.0


# ---------------------------------------------------------------------------
# B3: Model-aware beta headers
# ---------------------------------------------------------------------------


class TestContextMgmtModels:
    """_CONTEXT_MGMT_MODELS must gate beta header injection."""

    def test_opus_in_context_mgmt(self):
        from core.llm.providers.anthropic import _CONTEXT_MGMT_MODELS

        assert "claude-opus-4-6" in _CONTEXT_MGMT_MODELS

    def test_haiku_not_in_context_mgmt(self):
        from core.llm.providers.anthropic import _CONTEXT_MGMT_MODELS

        assert "claude-haiku-4-5-20251001" not in _CONTEXT_MGMT_MODELS

    def test_sonnet_in_context_mgmt(self):
        from core.llm.providers.anthropic import _CONTEXT_MGMT_MODELS

        assert "claude-sonnet-4-6" in _CONTEXT_MGMT_MODELS


# ---------------------------------------------------------------------------
# B2: check_context overhead uses measured default
# ---------------------------------------------------------------------------


class TestCheckContextOverhead:
    def test_default_overhead_is_10k(self):
        from core.orchestration.context_monitor import _DEFAULT_TOOLS_OVERHEAD

        assert _DEFAULT_TOOLS_OVERHEAD == 10_000

    def test_small_conversation_includes_overhead(self):
        msgs = [{"role": "user", "content": "hello"}]
        metrics = check_context(msgs, "claude-haiku-4-5-20251001")
        # Even a tiny conversation should estimate > 10K due to default overhead
        assert metrics.estimated_tokens >= 10_000

    def test_custom_tools_tokens_overrides_default(self):
        msgs = [{"role": "user", "content": "hello"}]
        m1 = check_context(msgs, "glm-5", tools_tokens=500)
        m2 = check_context(msgs, "glm-5", tools_tokens=20_000)
        assert m2.estimated_tokens > m1.estimated_tokens


# ---------------------------------------------------------------------------
# B1: set_conversation_context wired in arun
# ---------------------------------------------------------------------------


class TestConversationContextWired:
    def test_set_conversation_context_called(self):
        """arun must call set_conversation_context so /model guard works."""
        import inspect

        from core.agent.loop import AgenticLoop, _phases

        source = inspect.getsource(AgenticLoop._arun_once)
        input_source = inspect.getsource(_phases.prepare_input)
        assert "_phases.prepare_input" in source
        assert "set_conversation_context" in input_source


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("defer", [False, True])
def test_model_switch_compaction_uses_public_checkpoints(defer: bool) -> None:
    ctx = ConversationContext()
    original = [{"role": "user", "content": "old"}] * 20
    ctx.messages = list(original)
    loop = _make_loop(ctx, model="gpt-5.6-luna")
    compacted = [{"role": "user", "content": "summary"}]
    observed: list[HookName] = []
    post_messages: list[list[dict[str, Any]]] = []

    def pre(invocation: Any) -> HookDecision:
        observed.append(invocation.name)
        assert invocation.payload["trigger"] == "model_switch"
        return (
            HookDecision(action=HookAction.DEFER)
            if defer
            else HookDecision(action=HookAction.REWRITE, updates={"keep_recent": 6})
        )

    def post(invocation: Any) -> None:
        observed.append(invocation.name)
        post_messages.append(list(ctx.messages))

    loop._hook_registry.register(HookName.PRE_COMPACT, pre)
    loop._hook_registry.register(HookName.POST_COMPACT, post)
    compact = AsyncMock(return_value=(compacted, True))
    with patch("core.orchestration.compaction.compact_conversation", compact):
        asyncio.run(
            loop._ctx_mgr.compact(ctx.messages, loop.model, loop._provider, trigger="model_switch")
        )

    if defer:
        compact.assert_not_awaited()
        assert observed == [HookName.PRE_COMPACT]
        assert ctx.messages == original
    else:
        compact.assert_awaited_once()
        assert compact.await_args.kwargs["keep_recent"] == 6
        assert observed == [HookName.PRE_COMPACT, HookName.POST_COMPACT]
        assert post_messages == [compacted]
        assert ctx.messages == compacted


def _make_loop(ctx: ConversationContext, model: str = "claude-opus-4-6") -> AgenticLoop:
    """Create a minimal AgenticLoop for testing context adaptation.

    PR-MAINPATH-67 (2026-05-24) — the legacy ``resolve_agentic_adapter``
    factory was deleted; the loop now resolves Path-B adapters via
    ``core.llm.adapters.resolve_for``. ``conftest.py`` already calls
    ``bootstrap_builtins`` so the registry is populated.
    """
    from core.config import _resolve_provider

    executor = ToolExecutor()
    loop = AgenticLoop(
        model=model,
        provider=_resolve_provider(model),
        context=ctx,
        tool_executor=executor,
    )
    return loop


def test_async_downshift_summarizes_on_previous_route_before_switch() -> None:
    ctx = ConversationContext()
    ctx.messages = [{"role": "user", "content": "x" * 20_000} for _ in range(40)]
    loop = _make_loop(ctx, model="gpt-5.6-sol")
    loop._source = "subscription"
    loop._effort = "xhigh"

    async def summarize(messages: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], bool]:
        await asyncio.sleep(0)
        assert loop.model == "gpt-5.6-sol"
        assert kwargs["model"] == loop.model
        assert kwargs["provider"] == loop._provider
        assert kwargs["source"] == "subscription"
        assert kwargs["effort"] == "xhigh"
        return [{"role": "user", "content": "summary"}], True

    summary = AsyncMock(side_effect=summarize)
    with patch("core.orchestration.compaction.compact_conversation", summary):
        asyncio.run(loop.update_model_async("o4-mini", provider=loop._provider))
    summary.assert_awaited_once()
    assert loop.model == "o4-mini"
    assert ctx.messages[0]["content"] == "summary"


def test_failed_downshift_retains_current_model_and_history() -> None:
    from core.agent.loop import _ContextExhaustedError

    ctx = ConversationContext()
    ctx.messages = [{"role": "user", "content": "x" * 900_000}]
    original = list(ctx.messages)
    loop = _make_loop(ctx, model="gpt-5.6-sol")
    summary = AsyncMock(side_effect=OSError("summary unavailable"))
    with (
        patch("core.orchestration.compaction.compact_conversation", summary),
        pytest.raises(_ContextExhaustedError, match="current model retained"),
    ):
        asyncio.run(loop.update_model_async("o4-mini", provider=loop._provider))
    assert loop.model == "gpt-5.6-sol"
    assert ctx.messages == original


@pytest.mark.parametrize("source,compacts", [("subscription", True), ("payg", False)])
def test_model_switch_budget_uses_current_openai_source(source: str, compacts: bool) -> None:
    ctx = ConversationContext()
    ctx.messages = [{"role": "user", "content": "x" * 800_000}]
    loop = _make_loop(ctx, model="gpt-5.6-luna")
    loop._source = source
    loop._source_explicit = True

    async def summarize(messages: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], bool]:
        assert loop.model == "gpt-5.6-luna"
        assert kwargs["model"] == loop.model
        assert kwargs["provider"] == "openai"
        assert kwargs["source"] == source
        assert kwargs["policy"].source == source
        assert kwargs["policy"].context_window == 272_000
        return [{"role": "user", "content": "summary"}], True

    summary = AsyncMock(side_effect=summarize)
    with patch("core.orchestration.compaction.compact_conversation", summary):
        asyncio.run(loop.update_model_async("gpt-5.6-sol", provider="openai"))
    assert summary.await_count == int(compacts)
    assert loop.model == "gpt-5.6-sol"
    assert loop._source == source


def test_explicit_provider_selects_openrouter_budget_but_summarizes_on_current_route() -> None:
    ctx = ConversationContext()
    ctx.messages = [{"role": "user", "content": "x" * 800_000}]
    loop = _make_loop(ctx, model="gpt-5.6-luna")
    loop._source = "payg"
    loop._source_explicit = True

    async def summarize(messages: Any, **kwargs: Any) -> tuple[list[dict[str, Any]], bool]:
        assert loop.model == "gpt-5.6-luna"
        assert loop._provider == kwargs["provider"] == "openai"
        assert kwargs["source"] == "payg"
        policy = kwargs["policy"]
        assert policy.provider == "openrouter"
        assert policy.context_window == 200_000
        assert policy.context_origin == "fallback"
        return [{"role": "user", "content": "summary"}], True

    summary = AsyncMock(side_effect=summarize)
    with patch("core.orchestration.compaction.compact_conversation", summary):
        asyncio.run(loop.update_model_async("gpt-5.6-sol", provider="openrouter"))
    summary.assert_awaited_once()
    assert loop._provider == "openrouter"
    assert loop._source == "payg"
