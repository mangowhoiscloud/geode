"""Tests for GAP 5: /resume CLI command + session detection."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.cli.commands import cmd_resume, resolve_action
from core.cli.session_checkpoint import SessionCheckpoint, SessionState


class TestResumeCommandMap:
    """COMMAND_MAP includes /resume."""

    def test_resolve_resume(self) -> None:
        assert resolve_action("/resume") == "resume"


class TestCmdResume:
    """cmd_resume() function behavior."""

    @pytest.fixture()
    def session_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "session"

    @pytest.fixture()
    def checkpoint(self, session_dir: Path) -> SessionCheckpoint:
        return SessionCheckpoint(session_dir=session_dir)

    @pytest.fixture(autouse=True)
    def _patch_default_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_dir: Path,
    ) -> None:
        """Redirect SessionCheckpoint default dir to tmp."""
        import core.cli.session_checkpoint as cp_mod

        monkeypatch.setattr(cp_mod, "DEFAULT_SESSION_DIR", session_dir)

    def test_no_sessions_returns_none(self) -> None:
        result = cmd_resume("")
        assert result is None

    def test_resume_explicit_session(
        self,
        checkpoint: SessionCheckpoint,
    ) -> None:
        state = SessionState(
            session_id="test-1",
            model="claude-opus-4-6",
            user_input="analyze Berserk",
            messages=[{"role": "user", "content": "hi"}],
        )
        checkpoint.save(state)
        result = cmd_resume("test-1")
        assert result == "test-1"

    def test_resume_nonexistent_returns_none(self) -> None:
        result = cmd_resume("nonexistent-id")
        assert result is None

    def test_resume_completed_session_returns_none(
        self,
        checkpoint: SessionCheckpoint,
    ) -> None:
        state = SessionState(
            session_id="done-1",
            status="completed",
            messages=[],
        )
        checkpoint.save(state)
        result = cmd_resume("done-1")
        assert result is None

    def test_list_resumable_sessions(
        self,
        checkpoint: SessionCheckpoint,
    ) -> None:
        """With no args, cmd_resume lists sessions and returns None."""
        checkpoint.save(SessionState(session_id="a1", user_input="first", messages=[]))
        checkpoint.save(SessionState(session_id="a2", user_input="second", messages=[]))
        result = cmd_resume("")
        assert result is None  # listing only, no auto-resume
