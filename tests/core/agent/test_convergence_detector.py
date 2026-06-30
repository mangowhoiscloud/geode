"""Tests for ConvergenceDetector — extracted from AgenticLoop.

v0.90.0 — auto-escalation removed. The detector no longer takes an
``escalation_fn`` and no longer carries an ``escalated`` flag; 3
consecutive identical errors break the loop immediately so the caller
can surface a ``model_action_required`` diagnostic.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from core.agent.convergence import ConvergenceDetector


class TestConvergenceDetector:
    """Test convergence detection logic."""

    def test_init_defaults(self) -> None:
        det = ConvergenceDetector()
        assert det.total_consecutive_tool_errors == 0
        assert det.recent_errors == []
        # v0.90.0 — escalation flag removed from public surface
        assert not hasattr(det, "convergence_escalated")
        assert det.last_error_key is None
        assert det.repeated_success_streak == 0
        assert det.last_success_tool is None

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
        assert det.last_error_key is not None

    def test_success_resets_counter(self) -> None:
        det = ConvergenceDetector()
        det.total_consecutive_tool_errors = 5
        results = [
            {"tool_use_id": "t1", "content": json.dumps({"status": "ok"})},
        ]
        det.update_tool_error_tracking(results, [])
        assert det.total_consecutive_tool_errors == 0

    def test_repeated_success_detects_no_progress_after_threshold(self) -> None:
        det = ConvergenceDetector()
        for i in range(5):
            results = [
                {"tool_use_id": f"t{i}", "content": json.dumps({"status": "ok"})},
            ]
            tool_log: list[dict[str, Any]] = [
                {
                    "tool": "check_status",
                    "input": {},
                    "result": {"status": "ok"},
                    "tool_use_id": f"t{i}",
                },
            ]
            det.update_tool_error_tracking(results, tool_log)

        assert det.repeated_success_streak == 5
        assert det.last_success_tool == "check_status"
        assert det.check_repeated_success_no_progress() is True

    def test_repeated_success_resets_when_input_changes(self) -> None:
        det = ConvergenceDetector()
        for i in range(4):
            results = [
                {"tool_use_id": f"t{i}", "content": json.dumps({"status": "ok"})},
            ]
            tool_log: list[dict[str, Any]] = [
                {
                    "tool": "check_status",
                    "input": {},
                    "result": {"status": "ok"},
                    "tool_use_id": f"t{i}",
                },
            ]
            det.update_tool_error_tracking(results, tool_log)

        det.update_tool_error_tracking(
            [{"tool_use_id": "t_changed", "content": json.dumps({"status": "ok"})}],
            [
                {
                    "tool": "check_status",
                    "input": {"scope": "different"},
                    "result": {"status": "ok"},
                    "tool_use_id": "t_changed",
                }
            ],
        )

        assert det.repeated_success_streak == 1
        assert det.check_repeated_success_no_progress() is False

    def test_tool_error_resets_repeated_success_streak(self) -> None:
        det = ConvergenceDetector()
        det.update_tool_error_tracking(
            [{"tool_use_id": "t1", "content": json.dumps({"status": "ok"})}],
            [
                {
                    "tool": "check_status",
                    "input": {},
                    "result": {"status": "ok"},
                    "tool_use_id": "t1",
                }
            ],
        )
        det.update_tool_error_tracking(
            [{"tool_use_id": "t2", "content": json.dumps({"error": "fail"})}],
            [
                {
                    "tool": "check_status",
                    "input": {},
                    "result": {"error": "fail"},
                    "tool_use_id": "t2",
                }
            ],
        )

        assert det.repeated_success_streak == 0
        assert det.last_success_tool is None

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

    def test_3_identical_breaks_immediately(self) -> None:
        """v0.90.0 — 3 identical errors break the loop on first detection.

        Pre-v0.90.0 the detector tried a model-escalation callback
        first and only broke after a 4th identical error. With auto-
        escalation removed there's no callback to attempt, so we break
        right away and the AgenticLoop surfaces a diagnostic.
        """
        det = ConvergenceDetector()
        det.recent_errors = ["a:timeout", "a:timeout", "a:timeout"]
        assert det.check_convergence_break() is True

    def test_mixed_errors_no_break(self) -> None:
        det = ConvergenceDetector()
        det.recent_errors = ["a:1", "b:2", "a:1", "c:3"]
        assert det.check_convergence_break() is False

    def test_init_takes_no_arguments(self) -> None:
        """v0.90.0 — escalation_fn parameter removed from __init__.

        Constructing with ``escalation_fn=...`` should raise TypeError
        so no caller silently re-introduces the auto-swap path.
        """
        with pytest.raises(TypeError):
            ConvergenceDetector(escalation_fn=lambda: True)  # type: ignore[call-arg]
