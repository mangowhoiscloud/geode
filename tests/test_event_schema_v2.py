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

    def test_emit_model_escalation(self) -> None:
        from core.ui.agentic_ui import emit_model_escalation

        emit_model_escalation("claude-opus-4-6", "claude-sonnet-4-6", 2)
        self.mock_writer.send_event.assert_called_once_with(
            "model_escalation",
            from_model="claude-opus-4-6",
            to_model="claude-sonnet-4-6",
            failures=2,
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
                "ip_name": "Berserk",
                "media_type": "manga",
                "release_year": 1989,
                "studio": "Hakusensha",
            },
            {"dau_current": 0, "revenue_ltm": 0},
        )
        self.mock_writer.send_event.assert_called_once()
        call_args = self.mock_writer.send_event.call_args
        assert call_args[0][0] == "pipeline_gather"
        assert call_args[1]["ip_name"] == "Berserk"

    def test_emit_pipeline_score(self) -> None:
        from core.ui.agentic_ui import emit_pipeline_score

        emit_pipeline_score(81.2, {"psm": 85.0}, 92.0, "S")
        self.mock_writer.send_event.assert_called_once_with(
            "pipeline_score",
            final_score=81.2,
            subscores={"psm": 85.0},
            confidence=92.0,
            tier="S",
            att_pct=0,
            z_value=0,
            rosenbaum_gamma=0,
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

        emit_pipeline_verification(True, False)
        self.mock_writer.send_event.assert_called_once_with(
            "pipeline_verification",
            guardrails_pass=True,
            biasbuster_pass=False,
            details=[],
        )

    def test_no_writer_no_crash(self) -> None:
        """When no IPC writer, pipeline emitters should not crash."""
        from core.ui.agentic_ui import _ipc_writer_local

        _ipc_writer_local.writer = None
        from core.ui.agentic_ui import emit_pipeline_gather

        emit_pipeline_gather({"ip_name": "X"}, {"dau_current": 0})  # no crash


class TestEventRendererV2:
    """Test EventRenderer handles all 16 new event types."""

    @pytest.fixture()
    def renderer(self) -> Any:
        from core.ui.event_renderer import EventRenderer

        r = EventRenderer()
        r._out = io.StringIO()
        return r

    def test_model_escalation(self, renderer) -> None:
        renderer.on_event(
            {"type": "model_escalation", "from_model": "a", "to_model": "b", "failures": 2}
        )
        assert "escalated" in renderer._out.getvalue().lower()

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
        assert "2 steps" in renderer._out.getvalue()

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
        renderer.on_event({"type": "pipeline_gather", "ip_name": "Berserk", "release_year": 1989})
        assert "Berserk" in renderer._out.getvalue()

    def test_pipeline_gather_signals(self, renderer) -> None:
        """G1: Signals (YouTube/Reddit/FanArt) rendered in gather event."""
        renderer.on_event(
            {
                "type": "pipeline_gather",
                "ip_name": "Berserk",
                "youtube_views": 15_000_000,
                "reddit_subscribers": 89_000,
                "fan_art_yoy_pct": 12.5,
            }
        )
        out = renderer._out.getvalue()
        assert "YouTube 15M" in out
        assert "Reddit 89K" in out
        assert "+12%" in out

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
        renderer.on_event(
            {"type": "pipeline_score", "final_score": 81.2, "tier": "S", "confidence": 92}
        )
        assert "S" in renderer._out.getvalue()

    def test_pipeline_score_psm(self, renderer) -> None:
        """G2: PSM details (ATT/Z/Gamma) rendered in score event."""
        renderer.on_event(
            {
                "type": "pipeline_score",
                "final_score": 81.2,
                "tier": "S",
                "att_pct": 31.2,
                "z_value": 2.45,
                "rosenbaum_gamma": 1.8,
            }
        )
        out = renderer._out.getvalue()
        assert "ATT=+31.2%" in out
        assert "Z=2.45" in out
        assert "1.8" in out

    def test_pipeline_verification(self, renderer) -> None:
        renderer.on_event(
            {"type": "pipeline_verification", "guardrails_pass": True, "biasbuster_pass": False}
        )
        out = renderer._out.getvalue()
        assert "\u2713" in out
        assert "\u2717" in out

    def test_pipeline_verification_details(self, renderer) -> None:
        """G4: Guardrail failure details rendered in verification event."""
        renderer.on_event(
            {
                "type": "pipeline_verification",
                "guardrails_pass": False,
                "biasbuster_pass": True,
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
        # Simulate tool_start for analyze_ip
        renderer._tool_tracker.on_tool_start(
            {"name": "analyze_ip", "args_preview": 'ip_name="Berserk"'}
        )
        assert renderer._tool_tracker._line_count > 0

        # Pipeline event should suspend tracker
        renderer.on_event(
            {
                "type": "pipeline_header",
                "ip_name": "Berserk",
                "pipeline_mode": "full_pipeline",
                "model": "claude-opus-4-6",
                "version": "0.38.0",
            }
        )
        # Tracker line_count reset — no stale cursor-up
        assert renderer._tool_tracker._line_count == 0
        assert not renderer._tool_tracker._running
        # Pipeline output was written
        assert "Berserk" in renderer._out.getvalue()

    def test_stream_suspends_tracker(self, renderer) -> None:
        """on_stream() suspends the tool tracker before writing stream data."""
        renderer._tool_tracker.on_tool_start({"name": "list_ips", "args_preview": ""})
        assert renderer._tool_tracker._line_count > 0

        renderer.on_stream("  Available IPs\n  - Berserk\n")
        assert renderer._tool_tracker._line_count == 0
        assert "Berserk" in renderer._out.getvalue()


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
            "model_escalation",
            "cost_budget_exceeded",
            "time_budget_expired",
            "convergence_detected",
            "goal_decomposition",
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
