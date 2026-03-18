"""Session Checkpoint — save/restore agentic loop state for resume.

Context Layer C3: "What are we doing right now?"

Persists session state to .geode/session/{id}/ so that:
- Sessions can be resumed after interruption
- Core results settle into C2 (Journal) on completion
- Old checkpoints are auto-cleaned after 72 hours
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_SESSION_DIR = Path(".geode") / "session"
CHECKPOINT_MAX_MESSAGES = 20  # Context Budget: keep recent N messages
CLEANUP_AGE_HOURS = 72


@dataclass
class SessionState:
    """Serializable session checkpoint."""

    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    round_idx: int = 0
    model: str = ""
    provider: str = "anthropic"
    status: str = "active"  # active | paused | completed | error
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    system_prompt_hash: str = ""
    user_input: str = ""  # original user request for context


class SessionCheckpoint:
    """Manage session checkpoints in .geode/session/.

    Usage::

        cp = SessionCheckpoint()
        cp.save(SessionState(session_id="s1", messages=[...], round_idx=3))
        state = cp.load("s1")
        active = cp.list_resumable()
        cp.cleanup()
    """

    def __init__(self, session_dir: Path | str | None = None) -> None:
        self._dir = Path(session_dir) if session_dir else DEFAULT_SESSION_DIR

    def save(self, state: SessionState) -> None:
        """Save session checkpoint. Overwrites previous checkpoint for same ID."""
        state.updated_at = time.time()
        session_path = self._dir / state.session_id
        session_path.mkdir(parents=True, exist_ok=True)

        # Trim messages to budget
        trimmed = state.messages[-CHECKPOINT_MAX_MESSAGES:]

        data = {
            "session_id": state.session_id,
            "created_at": state.created_at,
            "updated_at": state.updated_at,
            "round_idx": state.round_idx,
            "model": state.model,
            "provider": state.provider,
            "status": state.status,
            "system_prompt_hash": state.system_prompt_hash,
            "user_input": state.user_input,
        }

        # Write state.json (metadata)
        state_file = session_path / "state.json"
        state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        # Write messages.json (conversation, trimmed)
        msg_file = session_path / "messages.json"
        msg_file.write_text(
            json.dumps(trimmed, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

        # Write tools.json (tool call log)
        if state.tool_log:
            tools_file = session_path / "tools.json"
            tools_file.write_text(
                json.dumps(state.tool_log[-50:], ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        # Update active.json pointer
        active_file = self._dir / "active.json"
        self._dir.mkdir(parents=True, exist_ok=True)
        active_file.write_text(
            json.dumps(
                {"session_id": state.session_id, "updated_at": state.updated_at},
                indent=2,
            ),
            encoding="utf-8",
        )

    def load(self, session_id: str) -> SessionState | None:
        """Load a session checkpoint. Returns None if not found."""
        session_path = self._dir / session_id
        state_file = session_path / "state.json"
        if not state_file.exists():
            return None

        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            messages = []
            msg_file = session_path / "messages.json"
            if msg_file.exists():
                messages = json.loads(msg_file.read_text(encoding="utf-8"))

            tool_log = []
            tools_file = session_path / "tools.json"
            if tools_file.exists():
                tool_log = json.loads(tools_file.read_text(encoding="utf-8"))

            return SessionState(
                session_id=data["session_id"],
                created_at=data.get("created_at", 0),
                updated_at=data.get("updated_at", 0),
                round_idx=data.get("round_idx", 0),
                model=data.get("model", ""),
                provider=data.get("provider", "anthropic"),
                status=data.get("status", "paused"),
                messages=messages,
                tool_log=tool_log,
                system_prompt_hash=data.get("system_prompt_hash", ""),
                user_input=data.get("user_input", ""),
            )
        except (json.JSONDecodeError, KeyError, OSError) as e:
            log.warning("Failed to load session %s: %s", session_id, e)
            return None

    def mark_completed(self, session_id: str) -> None:
        """Mark a session as completed (no longer resumable)."""
        session_path = self._dir / session_id
        state_file = session_path / "state.json"
        if not state_file.exists():
            return
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            data["status"] = "completed"
            data["updated_at"] = time.time()
            state_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except (json.JSONDecodeError, OSError):
            pass

        # Clear active pointer if it points to this session
        self._clear_active_if_matches(session_id)

    def list_resumable(self) -> list[SessionState]:
        """List sessions that can be resumed (status=active or paused)."""
        if not self._dir.exists():
            return []

        sessions = []
        for entry in self._dir.iterdir():
            if not entry.is_dir():
                continue
            state = self.load(entry.name)
            if state and state.status in ("active", "paused"):
                sessions.append(state)

        # Sort by updated_at descending (most recent first)
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def cleanup(self, max_age_hours: float = CLEANUP_AGE_HOURS) -> int:
        """Remove completed/old session checkpoints. Returns count removed."""
        if not self._dir.exists():
            return 0

        cutoff = time.time() - (max_age_hours * 3600)
        removed = 0

        for entry in list(self._dir.iterdir()):
            if not entry.is_dir():
                continue
            state = self.load(entry.name)
            if state is None:
                continue
            # Remove completed sessions or sessions older than cutoff
            if state.status == "completed" or state.updated_at < cutoff:
                import shutil

                shutil.rmtree(entry, ignore_errors=True)
                removed += 1

        return removed

    def _clear_active_if_matches(self, session_id: str) -> None:
        active_file = self._dir / "active.json"
        if not active_file.exists():
            return
        try:
            data = json.loads(active_file.read_text(encoding="utf-8"))
            if data.get("session_id") == session_id:
                active_file.unlink(missing_ok=True)
        except (json.JSONDecodeError, OSError):
            pass
