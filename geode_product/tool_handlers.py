"""Tool handlers for the ``evaluation`` category.

Mirrors the ``execution.py`` factory pattern. Funnels three evaluation
tools into the GEODE ToolExecutor:

- ``petri_audit`` — full audit run via
  :func:`geode_product.petri_audit.runner.run_audit`. EXPENSIVE_TOOLS-gated;
  default ``dry_run=True``.
- ``eval_inspect_viz`` — render a Petri/inspect_ai eval log into one of
  five chart types (heatmap / cost / tool / agree / trend) via
  :mod:`geode_product.petri_audit.viz`. cost_tier=free.
- ``eval_dspy_optimize`` — Petri smoke result → DSPy prompt re-compile
  via :func:`geode_product.petri_audit.optimize.optimize_prompt`. M1 (judge ≠
  generator provider) + M2 (PR-only auto-edit) + M3 (budget cap) + M10
  (compile_id) gates enforced inside the runner; M4 (TextGrad depth=1)
  enforced by the audit invariants when the
  caller follows up with a textual-gradient step. EXPENSIVE_TOOLS-gated;
  default ``dry_run=True``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.cli.tool_handlers.delegated import make_delegate_handler
from core.cli.tool_handlers.registration import UniqueEntries

_SEED_TOOL_CLASSES = (
    (
        "geode_seed_pool_search",
        "geode_product.seed_generation.tools.seed_pool_search",
        "SeedPoolSearchTool",
    ),
    (
        "seed_debate_turn",
        "geode_product.seed_generation.tools.seed_debate",
        "SeedDebateTurnTool",
    ),
    (
        "freeze_paper_snapshot",
        "geode_product.seed_generation.tools.literature_snapshot",
        "FreezePaperSnapshotTool",
    ),
)


def product_handler_groups() -> tuple[tuple[str, UniqueEntries[str, Any]], ...]:
    """Return the product-owned batches consumed by the core composer."""
    seed_handlers = UniqueEntries[str, Any](
        (name, make_delegate_handler(module, class_name))
        for name, module, class_name in _SEED_TOOL_CLASSES
    )
    return (("product-audit", _build_audit_handlers()), ("product-seed", seed_handlers))


def build_tool_handlers(
    *,
    verbose: bool = False,
    mcp_manager: Any = None,
    skill_registry: Any = None,
) -> dict[str, Any]:
    """Compose the kernel and product handler groups once."""
    from core.cli.routing import compose_command_registry
    from core.cli.tool_handlers import build_tool_handlers as build_core_tool_handlers

    from geode_product.cli import PRODUCT_COMMAND_SPECS

    return build_core_tool_handlers(
        verbose=verbose,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        command_registry=compose_command_registry(PRODUCT_COMMAND_SPECS),
        extra_groups=product_handler_groups(),
    )


def _build_audit_handlers() -> UniqueEntries[str, Any]:
    """Build evaluation tool name -> handler mapping for ToolExecutor."""
    from geode_product.petri_audit.optimize import (
        DEFAULT_COMPILE_USD_CAP,
        OptimizeError,
        optimize_prompt,
    )
    from geode_product.petri_audit.runner import run_audit
    from geode_product.petri_audit.viz import (
        VizError,
        available_charts,
        render_from_eval_log,
    )

    def handle_petri_audit(**kwargs: Any) -> dict[str, Any]:
        # None delegates defaults to the Petri manifest/override resolver.
        judge = kwargs.get("judge") or None
        auditor = kwargs.get("auditor") or None
        # target=None → fall back to GEODE's active settings.model (drift
        # sync stays active). Pinned id sticks for the audit's lifetime.
        target = kwargs.get("target") or None
        seeds = int(kwargs.get("seeds") or 1)
        max_turns = int(kwargs.get("max_turns") or 10)
        tags = kwargs.get("tags") or None
        seed_select = kwargs.get("seed_select") or None
        dim_set = kwargs.get("dim_set") or "subset"
        target_tools = kwargs.get("target_tools") or "none"
        cache = bool(kwargs.get("cache", False))
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
                seed_select=seed_select,
                dim_set=dim_set,
                target_tools=target_tools,
                cache=cache,
                dry_run=dry_run,
                # dry_run never spends — auto-skip the runner-level confirm.
                # live runs honour ``confirm`` so the AgenticLoop tool can
                # decline a second prompt after the EXPENSIVE_TOOLS gate.
                yes=confirm or dry_run,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc), "tool": "petri_audit"}

        # PR-PILOT-PETRI-AUDIT-WIRING (2026-06-01) — fail LOUDLY when a LIVE
        # audit aborted before running (e.g. ``inspect`` CLI / inspect_ai not
        # installed — the [audit] extra is missing). The runner records that
        # as ``aborted=True`` with a note but a blank ``returncode``; surfacing
        # it as ``status="ok"`` would let a tool caller mistake a never-run
        # audit for a finished one. (The seed-gen Pilot no longer routes
        # through this tool — PR-PILOT-UNIFY-DIM-EXTRACT 2026-06-04 — but the
        # loud-fail still helps the REPL ``petri_audit`` caller see a missing
        # [audit] extra instead of an empty result.) dry-run never aborts, so
        # the cost-preview path is unaffected.
        audit = report.to_dict()
        if not dry_run and report.aborted:
            return {
                "status": "error",
                "tool": "petri_audit",
                "error": (
                    "petri_audit aborted before running — "
                    + "; ".join(report.notes or ["unknown reason"])
                    + ". If `inspect` is missing, install the [audit] extra: "
                    '`uv tool install -e ".[audit]"` (or `uv sync --extra audit`).'
                ),
                "audit": audit,
            }

        return {
            "status": "ok",
            "tool": "petri_audit",
            "audit": audit,
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

    def handle_eval_dspy_optimize(**kwargs: Any) -> dict[str, Any]:
        judge = kwargs.get("judge")
        generator = kwargs.get("generator")
        eval_log_path = kwargs.get("eval_log_path")

        if not judge or not generator or not eval_log_path:
            return {
                "status": "error",
                "tool": "eval_dspy_optimize",
                "error": (
                    "judge, generator, eval_log_path are required. M1 needs "
                    "judge ≠ generator provider — pick e.g. judge=claude-haiku-4-5-* "
                    "with generator=gpt-5.4."
                ),
            }

        seed = int(kwargs.get("seed") or 42)
        max_compile_usd = float(kwargs.get("max_compile_usd") or DEFAULT_COMPILE_USD_CAP)
        output_dir = kwargs.get("output_dir") or "optimized_prompts"
        dry_run = bool(kwargs.get("dry_run", True))

        try:
            report = optimize_prompt(
                judge=judge,
                generator=generator,
                eval_log_path=Path(eval_log_path),
                output_dir=Path(output_dir),
                dry_run=dry_run,
                seed=seed,
                max_compile_usd=max_compile_usd,
            )
        except OptimizeError as exc:
            return {
                "status": "error",
                "tool": "eval_dspy_optimize",
                "error": str(exc),
            }

        return {
            "status": "ok",
            "tool": "eval_dspy_optimize",
            "optimize": report.to_dict(),
        }

    return UniqueEntries[str, Any](
        (
            ("petri_audit", handle_petri_audit),
            ("eval_inspect_viz", handle_eval_inspect_viz),
            ("eval_dspy_optimize", handle_eval_dspy_optimize),
        )
    )
