"""Integration tests for PIPELINE_END → MEMORY.md write-back loop (P0)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.hooks import HookEvent, HookSystem
from core.lifecycle.automation import build_automation
from core.memory.project import ProjectMemory


def _make_hooks_and_memory(
    tmp_path: Path,
) -> tuple[HookSystem, ProjectMemory]:
    """Create a HookSystem + ProjectMemory wired via _build_automation."""
    hooks = HookSystem()
    mem = ProjectMemory(tmp_path)
    mem.ensure_structure()
    return hooks, mem


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
            ip_name="Berserk",
            project_memory=None,
        )

        # Should not raise
        hooks.trigger(
            HookEvent.PIPELINE_END,
            {
                "node": "synthesizer",
                "ip_name": "Berserk",
                "final_score": 0.85,
                "tier": "S",
                "dry_run": False,
            },
        )


class TestEnrichedHookData:
    def test_enriched_hook_data_fields(self):
        """Verify hook_data enrichment in _make_hooked_node for synthesizer."""
        from core.graph import _make_hooked_node

        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def _capture(event: HookEvent, data: dict[str, Any]) -> None:
            captured.append(dict(data))

        hooks.register(HookEvent.PIPELINE_END, _capture, name="test_capture", priority=50)

        # Create a fake synthesizer node that returns synthesis-like result
        class FakeSynthesis:
            undervaluation_cause = "discovery_failure"
            action_type = "relaunch"

        def fake_synthesizer(state: dict[str, Any]) -> dict[str, Any]:
            return {
                "synthesis": FakeSynthesis(),
            }

        wrapped = _make_hooked_node(fake_synthesizer, "synthesizer", hooks)  # type: ignore[arg-type]

        # Execute with state containing final_score/tier (set by scoring node)
        wrapped({"ip_name": "Ghost in the Shell", "final_score": 0.72, "tier": "A"})  # type: ignore[arg-type]

        assert len(captured) == 1
        data = captured[0]
        assert data["synthesis_cause"] == "discovery_failure"
        assert data["synthesis_action"] == "relaunch"
        assert data["final_score"] == 0.72
        assert data["tier"] == "A"
        assert data["dry_run"] is False
