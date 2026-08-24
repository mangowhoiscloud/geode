"""Native GEODE tool-plan composition.

Evaluation callers may add explicit handler groups and metadata. The runtime
never imports those outer packages.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.slash_routing import CommandSpec
from core.tools.handlers import ToolIntegrationServices, ToolPersistenceServices
from core.tools.handlers.registration import UniqueEntries

if TYPE_CHECKING:
    from core.tools.plan import BoundToolPlan

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
        "update_grill": ("grill-session:v1", constant("grill")),
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
        "obs_otel_export": ("observability-config:v1", constant("otel")),
        "browser_execute_js": ("browser-session:v1", constant("browser")),
    }


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
    persistence: ToolPersistenceServices | None = None,
    integrations: ToolIntegrationServices | None = None,
    hooks: Any = None,
    scheduler_service: Any = None,
    handler_groups: Sequence[tuple[str, UniqueEntries[str, Any]]] = (),
    command_specs: Sequence[CommandSpec] = (),
    resource_metadata: Mapping[str, tuple[str, Any]] | None = None,
    execution_tools: frozenset[str] = frozenset(),
) -> tuple[BoundToolPlan, dict[str, Any]]:
    """Bind one native plan plus explicit outer contributions."""
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

    catalog = _build_tool_handler_catalog(
        (
            *neutral_handler_groups(
                mcp_manager=mcp_manager,
                skill_registry=skill_registry,
                persistence=persistence,
                integrations=integrations,
            ),
            *cli_handler_groups(
                mcp_manager=mcp_manager,
                command_registry=compose_command_registry(command_specs),
                hooks=hooks,
                project_memory=(persistence.memory.project_memory if persistence else None),
                scheduler_service=scheduler_service,
            ),
            *handler_groups,
        )
    )
    if invalid := [name for name, handler in catalog.handlers.items() if not callable(handler)]:
        raise TypeError(f"tool handlers must be callable: {', '.join(invalid)}")
    definitions = load_all_tool_definitions()
    enabled_names = (set(catalog.handlers) - _INTERNAL_ONLY_HANDLERS) | set(
        SPECIAL_EXECUTION_BINDINGS
    )
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
        if item["name"] in enabled_names
    )
    resolved_resource_metadata = {**_resource_metadata(), **(resource_metadata or {})}
    definition_names = {item["name"] for item in definitions}
    if unknown := sorted(resolved_resource_metadata.keys() - definition_names):
        raise ValueError(f"resource metadata references unknown tools: {', '.join(unknown)}")
    bindings = tuple(
        ExecutionBinding(
            name=name,
            origin=catalog.origins[name],
            resource_strategy=resolved_resource_metadata.get(name, ("none", None))[0],
        )
        for name in catalog.handlers
        if name not in _INTERNAL_ONLY_HANDLERS
    ) + tuple(
        ExecutionBinding(
            name=name,
            origin="core.agent.tool_executor.special",
            route="special",
            resource_strategy=resolved_resource_metadata.get(name, ("none", None))[0],
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
                if item["name"] in _EXECUTION_TOOLS or item["name"] in execution_tools
                else ToolEffect.MUTATE
                if item["name"] in resolved_resource_metadata
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
        if item["name"] in enabled_names
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
        deferred_tools=default_deferred_tool_names(spec.name for spec, _origin in specs),
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
            for name, (_strategy, resolver) in resolved_resource_metadata.items()
            if name in plan.schema_map
        },
    )
    transient_handlers = {name: catalog.handlers[name] for name in _INTERNAL_ONLY_HANDLERS}
    return bound, transient_handlers
