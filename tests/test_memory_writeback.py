"""Integration tests for PIPELINE_END → MEMORY.md write-back loop (P0)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from geode.memory.project import ProjectMemory
from geode.orchestration.hooks import HookEvent, HookSystem
from geode.runtime import GeodeRuntime


def _make_hooks_and_memory(
    tmp_path: Path,
) -> tuple[HookSystem, ProjectMemory]:
    """Create a HookSystem + ProjectMemory wired via _build_automation."""
    hooks = HookSystem()
    mem = ProjectMemory(tmp_path)
    mem.ensure_structure()
    return hooks, mem


class TestPipelineEndMemoryWrite:
    def test_pipeline_end_triggers_memory_write(self, tmp_path: Path):
        """PIPELINE_END handler calls add_insight() with enriched data."""
        hooks, mem = _make_hooks_and_memory(tmp_path)

        GeodeRuntime._build_automation(
            hooks=hooks,
            session_key="test-session",
            ip_name="Berserk",
            project_memory=mem,
        )

        # Simulate PIPELINE_END with enriched data
        hooks.trigger(HookEvent.PIPELINE_END, {
            "node": "synthesizer",
            "ip_name": "Berserk",
            "final_score": 0.85,
            "tier": "S",
            "synthesis_cause": "conversion_failure",
            "synthesis_action": "marketing_push",
            "dry_run": False,
        })

        content = mem.memory_file.read_text(encoding="utf-8")
        assert "Berserk" in content
        assert "tier=S" in content
        assert "score=0.85" in content
        assert "cause=conversion_failure" in content
        assert "action=marketing_push" in content

    def test_dry_run_skips_memory_write(self, tmp_path: Path):
        """dry_run=True → add_insight() is NOT called."""
        hooks, mem = _make_hooks_and_memory(tmp_path)

        GeodeRuntime._build_automation(
            hooks=hooks,
            session_key="test-session",
            ip_name="Berserk",
            project_memory=mem,
        )

        hooks.trigger(HookEvent.PIPELINE_END, {
            "node": "synthesizer",
            "ip_name": "Berserk",
            "final_score": 0.85,
            "tier": "S",
            "dry_run": True,
        })

        content = mem.memory_file.read_text(encoding="utf-8")
        # The insight section should be empty (only the header from ensure_structure)
        assert "tier=S" not in content

    def test_no_project_memory_does_not_crash(self, tmp_path: Path):
        """project_memory=None → handler is a no-op, no error."""
        hooks = HookSystem()

        GeodeRuntime._build_automation(
            hooks=hooks,
            session_key="test-session",
            ip_name="Berserk",
            project_memory=None,
        )

        # Should not raise
        hooks.trigger(HookEvent.PIPELINE_END, {
            "node": "synthesizer",
            "ip_name": "Berserk",
            "final_score": 0.85,
            "tier": "S",
            "dry_run": False,
        })

    def test_minimal_hook_data_still_writes(self, tmp_path: Path):
        """Missing optional fields → insight still written with defaults."""
        hooks, mem = _make_hooks_and_memory(tmp_path)

        GeodeRuntime._build_automation(
            hooks=hooks,
            session_key="test-session",
            ip_name="TestIP",
            project_memory=mem,
        )

        hooks.trigger(HookEvent.PIPELINE_END, {
            "node": "synthesizer",
            "ip_name": "TestIP",
        })

        content = mem.memory_file.read_text(encoding="utf-8")
        assert "TestIP" in content
        assert "tier=?" in content
        assert "score=0.00" in content


class TestEnrichedHookData:
    def test_enriched_hook_data_fields(self):
        """Verify hook_data enrichment in _make_hooked_node for synthesizer."""
        from geode.graph import _make_hooked_node

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
