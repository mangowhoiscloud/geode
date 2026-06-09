"""Journal Hook Handlers — auto-record to .geode/journal/ on subagent lifecycle events.

Bridges HookSystem events to ProjectJournal (C2 layer).
Registered by GeodeRuntime at startup.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks import HookEvent

log = logging.getLogger(__name__)


def make_journal_handlers(
    journal: Any,
) -> list[tuple[str, Any]]:
    """Create hook handlers that auto-record to ProjectJournal.

    Args:
        journal: ProjectJournal instance.

    Returns:
        List of (handler_name, handler_fn) tuples for HookSystem.register().
    """

    def _on_subagent_completed(event: HookEvent, data: dict[str, Any]) -> None:
        if event != HookEvent.SUBAGENT_COMPLETED:
            return
        task_id = data.get("task_id", "")
        summary = data.get("summary", "")
        _journal_to_session(
            "subagent_completed",
            "info",
            {"task_id": task_id, "summary": summary[:200] if summary else None},
        )
        if not summary:
            return
        session_id = data.get("session_id", "")
        journal.record_run(
            session_id=session_id,
            run_type="subagent",
            summary=f"[subagent:{task_id}] {summary[:100]}",
            status=data.get("status", "ok"),
        )

    def _on_subagent_started(event: HookEvent, data: dict[str, Any]) -> None:
        """P1c — emit a session-journal entry on subagent start.

        Falls through silently when no session journal is bound to the
        current ContextVar (i.e. outside an self-improving-loop run). The
        existing project journal is not touched on STARTED — only
        COMPLETED / FAILED carry summary text worth recording there.
        """
        if event != HookEvent.SUBAGENT_STARTED:
            return
        _journal_to_session(
            "subagent_started",
            "info",
            {
                "task_id": data.get("task_id", ""),
                "task_type": data.get("task_type", ""),
            },
        )

    def _on_subagent_failed(event: HookEvent, data: dict[str, Any]) -> None:
        """P1c — emit a session-journal entry + project-journal error row."""
        if event != HookEvent.SUBAGENT_FAILED:
            return
        task_id = data.get("task_id", "")
        error = data.get("error", "")
        _journal_to_session(
            "subagent_failed",
            "error",
            {"task_id": task_id, "error": error[:300] if error else None},
        )
        session_id = data.get("session_id", "")
        journal.record_run(
            session_id=session_id,
            run_type="subagent",
            summary=f"[subagent:{task_id}] FAILED: {error[:120] if error else 'unknown'}",
            status="error",
        )

    return [
        ("journal_subagent", _on_subagent_completed),
        ("journal_subagent_started", _on_subagent_started),
        ("journal_subagent_failed", _on_subagent_failed),
    ]


def _journal_to_session(
    event: str,
    level: str,
    payload: dict[str, Any],
) -> None:
    """Forward an event to the active RunTranscript if one is bound.

    No-op when no journal is bound to the ContextVar. Import is local
    so journal_hooks stays import-light when observability is unused.
    """
    try:
        from core.self_improving.loop.run_transcript import current_run_transcript
    except ImportError:
        return
    rt = current_run_transcript()
    if rt is None:
        return
    rt.append(event, level=level, payload=payload)
