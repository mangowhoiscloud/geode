"""GEODE observability surface — OpenLLMetry / OTel exporter wiring.

Module-level surface stays import-light so default ``uv sync`` cold-start
is unaffected (the ``[obs]`` extra is opt-in via
``uv sync --extra obs``). The actual ``traceloop-sdk`` /
``opentelemetry-instrumentation-anthropic`` import only happens inside
:func:`enable`, which the ``obs_otel_export`` tool calls when the user
explicitly enables tracing.

PR-CLEANUP-7 (2026-05-23): the per-self-improving-loop-run lifecycle
writer (``SessionJournal`` re-exported from here, since renamed to
:class:`~core.self_improving.loop.run_transcript.RunTranscript`)
moved into :mod:`core.self_improving.loop.run_transcript`; this
package is back to OTel + per-session metrics only.

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
from core.observability.session_metrics import (
    SessionMetrics,
    current_session_metrics,
    session_metrics_scope,
    set_current_session_metrics,
)

__all__ = [
    "OtelExportError",
    "SessionMetrics",
    "current_session_metrics",
    "disable",
    "enable",
    "session_metrics_scope",
    "set_current_session_metrics",
    "status",
]
