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

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.tools.handlers import make_delegate_handler
from core.tools.handlers.registration import UniqueEntries

if TYPE_CHECKING:
    from core.tools.plan import BoundToolPlan

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

_INTERNAL_ONLY_HANDLERS = frozenset({"computer", "doctor_slack", "recall_tool_result"})

_ADMINISTRATIVE_TOOLS = frozenset(
    {
        "switch_model",
        "manage_rule",
        "set_api_key",
        "manage_auth",
        "manage_login",
        "manage_context",
        "obs_otel_export",
    }
)
_COMMUNICATION_TOOLS = frozenset(
    {"send_message", "followup_task", "send_notification", "gmail_send"}
)
_EXECUTION_TOOLS = frozenset(
    {
        "run_bash",
        "computer_use",
        "browser_execute_js",
        "delegate_task",
        "spawn_agent",
        "trigger_event",
        "petri_audit",
        "eval_dspy_optimize",
    }
)


def _constant_resource(key: str) -> Any:
    def resolve(_arguments: Any) -> tuple[str, ...]:
        return (key,)

    return resolve


def _selected_resource(*fields: str) -> Any:
    def resolve(arguments: Any) -> tuple[str, ...]:
        selected = {field: arguments.get(field) for field in fields}
        return (json.dumps(selected, sort_keys=True, separators=(",", ":")),)

    return resolve


def _canonical_path(raw: Any, default: str = ".") -> str:
    return str(Path(str(raw or default)).expanduser().resolve(strict=False))


def _path_resource(field: str, default: str = ".", *, strip: bool = False) -> Any:
    def resolve(arguments: Any) -> tuple[str, ...]:
        raw = arguments.get(field)
        if strip:
            raw = str(raw or "").strip()
        return (_canonical_path(raw, default),)

    return resolve


def _vault_root() -> str:
    from core.memory.vault import Vault

    return _canonical_path(Vault().vault_dir)


def _export_resources(arguments: Any) -> tuple[str, ...]:
    output_dir = Path(str(arguments.get("output_dir") or ".")).expanduser()
    filename = str(arguments.get("filename") or "").strip()
    target = output_dir / filename if filename else output_dir
    return (_canonical_path(target), _vault_root())


def _document_resources(arguments: Any) -> tuple[str, ...]:
    if output_dir := arguments.get("output_dir"):
        return (_canonical_path(output_dir),)
    from core.paths import get_project_root

    return (_canonical_path(get_project_root() / ".geode" / "documents"),)


def _viz_resources(arguments: Any) -> tuple[str, ...]:
    chart = str(arguments.get("chart") or "heatmap").lower()
    return (_canonical_path(arguments.get("output_path"), f"./reports/{chart}.png"),)


def _trimmed_resource(field: str) -> Any:
    def resolve(arguments: Any) -> tuple[str, ...]:
        return (str(arguments.get(field, "")).strip(),)

    return resolve


def _google_remote_item_resource(field: str) -> Any:
    def resolve(arguments: Any) -> tuple[str, ...]:
        if str(arguments.get("action", "")) == "create":
            return ("new",)
        return (str(arguments.get(field, "")).strip(),)

    return resolve


def _google_task_resource(arguments: Any) -> tuple[str, ...]:
    tasklist = str(arguments.get("tasklist_id", "@default"))
    task = (
        "new"
        if str(arguments.get("action", "")) == "create"
        else str(arguments.get("task_id", "")).strip()
    )
    return (json.dumps((tasklist, task), separators=(",", ":")),)


def _google_drive_resource(arguments: Any) -> tuple[str, ...]:
    parent = str(arguments.get("parent_id") or "").strip() or "root"
    name = str(arguments.get("name") or "").strip()
    return (json.dumps((parent, name), separators=(",", ":")),)


def _notification_resource(arguments: Any) -> tuple[str, ...]:
    channel = str(arguments.get("channel", ""))
    recipient = str(arguments.get("recipient", "default"))
    return (json.dumps((channel, recipient), separators=(",", ":")),)


def _resource_metadata() -> dict[str, tuple[str, Any]]:
    """Return explicit resource strategies; field selection is never inferred."""
    constant = _constant_resource
    selected = _selected_resource
    return {
        "generate_report": ("local-path:v1", lambda _arguments: (_vault_root(),)),
        "export_json": ("local-path:v1", _export_resources),
        "switch_model": ("runtime-model:v1", constant("active-model")),
        "memory_save": ("project-memory:v1", constant("memory")),
        "manage_rule": ("project-rules:v1", constant("rules")),
        "set_api_key": ("auth-store:v1", constant("auth")),
        "manage_auth": ("auth-store:v1", constant("auth")),
        "manage_login": ("auth-store:v1", constant("auth")),
        "schedule_job": ("scheduler-calendar:v1", constant("scheduler")),
        "trigger_event": ("runtime-event:v1", selected("event_name")),
        "run_bash": ("local-shell:v1", constant("shell")),
        "computer_use": ("desktop-control:v1", constant("desktop")),
        "delegate_task": ("subagent-session:v1", constant("children")),
        "spawn_agent": ("subagent-session:v1", constant("children")),
        "interrupt_agent": ("subagent-task:v1", selected("task_id")),
        "send_message": ("subagent-task:v1", selected("task_id")),
        "followup_task": ("subagent-task:v1", selected("task_id")),
        "create_goal": ("active-goal:v1", constant("goal")),
        "update_goal": ("active-goal:v1", constant("goal")),
        "update_plan": ("turn-plan:v1", constant("plan")),
        "create_plan": ("review-plan:v1", constant("plans")),
        "approve_plan": ("review-plan:v1", constant("plans")),
        "reject_plan": ("review-plan:v1", constant("plans")),
        "modify_plan": ("review-plan:v1", constant("plans")),
        "document_ingest": ("local-path:v1", _document_resources),
        "edit_file": ("local-path:v1", _path_resource("file_path")),
        "write_file": ("local-path:v1", _path_resource("file_path")),
        "note_save": ("project-memory:v1", constant("memory")),
        "rate_result": ("result-feedback:v1", selected("subject")),
        "accept_result": ("result-feedback:v1", selected("subject")),
        "reject_result": ("result-feedback:v1", selected("subject")),
        "profile_update": ("user-profile:v1", constant("profile")),
        "profile_preference": ("user-profile:v1", constant("profile")),
        "profile_learn": ("user-profile:v1", constant("profile")),
        "send_notification": ("notification:v1", _notification_resource),
        "gmail_send": ("google-mailbox:v1", constant("mailbox")),
        "google_drive_create": (
            "google-drive-parent:v1",
            _google_drive_resource,
        ),
        "google_docs_write": (
            "google-document:v1",
            _google_remote_item_resource("document_id"),
        ),
        "google_sheets_write": (
            "google-sheet:v1",
            _google_remote_item_resource("spreadsheet_id"),
        ),
        "google_tasks_write": (
            "google-task:v1",
            _google_task_resource,
        ),
        "calendar_create_event": ("scheduler-calendar:v1", constant("calendar")),
        "calendar_sync_scheduler": (
            "scheduler-calendar:v1",
            lambda _arguments: ("scheduler", "calendar"),
        ),
        "manage_context": ("session-context:v1", constant("context")),
        "task_create": ("tracked-task:v1", constant("tasks")),
        "task_update": ("tracked-task:v1", selected("task_id")),
        "task_stop": ("tracked-task:v1", selected("task_id")),
        "petri_audit": ("petri-runtime:v1", constant("audit")),
        "obs_otel_export": ("observability-config:v1", constant("otel")),
        "eval_inspect_viz": ("local-path:v1", _viz_resources),
        "eval_dspy_optimize": (
            "local-path:v1",
            _path_resource("output_dir", "optimized_prompts"),
        ),
        "seed_debate_turn": (
            "local-path:v1",
            _path_resource("sidecar_path", strip=True),
        ),
        "freeze_paper_snapshot": ("paper-snapshot:v1", _trimmed_resource("arxiv_id")),
        "browser_execute_js": ("browser-session:v1", constant("browser")),
    }


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
    """Return a mutable compatibility copy of the validated product catalog."""
    bound, transient_handlers = compose_tool_plan(
        verbose=verbose,
        mcp_manager=mcp_manager,
        skill_registry=skill_registry,
    )
    return {**bound.handlers, **transient_handlers}


def compose_tool_plan(
    *,
    verbose: bool = False,
    mcp_manager: Any = None,
    skill_registry: Any = None,
    previous: BoundToolPlan | None = None,
) -> tuple[BoundToolPlan, dict[str, Any]]:
    """Bind one product plan and its non-schema execution overlays."""
    from core.agent.safety import (
        COMPUTER_USE_TOOLS,
        DANGEROUS_TOOLS,
        EXPENSIVE_TOOLS,
        HEADLESS_DENIED_TOOLS,
        SENSITIVE_TOOLS,
        WRITE_TOOLS,
    )
    from core.agent.sub_agent import SUBAGENT_DENIED_TOOLS
    from core.agent.tool_executor.executor import SPECIAL_EXECUTION_BINDINGS
    from core.cli.tool_handlers import cli_handler_groups
    from core.llm.tool_defer import default_deferred_tool_names
    from core.slash_routing import compose_command_registry
    from core.tools.base import load_all_tool_definitions
    from core.tools.google_capabilities import GOOGLE_TOOL_BINDINGS, GOOGLE_WRITE_TOOLS
    from core.tools.handlers import _build_tool_handler_catalog, neutral_handler_groups
    from core.tools.personal_data import PERSONAL_DATA_TOOLS
    from core.tools.plan import (
        ApprovalPolicy,
        CapabilityRequirement,
        DataClassification,
        ExecutionBinding,
        PersistenceRule,
        ProfileRestriction,
        SafetyPolicy,
        ToolEffect,
        ToolSpec,
        bind_tool_plan,
        compile_tool_plan,
    )

    from geode_product.slash_commands import PRODUCT_COMMAND_SPECS

    catalog = _build_tool_handler_catalog(
        (
            *neutral_handler_groups(
                mcp_manager=mcp_manager,
                skill_registry=skill_registry,
            ),
            *cli_handler_groups(
                mcp_manager=mcp_manager,
                command_registry=compose_command_registry(PRODUCT_COMMAND_SPECS),
            ),
            *product_handler_groups(),
        )
    )
    if invalid := [name for name, handler in catalog.handlers.items() if not callable(handler)]:
        raise TypeError(f"tool handlers must be callable: {', '.join(invalid)}")
    definitions = load_all_tool_definitions()
    specs = tuple(
        (
            ToolSpec(
                name=item["name"],
                description=item["description"],
                input_schema=item["input_schema"],
            ),
            f"core/tools/definitions.json[{index}]",
        )
        for index, item in enumerate(definitions)
    )
    resource_metadata = _resource_metadata()
    definition_names = {item["name"] for item in definitions}
    if unknown := sorted(resource_metadata.keys() - definition_names):
        raise ValueError(f"resource metadata references unknown tools: {', '.join(unknown)}")
    bindings = tuple(
        ExecutionBinding(
            name=name,
            origin=catalog.origins[name],
            resource_strategy=resource_metadata.get(name, ("none", None))[0],
        )
        for name in catalog.handlers
        if name not in _INTERNAL_ONLY_HANDLERS
    ) + tuple(
        ExecutionBinding(
            name=name,
            origin="core.agent.tool_executor.special",
            route="special",
            resource_strategy=resource_metadata.get(name, ("none", None))[0],
        )
        for name in sorted(SPECIAL_EXECUTION_BINDINGS)
    )
    gated = DANGEROUS_TOOLS | SENSITIVE_TOOLS | WRITE_TOOLS | set(EXPENSIVE_TOOLS)
    profile_write_tools = {
        "memory_save",
        "note_save",
        "set_api_key",
        "manage_login",
        "profile_update",
        *GOOGLE_WRITE_TOOLS,
    }
    safety = {
        item["name"]: SafetyPolicy(
            effect=(
                ToolEffect.ADMINISTRATIVE
                if item["name"] in _ADMINISTRATIVE_TOOLS
                else ToolEffect.COMMUNICATE
                if item["name"] in _COMMUNICATION_TOOLS
                else ToolEffect.EXECUTE
                if item["name"] in _EXECUTION_TOOLS
                else ToolEffect.MUTATE
                if item["name"] in resource_metadata
                else ToolEffect.READ
            ),
            data_class=(
                DataClassification.PERSONAL
                if item["name"] in PERSONAL_DATA_TOOLS
                else DataClassification.PUBLIC
            ),
            persistence=(
                PersistenceRule.REDACT
                if item["name"] in PERSONAL_DATA_TOOLS
                else PersistenceRule.PERSIST
            ),
            approval=(
                ApprovalPolicy.PER_INVOCATION
                if item["name"] in SENSITIVE_TOOLS
                else ApprovalPolicy.CACHED
                if item["name"] in gated
                else ApprovalPolicy.NONE
            ),
            allow_headless=(
                item["name"] not in HEADLESS_DENIED_TOOLS or item["name"] in COMPUTER_USE_TOOLS
            ),
            allow_subagents=item["name"] not in SUBAGENT_DENIED_TOOLS,
            profile_restrictions=tuple(
                restriction
                for restriction, names in (
                    (ProfileRestriction.WRITE, profile_write_tools),
                    (ProfileRestriction.DANGEROUS, {"run_bash"}),
                    (ProfileRestriction.EXPENSIVE, set(EXPENSIVE_TOOLS)),
                )
                if item["name"] in names
            ),
        )
        for item in definitions
    }
    capabilities = {
        name: CapabilityRequirement(
            services=tuple(dict.fromkeys((*binding.read_services, *binding.write_services))),
            auth=("google-oauth",),
        )
        for name, binding in GOOGLE_TOOL_BINDINGS.items()
        if binding.handler_class is not None
    }
    plan = compile_tool_plan(
        specs,
        bindings,
        safety=safety,
        capabilities=capabilities,
        deferred_tools=default_deferred_tool_names(item["name"] for item in definitions),
        previous=previous.plan if previous is not None else None,
    )
    ordinary_handlers = {
        name: catalog.handlers[name]
        for name, binding in plan.execution_map.items()
        if binding.route == "handler"
    }
    bound = bind_tool_plan(
        plan,
        ordinary_handlers,
        {
            name: resolver
            for name, (_strategy, resolver) in resource_metadata.items()
            if name in plan.schema_map
        },
    )
    transient_handlers = {name: catalog.handlers[name] for name in _INTERNAL_ONLY_HANDLERS}
    return bound, transient_handlers


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
