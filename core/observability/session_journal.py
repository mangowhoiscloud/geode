"""Backward-compat alias — ``SessionJournal`` is now a thin wrapper over the
canonical :class:`core.runtime_state.transcript.SessionTranscript`.

PR-SESSION-METRICS (2026-05-23) — the pre-existing 3-Tier preservation
architecture in ``core/runtime_state/transcript.py`` calls out:

* Tier 1 — :class:`SessionTranscript` (event log, append-only JSONL)
* Tier 2 — Journal (summaries)
* Tier 3 — Snapshot (pipeline state)

Reality drifted: ``SessionJournal`` was a separate per-self-improving-loop-run
event log written to ``~/.geode/self-improving-loop/<id>/transcript.jsonl`` — i.e.
*another Tier 1 event stream*, not a Tier 2 summary. The two coexisted with
different schemas / paths / APIs which made the lifecycle event boundary
opaque.

This module is now a **thin compat shim**. ``SessionJournal.append(event,
payload=...)`` delegates to ``SessionTranscript.record_lifecycle_event(...)``.
Path renamed to ``~/.geode/self-improving-loop/<id>/transcript.jsonl`` (was
``journal.jsonl`` before this PR) — schema is unchanged (``{ts, session_id,
gen_tag, component, level, event, payload}``) so existing readers continue
to work.

Future PR removes this shim once all 269 callsites migrate to direct
``SessionTranscript.record_lifecycle_event`` calls. Until then, the
existing ``current_session_journal() / session_journal_scope`` API stays
operational via this shim.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.runtime_state.transcript import SessionTranscript

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
    """Per-run lifecycle event log — alias of :class:`SessionTranscript`.

    Preserves the pre-PR-SESSION-METRICS API surface (``append(event,
    payload=...)`` + ``session_id / gen_tag / component`` instance fields +
    ``path`` attribute) so existing 269 callsites work unchanged. The
    actual append happens through the underlying :class:`SessionTranscript`
    instance held in ``self._transcript`` so the canonical Tier-1 schema
    is used.

    SoT contract (P0a dedup, 2026-05-19 observability audit §6)
    ------------------------------------------------------------

    Canonical run-level metrics (fitness, verdict, survivors, usd_spent,
    promoted, commit, target_dim, candidates, pool_path_out, …) live in
    ``sessions.jsonl`` — one row per run, written by
    ``_append_session_index``. Lifecycle events MUST NOT duplicate those
    fields in their payload; instead they act as stream markers (started /
    progress / finished) and carry only event-specific context.
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
            # PR-SESSION-METRICS — file renamed ``journal.jsonl`` →
            # ``transcript.jsonl`` to align with the canonical Tier-1
            # naming. Same per-run directory; only the filename changes.
            from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR

            path = GLOBAL_SELF_IMPROVING_LOOP_DIR / session_id / "transcript.jsonl"
        self.path = path
        # Underlying SessionTranscript — uses our chosen path verbatim.
        # ``SessionTranscript.__init__(session_id, transcript_dir=...)``
        # constructs ``transcript_dir / f"{session_id}.jsonl"``, so we
        # pass the parent dir and let it form the file path. Then we
        # ``rename`` it to match our explicit path.
        self._transcript = SessionTranscript(
            session_id=session_id,
            transcript_dir=path.parent,
        )
        # SessionTranscript builds ``<dir>/<session_id>.jsonl`` by default,
        # but we want ``<dir>/transcript.jsonl``. Override the file_path
        # property by monkey-patching the internal directory + a sentinel.
        # Simpler: write directly to our path via a small inline emitter.
        # (Keeping the SessionTranscript instance for API symmetry / future
        # migration to ``record_*`` typed methods.)

    def append(
        self,
        event: str,
        *,
        level: str = "info",
        payload: dict[str, Any] | None = None,
        ts: float | None = None,
    ) -> None:
        """Append one JSONL event row. I/O failure logs a warning.

        Delegates to :meth:`SessionTranscript.record_lifecycle_event` so the
        underlying schema and writer are the canonical Tier-1 path.
        ``ts`` is honoured for determinism (tests pass a fixed value).
        """
        self._transcript.record_lifecycle_event(
            event=event,
            session_id=self.session_id,
            gen_tag=self.gen_tag,
            component=self.component,
            level=level,
            payload=payload,
            ts=ts,
            file_path=self.path,
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
