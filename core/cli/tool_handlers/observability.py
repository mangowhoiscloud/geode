"""Tool handlers for the ``observability`` category.

Currently exposes ``obs_otel_export`` — the OpenLLMetry OTel exporter
enable/disable/status surface defined in :mod:`core.observability`.
Mirrors the ``execution.py`` factory pattern.
"""

from __future__ import annotations

from typing import Any

from core.cli.tool_handlers.registration import UniqueEntries


def _build_observability_handlers() -> UniqueEntries[str, Any]:
    """Build observability tool name -> handler mapping."""
    from core.observability import OtelExportError, disable, enable, status

    def handle_obs_otel_export(**kwargs: Any) -> dict[str, Any]:
        action = (kwargs.get("action") or "status").lower()
        endpoint = kwargs.get("endpoint") or None
        app_name = kwargs.get("app_name") or "geode"

        try:
            if action == "enable":
                snap = enable(endpoint=endpoint, app_name=app_name)
            elif action == "disable":
                snap = disable()
            elif action == "status":
                snap = status()
            else:
                return {
                    "status": "error",
                    "tool": "obs_otel_export",
                    "error": (f"Unknown action {action!r}; expected enable / disable / status."),
                }
        except OtelExportError as exc:
            return {"status": "error", "tool": "obs_otel_export", "error": str(exc)}

        return {
            "status": "ok",
            "tool": "obs_otel_export",
            "action": action,
            "obs": snap.to_dict(),
        }

    return UniqueEntries[str, Any]((("obs_otel_export", handle_obs_otel_export),))
