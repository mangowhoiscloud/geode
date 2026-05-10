"""Tool handlers for the ``evaluation`` category.

Mirrors the ``execution.py`` factory pattern. Funnels two evaluation
tools into the GEODE ToolExecutor:

- ``petri_audit`` — full audit run via
  :func:`plugins.petri_audit.runner.run_audit`. EXPENSIVE_TOOLS-gated;
  default ``dry_run=True``.
- ``eval_inspect_viz`` — render a Petri/inspect_ai eval log into one of
  five chart types (heatmap / cost / tool / agree / trend) via
  :mod:`plugins.petri_audit.viz`. cost_tier=free.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _build_audit_handlers() -> dict[str, Any]:
    """Build evaluation tool name -> handler mapping for ToolExecutor."""
    from plugins.petri_audit.runner import run_audit
    from plugins.petri_audit.viz import (
        VizError,
        available_charts,
        render_from_eval_log,
    )

    def handle_petri_audit(**kwargs: Any) -> dict[str, Any]:
        judge = kwargs.get("judge") or "claude-haiku-4-5-20251001"
        auditor = kwargs.get("auditor") or "claude-sonnet-4-6"
        target = kwargs.get("target") or "claude-opus-4-7"
        seeds = int(kwargs.get("seeds") or 1)
        max_turns = int(kwargs.get("max_turns") or 5)
        tags = kwargs.get("tags") or None
        cache = bool(kwargs.get("cache", True))
        dry_run = bool(kwargs.get("dry_run", True))
        confirm = bool(kwargs.get("confirm", False))

        try:
            report = run_audit(
                judge=judge,
                auditor=auditor,
                target=target,
                seeds=seeds,
                max_turns=max_turns,
                tags=tags,
                cache=cache,
                dry_run=dry_run,
                # dry_run never spends — auto-skip the runner-level confirm.
                # live runs honour ``confirm`` so the AgenticLoop tool can
                # decline a second prompt after the EXPENSIVE_TOOLS gate.
                yes=confirm or dry_run,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc), "tool": "petri_audit"}

        return {
            "status": "ok",
            "tool": "petri_audit",
            "audit": report.to_dict(),
        }

    def handle_eval_inspect_viz(**kwargs: Any) -> dict[str, Any]:
        log_path = kwargs.get("log_path")
        chart = (kwargs.get("chart") or "heatmap").lower()
        output_path = kwargs.get("output_path") or f"./reports/{chart}.png"

        if not log_path:
            return {
                "status": "error",
                "tool": "eval_inspect_viz",
                "error": "log_path is required (path to an inspect_ai *.eval file).",
                "available_charts": list(available_charts()),
            }

        try:
            out = render_from_eval_log(
                log_path=Path(log_path),
                chart=chart,
                output_path=Path(output_path),
            )
        except VizError as exc:
            return {"status": "error", "tool": "eval_inspect_viz", "error": str(exc)}

        return {
            "status": "ok",
            "tool": "eval_inspect_viz",
            "chart": chart,
            "output_path": str(out),
        }

    return {
        "petri_audit": handle_petri_audit,
        "eval_inspect_viz": handle_eval_inspect_viz,
    }
