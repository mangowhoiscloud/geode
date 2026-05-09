"""Tool handler for ``petri_audit`` — natural-language entry point.

Mirrors the ``execution.py`` factory pattern. The handler funnels into
``plugins.petri_audit.runner.run_audit`` so the slash and Typer paths
stay in lockstep with the AgenticLoop tool path.

Cost gating: ``petri_audit`` is registered in
``core/agent/safety.py:EXPENSIVE_TOOLS`` so every dispatch passes
through ``apply_safety_gates`` first; this handler only runs after the
user has consented.
"""

from __future__ import annotations

from typing import Any


def _build_audit_handlers() -> dict[str, Any]:
    """Build petri_audit -> handler mapping for ToolExecutor."""
    from plugins.petri_audit.runner import run_audit

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

    return {"petri_audit": handle_petri_audit}
