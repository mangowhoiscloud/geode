"""Evaluation contributions to the native GEODE tool plan."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.tools.composition import compose_tool_plan as compose_native_tool_plan
from core.tools.handlers import make_delegate_handler
from core.tools.handlers.registration import UniqueEntries

from evals.slash_commands import EVAL_COMMAND_SPECS

if TYPE_CHECKING:
    from core.tools.handlers import ToolIntegrationServices, ToolPersistenceServices
    from core.tools.plan import BoundToolPlan

_SEED_TOOL_CLASSES = (
    (
        "geode_seed_pool_search",
        "evals.seed_generation.tools.seed_pool_search",
        "SeedPoolSearchTool",
    ),
    ("seed_debate_turn", "evals.seed_generation.tools.seed_debate", "SeedDebateTurnTool"),
    (
        "freeze_paper_snapshot",
        "evals.seed_generation.tools.literature_snapshot",
        "FreezePaperSnapshotTool",
    ),
)


def _constant_resource(key: str) -> Any:
    def resolve(_arguments: Any) -> tuple[str, ...]:
        return (key,)

    return resolve


def _path_resource(field: str, default: str = ".", *, strip: bool = False) -> Any:
    def resolve(arguments: Any) -> tuple[str, ...]:
        raw = arguments.get(field)
        if strip:
            raw = str(raw or "").strip()
        return (str(Path(str(raw or default)).expanduser().resolve(strict=False)),)

    return resolve


def _viz_resource(arguments: Any) -> tuple[str, ...]:
    chart = str(arguments.get("chart") or "heatmap").lower()
    raw = arguments.get("output_path") or f"./reports/{chart}.png"
    return (str(Path(str(raw)).expanduser().resolve(strict=False)),)


def _trimmed_resource(field: str) -> Any:
    def resolve(arguments: Any) -> tuple[str, ...]:
        return (str(arguments.get(field, "")).strip(),)

    return resolve


def evaluation_resource_metadata() -> dict[str, tuple[str, Any]]:
    """Return hash-stable resource strategies for evaluation tools."""
    return {
        "update_geo": ("geo-run:v1", _constant_resource("geo")),
        "petri_audit": ("petri-runtime:v1", _constant_resource("audit")),
        "eval_inspect_viz": ("local-path:v1", _viz_resource),
        "eval_dspy_optimize": (
            "local-path:v1",
            _path_resource("output_dir", "optimized_prompts"),
        ),
        "seed_debate_turn": (
            "local-path:v1",
            _path_resource("sidecar_path", strip=True),
        ),
        "freeze_paper_snapshot": ("paper-snapshot:v1", _trimmed_resource("arxiv_id")),
    }


def evaluation_handler_groups() -> tuple[tuple[str, UniqueEntries[str, Any]], ...]:
    """Return evaluation handler batches consumed by the core compiler."""
    from evals.geo import build_geo_handlers

    seed_handlers = UniqueEntries[str, Any](
        (name, make_delegate_handler(module, class_name))
        for name, module, class_name in _SEED_TOOL_CLASSES
    )
    return (
        ("eval-audit", _build_audit_handlers()),
        ("eval-seed", seed_handlers),
        ("eval-geo", build_geo_handlers()),
    )


def compose_tool_plan(
    *,
    verbose: bool = False,
    mcp_manager: Any = None,
    skill_registry: Any = None,
    previous: BoundToolPlan | None = None,
    persistence: ToolPersistenceServices | None = None,
    integrations: ToolIntegrationServices | None = None,
    hooks: Any = None,
    scheduler_service: Any = None,
) -> tuple[BoundToolPlan, dict[str, Any]]:
    """Compose the native plan with evaluation-owned tools."""
    return compose_native_tool_plan(
        verbose=verbose,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
        previous=previous,
        persistence=persistence,
        integrations=integrations,
        hooks=hooks,
        scheduler_service=scheduler_service,
        handler_groups=evaluation_handler_groups(),
        command_specs=EVAL_COMMAND_SPECS,
        resource_metadata=evaluation_resource_metadata(),
        execution_tools=frozenset({"petri_audit", "eval_dspy_optimize"}),
    )


def build_tool_handlers(**kwargs: Any) -> dict[str, Any]:
    """Return a compatibility copy of the validated evaluation catalog."""
    bound, transient = compose_tool_plan(**kwargs)
    return {**bound.handlers, **transient}


def _build_audit_handlers() -> UniqueEntries[str, Any]:
    """Build evaluation tool name -> handler mapping for ToolExecutor."""
    from evals.petri.optimize import DEFAULT_COMPILE_USD_CAP, OptimizeError, optimize_prompt
    from evals.petri.runner import run_audit
    from evals.petri.viz import VizError, available_charts, render_from_eval_log

    def handle_petri_audit(**kwargs: Any) -> dict[str, Any]:
        dry_run = bool(kwargs.get("dry_run", True))
        try:
            report = run_audit(
                judge=kwargs.get("judge") or None,
                auditor=kwargs.get("auditor") or None,
                target=kwargs.get("target") or None,
                seeds=int(kwargs.get("seeds") or 1),
                max_turns=int(kwargs.get("max_turns") or 10),
                tags=kwargs.get("tags") or None,
                seed_select=kwargs.get("seed_select") or None,
                dim_set=kwargs.get("dim_set") or "subset",
                target_tools=kwargs.get("target_tools") or "none",
                cache=bool(kwargs.get("cache", False)),
                dry_run=dry_run,
                yes=bool(kwargs.get("confirm", False)) or dry_run,
            )
        except Exception as exc:
            return {"status": "error", "error": str(exc), "tool": "petri_audit"}
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
        return {"status": "ok", "tool": "petri_audit", "audit": audit}

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
        try:
            report = optimize_prompt(
                judge=judge,
                generator=generator,
                eval_log_path=Path(eval_log_path),
                output_dir=Path(kwargs.get("output_dir") or "optimized_prompts"),
                dry_run=bool(kwargs.get("dry_run", True)),
                seed=int(kwargs.get("seed") or 42),
                max_compile_usd=float(kwargs.get("max_compile_usd") or DEFAULT_COMPILE_USD_CAP),
            )
        except OptimizeError as exc:
            return {"status": "error", "tool": "eval_dspy_optimize", "error": str(exc)}
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


__all__ = ["build_tool_handlers", "compose_tool_plan"]
