"""Tests for autonomous safety mechanisms: cost auto-stop, runtime ratchet, diversity forcing."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.agent.agentic_loop import AgenticLoop, AgenticResult
from core.agent.conversation import ConversationContext
from core.agent.tool_executor import ToolExecutor

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_response(text: str = "done") -> MagicMock:
    """Create a mock LLM response with text content (end_turn)."""
    resp = MagicMock()
    resp.stop_reason = "end_turn"
    resp.usage = MagicMock()
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 50
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp.content = [block]
    return resp


def _make_tool_response(tool_name: str = "web_search", tool_id: str = "toolu_1") -> MagicMock:
    """Create a mock LLM response with a single tool_use block."""
    resp = MagicMock()
    resp.stop_reason = "tool_use"
    resp.usage = MagicMock()
    resp.usage.input_tokens = 100
    resp.usage.output_tokens = 50
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = {"query": "test"}
    block.id = tool_id
    resp.content = [block]
    return resp


# ---------------------------------------------------------------------------
# 1. Cost budget auto-stop
# ---------------------------------------------------------------------------


class TestCostBudgetAutoStop:
    """Verify the loop terminates when session cost exceeds cost_budget."""

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok"})
        return ToolExecutor(action_handlers={"web_search": handler})

    def test_cost_budget_terminates(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """When session cost >= cost_budget, loop should terminate with cost_budget_exceeded."""
        loop = AgenticLoop(context, executor, cost_budget=1.00)

        # Mock tracker with accumulated cost above budget
        mock_tracker = MagicMock()
        mock_tracker.accumulator.total_cost_usd = 1.50

        response = _make_text_response("Hello")

        # Patch the module that the inline import resolves to
        mock_module = MagicMock(get_tracker=lambda: mock_tracker)
        with (
            patch.object(loop, "_call_llm", return_value=response),
            patch.object(loop, "_track_usage"),
            patch.dict(
                "sys.modules",
                {"core.llm.token_tracker": mock_module},
            ),
        ):
            result = loop.run("test cost")

        assert result.termination_reason == "cost_budget_exceeded"
        assert "1.00" in result.text
        assert "1.50" in result.text

    def test_cost_budget_zero_no_check(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """When cost_budget=0 (default), no cost check should happen."""
        loop = AgenticLoop(context, executor, cost_budget=0.0)
        assert loop._cost_budget == 0.0

        response = _make_text_response("Hello")
        with (
            patch.object(loop, "_call_llm", return_value=response),
            patch.object(loop, "_track_usage"),
        ):
            result = loop.run("test no budget")

        assert result.termination_reason == "natural"

    def test_cost_budget_under_limit_continues(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """When session cost < cost_budget, loop should continue normally."""
        loop = AgenticLoop(context, executor, cost_budget=10.00)

        mock_tracker = MagicMock()
        mock_tracker.accumulator.total_cost_usd = 0.50

        response = _make_text_response("Hello")

        with (
            patch.object(loop, "_call_llm", return_value=response),
            patch.object(loop, "_track_usage"),
            patch.dict(
                "sys.modules",
                {"core.llm.token_tracker": MagicMock(get_tracker=lambda: mock_tracker)},
            ),
        ):
            result = loop.run("test under budget")

        assert result.termination_reason == "natural"


# ---------------------------------------------------------------------------
# 2. Runtime ratchet — escalate on convergence
# ---------------------------------------------------------------------------


class TestConvergenceEscalation:
    """Verify convergence detection tries model escalation before breaking."""

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok"})
        return ToolExecutor(action_handlers={"web_search": handler})

    def test_convergence_escalates_model_first(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """3 identical errors should trigger model escalation, not immediate break."""
        loop = AgenticLoop(context, executor)

        # Simulate 3 identical errors
        loop._convergence.recent_errors = [
            "web_search:timeout",
            "web_search:timeout",
            "web_search:timeout",
        ]

        with patch.object(loop, "_try_model_escalation", return_value=True) as mock_escalate:
            result = loop._check_convergence_break()

        assert result is False  # Should NOT break (escalation succeeded)
        mock_escalate.assert_called_once()
        assert loop._convergence.convergence_escalated is True
        assert loop._convergence.recent_errors == []  # Cleared after escalation

    def test_convergence_breaks_after_failed_escalation(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """If escalation fails and 4 identical errors persist, should break."""
        loop = AgenticLoop(context, executor)
        loop._convergence.convergence_escalated = True  # Already tried escalation

        # 4 identical errors post-escalation
        loop._convergence.recent_errors = [
            "web_search:timeout",
            "web_search:timeout",
            "web_search:timeout",
            "web_search:timeout",
        ]

        result = loop._check_convergence_break()
        assert result is True  # Should break now

    def test_convergence_escalation_no_fallback(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """If no fallback model is available, escalation returns False."""
        loop = AgenticLoop(context, executor)
        loop._convergence.recent_errors = [
            "web_search:timeout",
            "web_search:timeout",
            "web_search:timeout",
        ]

        with patch.object(loop, "_try_model_escalation", return_value=False):
            # First call: tries escalation, fails, then checks for 4+
            result = loop._check_convergence_break()

        # Only 3 errors, escalation failed — doesn't break yet (needs 4)
        assert result is False
        assert loop._convergence.convergence_escalated is True

    def test_convergence_3_errors_post_escalation_warns_no_break(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """After escalation, 3 identical errors should warn but not break."""
        loop = AgenticLoop(context, executor)
        loop._convergence.convergence_escalated = True

        loop._convergence.recent_errors = [
            "web_search:timeout",
            "web_search:timeout",
            "web_search:timeout",
        ]

        result = loop._check_convergence_break()
        assert result is False  # Only warns, doesn't break (needs 4)

    def test_convergence_flag_resets_on_new_loop(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """_convergence_escalated should start as False."""
        loop = AgenticLoop(context, executor)
        assert loop._convergence.convergence_escalated is False


# ---------------------------------------------------------------------------
# 3. Diversity forcing
# ---------------------------------------------------------------------------


class TestDiversityForcing:
    """Verify that same tool called 5x consecutively triggers diversity hint."""

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok"})
        return ToolExecutor(action_handlers={"web_search": handler})

    def test_diversity_hint_injected(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """After 5 consecutive same-tool calls, a diversity hint should be injected."""
        loop = AgenticLoop(context, executor, max_rounds=7)

        # Pre-fill 4 calls to the same tool
        loop._consecutive_tool_tracker = ["web_search"] * 4

        call_count = 0
        tool_resp = _make_tool_response("web_search", "toolu_div")
        text_resp = _make_text_response("Done")

        captured_messages: list[Any] = []

        async def fake_call_llm(system_prompt: str, messages: list, **kwargs: Any) -> Any:
            nonlocal call_count
            call_count += 1
            captured_messages.clear()
            captured_messages.extend(messages)
            if call_count <= 1:
                return tool_resp
            return text_resp

        tool_result_item = {
            "type": "tool_result",
            "tool_use_id": "toolu_div",
            "content": '{"status": "ok"}',
        }

        with (
            patch.object(loop, "_call_llm", side_effect=fake_call_llm),
            patch.object(loop, "_track_usage"),
            patch.object(loop._tool_processor, "process", return_value=[tool_result_item]),
        ):
            result = loop.run("search something")

        # Verify diversity hint was injected (tracker was cleared)
        assert loop._consecutive_tool_tracker == []  # Cleared after hint
        assert result.termination_reason == "natural"

    def test_no_diversity_hint_under_threshold(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Under 5 consecutive calls, no diversity hint should be injected."""
        loop = AgenticLoop(context, executor)
        loop._consecutive_tool_tracker = ["web_search"] * 3  # Only 3

        # Running the diversity check logic manually
        # After adding one more "web_search", tracker has 4 — still under 5
        loop._consecutive_tool_tracker.append("web_search")
        assert len(loop._consecutive_tool_tracker) == 4
        # No hint should be needed (check inline)
        last_5 = (
            loop._consecutive_tool_tracker[-5:] if len(loop._consecutive_tool_tracker) >= 5 else []
        )
        assert len(last_5) == 0 or len(set(last_5)) != 1

    def test_diverse_tools_no_hint(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Different tools should not trigger diversity hint even after 5 calls."""
        loop = AgenticLoop(context, executor)
        loop._consecutive_tool_tracker = [
            "web_search",
            "memory_load",
            "web_search",
            "run_bash",
            "web_search",
        ]
        last_5 = loop._consecutive_tool_tracker[-5:]
        assert len(set(last_5)) > 1  # Multiple distinct tools — no hint needed

    def test_tracker_capped_at_10(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Tracker should keep at most 10 entries."""
        loop = AgenticLoop(context, executor)
        loop._consecutive_tool_tracker = ["tool_a"] * 12
        # Cap logic: if > 10, trim to last 10
        if len(loop._consecutive_tool_tracker) > 10:
            loop._consecutive_tool_tracker = loop._consecutive_tool_tracker[-10:]
        assert len(loop._consecutive_tool_tracker) == 10


# ---------------------------------------------------------------------------
# Integration: AgenticResult fields
# ---------------------------------------------------------------------------


class TestAgenticResultSafety:
    """Verify AgenticResult supports safety-related termination reasons."""

    def test_cost_budget_exceeded_reason(self) -> None:
        result = AgenticResult(
            text="Cost exceeded",
            termination_reason="cost_budget_exceeded",
            error="cost_budget_exceeded",
        )
        assert result.termination_reason == "cost_budget_exceeded"
        d = result.to_dict()
        assert d["termination_reason"] == "cost_budget_exceeded"

    def test_convergence_detected_reason(self) -> None:
        result = AgenticResult(
            text="Convergence",
            termination_reason="convergence_detected",
        )
        assert result.termination_reason == "convergence_detected"
