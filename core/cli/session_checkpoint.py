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

from core.utils.atomic_io import atomic_write_json

log = logging.getLogger(__name__)

def _get_default_session_dir() -> Path:
    from core.paths import resolve_sessions_dir

    return resolve_sessions_dir()


DEFAULT_SESSION_DIR = _get_default_session_dir()
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
        atomic_write_json(state_file, data, indent=2)

        # Write messages.json (conversation, trimmed)
        msg_file = session_path / "messages.json"
        atomic_write_json(msg_file, trimmed)

        # Write tools.json (tool call log)
        if state.tool_log:
            tools_file = session_path / "tools.json"
            atomic_write_json(tools_file, state.tool_log[-50:])

        # Update active.json pointer
        self._dir.mkdir(parents=True, exist_ok=True)
        active_file = self._dir / "active.json"
        atomic_write_json(
            active_file,
            {"session_id": state.session_id, "updated_at": state.updated_at},
            indent=2,
        )

        # GAP 3: Sync to SQLite index for fast query
        self._sync_to_index(state, len(trimmed))

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
            atomic_write_json(state_file, data, indent=2)
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

    def _sync_to_index(self, state: SessionState, message_count: int) -> None:
        """Sync session metadata to SQLite index (GAP 3)."""
        try:
            from core.memory.session_manager import SessionManager, SessionMeta

            mgr = SessionManager(self._dir / "sessions.db")
            mgr.upsert(
                SessionMeta(
                    session_id=state.session_id,
                    created_at=state.created_at,
                    updated_at=state.updated_at,
                    status=state.status,
                    model=state.model,
                    provider=state.provider,
                    user_input=state.user_input,
                    round_count=state.round_idx,
                    message_count=message_count,
                )
            )
            mgr.close()
        except Exception:
            log.debug("Failed to sync session to SQLite index", exc_info=True)

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
