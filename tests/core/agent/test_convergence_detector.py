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

    @staticmethod
    def _offloaded_rounds(outputs: list[str]) -> ConvergenceDetector:
        """Feed offloaded results of identical calls through the real processor."""
        import asyncio
        import tempfile
        from pathlib import Path
        from unittest.mock import MagicMock

        from core.agent.tool_executor.processor import ToolCallProcessor
        from core.orchestration.tool_offload import ToolResultOffloadStore

        det = ConvergenceDetector()
        with tempfile.TemporaryDirectory() as tmp:
            executor = MagicMock()
            executor._contains_restricted_data.return_value = False
            processor = ToolCallProcessor(
                executor=executor,
                op_logger=MagicMock(),
                error_recovery=MagicMock(),
                offload_store=ToolResultOffloadStore(
                    session_id="s-conv", threshold=32, base_dir=Path(tmp)
                ),
            )
            for i, output in enumerate(outputs):
                call_id = f"toolu_{i:03d}"
                block = asyncio.run(
                    processor._serialize_tool_result({"output": output}, call_id, "read_file")
                )
                assert json.loads(block["content"])["_offloaded"] is True
                det.update_tool_error_tracking(
                    [block],
                    [{"tool": "read_file", "input": {"path": "a"}, "tool_use_id": call_id}],
                )
        return det

    def test_repeated_identical_offloaded_success_is_no_progress(self) -> None:
        det = self._offloaded_rounds(["same " * 200] * 5)
        assert det.check_repeated_success_no_progress() is True

    def test_different_offloaded_results_are_progress(self) -> None:
        # Same length and summary prefix, different content: never the same observation.
        det = self._offloaded_rounds([("same " * 200) + str(i) for i in range(5)])
        assert det.repeated_success_streak == 1
        assert det.check_repeated_success_no_progress() is False

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

    def test_parallel_error_batch_counts_as_one_round(self) -> None:
        det = ConvergenceDetector()
        results = [
            {"tool_use_id": f"t{i}", "content": json.dumps({"error": "same failure"})}
            for i in range(6)
        ]
        tool_log = [
            {"tool_use_id": f"t{i}", "tool": "create_directory", "input": {"path": str(i)}}
            for i in range(6)
        ]

        det.update_tool_error_tracking(results, tool_log)

        assert det.total_consecutive_tool_errors == 1
        assert len(det.recent_errors) == 1
        assert det.check_convergence_break() is False

    def test_long_errors_with_the_same_prefix_have_distinct_fingerprints(self) -> None:
        det = ConvergenceDetector()
        prefix = "Parent directory does not exist: /shared/long/path/"

        for suffix in ("experiments", "learning", "personal"):
            det.update_tool_error_tracking(
                [{"tool_use_id": suffix, "content": json.dumps({"error": prefix + suffix})}],
                [
                    {
                        "tool_use_id": suffix,
                        "tool": "create_directory",
                        "input": {"path": suffix},
                    }
                ],
            )

        assert len(set(det.recent_errors)) == 3
        assert det.check_convergence_break() is False

    def test_three_identical_all_error_rounds_converge(self) -> None:
        det = ConvergenceDetector()
        results = [{"tool_use_id": "t1", "content": json.dumps({"error": "fail"})}]
        tool_log = [{"tool_use_id": "t1", "tool": "test", "input": {"x": 1}}]

        for _ in range(3):
            det.update_tool_error_tracking(results, tool_log)

        assert det.check_convergence_break() is True

    def test_success_breaks_error_round_streak(self) -> None:
        det = ConvergenceDetector()
        error = [{"tool_use_id": "t1", "content": json.dumps({"error": "fail"})}]
        tool_log = [{"tool_use_id": "t1", "tool": "test", "input": {}}]
        det.update_tool_error_tracking(error, tool_log)
        det.update_tool_error_tracking(error, tool_log)

        det.update_tool_error_tracking(
            [{"tool_use_id": "ok", "content": json.dumps({"status": "ok"})}], []
        )
        det.update_tool_error_tracking(error, tool_log)

        assert det.total_consecutive_tool_errors == 1
        assert len(det.recent_errors) == 1
        assert det.check_convergence_break() is False

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
        det.total_consecutive_tool_errors = 3
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
