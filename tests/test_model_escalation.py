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

from core.agent.agentic_loop import AgenticLoop
from core.agent.conversation import ConversationContext
from core.agent.tool_executor import ToolExecutor
from core.config import (
    ANTHROPIC_FALLBACK_CHAIN,
    ANTHROPIC_PRIMARY,
    GLM_FALLBACK_CHAIN,
    OPENAI_FALLBACK_CHAIN,
    OPENAI_PRIMARY,
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
        """Escalate from primary to next in fallback chain."""
        loop = _make_loop(model=ANTHROPIC_PRIMARY, provider="anthropic")
        assert loop.model == ANTHROPIC_PRIMARY

        result = loop._try_model_escalation()
        assert result is True
        # Fallback chain: opus-4-7 → opus-4-6 → sonnet-4-6
        assert loop.model == "claude-opus-4-6"
        assert loop._provider == "anthropic"

    def test_try_model_escalation_openai_chain(self) -> None:
        """Escalate within OpenAI chain."""
        loop = _make_loop(model="gpt-5.4", provider="openai")
        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == "gpt-5.2"

    def test_try_model_escalation_openai_second_step(self) -> None:
        """Escalate to third model in OpenAI chain."""
        loop = _make_loop(model="gpt-5.2", provider="openai")
        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == "gpt-4.1"

    def test_try_model_escalation_glm_chain(self) -> None:
        """Escalate within GLM chain."""
        loop = _make_loop(model="glm-5", provider="glm")
        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == "glm-5-turbo"

    # ---------------------------------------------------------------------------
    # Feature 4: Cross-provider escalation
    # ---------------------------------------------------------------------------

    def test_cross_provider_anthropic_to_openai(self) -> None:
        """When Anthropic chain is exhausted, escalate to OpenAI."""
        # Start from the last model in Anthropic chain
        last_anthropic = ANTHROPIC_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_anthropic, provider="anthropic")

        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == OPENAI_PRIMARY
        assert loop._provider == "openai"

    def test_cross_provider_openai_to_anthropic(self) -> None:
        """When OpenAI chain is exhausted, escalate to Anthropic."""
        last_openai = OPENAI_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_openai, provider="openai")

        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == ANTHROPIC_PRIMARY
        assert loop._provider == "anthropic"

    def test_cross_provider_glm_to_openai(self) -> None:
        """When GLM chain is exhausted, escalate to OpenAI."""
        last_glm = GLM_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_glm, provider="glm")

        result = loop._try_model_escalation()
        assert result is True
        assert loop.model == OPENAI_PRIMARY
        assert loop._provider == "openai"

    def test_escalation_returns_false_when_fully_exhausted(self) -> None:
        """Returns False when both intra-chain and cross-provider are exhausted."""
        # If we're already at the cross-provider target
        loop = _make_loop(model=OPENAI_PRIMARY, provider="anthropic")
        # Set model to the cross-provider fallback to simulate exhaustion
        loop.model = OPENAI_PRIMARY
        loop._provider = "openai"
        # The last model in OpenAI chain
        loop.model = OPENAI_FALLBACK_CHAIN[-1]

        # Cross-provider for openai -> anthropic, but anthropic primary != current
        result = loop._try_model_escalation()
        # Should escalate to anthropic primary
        assert result is True
        assert loop.model == ANTHROPIC_PRIMARY

    def test_unknown_model_cross_provider(self) -> None:
        """Unknown model not in chain triggers cross-provider fallback."""
        loop = _make_loop(model="claude-unknown-999", provider="anthropic")
        result = loop._try_model_escalation()
        # Model not in chain, so should try cross-provider
        assert result is True
        assert loop.model == OPENAI_PRIMARY
        assert loop._provider == "openai"

    def test_cross_provider_emits_fallback_hook(self) -> None:
        """Cross-provider escalation fires FALLBACK_CROSS_PROVIDER hook."""
        from core.hooks import HookEvent

        last_anthropic = ANTHROPIC_FALLBACK_CHAIN[-1]
        loop = _make_loop(model=last_anthropic, provider="anthropic")
        hooks = MagicMock()
        loop._hooks = hooks

        result = loop._try_model_escalation()
        assert result is True

        hooks.trigger.assert_any_call(
            HookEvent.FALLBACK_CROSS_PROVIDER,
            {
                "from_model": last_anthropic,
                "to_model": OPENAI_PRIMARY,
                "from_provider": "anthropic",
                "to_provider": "openai",
            },
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
