"""GEODE observability surface — OpenLLMetry / OTel exporter wiring.

Module-level surface stays import-light so default ``uv sync`` cold-start
is unaffected (the ``[obs]`` extra is opt-in via
``uv sync --extra obs``). The actual ``traceloop-sdk`` /
``opentelemetry-instrumentation-anthropic`` import only happens inside
:func:`enable`, which the ``obs_otel_export`` tool calls when the user
explicitly enables tracing.

See ``docs/plans/eval-petri-p3b-2-execution.md`` § Future tooling —
Observability.
"""

from __future__ import annotations

from core.observability.otel_export import (
    OtelExportError,
    disable,
    enable,
    status,
)
from core.observability.session_journal import (
    SessionJournal,
    current_session_journal,
    session_journal_scope,
    set_current_session_journal,
)
from core.observability.session_metrics import (
    SessionMetrics,
    current_session_metrics,
    session_metrics_scope,
    set_current_session_metrics,
)

__all__ = [
    "OtelExportError",
    "SessionJournal",
    "SessionMetrics",
    "current_session_journal",
    "current_session_metrics",
    "disable",
    "enable",
    "session_journal_scope",
    "session_metrics_scope",
    "set_current_session_journal",
    "set_current_session_metrics",
    "status",
]
