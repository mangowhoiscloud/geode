"""Run-event path and legacy-row compatibility helpers.

New writers use ``events.jsonl``. Readers select that file first and accept the
retired ``transcript.jsonl`` / ``dialogue.jsonl`` names without rewriting the
source artifact.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.memory.atomic_write import iter_jsonl

EVENTS_FILENAME = "events.jsonl"
LEGACY_EVENT_FILENAMES = ("transcript.jsonl", "dialogue.jsonl")
EVENT_STREAM_FILENAMES = (EVENTS_FILENAME, *LEGACY_EVENT_FILENAMES)

_SESSION_KIND_TO_LEGACY = {
    "session.started": "session_start",
    "session.ended": "session_end",
    "verification.continued": "verification_continued",
    "verification.evidence": "verification_evidence",
    "verification.pending": "verification_pending",
    "message.user": "user_message",
    "message.assistant": "assistant_message",
    "tool.called": "tool_call",
    "tool.completed": "tool_result",
    "subagent.started": "subagent_start",
    "subagent.stopped": "subagent_complete",
    "artifact.saved": "vault_save",
    "usage.recorded": "cost",
    "error.recorded": "error",
    "preflight.recorded": "task_preflight",
    "handoff.triggered": "handoff_triggered",
    "gui.step": "gui_step",
}


def event_stream_candidates(directory: Path | str) -> tuple[Path, ...]:
    """Return new-first event paths for one run or sub-agent directory."""
    root = Path(directory)
    return tuple(root / name for name in EVENT_STREAM_FILENAMES)


def resolve_event_stream_path(directory: Path | str) -> Path | None:
    """Resolve a readable stream, preferring the versioned filename."""
    return next((path for path in event_stream_candidates(directory) if path.is_file()), None)


def normalize_event_row(row: dict[str, Any]) -> dict[str, Any]:
    """Project either versioned or legacy rows onto the legacy reader shape.

    This is a read adapter only. It keeps old hub and evaluation logic useful
    while every new persisted row remains schema-first and nested.
    """
    if "schema_id" not in row:
        return row
    normalized = dict(row)
    payload = row.get("payload")
    body = payload if isinstance(payload, dict) else {}
    for key, value in body.items():
        normalized.setdefault(key, value)
    kind = str(row.get("kind") or row.get("event") or "")
    normalized["event"] = _SESSION_KIND_TO_LEGACY.get(kind, kind)
    normalized.setdefault("ts", row.get("occurred_at", 0.0))
    normalized.setdefault("seq", row.get("ordinal", 0))
    if kind in {"message.user", "message.assistant"}:
        normalized.setdefault("text", body.get("content", ""))
    elif kind == "tool.called":
        normalized.setdefault("tool", body.get("tool", ""))
        normalized.setdefault("input", body.get("arguments", {}))
    elif kind == "tool.completed":
        normalized.setdefault("tool", body.get("tool", ""))
        normalized.setdefault("summary", body.get("summary", ""))
    elif kind == "usage.recorded":
        normalized.setdefault("in", body.get("input_tokens", 0))
        normalized.setdefault("out", body.get("output_tokens", 0))
        normalized.setdefault("cost", body.get("cost_usd", 0.0))
    elif kind == "session.ended":
        normalized.setdefault("total_cost", body.get("total_cost_usd", 0.0))
    return normalized


def read_event_stream(directory_or_file: Path | str) -> list[dict[str, Any]]:
    """Read a selected event stream and normalize rows for compatibility."""
    candidate = Path(directory_or_file)
    path = candidate if candidate.is_file() else resolve_event_stream_path(candidate)
    if path is None:
        return []
    return [normalize_event_row(row) for row in iter_jsonl(path)]


__all__ = [
    "EVENTS_FILENAME",
    "EVENT_STREAM_FILENAMES",
    "LEGACY_EVENT_FILENAMES",
    "event_stream_candidates",
    "normalize_event_row",
    "read_event_stream",
    "resolve_event_stream_path",
]
