"""Tests for core.agent.worker — subprocess worker data contracts and bootstrap."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from core.agent.loop.models import AgenticResult
from core.agent.worker import (
    _FAILURE_TERMINATION_REASONS,
    WorkerRequest,
    WorkerResult,
    _resolve_worker_outcome,
)

# ---------------------------------------------------------------------------
# WorkerRequest / WorkerResult serialization
# ---------------------------------------------------------------------------


class TestWorkerRequest:
    def test_roundtrip(self) -> None:
        req = WorkerRequest(
            task_id="t-001",
            task_type="analyze",
            description="Analyze Project Orion",
            args={"subject_id": "Project Orion"},
            denied_tools=["delegate_task", "run_bash"],
            model="claude-opus-4-6",
            provider="anthropic",
            timeout_s=120.0,
        )
        data = req.to_dict()
        restored = WorkerRequest.from_dict(data)
        assert restored.task_id == "t-001"
        assert restored.description == "Analyze Project Orion"
        assert "delegate_task" in restored.denied_tools

    def test_defaults(self) -> None:
        req = WorkerRequest.from_dict({"task_id": "t-002"})
        assert req.model == "claude-opus-4-6"
        assert req.provider == "anthropic"
        # PR-CHECKPOINT-RESUME-TIMEBUDGET (2026-05-25, S6) — default
        # wall-clock cap lifted 120s → 600s. Operator overrides via
        # GEODE_SUBAGENT_TIMEOUT_S env or per-request payload.
        assert req.timeout_s == 600.0
        assert req.denied_tools == []
        assert req.isolation == ""

    def test_json_serializable(self) -> None:
        req = WorkerRequest(task_id="t-003", description="hello")
        raw = json.dumps(req.to_dict())
        parsed = json.loads(raw)
        assert parsed["task_id"] == "t-003"

    def test_reasoning_depth_roundtrip(self) -> None:
        """v0.55.0 R5 — pre-fix ``from_dict`` silently dropped ``effort``,
        ``thinking_budget``, ``time_budget_s`` so every sub-agent ran at
        the dataclass defaults. Wired in v0.55.0 to mirror Hermes
        (``delegate_tool.py:608`` parent-inherit) + Claude Code
        (``loadAgentsDir.ts:116`` agent-level effort frontmatter)."""
        req = WorkerRequest(
            task_id="t-r5",
            description="reasoning-heavy subtask",
            effort="max",
            thinking_budget=8192,
            time_budget_s=180.0,
        )
        data = req.to_dict()
        restored = WorkerRequest.from_dict(data)
        assert restored.effort == "max"
        assert restored.thinking_budget == 8192
        assert restored.time_budget_s == 180.0

    def test_reasoning_depth_defaults(self) -> None:
        """Defaults preserved when fields omitted from dict."""
        req = WorkerRequest.from_dict({"task_id": "t-default"})
        assert req.effort == "high"
        assert req.thinking_budget == 0
        assert req.time_budget_s == 0.0

    def test_toolkit_roundtrip(self) -> None:
        """CSP-1 — ``toolkit`` survives the parent→worker IPC boundary."""
        req = WorkerRequest(
            task_id="t-csp1",
            description="seed generator spawn",
            toolkit="seed_generation",
        )
        data = req.to_dict()
        assert data["toolkit"] == "seed_generation"
        restored = WorkerRequest.from_dict(data)
        assert restored.toolkit == "seed_generation"

    def test_toolkit_default_empty(self) -> None:
        """Default ``toolkit`` is empty string — legacy callers unaffected."""
        req = WorkerRequest.from_dict({"task_id": "t-bc"})
        assert req.toolkit == ""


class TestWorkerResult:
    def test_roundtrip(self) -> None:
        res = WorkerResult(
            task_id="t-001",
            success=True,
            output="Full response text",
            summary="Full response text"[:500],
            duration_ms=1234.5,
        )
        data = res.to_dict()
        restored = WorkerResult.from_dict(data)
        assert restored.task_id == "t-001"
        assert restored.success is True
        assert restored.output == "Full response text"
        assert restored.duration_ms == 1234.5

    def test_error_result(self) -> None:
        res = WorkerResult(
            task_id="t-002",
            success=False,
            error="Timeout after 120s",
        )
        data = res.to_dict()
        assert data["error"] == "Timeout after 120s"
        # None-valued fields should be excluded
        restored = WorkerResult.from_dict(data)
        assert restored.success is False

    def test_none_error_excluded(self) -> None:
        """to_dict() should omit None-valued fields."""
        res = WorkerResult(task_id="t-003", success=True)
        data = res.to_dict()
        assert "error" not in data


# ---------------------------------------------------------------------------
# Worker subprocess integration (no LLM call)
# ---------------------------------------------------------------------------


class TestWorkerSubprocess:
    """Test the worker as an actual subprocess (stdin/stdout JSON protocol)."""

    def test_empty_stdin_returns_error(self) -> None:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "core.agent.worker"],
            input="\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        result = json.loads(proc.stdout.strip())
        assert result["success"] is False
        assert "Empty stdin" in result["error"]

    def test_invalid_json_returns_error(self) -> None:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "core.agent.worker"],
            input="not-json\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        result = json.loads(proc.stdout.strip())
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_missing_task_id_returns_error(self) -> None:
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "core.agent.worker"],
            input=json.dumps({"description": "hello"}) + "\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        result = json.loads(proc.stdout.strip())
        assert result["success"] is False
        assert "task_id" in result.get("error", "").lower() or result["task_id"] == "unknown"

    def test_result_backup_file_created(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Worker should save a backup result file."""
        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        # Import and call main directly to test backup
        from core.agent.worker import WorkerResult, _save_result_backup

        result = WorkerResult(task_id="bk-001", success=True, output="test")
        _save_result_backup(result)
        backup = tmp_path / "bk-001.result.json"
        assert backup.exists()
        data = json.loads(backup.read_text())
        assert data["task_id"] == "bk-001"


class TestResolveWorkerOutcome:
    """PR-DEFECT-AB (2026-05-24) — gate ``WorkerResult.success`` on the
    AgenticLoop's actual termination signal instead of ``bool(text)``.

    The seed-generation smoke (v0.99.52) revealed that proximity / critic
    sub-agents ingested the loop's ``_build_model_action_result`` fallback
    UI string ("! Unexpected error. Auto-retrying.") as legitimate
    content, because the worker reported ``success=True`` whenever the
    loop produced any non-empty string. The cases below pin the new
    contract so the regression cannot return silently.
    """

    def test_happy_path_real_response_is_success(self) -> None:
        result = AgenticResult(
            text="The answer is 42.",
            tool_calls=[],
            rounds=3,
            termination_reason="unknown",
            error=None,
        )
        success, summary, text = _resolve_worker_outcome(result)
        assert success is True
        assert text == "The answer is 42."
        assert summary == "The answer is 42."

    def test_convergence_detected_is_failure(self) -> None:
        """``convergence_detected`` is a failure exit — the loop bailed after
        detecting a repeating error pattern. agent_loop.py sets BOTH
        ``error="convergence_detected"`` AND
        ``termination_reason="convergence_detected"``, and the text is the
        diagnostic ("Detected repeating failure pattern. Breaking loop to
        avoid infinite retry."), not a real answer. Pinning this case so a
        future refactor that reorders the convergence path doesn't
        accidentally promote the bail-out to a legitimate response.
        """
        result = AgenticResult(
            text="Detected repeating failure pattern. Breaking loop to avoid infinite retry.",
            termination_reason="convergence_detected",
            error="convergence_detected",
        )
        success, summary, _text = _resolve_worker_outcome(result)
        assert success is False
        assert "convergence_detected" in summary

    @pytest.mark.parametrize(
        "termination_reason",
        sorted(_FAILURE_TERMINATION_REASONS),
    )
    def test_failure_termination_reasons_force_failure(self, termination_reason: str) -> None:
        """The five explicit failure sentinels must override ``bool(text)``.

        Each of these sentinels means the loop is emitting fallback UI
        text instead of a real LLM response, so downstream consumers
        MUST see ``success=False`` even though ``text`` is non-empty.
        """
        result = AgenticResult(
            text="! Unexpected error. Auto-retrying.",
            termination_reason=termination_reason,
        )
        success, summary, _text = _resolve_worker_outcome(result)
        assert success is False, (
            f"termination_reason={termination_reason!r} must force success=False"
        )
        assert "Sub-agent failed" in summary
        assert f"termination_reason={termination_reason}" in summary

    def test_error_field_forces_failure_even_with_text(self) -> None:
        """A non-None ``error`` always means failure, regardless of ``text`` or termination."""
        result = AgenticResult(
            text="partial output before crash",
            termination_reason="unknown",
            error="LLM provider timeout after 120s",
        )
        success, summary, _text = _resolve_worker_outcome(result)
        assert success is False
        assert "LLM provider timeout after 120s" in summary

    def test_empty_text_is_failure(self) -> None:
        result = AgenticResult(text="", termination_reason="unknown")
        success, summary, text = _resolve_worker_outcome(result)
        assert success is False
        assert text == ""
        # No error + unknown termination + no text — falls back to generic message.
        assert summary == "No response from sub-agent"

    def test_none_result_is_failure(self) -> None:
        success, summary, text = _resolve_worker_outcome(None)
        assert success is False
        assert text == ""
        assert summary == "No response from sub-agent"

    def test_user_clarification_needed_is_success(self) -> None:
        """The question IS the legitimate output, not fallback UI."""
        result = AgenticResult(
            text="What time zone should I use?",
            termination_reason="user_clarification_needed",
        )
        success, _summary, _text = _resolve_worker_outcome(result)
        assert success is True

    def test_input_blocked_is_success(self) -> None:
        """The diagnostic message IS the legitimate output."""
        result = AgenticResult(
            text="Input rejected by policy filter.",
            termination_reason="input_blocked",
        )
        success, _summary, _text = _resolve_worker_outcome(result)
        assert success is True

    def test_user_cancelled_is_success(self) -> None:
        """Operator-requested halt — text is the legitimate "Interrupted."
        marker (see agent_loop.py:705). No ``error`` is set, so the worker
        surfaces this as a clean exit and the parent decides what to do
        with the half-finished task rather than the parent treating it as
        a sub-agent failure."""
        result = AgenticResult(
            text="Interrupted.",
            termination_reason="user_cancelled",
        )
        success, _summary, _text = _resolve_worker_outcome(result)
        assert success is True

    def test_summary_truncates_at_500_chars(self) -> None:
        long_text = "x" * 1000
        result = AgenticResult(text=long_text, termination_reason="unknown")
        _success, summary, _text = _resolve_worker_outcome(result)
        assert len(summary) == 500

    def test_failure_sentinels_are_complete_catalog(self) -> None:
        """Lock the failure sentinel set against accidental shrinkage.

        If a new failure-tagged ``termination_reason`` is added to
        ``agent_loop.py`` without being added to
        ``_FAILURE_TERMINATION_REASONS``, this test won't catch it
        directly — but it pins the existing six so removal would
        require explicit acknowledgment.
        """
        expected = frozenset(
            {
                "model_action_required",
                "context_exhausted",
                "llm_error",
                "billing_error",
                "cost_budget_exceeded",
                "convergence_detected",
            }
        )
        assert expected == _FAILURE_TERMINATION_REASONS


class TestSubAgentReasoningWiring:
    """v0.55.0 R5 — verify ``_run_agentic`` actually plumbs the
    request's reasoning depth fields into ``AgenticLoop()``. Pre-fix
    these kwargs were never threaded through, so every sub-agent ran
    at the dataclass defaults (effort='high', thinking_budget=0,
    time_budget_s=0.0) regardless of what the parent put on the wire.
    """

    def test_loop_receives_reasoning_kwargs(self, monkeypatch, tmp_path) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        captured: dict = {}

        def _fake_loop(*args, **kwargs):
            captured.update(kwargs)
            mock_loop = MagicMock()
            # PR-DEFECT-AB (2026-05-24): _resolve_worker_outcome now reads
            # ``.error`` + ``.termination_reason`` off the loop's return,
            # so the stub must be a real AgenticResult (or close enough)
            # rather than a bare MagicMock whose attribute access yields
            # another MagicMock that breaks ``"; ".join(cause_bits)``.
            mock_loop.arun = AsyncMock(
                return_value=AgenticResult(
                    text="ok",
                    tool_calls=[],
                    rounds=1,
                    error=None,
                    termination_reason="unknown",
                )
            )
            return mock_loop

        # Stub out everything _run_agentic touches except the bit we test.
        monkeypatch.setattr("core.agent.worker.WORKER_DIR", tmp_path)
        with (
            patch("core.cli.tool_handlers._build_tool_handlers", return_value={}),
            patch("core.agent.tool_executor.ToolExecutor"),
            patch("core.agent.conversation.ConversationContext"),
            patch("core.agent.loop.AgenticLoop", side_effect=_fake_loop),
        ):
            from core.agent.worker import WorkerRequest, _run_agentic

            request = WorkerRequest(
                task_id="r5-test",
                description="reasoning subtask",
                effort="max",
                thinking_budget=8192,
                time_budget_s=240.0,
            )
            _run_agentic(request)

        assert captured.get("effort") == "max"
        assert captured.get("thinking_budget") == 8192
        assert captured.get("time_budget_s") == 240.0
