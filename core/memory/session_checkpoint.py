"""Session Checkpoint — save/restore agentic loop state for resume.

Context Layer C3: "What are we doing right now?"

Persists session state to ~/.geode/projects/{id}/sessions/{id}/ so that:
- Sessions can be resumed after interruption
- Core results settle into C2 (Journal) on completion
- Old checkpoints are auto-cleaned after 72 hours
"""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import logging
import re
import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from typing import Any

from core.config.session import SessionModelConfig
from core.memory.atomic_write import atomic_write_json
from core.tools.computer_observation import sanitize_computer_payload
from core.tools.personal_data import sanitize_personal_data_payload

log = logging.getLogger(__name__)


def _get_default_session_dir() -> Path:
    from core.paths import get_project_sessions_dir

    return get_project_sessions_dir()


DEFAULT_SESSION_DIR = _get_default_session_dir()
CLEANUP_AGE_HOURS = 72
# Transitions-ledger retention bound (rows kept by cleanup()).
_LEDGER_MAX_ROWS = 10_000
# R6.9 fork bounds: copied history window (ConversationContext's default
# 200-turn safety net) and the in-progress publication marker.
FORK_MAX_MESSAGES = 400
_FORK_PENDING_MARKER = ".fork-pending"
_SESSION_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


# Sessions directories already swept for crashed forks in this process. A
# re-sweep is idempotent, so the set is simply reset when it reaches its bound.
_ORPHAN_SWEPT_DIRS: set[str] = set()
_ORPHAN_SWEPT_MAX_DIRS = 256


def _remove_fork_dir(destination: Path) -> bool:
    """Remove an unpublished fork's directory, pending marker last.

    The marker goes only after every other entry, so a partial failure
    (permissions, I/O, a full disk) leaves it on disk without writing
    anything: any later sweep, in this process or the next, finds the
    leftover again. If only the final rmdir fails, the marker is written back
    (best effort). Returns whether the directory is gone.
    """
    marker = destination / _FORK_PENDING_MARKER
    try:
        for entry in destination.iterdir():
            if entry == marker:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        marker.unlink(missing_ok=True)
        destination.rmdir()
    except OSError:
        if destination.is_dir() and not marker.exists():
            # Only the final rmdir failed: an unmarked empty directory would
            # never be found again, so mark it once more (best effort).
            with suppress(OSError):
                marker.touch()
        log.warning(
            "Unpublished fork directory was not fully removed; later sweeps retry it: %s",
            destination,
            exc_info=True,
        )
        return False
    return True


class SessionForkError(ValueError):
    """A fork was refused before any destination session became visible."""


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _tool_links(message: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (tool-call ids, tool-result ids) in one provider-neutral message.

    Duplicates are kept so the caller can refuse them. The ``tool_calls``
    column the SQLite transcript mirrors from content blocks is read only when
    the message has no ``tool_use`` blocks of its own, so a round-tripped
    message does not name each call twice.
    """
    calls: list[str] = []
    results: list[str] = []
    content = message.get("content")
    if isinstance(content, list):
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id"):
                calls.append(str(block["id"]))
            elif block.get("type") == "tool_result" and block.get("tool_use_id"):
                results.append(str(block["tool_use_id"]))
    if not calls:
        for call in message.get("tool_calls") or ():
            if isinstance(call, dict) and call.get("id"):
                calls.append(str(call["id"]))
    if message.get("role") == "tool" and message.get("tool_call_id"):
        results.append(str(message["tool_call_id"]))
    return calls, results


def completed_turn_boundaries(messages: list[Any]) -> list[int]:
    """Return every index ``n`` where ``messages[:n]`` ends a completed turn.

    A completed turn ends with an assistant message that makes no tool call
    while every earlier tool call already has its result, so a prefix cut at
    such an index never leaves a pending call or an orphaned result. A result
    for a call that is not open, or a reused call ID, leaves the history
    unbalanced: no later index is a boundary.
    """
    open_calls: set[str] = set()
    seen_calls: set[str] = set()
    boundaries: list[int] = []
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            continue  # transcript placeholders carry no turn or tool structure
        calls, results = _tool_links(message)
        for result in results:
            if result not in open_calls:
                return boundaries  # orphan or duplicate result
            open_calls.remove(result)
        for call in calls:
            if call in seen_calls:
                return boundaries  # reused call ID
            seen_calls.add(call)
            open_calls.add(call)
        if message.get("role") == "assistant" and not calls and not open_calls:
            boundaries.append(index + 1)
    return boundaries


def _balanced_window(window: list[Any]) -> bool:
    """Whether ``window`` alone pairs every tool call with exactly one result.

    Checked independently of :func:`completed_turn_boundaries` so a copied
    window never carries an orphaned result, a duplicate, or an open call.
    """
    open_calls: set[str] = set()
    seen_calls: set[str] = set()
    for message in window:
        if not isinstance(message, dict):
            continue
        calls, results = _tool_links(message)
        for result in results:
            if result not in open_calls:
                return False
            open_calls.remove(result)
        for call in calls:
            if call in seen_calls:
                return False
            seen_calls.add(call)
            open_calls.add(call)
    return not open_calls


def _messages_digest(messages: list[Any]) -> str:
    """Digest of the role/content sequence a checkpoint commits.

    Computed over the fields the SQLite transcript round-trips unchanged, so
    the committed ``state.json`` can name exactly which messages it covers.
    """
    shape = [
        [message.get("role"), message.get("content")]
        for message in messages
        if isinstance(message, dict)
    ]
    encoded = json.dumps(shape, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _fork_history(message: dict[str, Any]) -> dict[str, Any]:
    """Copy one historical message without its effect-admission anchors."""
    copied = copy.deepcopy(message)
    metadata = copied.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("effect_operations", None)
    return copied


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
    pending_verification: dict[str, Any] = field(default_factory=dict)
    model_settings: SessionModelConfig | None = None
    # Durable R6.5 child marker; empty for root sessions and legacy records.
    parent_session_id: str = ""
    # R6.9 fork provenance (source session, generation, cut). Written once at
    # fork publication and carried forward by later saves; empty when absent.
    lineage: dict[str, Any] = field(default_factory=dict)


class SessionCheckpoint:
    """Manage session checkpoints in ~/.geode/projects/{id}/sessions/.

    Usage::

        cp = SessionCheckpoint()
        cp.save(SessionState(session_id="s1", messages=[...], round_idx=3))
        state = cp.load("s1")
        active = cp.list_resumable()
        cp.cleanup()
    """

    def __init__(self, session_dir: Path | str | None = None) -> None:
        if session_dir is None and _get_default_session_dir() == DEFAULT_SESSION_DIR:
            from core.paths import admit_project_data_dir

            admit_project_data_dir()
        self._dir = Path(session_dir) if session_dir else DEFAULT_SESSION_DIR

    @property
    def session_dir(self) -> Path:
        """Directory backing this checkpoint store."""
        return self._dir

    def save(self, state: SessionState, *, strict_messages: bool = False) -> None:
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
            "pending_verification": state.pending_verification,
        }
        if state.model_settings is not None:
            data["model_settings"] = state.model_settings.model_dump()
        state_file = session_path / "state.json"

        with self._status_lock():
            current = self.current_status(state.session_id)
            persisted = self._persisted_header(state.session_id)
            # Lineage is write-once publication metadata, not loop state.
            lineage = state.lineage or persisted.get("lineage")
            if isinstance(lineage, dict) and lineage:
                data["lineage"] = lineage
                state = replace(state, lineage=lineage)
            # The R6.5 child marker is durable ownership: a save from a loop
            # that lost it (a resume path, a legacy writer) never clears it.
            parent = state.parent_session_id or persisted.get("parent_session_id")
            if isinstance(parent, str) and parent:
                data["parent_session_id"] = parent
                state = replace(state, parent_session_id=parent)
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
            # full message list before publishing the metadata commit point.
            self._sync_messages_to_db(persisted_state, strict=strict_messages)

            # JSON message/tool files are compatibility caches, not the SoT.
            msg_file = session_path / "messages.json"
            atomic_write_json(msg_file, persisted_state.messages)
            if persisted_state.tool_log:
                tools_file = session_path / "tools.json"
                atomic_write_json(tools_file, persisted_state.tool_log[-50:])

            self._dir.mkdir(parents=True, exist_ok=True)
            active_file = self._dir / "active.json"
            atomic_write_json(
                active_file,
                {"session_id": state.session_id, "updated_at": state.updated_at},
                indent=2,
            )
            self._sync_to_index(state, len(state.messages))

            # state.json is the guard/checkpoint commit marker. Publish it last
            # so a failed save cannot make resume observe uncommitted plan state;
            # the digest binds it to the exact messages this save wrote.
            data["messages_digest"] = _messages_digest(persisted_state.messages)
            atomic_write_json(state_file, data, indent=2)

    def read_header(self, session_id: str) -> dict[str, Any] | None:
        """Return one session's committed ``state.json`` header, or None.

        Only a well-formed id naming a real (non-symlinked) directory of this
        sessions dir resolves; a guessed path or id elsewhere never does.
        """
        if not _SESSION_ID_RE.fullmatch(session_id):
            return None
        session_path = self._dir / session_id
        state_file = session_path / "state.json"
        if session_path.is_symlink() or state_file.is_symlink() or not state_file.is_file():
            return None
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def _persisted_header(self, session_id: str) -> dict[str, Any]:
        state_file = self._dir / session_id / "state.json"
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def fork_completed_turn(
        self,
        source_session_id: str,
        *,
        forked_by: str,
        allow_in_flight_tail: bool = False,
        max_messages: int = FORK_MAX_MESSAGES,
    ) -> SessionState:
        """Publish a new paused session from one frozen completed-turn cut.

        Every checkpoint write holds ``_status_lock``, so the source read here
        is one committed checkpoint. The copied window starts and ends at
        completed-turn boundaries. Without ``allow_in_flight_tail`` the
        source's persisted tail must itself be such a boundary; a caller may
        set it only while it owns the source's in-flight turn (self-fork).

        The destination is invisible until ``state.json`` commits: messages
        rows and caches land first under a pending marker, a failure removes
        only those owned rows/files, and a crash leaves a marker that the next
        fork or :meth:`cleanup` removes under the same lock. Source files,
        rows, and events are only read.
        """
        if not _SESSION_ID_RE.fullmatch(source_session_id):
            raise SessionForkError("invalid source session id")
        source_path = self._dir / source_session_id
        fork_id = f"s-{uuid.uuid4().hex[:12]}"
        with self._status_lock():
            self._remove_orphan_forks_locked()
            # Checked under the lock, immediately before the read: every file a
            # load may follow must be a regular file of this sessions dir.
            if source_path.is_symlink() or any(
                (source_path / name).is_symlink()
                for name in ("state.json", "messages.json", "tools.json")
            ):
                raise SessionForkError("refusing a symlinked source session path")
            header = self.read_header(source_session_id)
            source = self.load(source_session_id)
            if source is None or header is None:
                raise SessionForkError(f"unknown source session: {source_session_id}")
            committed = header.get("messages_digest")
            if not isinstance(committed, str):
                raise SessionForkError(
                    "source checkpoint predates fork verification; complete a turn first"
                )
            if committed != _messages_digest(source.messages):
                raise SessionForkError(
                    "source messages do not match its last committed checkpoint; "
                    "fork after the source saves again"
                )
            if source.pending_verification:
                raise SessionForkError("source has a pending external verification")
            boundaries = completed_turn_boundaries(source.messages)
            if not boundaries or (
                not allow_in_flight_tail and boundaries[-1] != len(source.messages)
            ):
                raise SessionForkError(
                    "source has an in-flight or incomplete turn; fork after it completes"
                )
            cut = boundaries[-1]
            floor = max(0, cut - max_messages)
            start = (
                0
                if floor == 0
                else next(
                    (
                        index
                        for index in [0, *boundaries]
                        if floor <= index < cut
                        and isinstance(source.messages[index], dict)
                        and source.messages[index].get("role") == "user"
                    ),
                    None,
                )
            )
            if start is None:
                raise SessionForkError("no completed-turn boundary fits the fork history bound")
            window = source.messages[start:cut]
            if not _balanced_window(window):
                raise SessionForkError("source history has unbalanced tool calls; fork refused")
            from core.observability.session_timeline import SessionEventStore

            now = time.time()
            lineage = {
                "kind": "fork",
                "source_session_id": source_session_id,
                "source_generation": SessionEventStore(self._dir / "sessions.db").latest_generation(
                    source_session_id
                ),
                "source_message_count": cut,
                "source_window_start": start,
                "source_updated_at": source.updated_at,
                "source_digest": hashlib.sha256(
                    json.dumps(window, sort_keys=True, ensure_ascii=False, default=str).encode()
                ).hexdigest(),
                "forked_at": now,
                "forked_by": forked_by,
            }
            fork = SessionState(
                session_id=fork_id,
                created_at=now,
                updated_at=now,
                model=source.model,
                provider=source.provider,
                model_settings=source.model_settings,
                status=str(SessionStatus.PAUSED),
                messages=[_fork_history(message) for message in window],
                user_input=source.user_input,
                # A restriction carries forward; nothing else in the guards does.
                loop_guards=(
                    {"reflection_requires_redaction": True}
                    if source.loop_guards.get("reflection_requires_redaction") is True
                    else {}
                ),
                lineage=lineage,
            )
            destination = self._dir / fork_id
            destination.mkdir()
            try:
                (destination / _FORK_PENDING_MARKER).write_text(source_session_id, encoding="utf-8")
                self._sync_messages_to_db(fork, strict=True)
                atomic_write_json(destination / "messages.json", fork.messages)
                data = {
                    "session_id": fork_id,
                    "created_at": now,
                    "updated_at": now,
                    "round_idx": 0,
                    "model": fork.model,
                    "provider": fork.provider,
                    "status": fork.status,
                    "system_prompt_hash": "",
                    "user_input": fork.user_input,
                    "cognitive_state": {},
                    "loop_guards": fork.loop_guards,
                    "pending_verification": {},
                    "lineage": lineage,
                    "messages_digest": _messages_digest(fork.messages),
                }
                if fork.model_settings is not None:
                    data["model_settings"] = fork.model_settings.model_dump()
                # Commit point: the fork becomes visible only with state.json.
                atomic_write_json(destination / "state.json", data, indent=2)
            except BaseException:
                self._discard_fork_locked(fork_id)
                raise
            (destination / _FORK_PENDING_MARKER).unlink(missing_ok=True)
            self._sync_to_index(fork, len(fork.messages))
            self._record_transition(
                fork_id, "fork", from_status=None, to_status=SessionStatus.PAUSED
            )
        return fork

    def sweep_orphan_forks_once(self) -> int:
        """Remove crashed fork publications once per process for this directory.

        Called at runtime startup so an interrupted fork's rows never stay
        searchable until some later fork happens to sweep them.
        """
        key = str(self._dir.resolve())
        if key in _ORPHAN_SWEPT_DIRS or not self._dir.is_dir():
            return 0
        with self._status_lock():
            removed, failed = self._remove_orphan_forks_locked()
        # Any failed discard keeps this directory unswept, whether or not its
        # marker survived, so every later call in this process retries it.
        if not failed:
            if len(_ORPHAN_SWEPT_DIRS) >= _ORPHAN_SWEPT_MAX_DIRS:
                _ORPHAN_SWEPT_DIRS.clear()
            _ORPHAN_SWEPT_DIRS.add(key)
        return removed

    def _remove_orphan_forks_locked(self) -> tuple[int, int]:
        """Remove forks whose publisher died before commit (caller holds the lock).

        A live publisher holds ``_status_lock`` for the whole publication, so a
        marker observed under the lock belongs to a dead or failed publisher.
        Returns ``(removed, failed)`` discard counts.
        """
        # ponytail: O(session dirs) scan per fork; index markers if dirs reach 10^5.
        removed = failed = 0
        for marker in self._dir.glob(f"*/{_FORK_PENDING_MARKER}"):
            session_dir = marker.parent
            if session_dir.is_symlink():
                continue
            if (session_dir / "state.json").exists():
                marker.unlink(missing_ok=True)
                continue
            if self._discard_fork_locked(session_dir.name):
                removed += 1
            else:
                failed += 1
        return removed, failed

    def _discard_fork_locked(self, fork_id: str) -> bool:
        """Delete only an unpublished fork's own rows, index entry, and directory.

        Rows go first: the directory holds the pending marker, the only record
        a later sweep retries from, so it outlives every row it accounts for.
        Returns whether the fork is gone.
        """
        destination = self._dir / fork_id
        try:
            from core.memory.session_manager import SessionManager

            with closing(SessionManager(self._dir / "sessions.db")) as mgr:
                mgr.upsert_messages(fork_id, [])
                mgr.delete(fork_id)
        except Exception:
            log.warning(
                "Unpublished fork rows were not removed; marker kept for retry (fork=%s)",
                fork_id,
                exc_info=True,
            )
            return False
        return not destination.is_dir() or destination.is_symlink() or _remove_fork_dir(destination)

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
            # Absence is legacy; a present invalid record must never fall back
            # to today's defaults or partially restore historical identity.
            model_settings = (
                SessionModelConfig.model_validate(data["model_settings"])
                if "model_settings" in data
                else None
            )

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

            lineage = data.get("lineage")
            return SessionState(
                session_id=data["session_id"],
                parent_session_id=str(data.get("parent_session_id") or ""),
                lineage=lineage if isinstance(lineage, dict) else {},
                created_at=data.get("created_at", 0),
                updated_at=data.get("updated_at", 0),
                round_idx=data.get("round_idx", 0),
                model=data.get("model", ""),
                provider=data.get("provider", "anthropic"),
                model_settings=model_settings,
                status=normalize_status(data.get("status", SessionStatus.PAUSED)),
                messages=messages,
                tool_log=tool_log,
                cognitive_state=cognitive_state,
                system_prompt_hash=data.get("system_prompt_hash", ""),
                user_input=data.get("user_input", ""),
                loop_guards=(
                    data["loop_guards"] if isinstance(data.get("loop_guards"), dict) else {}
                ),
                pending_verification=(
                    data["pending_verification"]
                    if isinstance(data.get("pending_verification"), dict)
                    else {}
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
        """Persist status before its index projection — callers go through
        :meth:`transition` / :meth:`reopen`; never call this directly.

        Updates ``state.json`` first, then the SQLite index row —
        ``geode session list`` reads the index first, so a JSON-only write
        would keep showing parked/finished sessions as active.
        Propagate authoritative state-file failures before updating projections
        or reporting a successful transition.
        """
        state_file = self._dir / session_id / "state.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        data["status"] = str(status)
        data["updated_at"] = time.time()
        atomic_write_json(state_file, data, indent=2)
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
                self._write_status(session_id, SessionStatus.ACTIVE)
                log.info("Session %s reopened (%s -> active)", session_id, current)
                self._record_transition(
                    session_id, "reopen", from_status=current, to_status=SessionStatus.ACTIVE
                )
        return True

    def mark_completed(self, session_id: str) -> bool:
        """Mark a session as completed (no longer resumable)."""
        transitioned = self.transition(session_id, SessionStatus.COMPLETED)
        if transitioned:
            # Clear active pointer if it points to this session
            self._clear_active_if_matches(session_id)
        return transitioned

    def mark_paused(self, session_id: str) -> bool:
        """Mark a session as paused — parked awaiting operator input."""
        return self.transition(session_id, SessionStatus.PAUSED)

    def mark_error(self, session_id: str) -> bool:
        """Mark a session as errored (one-shot run died; not resumable)."""
        return self.transition(session_id, SessionStatus.ERROR)

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
        with self._status_lock():
            removed, _failed = self._remove_orphan_forks_locked()

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

            with closing(SessionManager(self._dir / "sessions.db")) as mgr:
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
                        parent_session_id=state.parent_session_id,
                        source_session_id=str(state.lineage.get("source_session_id", "")),
                        source_generation=_as_int(state.lineage.get("source_generation")),
                        source_message_count=_as_int(state.lineage.get("source_message_count")),
                    )
                )
        except Exception:
            log.debug("Failed to sync session to SQLite index", exc_info=True)

    def _sync_messages_to_db(self, state: SessionState, *, strict: bool = False) -> None:
        """Phase 1a: mirror ``state.messages`` into the messages table.

        Independent of ``_sync_to_index`` — uses a separate transaction so
        a failure here does not roll back metadata. Ordinary compatibility
        saves retain the JSON fallback; effect boundaries pass ``strict`` so
        the SQLite message SoT cannot silently remain stale.
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
            if strict:
                raise

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
