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

    def test_result_backup_file_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
