"""Session Checkpoint — save/restore agentic loop state for resume.

Context Layer C3: "What are we doing right now?"

Persists session state to .geode/session/{id}/ so that:
- Sessions can be resumed after interruption
- Core results settle into C2 (Journal) on completion
- Old checkpoints are auto-cleaned after 72 hours
"""

from __future__ import annotations

import fcntl
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.memory.atomic_write import atomic_write_json
from core.tools.computer_observation import sanitize_computer_payload
from core.tools.personal_data import sanitize_personal_data_payload

log = logging.getLogger(__name__)


def _get_default_session_dir() -> Path:
    from core.paths import resolve_sessions_dir

    return resolve_sessions_dir()


DEFAULT_SESSION_DIR = _get_default_session_dir()
CLEANUP_AGE_HOURS = 72
# Transitions-ledger retention bound (rows kept by cleanup()).
_LEDGER_MAX_ROWS = 10_000


class SessionStatus(StrEnum):
    """Closed session-status space with an enforced transition graph.

    - ACTIVE: written by every per-turn ``save()`` — the session may take
      more turns.
    - PAUSED: a one-shot surface parked the session awaiting operator
      input (pending ask); resumable.
    - COMPLETED: clean finish (REPL exit, one-shot run, ask continuation,
      gateway context exhaustion); ``cleanup()`` may remove it.
    - ERROR: a one-shot run died (timeout / unhandled exception).

    Transitions go through :meth:`SessionCheckpoint.transition` against
    ``_LEGAL_TRANSITIONS``; the terminal states re-enter ACTIVE only via
    the explicit :meth:`SessionCheckpoint.reopen` edge. Full graph, owners,
    and accepted gaps: ``docs/architecture/session-state-machine.md``.
    """

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"


# The session automaton's transition function. Terminal states have no
# outgoing edges here — ``reopen()`` is the single deliberate exception.
_LEGAL_TRANSITIONS: dict[SessionStatus, frozenset[SessionStatus]] = {
    SessionStatus.ACTIVE: frozenset(
        {SessionStatus.ACTIVE, SessionStatus.PAUSED, SessionStatus.COMPLETED, SessionStatus.ERROR}
    ),
    SessionStatus.PAUSED: frozenset(
        {SessionStatus.ACTIVE, SessionStatus.PAUSED, SessionStatus.COMPLETED, SessionStatus.ERROR}
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.ERROR: frozenset(),
}


def normalize_status(raw: Any) -> SessionStatus:
    """Coerce a persisted status string into the closed state space.

    Unknown values coerce to ERROR with a warning — an out-of-alphabet
    status means some writer bypassed the transition primitives.
    """
    try:
        return SessionStatus(str(raw))
    except ValueError:
        log.warning("Unknown session status %r — coercing to ERROR", raw)
        return SessionStatus.ERROR


@dataclass
class SessionState:
    """Serializable session checkpoint."""

    session_id: str
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    round_idx: int = 0
    model: str = ""
    provider: str = "anthropic"
    status: str = SessionStatus.ACTIVE  # see SessionStatus
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_log: list[dict[str, Any]] = field(default_factory=list)
    cognitive_state: dict[str, Any] = field(default_factory=dict)
    system_prompt_hash: str = ""
    user_input: str = ""  # original user request for context
    # Guard counters the messages don't carry (overthinking streak, LLM
    # retry counter, diversity tracker, convergence detector) — written by
    # ``_lifecycle.collect_guard_state``, restored by ``restore_loop_state``.
    loop_guards: dict[str, Any] = field(default_factory=dict)


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

    @property
    def session_dir(self) -> Path:
        """Directory backing this checkpoint store."""
        return self._dir

    def save(self, state: SessionState) -> None:
        """Save session checkpoint. Overwrites previous checkpoint for same ID.

        Phase 1b (Hermes absorption) flips the SoT to the SQLite
        ``messages`` table. The JSON ``messages.json`` and ``tools.json``
        are kept as a hot cache (so old offline tooling that reads them
        still works) but no longer carry truncated state — the DB is now
        the only place that has the full conversation.
        """
        state.updated_at = time.time()
        # The persisted alphabet is closed — a caller-supplied junk status
        # never reaches disk (it coerces to ERROR with a warning).
        incoming = normalize_status(state.status)
        state.status = str(incoming)
        session_path = self._dir / state.session_id
        session_path.mkdir(parents=True, exist_ok=True)

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
            "cognitive_state": state.cognitive_state,
            "loop_guards": state.loop_guards,
        }
        state_file = session_path / "state.json"

        with self._status_lock():
            current = self.current_status(state.session_id)
            if current in (SessionStatus.COMPLETED, SessionStatus.ERROR):
                # Terminal-state writes are an implicit reopen — tolerated
                # (losing a resumed conversation is worse than a noisy edge)
                # but warned, so a writer that bypassed reopen() stays
                # visible.
                log.warning(
                    "save() on terminal session %s (%s) — implicit reopen; "
                    "resume surfaces should call reopen() explicitly",
                    state.session_id,
                    current,
                )
                self._record_transition(
                    state.session_id,
                    "implicit_reopen",
                    from_status=current,
                    to_status=incoming,
                )
            elif current != incoming:
                # Status-changing save (absent -> active, paused -> active on
                # a resume turn). Steady-state ACTIVE -> ACTIVE saves are NOT
                # ledgered — one row per round would be noise, not signal.
                self._record_transition(
                    state.session_id, "save", from_status=current, to_status=incoming
                )
            # Write state.json (metadata) inside the lock so a concurrent
            # transition cannot interleave its read-check-write with ours.
            atomic_write_json(state_file, data, indent=2)

        self._sync_cognitive_state_to_db(state)
        personal_safe = sanitize_personal_data_payload(
            {
                "messages": sanitize_computer_payload(state.messages),
                "tool_log": sanitize_computer_payload(state.tool_log),
            }
        )
        persisted_state = replace(
            state,
            messages=personal_safe["messages"],
            tool_log=personal_safe["tool_log"],
        )

        # Phase 1b: SoT lives in SQLite ``messages`` table. Mirror the
        # *full* message list into the DB **first** so a JSON-only failure
        # below (disk full, write race) cannot leave the SoT with a stale
        # message count.
        self._sync_messages_to_db(persisted_state)

        # Write messages.json as a hot cache (full list, no trim). Old
        # offline tooling can still read this; the runtime ``load()`` path
        # prefers the DB.
        msg_file = session_path / "messages.json"
        atomic_write_json(msg_file, persisted_state.messages)

        # Write tools.json hot cache when tool log exists. The structured
        # ``tool_calls`` column on each ``messages`` row is now the SoT,
        # so this is a convenience copy only.
        if persisted_state.tool_log:
            tools_file = session_path / "tools.json"
            atomic_write_json(tools_file, persisted_state.tool_log[-50:])

        # Update active.json pointer
        self._dir.mkdir(parents=True, exist_ok=True)
        active_file = self._dir / "active.json"
        atomic_write_json(
            active_file,
            {"session_id": state.session_id, "updated_at": state.updated_at},
            indent=2,
        )

        # Sync session metadata to SQLite index for fast query (GAP 3).
        self._sync_to_index(state, len(state.messages))

    def load(self, session_id: str) -> SessionState | None:
        """Load a session checkpoint. Returns None if not found.

        Phase 1b — read order:
            1. ``state.json`` for metadata (always; the DB ``sessions``
               table mirrors this but the JSON keeps the user-input and
               status fields so old offline tooling still works).
            2. ``messages`` table (DB) for the full conversation. This is
               the new SoT.
            3. ``messages.json`` only when the DB cannot answer
               authoritatively for this session — happens for sessions
               written before the v3→v4 migration had a chance to run,
               and for sessions whose DB write raced with the JSON write.
            4. ``tools.json`` for the tool log (kept JSON-only; the DB
               ``messages.tool_calls`` column carries per-message tool
               metadata but does not subsume the loop's tool_log shape).
        """
        session_path = self._dir / session_id
        state_file = session_path / "state.json"
        if not state_file.exists():
            return None

        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))

            msg_file = session_path / "messages.json"
            state_updated_at_raw = data.get("updated_at")
            state_updated_at = (
                float(state_updated_at_raw)
                if isinstance(state_updated_at_raw, (int, float))
                else None
            )

            messages = self._load_messages_from_db(
                session_id,
                state_updated_at=state_updated_at,
                msg_file=msg_file,
            )
            if messages is None:
                if msg_file.exists():
                    messages = json.loads(msg_file.read_text(encoding="utf-8"))
                else:
                    messages = []

            tool_log = []
            tools_file = session_path / "tools.json"
            if tools_file.exists():
                tool_log = json.loads(tools_file.read_text(encoding="utf-8"))

            cognitive_state = self._load_cognitive_state_from_db(session_id)
            if cognitive_state is None:
                cognitive_state = data.get("cognitive_state", {})
            if not isinstance(cognitive_state, dict):
                cognitive_state = {}

            return SessionState(
                session_id=data["session_id"],
                created_at=data.get("created_at", 0),
                updated_at=data.get("updated_at", 0),
                round_idx=data.get("round_idx", 0),
                model=data.get("model", ""),
                provider=data.get("provider", "anthropic"),
                status=normalize_status(data.get("status", SessionStatus.PAUSED)),
                messages=messages,
                tool_log=tool_log,
                cognitive_state=cognitive_state,
                system_prompt_hash=data.get("system_prompt_hash", ""),
                user_input=data.get("user_input", ""),
                loop_guards=(
                    data["loop_guards"] if isinstance(data.get("loop_guards"), dict) else {}
                ),
            )
        except (json.JSONDecodeError, KeyError, OSError) as e:
            log.warning("Failed to load session %s: %s", session_id, e)
            return None

    def _load_messages_from_db(
        self,
        session_id: str,
        *,
        state_updated_at: float | None = None,
        msg_file: Path | None = None,
    ) -> list[dict[str, Any]] | None:
        """Read the full message history from the SQLite ``messages`` table.

        Returns ``None`` when the DB cannot answer authoritatively so the
        caller can fall back to JSON. A valid DB result may be an empty list:
        after Phase 1b an explicit zero-message save must not resurrect a
        stale ``messages.json`` cache.
        """
        db_path = self._dir / "sessions.db"
        if not db_path.exists():
            return None

        try:
            from core.memory.session_manager import SessionManager

            mgr = SessionManager(db_path)
            try:
                messages = mgr.get_messages(session_id)
                if messages:
                    return messages

                meta = mgr.get(session_id)
                if meta and meta.message_count == 0:
                    return []
                if msg_file is None or not msg_file.exists():
                    return []
                if state_updated_at is not None:
                    try:
                        if msg_file.stat().st_mtime < state_updated_at:
                            return []
                    except OSError:
                        return []
                return None
            finally:
                mgr.close()
        except Exception:
            log.debug("DB-first message load failed for %s", session_id, exc_info=True)
            return None

    @contextmanager
    def _status_lock(self) -> Iterator[None]:
        """Cross-process serialization for status read-check-write sections.

        Same fcntl pattern as ``PendingAskStore._locked`` — the daemon and a
        concurrent CLI process must not interleave a transition's
        read-check-write (a lost COMPLETED write would silently resurrect a
        finished machine).
        """
        self._dir.mkdir(parents=True, exist_ok=True)
        lock_path = self._dir / ".status.lock"
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _record_transition(
        self,
        session_id: str,
        edge: str,
        *,
        from_status: SessionStatus | None,
        to_status: SessionStatus | None,
    ) -> None:
        """Append one row to the transitions ledger (observability).

        ``<sessions>/transitions.jsonl`` is the automaton's audit trail:
        every legal edge, reopen, implicit reopen, and REFUSED attempt
        lands here as one bounded structured record, so "how did this
        session get into this state" is answerable after the fact.
        Best-effort: ledger failure never blocks a transition.
        """
        try:
            from core.memory.atomic_write import append_jsonl

            append_jsonl(
                self._dir / "transitions.jsonl",
                {
                    "ts": time.time(),
                    "session_id": session_id,
                    "edge": edge,
                    "from": str(from_status) if from_status else None,
                    "to": str(to_status) if to_status else None,
                },
            )
        except Exception:
            log.debug("Transition ledger append failed", exc_info=True)

    def current_status(self, session_id: str) -> SessionStatus | None:
        """Read one session's persisted status (None when absent)."""
        state_file = self._dir / session_id / "state.json"
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        return normalize_status(data.get("status", SessionStatus.ACTIVE))

    def _write_status(self, session_id: str, status: SessionStatus) -> None:
        """Unvalidated status write (both SoTs) — callers go through
        :meth:`transition` / :meth:`reopen`; never call this directly.

        Updates BOTH SoTs: ``state.json`` and the SQLite index row —
        ``geode session list`` reads the index first, so a JSON-only write
        would keep showing parked/finished sessions as active.
        """
        state_file = self._dir / session_id / "state.json"
        if not state_file.exists():
            return
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            data["status"] = str(status)
            data["updated_at"] = time.time()
            atomic_write_json(state_file, data, indent=2)
        except (json.JSONDecodeError, OSError):
            pass
        try:
            from core.memory.session_manager import SessionManager

            mgr = SessionManager(self._dir / "sessions.db")
            try:
                mgr.update_status(session_id, str(status))
            finally:
                mgr.close()
        except Exception:
            log.debug("SQLite status sync failed for %s", session_id, exc_info=True)

    def transition(self, session_id: str, to: SessionStatus) -> bool:
        """Apply one edge of the session automaton.

        Returns True when the edge is legal and written. An illegal edge
        (e.g. writing over a terminal COMPLETED/ERROR state) is refused
        with a warning — the fail-loud signal that a writer bypassed the
        graph; re-entering a terminal state goes through :meth:`reopen`.
        """
        with self._status_lock():
            current = self.current_status(session_id)
            if current is None:
                return False
            if to not in _LEGAL_TRANSITIONS[current]:
                log.warning(
                    "Illegal session transition %s -> %s refused (session=%s); "
                    "terminal states re-enter only via reopen()",
                    current,
                    to,
                    session_id,
                )
                self._record_transition(session_id, "refused", from_status=current, to_status=to)
                return False
            self._write_status(session_id, to)
            self._record_transition(session_id, "transition", from_status=current, to_status=to)
            return True

    def reopen(self, session_id: str) -> bool:
        """Explicit terminal -> ACTIVE edge (resume-by-id surfaces).

        No-op success when the session is already non-terminal; False when
        the session is absent.
        """
        with self._status_lock():
            current = self.current_status(session_id)
            if current is None:
                return False
            if current in (SessionStatus.COMPLETED, SessionStatus.ERROR):
                log.info("Session %s reopened (%s -> active)", session_id, current)
                self._write_status(session_id, SessionStatus.ACTIVE)
                self._record_transition(
                    session_id, "reopen", from_status=current, to_status=SessionStatus.ACTIVE
                )
        return True

    def mark_completed(self, session_id: str) -> None:
        """Mark a session as completed (no longer resumable)."""
        if self.transition(session_id, SessionStatus.COMPLETED):
            # Clear active pointer if it points to this session
            self._clear_active_if_matches(session_id)

    def mark_paused(self, session_id: str) -> None:
        """Mark a session as paused — parked awaiting operator input."""
        self.transition(session_id, SessionStatus.PAUSED)

    def mark_error(self, session_id: str) -> None:
        """Mark a session as errored (one-shot run died; not resumable)."""
        self.transition(session_id, SessionStatus.ERROR)

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

        # Transitions-ledger retention — the ledger lives in the sessions
        # ROOT (not a session dir), so directory removal below never prunes
        # it. Keep the newest rows only.
        ledger = self._dir / "transitions.jsonl"
        try:
            if ledger.exists():
                lines = ledger.read_text(encoding="utf-8").splitlines()
                if len(lines) > _LEDGER_MAX_ROWS:
                    from core.memory.atomic_write import atomic_write_text

                    atomic_write_text(ledger, "\n".join(lines[-_LEDGER_MAX_ROWS:]) + "\n")
        except OSError:
            log.debug("Transition ledger retention failed", exc_info=True)

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

    def _sync_messages_to_db(self, state: SessionState) -> None:
        """Phase 1a: mirror ``state.messages`` into the messages table.

        Independent of ``_sync_to_index`` — uses a separate transaction so
        a failure here does not roll back metadata. JSON above remains
        authoritative; a WARN log surfaces DB-side problems without
        disturbing the resume path.
        """
        try:
            from core.memory.session_manager import SessionManager

            mgr = SessionManager(self._dir / "sessions.db")
            try:
                mgr.upsert_messages(
                    state.session_id,
                    state.messages,
                    default_timestamp=state.updated_at,
                )
            finally:
                mgr.close()
        except Exception:
            log.warning(
                "Failed to mirror messages to sessions.db (session=%s); JSON checkpoint retained.",
                state.session_id,
                exc_info=True,
            )

    def _sync_cognitive_state_to_db(self, state: SessionState) -> None:
        """Mirror ``state.cognitive_state`` into the central cognitive store."""
        if not state.cognitive_state:
            return
        try:
            from core.memory.cognitive_state_store import CognitiveStateStore

            store = CognitiveStateStore(self._dir / "sessions.db")
            try:
                store.save_latest(
                    state.session_id,
                    state.cognitive_state,
                    updated_at=state.updated_at,
                )
            finally:
                store.close()
        except Exception:
            log.warning(
                "Failed to mirror cognitive_state to sessions.db "
                "(session=%s); JSON cache retained.",
                state.session_id,
                exc_info=True,
            )

    def _load_cognitive_state_from_db(self, session_id: str) -> dict[str, Any] | None:
        """Read the latest cognitive snapshot from the central store."""
        db_path = self._dir / "sessions.db"
        if not db_path.exists():
            return None
        try:
            from core.memory.cognitive_state_store import CognitiveStateStore

            store = CognitiveStateStore(db_path)
            try:
                return store.load_latest(session_id)
            finally:
                store.close()
        except Exception:
            log.debug("DB-first cognitive state load failed for %s", session_id, exc_info=True)
            return None

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
