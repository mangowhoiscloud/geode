"""Versioned, bounded evaluation/evolution run-event JSONL projection.

Run lifecycle markers are portable artifacts, not resumable conversation
history. Canonical session history lives in ``sessions.db:session_events``.
"""

from __future__ import annotations

import contextvars
import fcntl
import logging
import math
import time
from collections.abc import Iterator
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from typing import Any

from core.observability.run_event import (
    RUN_EVENT_MAX_BYTES,
    RUN_EVENT_SCHEMA_ID,
    RUN_EVENT_SCHEMA_VERSION,
    RunIdentity,
    bound_run_field,
    compact_run_events,
)

log = logging.getLogger(__name__)


_current_run_timeline: contextvars.ContextVar[RunTimeline | None] = contextvars.ContextVar(
    "self_improving_loop_run_timeline",
    default=None,
)


class RunTimeline:
    """Per-run lifecycle projection with stable correlation and schema."""

    def __init__(
        self,
        *,
        session_id: str,
        gen_tag: str,
        component: str,
        path: Path | None = None,
        max_bytes: int = RUN_EVENT_MAX_BYTES,
    ) -> None:
        self.session_id = session_id
        self.gen_tag = gen_tag
        self.component = component
        if path is None:
            from core.paths import GLOBAL_AUTORESEARCH_HANDOFF_DIR

            path = GLOBAL_AUTORESEARCH_HANDOFF_DIR / session_id / "events.jsonl"
        self.path = path
        self._max_bytes = max(1, int(max_bytes))
        self._seq = _last_sequence(path)
        self._write_failed = False

    @property
    def write_failed(self) -> bool:
        """Whether a projection write failed during this process."""
        return self._write_failed

    def last_touched_at(self) -> float | None:
        try:
            return self.path.stat().st_mtime
        except (FileNotFoundError, OSError):
            return None

    def is_stale(self, threshold_s: float, *, now: float | None = None) -> bool:
        touched = self.last_touched_at()
        if touched is None:
            return False
        return ((time.time() if now is None else now) - touched) > threshold_s

    def append(
        self,
        event: str,
        *,
        level: str = "info",
        payload: dict[str, Any] | None = None,
        ts: float | None = None,
        actor_type: str = "orchestrator",
        actor_id: str = "pipeline",
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        task_id: str | None = None,
        turn_id: str = "",
        call_id: str = "",
    ) -> None:
        """Append one redacted run marker to the bounded projection.

        The hidden sidecar lock coordinates ordinals and compaction across
        subprocesses. JSONL is a convenience projection, so I/O failure is
        surfaced through :attr:`write_failed` and logging rather than aborting
        the canonical agent operation.
        """
        from core.observability.session_timeline import bound_session_payload

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_name(f".{self.path.name}.lock")
            with lock_path.open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                lock.seek(0)
                try:
                    shared_seq = int(lock.read().strip() or 0)
                except ValueError:
                    shared_seq = _last_sequence(self.path)
                self._seq = max(self._seq, shared_seq) + 1
                lock.seek(0)
                lock.truncate()
                lock.write(str(self._seq))
                lock.flush()

                body = bound_session_payload(payload or {})
                occurred_at = time.time() if ts is None else float(ts)
                if not math.isfinite(occurred_at):
                    occurred_at = time.time()
                    body["_invalid_occurred_at"] = True
                kind = bound_run_field(event, 256) or "event.unknown"
                session_id = bound_run_field(self.session_id, 256) or "unbound-run"
                record = {
                    "schema_id": RUN_EVENT_SCHEMA_ID,
                    "schema_version": RUN_EVENT_SCHEMA_VERSION,
                    "event_id": sha256(
                        f"{session_id}:{self._seq}:{occurred_at}:{kind}".encode()
                    ).hexdigest()[:32],
                    "occurred_at": occurred_at,
                    # Legacy aliases remain for old readers during the compatibility
                    # window. New readers use occurred_at / ordinal / kind.
                    "ts": occurred_at,
                    "ordinal": self._seq,
                    "seq": self._seq,
                    "session_id": session_id,
                    "turn_id": bound_run_field(turn_id, 256),
                    "call_id": bound_run_field(call_id, 256),
                    "gen_tag": bound_run_field(self.gen_tag, 256),
                    "component": bound_run_field(self.component, 256) or "runtime",
                    "level": bound_run_field(level, 64),
                    "kind": kind,
                    "event": kind,
                    "actor_type": bound_run_field(actor_type, 128),
                    "actor_id": bound_run_field(actor_id, 256),
                    "action": bound_run_field(action or f"pipeline.{kind}", 256),
                    "entity_type": bound_run_field(entity_type or "", 128),
                    "entity_id": bound_run_field(entity_id or "", 256),
                    "task_id": bound_run_field(task_id or "", 256),
                    "payload": body,
                }
                from core.memory.atomic_write import append_jsonl

                append_jsonl(self.path, record)
                if self.path.stat().st_size > self._max_bytes:
                    compact_run_events(
                        self.path,
                        self._max_bytes,
                        identity=RunIdentity(
                            session_id=self.session_id,
                            gen_tag=self.gen_tag,
                            component=self.component,
                        ),
                        ordinal=self._seq,
                    )
        except (OSError, UnicodeError) as exc:
            self._write_failed = True
            log.warning("Run timeline projection failed for %s: %s", self.path, exc)


def current_run_timeline() -> RunTimeline | None:
    return _current_run_timeline.get()


def set_current_run_timeline(
    timeline: RunTimeline | None,
) -> contextvars.Token[RunTimeline | None]:
    return _current_run_timeline.set(timeline)


@contextmanager
def run_timeline_scope(timeline: RunTimeline) -> Iterator[RunTimeline]:
    token = set_current_run_timeline(timeline)
    try:
        yield timeline
    finally:
        _current_run_timeline.reset(token)


def _last_sequence(path: Path) -> int:
    from core.memory.atomic_write import read_jsonl

    rows = read_jsonl(path, tail=1)
    if not rows:
        return 0
    raw = rows[0].get("ordinal", rows[0].get("seq", 0))
    return int(raw) if isinstance(raw, int | float) else 0


def compact_run_timeline(
    path: Path,
    max_bytes: int,
    *,
    session_id: str,
    gen_tag: str,
    component: str,
    ordinal: int,
) -> None:
    """Compatibility wrapper for existing product callers."""
    compact_run_events(
        path,
        max_bytes,
        identity=RunIdentity(session_id=session_id, gen_tag=gen_tag, component=component),
        ordinal=ordinal,
    )


__all__ = [
    "RUN_EVENT_MAX_BYTES",
    "RUN_EVENT_SCHEMA_ID",
    "RUN_EVENT_SCHEMA_VERSION",
    "RunTimeline",
    "compact_run_timeline",
    "current_run_timeline",
    "run_timeline_scope",
    "set_current_run_timeline",
]
