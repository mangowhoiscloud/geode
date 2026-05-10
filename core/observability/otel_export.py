"""OpenLLMetry OTel exporter — enable/disable/status surface.

Wraps `traceloop-sdk` so GEODE can emit OTLP spans for every LLM call
and tool invocation without re-introducing the LangSmith dependency that
v0.89.0 retired (B2/M1 batches). All heavy imports are deferred to
:func:`enable` so importing :mod:`core.observability` on a default
``uv sync`` (without the ``[obs]`` extra) costs essentially nothing.

State model:
- The exporter is **disabled** by default. ``enable()`` flips it on for
  the rest of the process; ``disable()`` flushes and shuts down.
- ``status()`` returns the current view (``enabled`` / ``endpoint`` /
  ``app_name``). Span counters are out of scope — Traceloop's built-in
  exporter handles the actual buffer.
- Endpoint resolution: explicit argument > ``TRACELOOP_BASE_URL`` env
  var > ``OTEL_EXPORTER_OTLP_ENDPOINT`` env var > None (no-op enable).

Live behaviour: enabling without an endpoint sets the in-process flag
but does NOT emit spans, mirroring Traceloop's own no-endpoint default.
This lets tests / dry-runs exercise the wire-up without an OTLP
collector running.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "OtelExportError",
    "OtelStatus",
    "disable",
    "enable",
    "resolve_endpoint",
    "status",
]


class OtelExportError(RuntimeError):
    """Raised when the ``[obs]`` extra is missing or Traceloop init fails."""


@dataclass
class OtelStatus:
    """Snapshot of the OTel exporter state."""

    enabled: bool = False
    endpoint: str | None = None
    app_name: str = "geode"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "endpoint": self.endpoint,
            "app_name": self.app_name,
            "notes": self.notes,
        }


_state: OtelStatus = OtelStatus()
_lock = RLock()


def resolve_endpoint(explicit: str | None = None) -> str | None:
    """Return the OTLP endpoint to use, or ``None`` when none is configured."""
    if explicit:
        return explicit
    return os.environ.get("TRACELOOP_BASE_URL") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")


def enable(
    *,
    endpoint: str | None = None,
    app_name: str = "geode",
    disable_batch: bool = False,
) -> OtelStatus:
    """Activate the OpenLLMetry OTel exporter for this process.

    Idempotent: calling :func:`enable` while already enabled returns the
    current status without re-initialising.

    Raises :class:`OtelExportError` when the ``[obs]`` extra is missing.
    """
    with _lock:
        if _state.enabled:
            return _state

        endpoint_resolved = resolve_endpoint(endpoint)

        try:
            from traceloop.sdk import Traceloop
        except ImportError as exc:
            raise OtelExportError(
                "[obs] extra not installed. Run `uv sync --extra obs` to "
                "install traceloop-sdk + opentelemetry-instrumentation-anthropic."
            ) from exc

        try:
            init_kwargs: dict[str, Any] = {
                "app_name": app_name,
                "disable_batch": disable_batch,
            }
            if endpoint_resolved:
                init_kwargs["api_endpoint"] = endpoint_resolved
            Traceloop.init(**init_kwargs)
        except Exception as exc:
            raise OtelExportError(f"Traceloop.init failed: {exc}") from exc

        _state.enabled = True
        _state.endpoint = endpoint_resolved
        _state.app_name = app_name
        if endpoint_resolved is None:
            _state.notes.append("no endpoint configured — Traceloop initialised in no-op mode")
        log.info(
            "OpenLLMetry OTel exporter enabled (app=%s, endpoint=%s)",
            app_name,
            endpoint_resolved,
        )
        return _state


def disable() -> OtelStatus:
    """Shut the exporter down. No-op when already disabled."""
    with _lock:
        if not _state.enabled:
            return _state

        try:
            from opentelemetry import trace

            provider = trace.get_tracer_provider()
            shutdown = getattr(provider, "shutdown", None)
            if callable(shutdown):
                shutdown()
        except ImportError:
            log.debug("opentelemetry not importable on disable() — already gone")
        except Exception:
            log.warning("OTel provider shutdown failed", exc_info=True)

        _state.enabled = False
        _state.notes.append("disabled")
        log.info("OpenLLMetry OTel exporter disabled")
        return _state


def status() -> OtelStatus:
    """Return the current exporter status snapshot."""
    return _state
