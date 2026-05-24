"""``RunTranscript`` — per-self-improving-loop-run binding over ``SessionTranscript``.

PR-CLEANUP-7 (2026-05-23) renamed + relocated from the legacy
``core/observability/session_journal.py``. The pre-PR module called
this class ``RunTranscript`` and lived under ``core/observability/``,
but every caller already lives inside the self-improving-loop / seed-
generation / petri-audit surface (25 caller files, 0 generic
``AgenticLoop`` consumers). "Journal" was the wrong name (the 3-Tier
preservation architecture in ``core/observability/transcript.py``
reserves "journal" for Tier 2 *summaries*, while this class writes
Tier 1 *event logs*), and "observability" was the wrong location
(the class is self-improving-loop runtime state, not the cross-layer
observability surface).

The class is **not** a shim. Each instance binds the four fields a
per-run lifecycle event needs — ``session_id`` / ``gen_tag`` /
``component`` / ``path`` — so callers can issue
``run_transcript.append(event, payload=...)`` without re-typing the
binding on every call. The actual append goes through
:meth:`core.observability.transcript.SessionTranscript.record_lifecycle_event`
so the canonical Tier-1 schema (``{ts, session_id, gen_tag, component,
level, event, payload}``) and writer is used.

On disk: ``~/.geode/self-improving-loop/<id>/transcript.jsonl`` (the
filename was renamed from ``journal.jsonl`` in PR-SESSION-METRICS;
PR-CLEANUP-7 brings the class + module names into line with the
filename).

SoT contract (P0a dedup, 2026-05-19 observability audit §6)
------------------------------------------------------------

Canonical run-level metrics (fitness, verdict, survivors, usd_spent,
promoted, commit, target_dim, candidates, pool_path_out, …) live in
``sessions.jsonl`` — one row per run, written by
``_append_session_index``. Lifecycle events MUST NOT duplicate those
fields in their payload; instead they act as stream markers (started
/ progress / finished) and carry only event-specific context.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from core.observability.transcript import SessionTranscript

__all__ = [
    "RunTranscript",
    "current_run_transcript",
    "run_transcript_scope",
    "set_current_run_transcript",
]


_current_run_transcript: contextvars.ContextVar[RunTranscript | None] = contextvars.ContextVar(
    "self_improving_loop_run_transcript", default=None
)


class RunTranscript:
    """Per-run lifecycle event writer for the self-improving loop.

    Binds ``session_id`` / ``gen_tag`` / ``component`` (+ optional
    explicit ``path``) so callers can issue
    ``run_transcript.append(event, payload=...)`` without re-typing the
    four fields on every call. The actual append delegates to
    :meth:`SessionTranscript.record_lifecycle_event` so the canonical
    Tier-1 schema is used.
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
            # PR-SESSION-METRICS — file is ``transcript.jsonl`` (renamed
            # from the pre-2026-05-23 ``journal.jsonl`` to align with
            # the canonical Tier-1 naming). Per-run directory unchanged.
            from core.paths import GLOBAL_SELF_IMPROVING_LOOP_DIR

            path = GLOBAL_SELF_IMPROVING_LOOP_DIR / session_id / "transcript.jsonl"
        self.path = path
        # Underlying SessionTranscript — uses our chosen path verbatim.
        # ``SessionTranscript.__init__(session_id, transcript_dir=...)``
        # constructs ``transcript_dir / f"{session_id}.jsonl"`` by default,
        # so we pass the parent dir and let ``record_lifecycle_event``
        # accept ``file_path=`` to override the per-call destination.
        self._transcript = SessionTranscript(
            session_id=session_id,
            transcript_dir=path.parent,
        )

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


def current_run_transcript() -> RunTranscript | None:
    """Return the run transcript active in the current ContextVar scope, if any.

    Used by hook handlers to discover the run transcript without explicit
    dependency injection. Returns ``None`` outside a
    :func:`run_transcript_scope`.
    """
    return _current_run_transcript.get()


def set_current_run_transcript(
    transcript: RunTranscript | None,
) -> contextvars.Token[RunTranscript | None]:
    """Bind the run transcript to the current ContextVar scope. Returns the reset token."""
    return _current_run_transcript.set(transcript)


@contextmanager
def run_transcript_scope(transcript: RunTranscript) -> Iterator[RunTranscript]:
    """Context manager — bind ``transcript`` as ``current_run_transcript()``
    for the duration of the ``with`` block. Restores the prior value on exit
    even if an exception propagates.
    """
    token = set_current_run_transcript(transcript)
    try:
        yield transcript
    finally:
        _current_run_transcript.reset(token)
