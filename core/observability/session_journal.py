"""Structured per-session journal — P1c self-improving-loop wiring plan.

The session journal is a JSONL artifact that captures discrete events
from one self-improving-loop run (autoresearch or seed-generation). It complements
the run-level ``~/.geode/self-improving-loop/sessions.jsonl`` index (P1a) which
holds exactly one row per run: this module captures the *event stream*
within that run.

Schema (one event per line)::

    {
      "ts": 1731957600.123,
      "session_id": "2026-05-19T1530Z-a1b2c3",
      "gen_tag": "autoresearch-a1b2c3d",
      "component": "autoresearch",
      "level": "info" | "warn" | "error",
      "event": "<short event name>",
      "payload": {...}
    }

Path: ``~/.geode/self-improving-loop/<session_id>/journal.jsonl``.

Design notes
------------

* Stateless persistence — each ``append`` re-opens the file. The
  expected event volume per run is small (10s-100s) so the open/close
  cost is negligible and we avoid lifecycle issues with long-running
  agents.
* I/O failures NEVER raise — observability must not break the run it
  observes. Failures are logged at WARNING and silently dropped.
* Direct callers (CLI, orchestrator) instantiate a journal per run and
  pass it through. Bootstrap-registered hook handlers route subagent
  events through this journal when the contextvar is set; otherwise
  they fall through to the existing project-journal pathway.
"""

from __future__ import annotations

import contextvars
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "SessionJournal",
    "current_session_journal",
    "session_journal_scope",
    "set_current_session_journal",
]


_current_journal: contextvars.ContextVar[SessionJournal | None] = contextvars.ContextVar(
    "self_improving_loop_session_journal", default=None
)


class SessionJournal:
    """Per-run JSONL event log.

    Constructed once at the start of an self-improving-loop run (autoresearch or
    seed-generation) and passed through to callers that emit structured
    events. Use :meth:`append` for individual events;
    :func:`session_journal_scope` for ContextVar-bound activation so
    hook handlers can discover the journal automatically.
    """

    def __init__(
        self,
        *,
        session_id: str,
        gen_tag: str,
        component: str,
        path: Path | None = None,
    ) -> None:
        self.session_id = session_id
        self.gen_tag = gen_tag
        self.component = component
        if path is None:
            # Lazy resolve via core.paths so test monkeypatch on
            # ``Path.home()`` is honoured after reloading the module.
            from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR

            path = GLOBAL_SELF_IMPROVING_LOOP_DIR / session_id / "journal.jsonl"
        self.path = path

    def append(
        self,
        event: str,
        *,
        level: str = "info",
        payload: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> None:
        """Append one JSONL event row. I/O failure logs a warning.

        ``payload`` is the per-event extensible data dict. ``ts``
        defaults to ``time.time()``; tests can pass a fixed value for
        determinism.
        """
        record = {
            "ts": ts if ts is not None else time.time(),
            "session_id": self.session_id,
            "gen_tag": self.gen_tag,
            "component": self.component,
            "level": level,
            "event": event,
            "payload": payload or {},
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning(
                "session journal append failed at %s: %s",
                self.path,
                exc,
            )


def current_session_journal() -> SessionJournal | None:
    """Return the journal active in the current ContextVar scope, if any.

    Used by hook handlers to discover the journal without explicit
    dependency injection. Returns ``None`` outside a
    :func:`session_journal_scope`.
    """
    return _current_journal.get()


def set_current_session_journal(
    journal: SessionJournal | None,
) -> contextvars.Token[SessionJournal | None]:
    """Bind the journal to the current ContextVar scope. Returns the reset token."""
    return _current_journal.set(journal)


@contextmanager
def session_journal_scope(journal: SessionJournal) -> Iterator[SessionJournal]:
    """Context manager — bind ``journal`` as ``current_session_journal()``
    for the duration of the ``with`` block. Restores the prior value on exit
    even if an exception propagates.
    """
    token = set_current_session_journal(journal)
    try:
        yield journal
    finally:
        _current_journal.reset(token)
