"""Tests for ConvergenceDetector — extracted from AgenticLoop."""

from __future__ import annotations

import json
from typing import Any

from core.agent.convergence import ConvergenceDetector


class TestConvergenceDetector:
    """Test convergence detection logic."""

    def test_init_defaults(self) -> None:
        det = ConvergenceDetector()
        assert det.total_consecutive_tool_errors == 0
        assert det.recent_errors == []
        assert det.convergence_escalated is False

    # -- update_tool_error_tracking --

    def test_error_increments_counter(self) -> None:
        det = ConvergenceDetector()
        results = [
            {"tool_use_id": "t1", "content": json.dumps({"error": "fail"})},
        ]
        tool_log: list[dict[str, Any]] = [
            {"tool": "test_tool", "input": {}, "result": {"error": "fail"}},
        ]
        det.update_tool_error_tracking(results, tool_log)
        assert det.total_consecutive_tool_errors == 1

    def test_success_resets_counter(self) -> None:
        det = ConvergenceDetector()
        det.total_consecutive_tool_errors = 5
        results = [
            {"tool_use_id": "t1", "content": json.dumps({"status": "ok"})},
        ]
        det.update_tool_error_tracking(results, [])
        assert det.total_consecutive_tool_errors == 0

    def test_recent_errors_capped_at_6(self) -> None:
        det = ConvergenceDetector()
        for i in range(10):
            results = [
                {"tool_use_id": f"t{i}", "content": json.dumps({"error": f"e{i}"})},
            ]
            det.update_tool_error_tracking(results, [])
        assert len(det.recent_errors) <= 6

    # -- check_convergence_break --

    def test_no_convergence_few_errors(self) -> None:
        det = ConvergenceDetector()
        det.recent_errors = ["a:1", "a:1"]
        assert det.check_convergence_break() is False

    def test_3_identical_triggers_escalation(self) -> None:
        escalated = False

        def fake_escalate() -> bool:
            nonlocal escalated
            escalated = True
            return True

        det = ConvergenceDetector(escalation_fn=fake_escalate)
        det.recent_errors = ["a:timeout", "a:timeout", "a:timeout"]
        result = det.check_convergence_break()
        assert result is False  # Escalation succeeded, don't break
        assert escalated is True
        assert det.convergence_escalated is True
        assert det.recent_errors == []

    def test_4_identical_after_escalation_breaks(self) -> None:
        det = ConvergenceDetector()
        det.convergence_escalated = True
        det.recent_errors = ["a:timeout"] * 4
        assert det.check_convergence_break() is True

    def test_mixed_errors_no_break(self) -> None:
        det = ConvergenceDetector()
        det.recent_errors = ["a:1", "b:2", "a:1", "c:3"]
        assert det.check_convergence_break() is False

    def test_escalation_failure_no_break_on_3(self) -> None:
        """If escalation fails, 3 errors should NOT break (needs 4)."""
        det = ConvergenceDetector(escalation_fn=lambda: False)
        det.recent_errors = ["a:timeout", "a:timeout", "a:timeout"]
        result = det.check_convergence_break()
        assert result is False
        assert det.convergence_escalated is True
