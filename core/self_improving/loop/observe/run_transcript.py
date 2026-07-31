"""Deprecated import surface for :mod:`.run_timeline`.

The compatibility module re-exports the exact same classes, functions, and
ContextVar state. New code imports ``run_timeline``.
"""

from core.self_improving.loop.observe.run_timeline import (
    RUN_EVENT_MAX_BYTES,
    RUN_EVENT_SCHEMA_ID,
    RUN_EVENT_SCHEMA_VERSION,
    RunTimeline,
    RunTranscript,
    current_run_timeline,
    current_run_transcript,
    run_timeline_scope,
    run_transcript_scope,
    set_current_run_timeline,
    set_current_run_transcript,
)

__all__ = [
    "RUN_EVENT_MAX_BYTES",
    "RUN_EVENT_SCHEMA_ID",
    "RUN_EVENT_SCHEMA_VERSION",
    "RunTimeline",
    "RunTranscript",
    "current_run_timeline",
    "current_run_transcript",
    "run_timeline_scope",
    "run_transcript_scope",
    "set_current_run_timeline",
    "set_current_run_transcript",
]
