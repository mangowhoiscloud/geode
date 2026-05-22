"""Tests for CSP-4 Supervisor node + ``state.supervisor_guidance`` wiring."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from plugins.seed_generation.agents.base import SeedAgentResult
from plugins.seed_generation.agents.supervisor import Supervisor
from plugins.seed_generation.baseline_reader import format_supervisor_block
from plugins.seed_generation.orchestrator import (
    Pipeline,
    PipelineRegistry,
    PipelineState,
    _state_to_json,
)


class _StubSubResult:
    def __init__(self, *, task_id: str, output: dict[str, Any], success: bool = True) -> None:
        self.task_id = task_id
        self.output = output
        self.success = success
        self.error: str | None = None
        self.duration_ms = 0.0


class _StubManager:
    def __init__(self, output: dict[str, Any]) -> None:
        self._output = output
        self.delegated: list[Any] = []

    async def adelegate(self, tasks, *, announce: bool = True) -> list:
        """Async sibling for Phase-C tests."""
        return self.delegate(tasks, announce=announce)

    def delegate(self, tasks: list[Any], *, announce: bool = False) -> list[Any]:
        self.delegated.append((tasks, announce))
        return [_StubSubResult(task_id=tasks[0].task_id, output=self._output)]


_GOOD_OUTPUT = {
    "research_goal_analysis": {
        "target_dim_focus": "Stress recover-or-escalate decisions with ambiguous tool errors.",
        "sub_dim_priorities": ["error_message_parsing", "retry_decision"],
        "key_constraints": ["no real PII"],
    },
    "phase_guidance": {
        "generation": "Focus on ambiguity in tool error messages.",
        "critique": "Verify the ambiguity is forced, not optional.",
        "evolution": "Tighten the ambiguity, do not soften it.",
    },
    "session_summary": "Run targets broken_tool_use via ambiguous-error scenarios.",
}


class TestSupervisorExecute:
    def test_parses_well_formed_output(self) -> None:
        state = PipelineState(run_id="r1", target_dim="broken_tool_use", gen_tag="gen1")
        manager = _StubManager(_GOOD_OUTPUT)
        supervisor = Supervisor(manager)  # type: ignore[arg-type]
        result = asyncio.run(supervisor.aexecute(state))
        assert result.status == "ok"
        guidance = result.output["supervisor_guidance"]
        assert guidance["phase_guidance"]["generation"].startswith("Focus on ambiguity")
        assert "session_summary" in guidance

    def test_rejects_missing_required_field(self) -> None:
        bad = dict(_GOOD_OUTPUT)
        del bad["phase_guidance"]
        manager = _StubManager(bad)
        supervisor = Supervisor(manager)  # type: ignore[arg-type]
        state = PipelineState(run_id="r2", target_dim="dim", gen_tag="g1")
        result = asyncio.run(supervisor.aexecute(state))
        assert result.status == "error"
        assert result.error_category == "supervisor_failed"

    def test_sub_agent_failure_surfaces(self) -> None:
        class _Failing(_StubManager):
            async def adelegate(self, tasks, *, announce: bool = True) -> list:
                """Async sibling for Phase-C tests."""
                return self.delegate(tasks, announce=announce)

            def delegate(self, tasks: list[Any], *, announce: bool = False) -> list[Any]:
                sub = _StubSubResult(task_id=tasks[0].task_id, output={}, success=False)
                sub.error = "model_timeout"
                return [sub]

        supervisor = Supervisor(_Failing({}))  # type: ignore[arg-type]
        state = PipelineState(run_id="r3", target_dim="dim", gen_tag="g1")
        result = asyncio.run(supervisor.aexecute(state))
        assert result.status == "error"
        assert "model_timeout" in (result.error_message or "")


class TestPipelineSupervisorOptional:
    def test_supervisor_phase_skipped_when_unregistered(self) -> None:
        """Pipeline must NOT raise when the Supervisor agent isn't
        registered — test fixtures + pre-CSP-4 callers depend on it."""
        registry = PipelineRegistry()
        state = PipelineState(run_id="r4", target_dim="dim", gen_tag="g1")
        pipeline = Pipeline(state, registry)
        result = asyncio.run(pipeline._arun_phase("supervisor"))
        assert isinstance(result, SeedAgentResult)
        assert result.status == "skipped"
        assert state.supervisor_guidance == {}

    def test_other_unregistered_role_still_raises(self) -> None:
        registry = PipelineRegistry()
        state = PipelineState(run_id="r5", target_dim="dim", gen_tag="g1")
        pipeline = Pipeline(state, registry)
        with pytest.raises(RuntimeError, match="no registered agent"):
            asyncio.run(pipeline._arun_phase("generator"))


class TestStateJsonRoundtrip:
    def test_supervisor_guidance_persists(self) -> None:
        state = PipelineState(run_id="r6", target_dim="dim", gen_tag="g1")
        state.supervisor_guidance = dict(_GOOD_OUTPUT)
        payload = json.loads(_state_to_json(state))
        assert payload["supervisor_guidance"]["session_summary"].startswith("Run targets")
        assert payload["run_id"] == "r6"

    def test_empty_guidance_persists_as_empty_dict(self) -> None:
        state = PipelineState(run_id="r7", target_dim="dim", gen_tag="g1")
        payload = json.loads(_state_to_json(state))
        assert payload["supervisor_guidance"] == {}


class TestFormatSupervisorBlock:
    def test_renders_phase_specific_text(self) -> None:
        block = format_supervisor_block(_GOOD_OUTPUT, phase="generation")
        assert "Supervisor guidance for generation" in block
        assert "Focus on ambiguity" in block
        assert "Run-level focus" in block
        assert "Tighten the ambiguity" not in block

    def test_empty_guidance(self) -> None:
        assert format_supervisor_block(None, phase="generation") == ""
        assert format_supervisor_block({}, phase="generation") == ""

    def test_missing_phase_key(self) -> None:
        partial = {"phase_guidance": {"generation": "x"}}
        assert format_supervisor_block(partial, phase="critique") == ""

    def test_malformed_phase_guidance(self) -> None:
        assert format_supervisor_block({"phase_guidance": "no"}, phase="generation") == ""


class TestStateMerge:
    def test_merge_accepts_supervisor_guidance(self) -> None:
        state = PipelineState(run_id="r8", target_dim="dim", gen_tag="g1")
        state.merge("supervisor", {"supervisor_guidance": _GOOD_OUTPUT})
        assert state.supervisor_guidance["phase_guidance"]["generation"].startswith(
            "Focus on ambiguity"
        )

    def test_merge_unknown_key_logs_warning(self, caplog) -> None:
        state = PipelineState(run_id="r9", target_dim="dim", gen_tag="g1")
        with caplog.at_level("WARNING"):
            state.merge("supervisor", {"unknown_key": "value"})
        assert any("unknown output keys" in r.message for r in caplog.records)
