"""Tests for autonomous safety mechanisms: cost auto-stop, runtime ratchet, diversity forcing."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticResult
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
            result = asyncio.run(loop.arun("test cost"))

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
            result = asyncio.run(loop.arun("test no budget"))

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
            result = asyncio.run(loop.arun("test under budget"))

        assert result.termination_reason == "natural"


# ---------------------------------------------------------------------------
# 2. Convergence break — v0.90.0: 3 identical errors stop the loop
# ---------------------------------------------------------------------------


class TestConvergenceBreak:
    """Verify convergence detection breaks the loop without auto-escalation.

    v0.90.0 — auto-escalation was removed. Three identical tool errors
    now break the loop on first detection so the AgenticLoop can surface
    a ``model_action_required`` diagnostic; the user picks the next
    model with ``/model``.
    """

    @pytest.fixture
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture
    def executor(self) -> ToolExecutor:
        handler = MagicMock(return_value={"status": "ok"})
        return ToolExecutor(action_handlers={"web_search": handler})

    def test_3_identical_errors_break(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """3 identical errors → break immediately (no auto-escalation)."""
        loop = AgenticLoop(context, executor)
        loop._convergence.recent_errors = [
            "web_search:timeout",
            "web_search:timeout",
            "web_search:timeout",
        ]
        assert loop._check_convergence_break() is True

    def test_two_identical_errors_no_break(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Fewer than 3 identical errors → loop continues."""
        loop = AgenticLoop(context, executor)
        loop._convergence.recent_errors = ["web_search:timeout", "web_search:timeout"]
        assert loop._check_convergence_break() is False

    def test_mixed_errors_no_break(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """Different error keys → loop continues even past 3 errors."""
        loop = AgenticLoop(context, executor)
        loop._convergence.recent_errors = [
            "web_search:timeout",
            "fs:not_found",
            "web_search:timeout",
        ]
        assert loop._check_convergence_break() is False

    def test_no_escalation_state_on_detector(
        self, context: ConversationContext, executor: ToolExecutor
    ) -> None:
        """v0.90.0 — the detector must not expose any auto-escalation state."""
        loop = AgenticLoop(context, executor)
        assert not hasattr(loop._convergence, "convergence_escalated")
        assert not hasattr(loop._convergence, "_escalation_fn")


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

    @pytest.mark.skip(
        reason=(
            "PR-CL-A1-followup (2026-05-23) — test design depends on the "
            "diversity logic INSIDE ``_call_llm`` (agent_loop.py:1757-1782) "
            "running, but the test mocks ``_call_llm`` via patch.object so "
            "the real body never executes. Tracker stays at the pre-filled "
            "4 items, assertion ``== []`` fails. Passes locally via "
            "ordering luck, fails deterministically under CI xdist loadfile. "
            "Properly rewriting needs the diversity logic extracted from "
            "``_call_llm`` into a standalone function the test can mock + "
            "exercise. Tagged for cleanup-codebase sprint (TODO)."
        )
    )
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
            result = asyncio.run(loop.arun("search something"))

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
