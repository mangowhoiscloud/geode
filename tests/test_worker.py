"""Tests for core.agent.worker — subprocess worker data contracts and bootstrap."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from core.agent.worker import WorkerRequest, WorkerResult

# ---------------------------------------------------------------------------
# WorkerRequest / WorkerResult serialization
# ---------------------------------------------------------------------------


class TestWorkerRequest:
    def test_roundtrip(self) -> None:
        req = WorkerRequest(
            task_id="t-001",
            task_type="analyze",
            description="Analyze Cowboy Bebop",
            args={"ip_name": "Cowboy Bebop"},
            denied_tools=["delegate_task", "run_bash"],
            model="claude-opus-4-6",
            provider="anthropic",
            timeout_s=120.0,
            domain="game_ip",
        )
        data = req.to_dict()
        restored = WorkerRequest.from_dict(data)
        assert restored.task_id == "t-001"
        assert restored.description == "Analyze Cowboy Bebop"
        assert "delegate_task" in restored.denied_tools
        assert restored.domain == "game_ip"

    def test_defaults(self) -> None:
        req = WorkerRequest.from_dict({"task_id": "t-002"})
        assert req.model == "claude-opus-4-6"
        assert req.provider == "anthropic"
        assert req.timeout_s == 120.0
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


class TestSubAgentReasoningWiring:
    """v0.55.0 R5 — verify ``_run_agentic`` actually plumbs the
    request's reasoning depth fields into ``AgenticLoop()``. Pre-fix
    these kwargs were never threaded through, so every sub-agent ran
    at the dataclass defaults (effort='high', thinking_budget=0,
    time_budget_s=0.0) regardless of what the parent put on the wire.
    """

    def test_loop_receives_reasoning_kwargs(self, monkeypatch, tmp_path) -> None:
        from unittest.mock import MagicMock, patch

        captured: dict = {}

        def _fake_loop(*args, **kwargs):
            captured.update(kwargs)
            mock_loop = MagicMock()
            mock_loop.run.return_value = MagicMock(text="ok", tool_calls=[], rounds=1)
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
