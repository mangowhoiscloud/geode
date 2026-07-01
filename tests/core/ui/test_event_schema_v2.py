"""Tests for Event Schema V2 — 16 new structured IPC events.

Verifies:
1. Emit functions send events via IPC writer when present
2. Emit functions render to console when no IPC writer
3. EventRenderer dispatches all new event types
4. IPCClient recognizes all new event types
"""

from __future__ import annotations

import io
from typing import Any
from unittest.mock import MagicMock

import pytest


class TestAgenticLoopEmitters:
    """Test emit_* functions from agentic_ui.py send IPC events."""

    @pytest.fixture(autouse=True)
    def _setup_writer(self) -> None:
        from core.ui.agentic_ui import _ipc_writer_local

        self.mock_writer = MagicMock()
        _ipc_writer_local.writer = self.mock_writer
        yield
        _ipc_writer_local.writer = None

    def test_emit_model_switch_required(self) -> None:
        from core.ui.agentic_ui import emit_model_switch_required

        emit_model_switch_required(
            "claude-opus-4-6",
            "rate_limit",
            5,
            ["claude-sonnet-4-6"],
        )
        self.mock_writer.send_event.assert_called_once_with(
            "model_switch_required",
            model="claude-opus-4-6",
            error_type="rate_limit",
            attempts=5,
            suggested_models=["claude-sonnet-4-6"],
        )

    def test_emit_cost_budget_exceeded(self) -> None:
        from core.ui.agentic_ui import emit_cost_budget_exceeded

        emit_cost_budget_exceeded(1.0, 1.25)
        self.mock_writer.send_event.assert_called_once_with(
            "cost_budget_exceeded",
            budget=1.0,
            actual=1.25,
        )

    def test_emit_time_budget_expired(self) -> None:
        from core.ui.agentic_ui import emit_time_budget_expired

        emit_time_budget_expired(300.0, 305.0, 5)
        self.mock_writer.send_event.assert_called_once_with(
            "time_budget_expired",
            budget_s=300.0,
            elapsed_s=305.0,
            rounds=5,
        )

    def test_emit_convergence_detected(self) -> None:
        from core.ui.agentic_ui import emit_convergence_detected

        emit_convergence_detected("timeout", 3)
        self.mock_writer.send_event.assert_called_once_with(
            "convergence_detected",
            error="timeout",
            rounds=3,
        )

    def test_emit_goal_decomposition(self) -> None:
        from core.ui.agentic_ui import emit_goal_decomposition

        steps = ["Search web", "Summarize results"]
        emit_goal_decomposition(steps)
        self.mock_writer.send_event.assert_called_once_with(
            "goal_decomposition",
            steps=steps,
            count=2,
        )

    def test_render_progress_plan_sends_structured_event(self) -> None:
        from core.ui.agentic_ui import render_progress_plan

        plan = [
            {"step": "Inspect UX", "status": "completed"},
            {"step": "Patch renderer", "status": "in_progress"},
        ]
        render_progress_plan(plan, explanation="implementation")
        self.mock_writer.send_event.assert_called_once_with(
            "progress_plan",
            plan=plan,
            explanation="implementation",
        )

    def test_emit_tool_backpressure(self) -> None:
        from core.ui.agentic_ui import emit_tool_backpressure

        emit_tool_backpressure(3)
        self.mock_writer.send_event.assert_called_once_with(
            "tool_backpressure",
            consecutive_errors=3,
        )

    def test_emit_tool_diversity_forced(self) -> None:
        from core.ui.agentic_ui import emit_tool_diversity_forced

        emit_tool_diversity_forced("web_search", 5)
        self.mock_writer.send_event.assert_called_once_with(
            "tool_diversity_forced",
            tool="web_search",
            count=5,
        )

    def test_emit_model_switched(self) -> None:
        from core.ui.agentic_ui import emit_model_switched

        emit_model_switched("opus", "sonnet", "user_switch")
        self.mock_writer.send_event.assert_called_once_with(
            "model_switched",
            from_model="opus",
            to_model="sonnet",
            reason="user_switch",
        )

    def test_emit_checkpoint_saved(self) -> None:
        from core.ui.agentic_ui import emit_checkpoint_saved

        emit_checkpoint_saved("s-abc123", 5)
        self.mock_writer.send_event.assert_called_once_with(
            "checkpoint_saved",
            session_id="s-abc123",
            round_idx=5,
        )


class TestPipelineEmitters:
    """Test pipeline emit_* functions."""

    @pytest.fixture(autouse=True)
    def _setup_writer(self) -> None:
        from core.ui.agentic_ui import _ipc_writer_local

        self.mock_writer = MagicMock()
        _ipc_writer_local.writer = self.mock_writer
        yield
        _ipc_writer_local.writer = None

    def test_emit_pipeline_gather(self) -> None:
        from core.ui.agentic_ui import emit_pipeline_gather

        emit_pipeline_gather(
            {
                "subject_id": "demo-subject",
                "subject_type": "repository",
                "source": "local",
            },
            {"files": 12, "tests": 8},
        )
        self.mock_writer.send_event.assert_called_once()
        call_args = self.mock_writer.send_event.call_args
        assert call_args[0][0] == "pipeline_gather"
        assert call_args[1]["subject_id"] == "demo-subject"

    def test_emit_pipeline_score(self) -> None:
        from core.ui.agentic_ui import emit_pipeline_score

        emit_pipeline_score(81.2, {"quality": 85.0}, 92.0)
        self.mock_writer.send_event.assert_called_once_with(
            "pipeline_score",
            final_score=81.2,
            subscores={"quality": 85.0},
            confidence=92.0,
        )

    def test_emit_feedback_loop(self) -> None:
        from core.ui.agentic_ui import emit_feedback_loop

        emit_feedback_loop(2, 55.0, 70.0)
        self.mock_writer.send_event.assert_called_once_with(
            "feedback_loop",
            iteration=2,
            confidence=55.0,
            threshold=70.0,
        )

    def test_emit_node_skipped(self) -> None:
        from core.ui.agentic_ui import emit_node_skipped

        emit_node_skipped("verification", "extreme score")
        self.mock_writer.send_event.assert_called_once_with(
            "node_skipped",
            node="verification",
            reason="extreme score",
        )

    def test_emit_pipeline_verification(self) -> None:
        from core.ui.agentic_ui import emit_pipeline_verification

        emit_pipeline_verification(True)
        self.mock_writer.send_event.assert_called_once_with(
            "pipeline_verification",
            guardrails_pass=True,
            details=[],
        )

    def test_no_writer_no_crash(self) -> None:
        """When no IPC writer, pipeline emitters should not crash."""
        from core.ui.agentic_ui import _ipc_writer_local

        _ipc_writer_local.writer = None
        from core.ui.agentic_ui import emit_pipeline_gather

        emit_pipeline_gather({"subject_id": "X"}, {"count": 0})  # no crash


class TestEventRendererV2:
    """Test EventRenderer handles all 16 new event types."""

    @pytest.fixture()
    def renderer(self) -> Any:
        from core.ui.event_renderer import EventRenderer

        r = EventRenderer()
        r._out = io.StringIO()
        return r

    def test_model_switch_required(self, renderer) -> None:
        renderer.on_event(
            {
                "type": "model_switch_required",
                "model": "claude-opus-4-7",
                "error_type": "rate_limit",
                "attempts": 5,
                "suggested_models": ["claude-sonnet-4-6"],
            }
        )
        out = renderer._out.getvalue().lower()
        assert "switch required" in out
        assert "rate_limit" in out
        assert "claude-sonnet-4-6" in out

    def test_cost_budget_exceeded(self, renderer) -> None:
        renderer.on_event({"type": "cost_budget_exceeded", "budget": 1.0, "actual": 1.5})
        assert "exceeded" in renderer._out.getvalue().lower()

    def test_time_budget_expired(self, renderer) -> None:
        renderer.on_event(
            {"type": "time_budget_expired", "budget_s": 300, "elapsed_s": 310, "rounds": 5}
        )
        assert "expired" in renderer._out.getvalue().lower()

    def test_convergence_detected(self, renderer) -> None:
        renderer.on_event({"type": "convergence_detected", "rounds": 3})
        assert "convergence" in renderer._out.getvalue().lower()

    def test_goal_decomposition(self, renderer) -> None:
        renderer.on_event({"type": "goal_decomposition", "steps": ["a", "b"], "count": 2})
        out = renderer._out.getvalue()
        assert "Plan" in out
        assert "2 steps" in out
        assert "● a" in out

    def test_progress_plan_first_render_is_full_checklist(self, renderer) -> None:
        renderer.on_event(
            {
                "type": "progress_plan",
                "explanation": "implementation",
                "plan": [
                    {"step": "Inspect UX", "status": "completed"},
                    {"step": "Patch renderer", "status": "in_progress"},
                    {"step": "Run tests", "status": "pending"},
                ],
            }
        )
        out = renderer._out.getvalue()
        assert "Plan · implementation" in out
        assert "✓" in out
        assert "Inspect UX" in out
        assert "Patch renderer" in out
        assert "Run tests" in out

    def test_progress_plan_updates_in_place_when_still_at_bottom(self, renderer) -> None:
        renderer.on_event(
            {
                "type": "progress_plan",
                "plan": [{"step": "First plan", "status": "in_progress"}],
            }
        )
        renderer.on_event(
            {
                "type": "progress_plan",
                "plan": [{"step": "Second plan", "status": "in_progress"}],
            }
        )
        out = renderer._out.getvalue()
        assert "\033[" in out and "A" in out
        assert "Second plan" in out

    def test_progress_plan_after_tool_output_is_compact_not_second_full_block(
        self, renderer
    ) -> None:
        renderer.on_event(
            {
                "type": "progress_plan",
                "explanation": "first",
                "plan": [{"step": "Initial investigation", "status": "in_progress"}],
            }
        )
        renderer.on_event({"type": "subagent_complete", "count": 4, "elapsed_s": 12.0})
        renderer.on_event(
            {
                "type": "progress_plan",
                "explanation": "fallback",
                "plan": [
                    {"step": "Already done", "status": "completed"},
                    {"step": "Direct verification", "status": "in_progress"},
                    {"step": "This full-list tail should not print", "status": "pending"},
                ],
            }
        )
        out = renderer._out.getvalue()
        compact = out[out.rindex("Plan updated") :]
        assert "Plan updated · fallback · 1/3 complete" in compact
        assert "Direct verification" in compact
        assert "This full-list tail should not print" not in compact

    def test_plan_step(self, renderer) -> None:
        renderer.on_event(
            {
                "type": "plan_step",
                "current": 2,
                "total": 4,
                "description": "verify the renderer",
                "revision": 1,
            }
        )
        out = renderer._out.getvalue()
        assert "Plan" in out
        assert "step 2/4" in out
        assert "verify the renderer" in out

    def test_replan(self, renderer) -> None:
        renderer.on_event(
            {"type": "replan", "trigger": "verify_fail", "step_count": 3, "revision": 2}
        )
        out = renderer._out.getvalue()
        assert "Plan revised" in out
        assert "verify_fail" in out
        assert "3 steps" in out

    def test_tool_backpressure(self, renderer) -> None:
        renderer.on_event({"type": "tool_backpressure", "consecutive_errors": 3})
        assert "3" in renderer._out.getvalue()

    def test_tool_diversity_forced(self, renderer) -> None:
        renderer.on_event({"type": "tool_diversity_forced", "tool": "search", "count": 5})
        assert "search" in renderer._out.getvalue()

    def test_model_switched(self, renderer) -> None:
        renderer.on_event({"type": "model_switched", "from_model": "a", "to_model": "b"})
        assert "a" in renderer._out.getvalue()

    def test_checkpoint_saved_silent(self, renderer) -> None:
        renderer.on_event({"type": "checkpoint_saved", "session_id": "s-1", "round_idx": 1})
        assert renderer._out.getvalue() == ""  # silent

    def test_pipeline_gather(self, renderer) -> None:
        renderer.on_event({"type": "pipeline_gather", "subject_id": "demo-subject"})
        assert "demo-subject" in renderer._out.getvalue()

    def test_pipeline_gather_signals(self, renderer) -> None:
        """Structured signals render in gather events."""
        renderer.on_event(
            {
                "type": "pipeline_gather",
                "subject_id": "demo-subject",
                "signals": {"coverage": "high", "risk": "low"},
            }
        )
        out = renderer._out.getvalue()
        assert "coverage=high" in out
        assert "risk=low" in out

    def test_pipeline_analysis(self, renderer) -> None:
        renderer.on_event(
            {
                "type": "pipeline_analysis",
                "analysts": [{"analyst": "growth", "score": 4.0, "finding": "Strong"}],
            }
        )
        assert "growth" in renderer._out.getvalue()

    def test_pipeline_evaluation(self, renderer) -> None:
        renderer.on_event(
            {
                "type": "pipeline_evaluation",
                "evaluators": {"quality": {"score": 85}},
            }
        )
        # Renderer maps quality_judge→Quality, but "quality" key becomes "Quality" via labels
        out = renderer._out.getvalue()
        assert "EVALUATE" in out
        assert "85" in out

    def test_pipeline_score(self, renderer) -> None:
        renderer.on_event({"type": "pipeline_score", "final_score": 81.2, "confidence": 92})
        assert "81.2/100" in renderer._out.getvalue()

    def test_pipeline_score_subscores(self, renderer) -> None:
        """Subscores render in score event."""
        renderer.on_event(
            {
                "type": "pipeline_score",
                "final_score": 81.2,
                "subscores": {"quality": 82.0, "coverage": 77.5},
            }
        )
        out = renderer._out.getvalue()
        assert "quality=82.0" in out
        assert "coverage=77.5" in out

    def test_pipeline_verification(self, renderer) -> None:
        renderer.on_event({"type": "pipeline_verification", "guardrails_pass": True})
        out = renderer._out.getvalue()
        assert "\u2713" in out

    def test_pipeline_verification_details(self, renderer) -> None:
        """G4: Guardrail failure details rendered in verification event."""
        renderer.on_event(
            {
                "type": "pipeline_verification",
                "guardrails_pass": False,
                "details": ["G2 FAIL: score out of range", "G3 FAIL: grounding < 0.5"],
            }
        )
        out = renderer._out.getvalue()
        assert "G2 FAIL" in out
        assert "G3 FAIL" in out

    def test_feedback_loop(self, renderer) -> None:
        renderer.on_event(
            {"type": "feedback_loop", "iteration": 2, "confidence": 55, "threshold": 70}
        )
        assert "55" in renderer._out.getvalue()

    def test_node_skipped(self, renderer) -> None:
        renderer.on_event({"type": "node_skipped", "node": "verification", "reason": "skip"})
        assert "verification" in renderer._out.getvalue()

    def test_pipeline_result_errors(self, renderer) -> None:
        """G3: Pipeline errors rendered in result event."""
        renderer.on_event(
            {
                "type": "pipeline_result",
                "tier": "A",
                "final_score": 68.4,
                "cause": "undermarketed",
                "errors": ["Analyst timeout: growth_potential", "Evaluator retry: quality_judge"],
            }
        )
        out = renderer._out.getvalue()
        assert "2 warnings" in out
        assert "Analyst timeout" in out

    def test_pipeline_event_suspends_tracker(self, renderer) -> None:
        """Pipeline events suspend the tool tracker to prevent cursor-up interference."""
        # Simulate tool_start for a generic tool
        renderer._tool_tracker.on_tool_start(
            {"name": "web_search", "args_preview": 'query="release notes"'}
        )
        assert renderer._tool_tracker._line_count > 0

        # Pipeline event should suspend tracker
        renderer.on_event(
            {
                "type": "pipeline_header",
                "subject_id": "demo-subject",
                "pipeline_mode": "analysis",
                "model": "claude-opus-4-6",
                "version": "0.38.0",
            }
        )
        # Tracker line_count reset — no stale cursor-up
        assert renderer._tool_tracker._line_count == 0
        assert not renderer._tool_tracker._running
        # Pipeline output was written
        assert "demo-subject" in renderer._out.getvalue()

    def test_stream_suspends_tracker(self, renderer) -> None:
        """on_stream() suspends the tool tracker before writing stream data."""
        renderer._tool_tracker.on_tool_start({"name": "memory_search", "args_preview": ""})
        assert renderer._tool_tracker._line_count > 0

        renderer.on_stream("  Available subjects\n  - demo-subject\n")
        assert renderer._tool_tracker._line_count == 0
        assert "demo-subject" in renderer._out.getvalue()

    def test_stop_clears_raw_markdown_stream_region(self, renderer) -> None:
        """Plain markdown streamed raw is transient; final result renders it."""
        renderer.on_stream("Intro\n**bold** answer\n")

        renderer.stop()
        out = renderer._out.getvalue()
        assert "**bold** answer" in out  # was visible progressively
        assert "\033[1A\033[2K" in out  # then erased before final Markdown render

    def test_stop_preserves_non_markdown_plain_stream(self, renderer) -> None:
        """Plain non-markdown console output should remain visible after stop()."""
        renderer.on_stream("  Available subjects\n  - demo-subject\n")

        renderer.stop()
        out = renderer._out.getvalue()
        assert "demo-subject" in out
        assert "\033[1A\033[2K" not in out

    def test_event_resets_clearable_stream_region(self, renderer) -> None:
        """Do not erase earlier raw text once a structured event has followed it."""
        renderer.on_stream("**bold** answer\n")
        renderer.on_event({"type": "round_start", "round": 1})

        renderer.stop()
        out = renderer._out.getvalue()
        assert "**bold** answer" in out
        assert "\033[1A\033[2K" not in out


class TestIPCClientEventWhitelist:
    """All 28 event types are in IPCClient's event whitelist."""

    def test_all_events_recognized(self) -> None:
        """IPCClient.send_prompt should recognize all event types as structured."""
        import re
        from pathlib import Path

        source = Path("core/cli/ipc_client.py").read_text()
        # Extract all quoted strings from the event tuple
        events = re.findall(
            r'"(\w+)"', source[source.index("# Structured events") : source.index("if on_event")]
        )
        expected = {
            "tool_start",
            "tool_end",
            "tokens",
            "round_start",
            "thinking_start",
            "thinking_end",
            "turn_end",
            "context_event",
            "subagent_dispatch",
            "subagent_progress",
            "subagent_complete",
            "session_cost",
            # V2
            "model_switch_required",
            "cost_budget_exceeded",
            "time_budget_expired",
            "convergence_detected",
            "goal_decomposition",
            "progress_plan",
            "tool_backpressure",
            "tool_diversity_forced",
            "model_switched",
            "checkpoint_saved",
            "pipeline_gather",
            "pipeline_analysis",
            "pipeline_evaluation",
            "pipeline_score",
            "pipeline_verification",
            "feedback_loop",
            "node_skipped",
        }
        assert expected.issubset(set(events)), f"Missing: {expected - set(events)}"
