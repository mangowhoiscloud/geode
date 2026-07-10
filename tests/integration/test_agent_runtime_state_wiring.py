"""End-to-end wiring tests for PR-COMM-3b — emit-site augmentation +
bootstrap handler registration for the SQLite ``agent_runtime_state``
writers.

PR-COMM-3 landed the schema + writer module but explicitly deferred
bootstrap wiring because the existing SESSION_ENDED /
SUBAGENT_COMPLETED payloads did not carry the fields the writers need
(``agent_kind`` / ``component`` / ``adapter_type`` /
``claude_cli_session_id`` / ``status``).

PR-COMM-3b closes that gap. These tests pin the wire so future
refactors of the emit sites or the bootstrap handlers can't
reintroduce the silent-no-op regression.

Coverage map:

* :class:`TestSessionEndedPayloadEnrichment` — verifies
  ``_final_hook_payloads`` adds the four new keys with the expected
  values across REPL / sub-agent / no-orchestrator paths.
* :class:`TestSubagentCompletedPayloadEnrichment` — verifies
  ``SubAgent._emit_hook`` populates ``component`` + ``status`` on
  SUBAGENT_COMPLETED.
* :class:`TestBootstrapHandlerWiring` — drives the actual
  ``build_hooks()`` factory then triggers SESSION_ENDED /
  SUBAGENT_COMPLETED and confirms the SQLite row lands with the
  right shape.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from core.agent.loop._lifecycle import _final_hook_payloads
from core.agent.loop.models import AgenticResult
from core.memory.session_manager import SessionManager
from core.observability import agent_runtime_state as ars


@pytest.fixture()
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db = tmp_path / "sessions.db"
    manager = SessionManager(db_path=db)
    manager.close()
    monkeypatch.setattr("core.memory.session_manager._get_default_db_path", lambda: db)
    ars._reset_for_tests(db_path=db)
    yield db
    ars._reset_for_tests()


def _fake_loop(
    *,
    session_id: str = "s-test",
    parent_session_id: str = "",
    last_emitted_session_id: str = "",
    adapter_name: str = "claude-cli",
    provider: str = "anthropic",
    model: str = "claude-sonnet-4-6",
) -> Any:
    """Mock AgenticLoop with only the fields ``_final_hook_payloads`` reads."""
    return SimpleNamespace(
        model=model,
        _provider=provider,
        _session_id=session_id,
        _parent_session_id=parent_session_id,
        _last_emitted_session_id=last_emitted_session_id,
        _new_adapter=SimpleNamespace(name=adapter_name),
    )


def _ok_result(text: str = "ok") -> AgenticResult:
    return AgenticResult(text=text, termination_reason="unknown")


class TestSessionEndedPayloadEnrichment:
    """``_final_hook_payloads`` must enrich SESSION_ENDED with the four
    columns the agent_runtime_state writer needs."""

    def test_repl_path_marks_agent_kind_repl(self) -> None:
        loop = _fake_loop(session_id="s-repl", parent_session_id="")
        session_ended, _turn, _metrics = _final_hook_payloads(loop, _ok_result(), "hi")
        assert session_ended["agent_kind"] == "repl"
        assert session_ended["session_id"] == "s-repl"

    def test_subagent_path_marks_agent_kind_subagent(self) -> None:
        loop = _fake_loop(session_id="task-001", parent_session_id="s-parent")
        session_ended, _turn, _metrics = _final_hook_payloads(loop, _ok_result(), "hi")
        assert session_ended["agent_kind"] == "subagent"

    def test_adapter_type_carried_from_loop(self) -> None:
        loop = _fake_loop(adapter_name="claude-payg")
        session_ended, _turn, _metrics = _final_hook_payloads(loop, _ok_result(), "hi")
        assert session_ended["adapter_type"] == "claude-payg"

    def test_claude_cli_session_id_carried_from_loop(self) -> None:
        loop = _fake_loop(last_emitted_session_id="cli-abc-123")
        session_ended, _turn, _metrics = _final_hook_payloads(loop, _ok_result(), "hi")
        assert session_ended["claude_cli_session_id"] == "cli-abc-123"

    def test_component_falls_back_when_no_run_transcript(self) -> None:
        """REPL / ad-hoc spawn without an active RunTranscript must
        produce a safe default rather than raising."""
        loop = _fake_loop()
        session_ended, _turn, _metrics = _final_hook_payloads(loop, _ok_result(), "hi")
        assert session_ended["component"] == "agentic_loop"

    def test_bare_loop_without_new_adapter_field_does_not_crash(self) -> None:
        """Some test scaffolds construct a loop stub without
        ``_new_adapter``; the payload builder must tolerate that and
        emit an empty adapter_type."""
        loop = SimpleNamespace(
            model="x",
            _provider="y",
            _session_id="s-bare",
            _parent_session_id="",
            _last_emitted_session_id="",
        )
        session_ended, _turn, _metrics = _final_hook_payloads(loop, _ok_result(), "hi")
        assert session_ended["adapter_type"] == ""


class TestSubagentCompletedPayloadEnrichment:
    """``SubAgent._emit_hook`` must add ``component`` + ``status`` to
    SUBAGENT_COMPLETED so the writer can persist the right row."""

    def test_completed_carries_component_and_status(self) -> None:
        from core.agent.sub_agent import SubAgentManager, SubResult, SubTask
        from core.hooks import HookEvent, HookSystem

        hooks = HookSystem()
        captured: list[dict[str, Any]] = []

        def _cap(_event: HookEvent, data: dict[str, Any]) -> None:
            captured.append(data)

        hooks.register(HookEvent.SUBAGENT_COMPLETED, _cap, name="cap")

        from core.orchestration.isolated_execution import IsolatedRunner

        sub = SubAgentManager(IsolatedRunner(), hooks=hooks)
        task = SubTask(task_id="t-comm3b", task_type="analyze", description="hi")
        result = SubResult(
            task_id="t-comm3b",
            description="hi",
            success=True,
            output={"summary": "done"},
        )
        asyncio.run(sub._emit_hook(HookEvent.SUBAGENT_COMPLETED, task, sub_result=result))

        assert len(captured) == 1
        assert captured[0]["component"] == "agentic_loop"
        assert captured[0]["status"] == "completed"
        assert captured[0]["task_id"] == "t-comm3b"

    def test_failed_subagent_status_is_failed(self) -> None:
        from core.agent.sub_agent import SubAgentManager, SubResult, SubTask
        from core.hooks import HookEvent, HookSystem

        hooks = HookSystem()
        captured: list[dict[str, Any]] = []
        hooks.register(
            HookEvent.SUBAGENT_FAILED,
            lambda _e, d: captured.append(d),
            name="cap_fail",
        )

        from core.orchestration.isolated_execution import IsolatedRunner

        sub = SubAgentManager(IsolatedRunner(), hooks=hooks)
        task = SubTask(task_id="t-fail", task_type="analyze", description="hi")
        result = SubResult(task_id="t-fail", description="hi", success=False, output={})
        asyncio.run(
            sub._emit_hook(
                HookEvent.SUBAGENT_FAILED,
                task,
                sub_result=result,
                error="boom",
            )
        )

        assert len(captured) == 1
        assert captured[0]["status"] == "failed"
        assert captured[0]["error"] == "boom"

    def test_subagent_started_does_not_carry_status(self) -> None:
        """SUBAGENT_STARTED has no ``sub_result`` yet — the ``status``
        field should remain unset so the writer's UPSERT doesn't
        prematurely stamp the row as "completed". ``component`` is
        set unconditionally so START events still feed the writer's
        component column."""
        from core.agent.sub_agent import SubAgentManager, SubTask
        from core.hooks import HookEvent, HookSystem
        from core.orchestration.isolated_execution import IsolatedRunner

        hooks = HookSystem()
        captured: list[dict[str, Any]] = []
        hooks.register(
            HookEvent.SUBAGENT_STARTED,
            lambda _e, d: captured.append(d),
            name="cap_start",
        )

        sub = SubAgentManager(IsolatedRunner(), hooks=hooks)
        task = SubTask(task_id="t-start", task_type="analyze", description="hi")
        asyncio.run(sub._emit_hook(HookEvent.SUBAGENT_STARTED, task))

        assert len(captured) == 1
        assert "status" not in captured[0]
        assert captured[0]["component"] == "agentic_loop"


class TestBootstrapHandlerWiring:
    """End-to-end: build_hooks registers the two handlers, triggering
    SESSION_ENDED / SUBAGENT_COMPLETED with augmented payloads writes
    the expected row to ``agent_runtime_state``."""

    def test_session_ended_writes_full_row(self, tmp_db: Path) -> None:
        from core.hooks import HookEvent
        from core.wiring.bootstrap import build_hooks

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_db.parent)

        # Simulate the augmented payload that _final_hook_payloads now
        # produces. (Direct lifecycle invocation would require a real
        # AgenticLoop; we exercise the handler contract with the same
        # payload shape.)
        hooks.trigger(
            HookEvent.SESSION_ENDED,
            {
                "session_id": "s-e2e",
                "model": "claude-sonnet-4-6",
                "provider": "anthropic",
                "agent_kind": "repl",
                "component": "seed-generation",
                "adapter_type": "claude-cli",
                "claude_cli_session_id": "cli-e2e-1",
                "termination_reason": "unknown",
                "rounds": 3,
                "tool_count": 2,
                "error": None,
            },
        )

        state = ars.get_agent_runtime_state("s-e2e")
        assert state is not None
        assert state.agent_kind == "repl"
        assert state.component == "seed-generation"
        assert state.adapter_type == "claude-cli"
        assert state.claude_cli_session_id == "cli-e2e-1"

    def test_subagent_completed_writes_run_link(self, tmp_db: Path) -> None:
        from core.hooks import HookEvent
        from core.wiring.bootstrap import build_hooks

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_db.parent)

        hooks.trigger(
            HookEvent.SUBAGENT_COMPLETED,
            {
                "task_id": "gen-e2e-001",
                "task_type": "generator",
                "description": "seed task",
                "source": "sub_agent",
                "component": "seed-generation",
                "status": "completed",
                "run_id": "gen1-run-001",
                "duration_ms": 1234.0,
                "success": True,
                "summary": "Generated 5 seeds",
            },
        )

        state = ars.get_agent_runtime_state("gen-e2e-001")
        assert state is not None
        assert state.agent_kind == "subagent"
        assert state.component == "seed-generation"
        assert state.last_run_id == "gen1-run-001"
        assert state.last_run_status == "completed"

    def test_subagent_failed_writes_error(self, tmp_db: Path) -> None:
        from core.hooks import HookEvent
        from core.wiring.bootstrap import build_hooks

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_db.parent)

        # SUBAGENT_FAILED uses the same handler — confirm error
        # propagates. (The handler is registered to SUBAGENT_COMPLETED;
        # we exercise the failure-flag-on-COMPLETED path that production
        # uses when sub_result.success is False but the worker still
        # surfaces a completion event.)
        hooks.trigger(
            HookEvent.SUBAGENT_COMPLETED,
            {
                "task_id": "gen-fail",
                "component": "seed-generation",
                "status": "failed",
                "run_id": "gen1-fail-001",
                "error": "termination_reason=model_action_required",
            },
        )
        state = ars.get_agent_runtime_state("gen-fail")
        assert state is not None
        assert state.last_run_status == "failed"
        assert state.last_error == "termination_reason=model_action_required"

    def test_handler_silent_on_missing_id(self, tmp_db: Path) -> None:
        """Handlers must skip writes when the agent_id key is missing
        — pre-fix the no-op guard prevents polluting the table with
        empty-key rows."""
        from core.hooks import HookEvent
        from core.wiring.bootstrap import build_hooks

        hooks, _, _ = build_hooks(session_key="t", run_id="r-1", log_dir=tmp_db.parent)
        hooks.trigger(HookEvent.SESSION_ENDED, {"agent_kind": "repl"})
        hooks.trigger(HookEvent.SUBAGENT_COMPLETED, {"task_type": "x"})

        conn = sqlite3.connect(str(tmp_db))
        count = conn.execute("SELECT COUNT(*) FROM agent_runtime_state").fetchone()[0]
        assert count == 0
