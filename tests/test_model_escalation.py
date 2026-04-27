"""Tests for model escalation (Feature 3) and cross-provider escalation (Feature 4).

Feature 3: Model escalation on consecutive LLM failures
  - After N consecutive None responses, auto-escalate to next model in chain
  - Reset counter on success

Feature 4: Cross-provider escalation
  - When current provider's chain is exhausted, switch to other provider
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop
from core.agent.tool_executor import ToolExecutor
from core.config import (
    ANTHROPIC_FALLBACK_CHAIN,
    ANTHROPIC_PRIMARY,
    GLM_FALLBACK_CHAIN,
    GLM_PRIMARY,
    OPENAI_FALLBACK_CHAIN,
)


def _make_loop(
    model: str = ANTHROPIC_PRIMARY,
    provider: str = "anthropic",
) -> AgenticLoop:
    """Create an AgenticLoop with minimal mocked dependencies."""
    ctx = ConversationContext()
    executor = ToolExecutor(auto_approve=True)
    loop = AgenticLoop(
        ctx,
        executor,
        model=model,
        provider=provider,
        max_rounds=10,
        quiet=True,
    )
    return loop


# ---------------------------------------------------------------------------
# Feature 3: Model escalation on consecutive LLM failures
# ---------------------------------------------------------------------------


class TestModelEscalation:
    """Test automatic model escalation after consecutive LLM failures."""

    def test_escalation_fields_initialized(self) -> None:
        loop = _make_loop()
        assert loop._consecutive_llm_failures == 0
        assert loop._ESCALATION_THRESHOLD == 2

    def test_try_model_escalation_anthropic_chain(self) -> None:
        """Escalate from primary to next in fallback chain.
        v0.53.0 — chain depth reduced to 1 (primary → secondary).
        Pre-fix opus-4-7 → opus-4-6; now opus-4-7 → sonnet-4-6 (next)."""
        loop = _make_loop(model=ANTHROPIC_PRIMARY, provider="anthropic")
        assert loop.model == ANTHROPIC_PRIMARY

        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == "claude-sonnet-4-6"
        assert loop._provider == "anthropic"

    def test_try_model_escalation_openai_chain(self) -> None:
        """Escalate within OpenAI chain.
        v0.53.0 — chain shortened to [gpt-5.5, gpt-5.4]."""
        loop = _make_loop(model="gpt-5.5", provider="openai")
        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == "gpt-5.4"

    def test_try_model_escalation_openai_chain_exhausted(self) -> None:
        """v0.53.0: chain depth=1 means after primary→secondary the chain
        is exhausted. No cross-provider fallback fires (governance)."""
        loop = _make_loop(model="gpt-5.4", provider="openai")
        result = loop._try_model_escalation()
        # Last in chain — no further model to escalate to.
        assert result is False, (
            "v0.53.0 chain depth=1: gpt-5.4 is last; must return False, no cross-provider auto-swap"
        )

    def test_try_model_escalation_glm_chain(self) -> None:
        """Escalate within GLM chain (v0.53.0: glm-5.1 → glm-5)."""
        loop = _make_loop(model=GLM_PRIMARY, provider="glm")
        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == "glm-5"

    # ---------------------------------------------------------------------------
    # v0.53.0 — Cross-provider escalation REMOVED (fail-fast governance)
    # ---------------------------------------------------------------------------

    def test_cross_provider_anthropic_to_openai_removed(self) -> None:
        """v0.53.0: cross-provider auto-swap removed. When Anthropic chain
        exhausted, escalation returns False — user picks next via /model.
        Pre-fix: silent jump to OpenAI created cost surprise (PAYG bills)."""
        last_anthropic = ANTHROPIC_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_anthropic, provider="anthropic")

        result = loop._try_model_escalation()
        assert result is False
        assert loop._provider == "anthropic", (
            "provider must NOT change — cross-provider auto-swap is removed"
        )

    def test_cross_provider_openai_to_anthropic_removed(self) -> None:
        """v0.53.0: same as above for OpenAI → Anthropic."""
        last_openai = OPENAI_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_openai, provider="openai")

        result = loop._try_model_escalation()
        assert result is False
        assert loop._provider == "openai"

    def test_glm_does_not_auto_escalate_cross_provider(self) -> None:
        """Pre-existing v0.50.0 invariant: GLM Coding Plan auth errors must
        not silently divert to a metered OpenAI key. v0.53.0 generalises this
        to all providers."""
        last_glm = GLM_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_glm, provider="glm")

        result = loop._try_model_escalation()
        assert result is False
        assert loop._provider == "glm"

    def test_unknown_model_does_not_cross_provider(self) -> None:
        """v0.53.0: unknown model not in chain ⇒ no escalation (no auto-swap)."""
        loop = _make_loop(model="claude-unknown-999", provider="anthropic")
        result = loop._try_model_escalation()
        assert result is False
        assert loop._provider == "anthropic"

    def test_cross_provider_hook_not_fired(self) -> None:
        """v0.53.0: FALLBACK_CROSS_PROVIDER hook must never fire from
        _try_model_escalation since the cross-provider branch is removed."""
        from core.hooks import HookEvent

        last_anthropic = ANTHROPIC_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_anthropic, provider="anthropic")
        hooks = MagicMock()
        loop._hooks = hooks

        result = loop._try_model_escalation()
        assert result is False
        # No FALLBACK_CROSS_PROVIDER hook trigger.
        called_events = [call.args[0] for call in hooks.trigger.call_args_list if call.args]
        assert HookEvent.FALLBACK_CROSS_PROVIDER not in called_events, (
            "FALLBACK_CROSS_PROVIDER hook must not fire — cross-provider "
            "auto-swap removed in v0.53.0"
        )

    def test_arun_escalation_on_consecutive_failures(self) -> None:
        """arun() auto-escalates when failures reach threshold and retries."""
        import asyncio

        loop = _make_loop()
        # Pre-set to 1 (simulating a failure from a previous arun call)
        # so the next failure in this call reaches the threshold (2).
        loop._consecutive_llm_failures = 1
        call_count = 0

        # Mock _call_llm: fail once (hitting threshold), then succeed
        async def fake_call_llm(system: str, messages: list, *, round_idx: int = 0) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None
            # Return a successful response with end_turn
            resp = MagicMock()
            resp.stop_reason = "end_turn"
            block = MagicMock()
            block.type = "text"
            block.text = "Hello from escalated model"
            resp.content = [block]
            resp.usage = None
            return resp

        with (
            patch.object(loop, "_call_llm", side_effect=fake_call_llm),
            patch.object(loop, "_try_model_escalation", return_value=True) as mock_esc,
            patch.object(loop, "_build_system_prompt", return_value="system"),
            patch.object(loop, "_try_decompose", return_value=None),
        ):
            result = asyncio.run(loop.arun("test prompt"))

        # Should have escalated once (failure hit threshold)
        mock_esc.assert_called_once()
        assert result.text == "Hello from escalated model"
        assert result.termination_reason == "natural"

    def test_arun_retries_on_single_failure_then_succeeds(self) -> None:
        """arun() retries with backoff on single failure (below threshold), no escalation."""
        import asyncio

        loop = _make_loop()
        call_count = 0

        async def fake_call_llm(system: str, messages: list, *, round_idx: int = 0) -> Any:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return None  # One failure
            resp = MagicMock()
            resp.stop_reason = "end_turn"
            resp.content = [MagicMock(type="text", text="ok")]
            resp.usage = None
            return resp

        with (
            patch.object(loop, "_call_llm", side_effect=fake_call_llm),
            patch.object(loop, "_try_model_escalation") as mock_esc,
            patch.object(loop, "_build_system_prompt", return_value="system"),
            patch.object(loop, "_try_decompose", return_value=None),
            patch("asyncio.sleep", new=AsyncMock(return_value=None)),
        ):
            result = asyncio.run(loop.arun("test prompt"))

        # Single failure → backoff retry → success on 2nd call
        mock_esc.assert_not_called()
        assert result.termination_reason == "natural"
        assert call_count == 2

    def test_arun_resets_failure_counter_on_success(self) -> None:
        """Successful LLM response resets the consecutive failure counter."""
        import asyncio

        loop = _make_loop()

        async def fake_call_llm(system: str, messages: list, *, round_idx: int = 0) -> Any:
            resp = MagicMock()
            resp.stop_reason = "end_turn"
            resp.content = [MagicMock(type="text", text="ok")]
            resp.usage = None
            return resp

        with (
            patch.object(loop, "_call_llm", side_effect=fake_call_llm),
            patch.object(loop, "_build_system_prompt", return_value="system"),
            patch.object(loop, "_try_decompose", return_value=None),
        ):
            loop._consecutive_llm_failures = 1  # pre-set
            result = asyncio.run(loop.arun("test prompt"))

        assert loop._consecutive_llm_failures == 0
        assert result.termination_reason == "natural"
