"""Tests for session resume: checkpoint save/load, /resume command, CLI flags."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core.cli.commands import cmd_resume, resolve_action
from core.cli.conversation import ConversationContext
from core.cli.session_checkpoint import SessionCheckpoint, SessionState


class TestResumeCommandMap:
    """COMMAND_MAP includes /resume."""

    def test_resolve_resume(self) -> None:
        assert resolve_action("/resume") == "resume"


class TestCmdResume:
    """cmd_resume() returns full SessionState for caller to restore."""

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

    def test_resume_explicit_session_returns_state(
        self,
        checkpoint: SessionCheckpoint,
    ) -> None:
        messages = [
            {"role": "user", "content": "analyze Berserk"},
            {"role": "assistant", "content": "Starting analysis..."},
        ]
        state = SessionState(
            session_id="test-1",
            model="claude-opus-4-6",
            user_input="analyze Berserk",
            messages=messages,
        )
        checkpoint.save(state)
        result = cmd_resume("test-1")
        # Returns full SessionState, not just session_id
        assert isinstance(result, SessionState)
        assert result.session_id == "test-1"
        assert len(result.messages) == 2
        assert result.user_input == "analyze Berserk"

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


class TestCheckpointSaveFromAgenticLoop:
    """AgenticLoop._save_checkpoint() persists session state."""

    @pytest.fixture()
    def session_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "session"

    @pytest.fixture(autouse=True)
    def _patch_default_dir(
        self,
        monkeypatch: pytest.MonkeyPatch,
        session_dir: Path,
    ) -> None:
        import core.cli.session_checkpoint as cp_mod

        monkeypatch.setattr(cp_mod, "DEFAULT_SESSION_DIR", session_dir)

    def test_save_checkpoint_creates_files(self, session_dir: Path) -> None:
        """_save_checkpoint writes state.json + messages.json."""
        from core.cli.agentic_loop import AgenticLoop

        ctx = ConversationContext()
        ctx.add_user_message("hello")
        ctx.add_assistant_message("hi there")
        executor = MagicMock()
        loop = AgenticLoop(ctx, executor)

        loop._save_checkpoint("hello", round_idx=1)

        # Checkpoint should have been created
        sid = loop._session_id
        assert sid  # non-empty
        state_file = session_dir / sid / "state.json"
        msg_file = session_dir / sid / "messages.json"
        assert state_file.exists()
        assert msg_file.exists()

    def test_mark_session_completed(self, session_dir: Path) -> None:
        """mark_session_completed marks checkpoint as completed."""
        from core.cli.agentic_loop import AgenticLoop

        ctx = ConversationContext()
        ctx.add_user_message("test")
        executor = MagicMock()
        loop = AgenticLoop(ctx, executor)

        # Save first
        loop._save_checkpoint("test", round_idx=1)
        # Then mark completed
        loop.mark_session_completed()

        # Verify status is completed
        cp = SessionCheckpoint(session_dir=session_dir)
        state = cp.load(loop._session_id)
        assert state is not None
        assert state.status == "completed"


class TestSessionRestore:
    """Session messages are restored into ConversationContext."""

    def test_messages_injected_into_conversation(self) -> None:
        """Simulates /resume wiring: messages injected into ConversationContext."""
        saved_messages = [
            {"role": "user", "content": "analyze Berserk"},
            {"role": "assistant", "content": [{"type": "text", "text": "Starting..."}]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
            },
        ]
        state = SessionState(
            session_id="s-resume1",
            messages=saved_messages,
            user_input="analyze Berserk",
        )

        # Simulate REPL wiring
        conversation = ConversationContext()
        conversation.messages = list(state.messages)

        assert len(conversation.messages) == 3
        assert conversation.messages[0]["role"] == "user"
        assert conversation.messages[0]["content"] == "analyze Berserk"

    def test_restored_conversation_accepts_new_messages(self) -> None:
        """After restore, new messages can be added normally."""
        saved = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous answer"},
        ]
        conversation = ConversationContext()
        conversation.messages = list(saved)

        # Add new message after restore
        conversation.add_user_message("follow-up question")
        assert len(conversation.messages) == 3
        assert conversation.messages[-1]["content"] == "follow-up question"


class TestHandleCommandResumeReturn:
    """_handle_command returns 3-tuple with resume state."""

    def test_handle_command_returns_three_tuple(self) -> None:
        """Non-resume commands return None as third element."""
        from core.cli.__init__ import _handle_command

        result = _handle_command("/help", "", False)
        assert len(result) == 3
        should_break, verbose, resume_state = result
        assert resume_state is None
