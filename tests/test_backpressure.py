"""Tests for backpressure on tool failures (Feature 5) and convergence detection (Feature 6).

Feature 5: Backpressure on tool failures
  - Track consecutive tool errors across rounds
  - After 3+ consecutive errors, inject a cooldown delay and hint

Feature 6: Convergence detection (stuck loop)
  - Track recent error keys (tool_name:error_type)
  - 3 identical errors → warning
  - 4+ identical errors → force break
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

from core.agent.agentic_loop import AgenticLoop
from core.agent.conversation import ConversationContext
from core.agent.tool_executor import ToolExecutor
from core.config import ANTHROPIC_PRIMARY


def _make_loop() -> AgenticLoop:
    """Create an AgenticLoop with minimal mocked dependencies."""
    ctx = ConversationContext()
    executor = ToolExecutor(auto_approve=True)
    loop = AgenticLoop(
        ctx,
        executor,
        model=ANTHROPIC_PRIMARY,
        provider="anthropic",
        max_rounds=10,
    )
    return loop


# ---------------------------------------------------------------------------
# Feature 5: Backpressure on tool failures
# ---------------------------------------------------------------------------


class TestBackpressure:
    """Test backpressure / cooldown when tools fail consecutively."""

    def test_backpressure_fields_initialized(self) -> None:
        loop = _make_loop()
        assert loop._total_consecutive_tool_errors == 0

    def test_update_tool_error_tracking_counts_errors(self) -> None:
        """All-error round increments consecutive counter."""
        loop = _make_loop()
        # Simulate tool results with errors
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": "id1",
                "content": json.dumps({"error": "Not found"}),
            },
        ]
        loop._tool_processor._tool_log.append({"tool": "test_tool", "input": {}, "result": {"error": "Not found"}})
        loop._update_tool_error_tracking(tool_results)
        assert loop._total_consecutive_tool_errors == 1

    def test_update_tool_error_tracking_resets_on_success(self) -> None:
        """Any success in a round resets the counter."""
        loop = _make_loop()
        loop._total_consecutive_tool_errors = 5
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": "id1",
                "content": json.dumps({"status": "ok"}),
            },
        ]
        loop._update_tool_error_tracking(tool_results)
        assert loop._total_consecutive_tool_errors == 0

    def test_update_tool_error_tracking_mixed_resets(self) -> None:
        """Mixed success+error in same round resets counter (success wins)."""
        loop = _make_loop()
        loop._total_consecutive_tool_errors = 3
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": "id1",
                "content": json.dumps({"error": "fail"}),
            },
            {
                "type": "tool_result",
                "tool_use_id": "id2",
                "content": json.dumps({"status": "ok"}),
            },
        ]
        loop._tool_processor._tool_log.append({"tool": "test_tool", "input": {}, "result": {"error": "fail"}})
        loop._update_tool_error_tracking(tool_results)
        assert loop._total_consecutive_tool_errors == 0

    def test_consecutive_errors_accumulate(self) -> None:
        """Multiple all-error rounds accumulate the counter."""
        loop = _make_loop()
        for i in range(4):
            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": f"id{i}",
                    "content": json.dumps({"error": "timeout"}),
                },
            ]
            loop._tool_processor._tool_log.append(
                {"tool": "test_tool", "input": {}, "result": {"error": "timeout"}}
            )
            loop._update_tool_error_tracking(tool_results)
        assert loop._total_consecutive_tool_errors == 4


# ---------------------------------------------------------------------------
# Feature 6: Convergence detection (stuck loop)
# ---------------------------------------------------------------------------


class TestConvergenceDetection:
    """Test stuck loop detection via repeating error patterns."""

    def test_recent_errors_initialized_empty(self) -> None:
        loop = _make_loop()
        assert loop._recent_errors == []

    def test_check_convergence_no_errors(self) -> None:
        """No errors → no convergence."""
        loop = _make_loop()
        assert loop._check_convergence_break() is False

    def test_check_convergence_few_errors(self) -> None:
        """Fewer than 3 errors → no convergence."""
        loop = _make_loop()
        loop._recent_errors = ["tool_a:timeout", "tool_a:timeout"]
        assert loop._check_convergence_break() is False

    def test_check_convergence_3_identical_no_break(self) -> None:
        """3 identical errors → warning but no break (need 4)."""
        loop = _make_loop()
        loop._recent_errors = ["tool_a:timeout", "tool_a:timeout", "tool_a:timeout"]
        assert loop._check_convergence_break() is False

    def test_check_convergence_4_identical_breaks(self) -> None:
        """4 identical errors → force break."""
        loop = _make_loop()
        loop._recent_errors = [
            "tool_a:timeout",
            "tool_a:timeout",
            "tool_a:timeout",
            "tool_a:timeout",
        ]
        assert loop._check_convergence_break() is True

    def test_check_convergence_5_identical_breaks(self) -> None:
        """5+ identical errors → force break."""
        loop = _make_loop()
        loop._recent_errors = [
            "tool_a:timeout",
            "tool_a:timeout",
            "tool_a:timeout",
            "tool_a:timeout",
            "tool_a:timeout",
        ]
        assert loop._check_convergence_break() is True

    def test_check_convergence_mixed_errors_no_break(self) -> None:
        """Different errors → no convergence."""
        loop = _make_loop()
        loop._recent_errors = [
            "tool_a:timeout",
            "tool_b:not_found",
            "tool_a:timeout",
            "tool_c:denied",
        ]
        assert loop._check_convergence_break() is False

    def test_check_convergence_4_with_different_prefix_no_break(self) -> None:
        """4 errors where last 4 aren't all identical → no break."""
        loop = _make_loop()
        loop._recent_errors = [
            "tool_a:timeout",
            "tool_b:error",
            "tool_a:timeout",
            "tool_a:timeout",
        ]
        assert loop._check_convergence_break() is False

    def test_recent_errors_max_6(self) -> None:
        """Recent errors list is capped at 6 entries."""
        loop = _make_loop()
        for i in range(10):
            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": f"id{i}",
                    "content": json.dumps({"error": f"error_{i}"}),
                },
            ]
            loop._tool_processor._tool_log.append(
                {"tool": f"tool_{i}", "input": {}, "result": {"error": f"error_{i}"}}
            )
            loop._update_tool_error_tracking(tool_results)
        assert len(loop._recent_errors) <= 6

    def test_error_key_format(self) -> None:
        """Error keys follow 'tool_name:error_message' format."""
        loop = _make_loop()
        loop._tool_processor._tool_log.append(
            {"tool": "run_bash", "input": {}, "result": {"error": "command not found"}}
        )
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": "id1",
                "content": json.dumps({"error": "command not found"}),
            },
        ]
        loop._update_tool_error_tracking(tool_results)
        assert len(loop._recent_errors) == 1
        # Should contain tool name and error
        assert "run_bash" in loop._recent_errors[0] or "unknown" in loop._recent_errors[0]
        assert "command not found" in loop._recent_errors[0]

    def test_arun_convergence_terminates_loop(self) -> None:
        """arun() terminates with convergence_detected when stuck."""
        import asyncio

        loop = _make_loop()
        call_count = 0

        # Pre-populate with 3 identical errors (one more triggers break)
        loop._recent_errors = [
            "test_tool:always fails",
            "test_tool:always fails",
            "test_tool:always fails",
        ]

        async def fake_call_llm(system: str, messages: list, *, round_idx: int = 0) -> Any:
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.stop_reason = "tool_use"
            block = MagicMock()
            block.type = "tool_use"
            block.name = "test_tool"
            block.input = {}
            block.id = f"tu_{call_count}"
            resp.content = [block]
            resp.usage = None
            return resp

        async def fake_process_tool_calls(
            response: Any,
        ) -> list[dict]:
            return [
                {
                    "type": "tool_result",
                    "tool_use_id": response.content[0].id,
                    "content": json.dumps({"error": "always fails"}),
                }
            ]

        with (
            patch.object(loop, "_call_llm", side_effect=fake_call_llm),
            patch.object(
                loop._tool_processor,
                "process",
                side_effect=fake_process_tool_calls,
            ),
            patch.object(loop, "_build_system_prompt", return_value="system"),
            patch.object(loop, "_try_decompose", return_value=None),
        ):
            result = asyncio.run(loop.arun("test prompt"))

        assert result.termination_reason == "convergence_detected"
        assert result.error == "convergence_detected"
