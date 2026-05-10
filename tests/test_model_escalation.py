"""v0.90.0 — auto-escalation removed. This file used to test:

  Feature 3: Model escalation on consecutive LLM failures
  Feature 4: Cross-provider escalation

Both features were removed. The loop now surfaces a
``model_action_required`` diagnostic (see ``_build_model_action_result``
+ ``build_model_action_message``) so the user picks the next model
explicitly via ``/model`` instead of getting silently swapped to a
different model/provider.

The file is kept (under its original name) as a pinning point for the
removal so that anyone searching for "model_escalation" lands on the
invariant tests below and reads the rationale.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop
from core.agent.tool_executor import ToolExecutor
from core.config import ANTHROPIC_PRIMARY


def _make_loop(
    model: str = ANTHROPIC_PRIMARY,
    provider: str = "anthropic",
) -> AgenticLoop:
    ctx = ConversationContext()
    executor = ToolExecutor(auto_approve=True)
    return AgenticLoop(
        ctx,
        executor,
        model=model,
        provider=provider,
        max_rounds=10,
        quiet=True,
    )


class TestNoAutoEscalation:
    """Pin the v0.90.0 removal so future code can't silently re-introduce it."""

    def test_loop_has_no_escalation_methods(self) -> None:
        assert not hasattr(AgenticLoop, "_try_model_escalation")
        assert not hasattr(AgenticLoop, "_try_cross_provider_escalation")
        assert not hasattr(AgenticLoop, "_persist_escalated_model")

    def test_loop_has_no_escalation_threshold_constant(self) -> None:
        loop = _make_loop()
        assert not hasattr(loop, "_ESCALATION_THRESHOLD")
        # Retry budget for the *same* model is still here.
        assert loop._LLM_RETRY_CAP == 5
        assert loop._consecutive_llm_failures == 0

    def test_model_switching_module_strips_escalation_helpers(self) -> None:
        import core.agent.loop._model_switching as _switching

        assert not hasattr(_switching, "try_model_escalation")
        assert not hasattr(_switching, "try_cross_provider_escalation")
        assert not hasattr(_switching, "persist_escalated_model")

    def test_fallback_chain_suggestions_replaces_escalation(self) -> None:
        """The remaining chain is exposed only as *suggestions* for the
        diagnostic, not as an auto-swap target."""
        loop = _make_loop()
        loop._adapter = MagicMock(fallback_chain=["a", "b", "c"])
        loop.model = "a"
        assert loop._fallback_chain_suggestions() == ["b", "c"]


class TestModelActionDiagnostic:
    """The new fail-stop path that replaces auto-escalation."""

    def test_build_model_action_result_carries_full_context(self) -> None:
        loop = _make_loop()
        loop._adapter = MagicMock(fallback_chain=[ANTHROPIC_PRIMARY, "claude-sonnet-4-6"])
        loop._consecutive_llm_failures = 5

        result = loop._build_model_action_result(
            error_type="rate_limit",
            severity="warning",
            hint="API rate limited. Switch to a different model with /model and re-run.",
            rounds=3,
            detail="429 from upstream",
        )

        assert result.error == "model_action_required"
        assert result.termination_reason == "model_action_required"
        assert result.rounds == 3

        text = result.text
        # Diagnostic carries the labelled fields the user needs to act.
        assert "rate_limit" in text
        assert ANTHROPIC_PRIMARY in text
        assert "anthropic" in text
        assert "attempts" in text and "5" in text
        assert "429 from upstream" in text
        assert "claude-sonnet-4-6" in text  # suggested next model
        assert "/model" in text  # call-to-action

    def test_build_model_action_message_omits_optional_fields_cleanly(self) -> None:
        from core.llm.errors import build_model_action_message

        msg = build_model_action_message(
            error_type="auth",
            severity="error",
            hint="API key invalid or expired.",
            model="gpt-5.5",
            provider="openai",
            attempts=1,
            cost_so_far_usd=None,
            suggested_models=None,
            detail=None,
        )
        assert "auth" in msg
        assert "gpt-5.5" in msg
        # Omitted fields don't leave a label behind.
        assert "cost_so_far" not in msg
        assert "suggested" not in msg
        assert "detail" not in msg


class TestOverthinkingThreshold:
    """The 2000-token magic was replaced with a context-window-proportional one."""

    def test_threshold_is_one_percent_of_ctx_window_with_floor(self) -> None:
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        loop = _make_loop()
        # Pick any registered model — the formula should match exactly.
        for model, ctx in MODEL_CONTEXT_WINDOW.items():
            loop.model = model
            assert loop._overthinking_token_threshold() == max(1024, ctx // 100), (
                f"threshold mismatch for model={model} (ctx={ctx})"
            )

    def test_threshold_falls_back_to_200k_for_unknown_model(self) -> None:
        loop = _make_loop()
        loop.model = "definitely-not-a-real-model"
        # 200_000 // 100 = 2000 (parity with the legacy magic number)
        assert loop._overthinking_token_threshold() == 2000

    def test_threshold_floor_protects_small_context_models(self) -> None:
        """Models with <102_400 ctx hit the 1024 floor instead of going below."""
        from unittest.mock import patch

        loop = _make_loop()
        loop.model = "tiny-model"
        with patch.dict(
            "core.llm.token_tracker.MODEL_CONTEXT_WINDOW",
            {"tiny-model": 64_000},
            clear=False,
        ):
            assert loop._overthinking_token_threshold() == 1024


# ---------------------------------------------------------------------------
# Helpers used in earlier history; kept as no-ops in case a downstream test
# imported them (none in-tree do, but this keeps the deletion safe).
# ---------------------------------------------------------------------------


def _make_text_response(text: str = "done") -> Any:
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.usage = MagicMock(input_tokens=10, output_tokens=5)
    block = MagicMock(type="text", text=text)
    resp.content = [block]
    return resp
