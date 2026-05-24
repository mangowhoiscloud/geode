"""Integration tests for PIPELINE_END → MEMORY.md write-back loop (P0)."""

from __future__ import annotations

from pathlib import Path

from core.wiring.automation import build_automation

from core.hooks import HookEvent, HookSystem


class TestPipelineEndMemoryWrite:
    """Memory write-back hook was removed (generated broken tier=?/score=0.00 entries).
    Pipeline results are recorded in journal (runs.jsonl) via journal_hooks.
    Remaining tests verify the hook registration doesn't crash without the callback.
    """

    def test_no_project_memory_does_not_crash(self, tmp_path: Path):
        """project_memory=None → no error."""
        hooks = HookSystem()

        build_automation(
            hooks=hooks,
            session_key="test-session",
            subject_id="demo-subject",
            project_memory=None,
        )

        # Should not raise
        hooks.trigger(
            HookEvent.PIPELINE_ENDED,
            {
                "node": "synthesizer",
                "subject_id": "demo-subject",
                "final_score": 0.85,
                "dry_run": False,
            },
        )
