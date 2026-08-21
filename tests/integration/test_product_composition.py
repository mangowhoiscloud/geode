"""Behavioral boundary checks for the first-party product shell."""

from __future__ import annotations

import asyncio
import runpy
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

PRODUCT_TOOLS = {
    "petri_audit",
    "eval_inspect_viz",
    "eval_dspy_optimize",
    "geode_seed_pool_search",
    "seed_debate_turn",
    "freeze_paper_snapshot",
}
_INTERNAL_ONLY_HANDLERS = {"computer", "doctor_slack", "recall_tool_result"}
_PRODUCT_HANDLER_ORIGINS = {
    "eval_dspy_optimize": "product-audit",
    "eval_inspect_viz": "product-audit",
    "freeze_paper_snapshot": "product-seed",
    "geode_seed_pool_search": "product-seed",
    "petri_audit": "product-audit",
    "seed_debate_turn": "product-seed",
}


def _handler(**_: Any) -> dict[str, bool]:
    return {"ok": True}


def test_product_tools_are_added_only_by_product_composition() -> None:
    from core.cli.tool_handlers import _build_tool_handlers
    from geode_product.tool_handlers import build_tool_handlers

    assert PRODUCT_TOOLS.isdisjoint(_build_tool_handlers())
    assert build_tool_handlers().keys() >= PRODUCT_TOOLS


def test_product_cli_owns_config_commands() -> None:
    from core.cli.commands.config import build_config_app
    from geode_product import cli

    assert {command.name for command in build_config_app().registered_commands} == {"explain"}
    assert {command.name for command in cli.config_app.registered_commands} == {
        "explain",
        "migrate-petri-toml",
    }


def test_product_show_help_uses_the_same_slash_registry() -> None:
    from geode_product.tool_handlers import build_tool_handlers

    result = build_tool_handlers()["show_help"]()

    assert set(result["commands"]) >= {
        "/audit",
        "/audit-seeds",
        "/geo",
        "/petri",
        "/recall",
        "/self-improving",
    }


def test_product_slash_commands_do_not_mutate_kernel_registry() -> None:
    from core.cli.routing import COMMAND_REGISTRY, compose_command_registry
    from geode_product.slash_commands import PRODUCT_COMMAND_SPECS

    product_registry = compose_command_registry(PRODUCT_COMMAND_SPECS)
    assert {"/audit", "/recall", "/self-improving"}.isdisjoint(COMMAND_REGISTRY)
    assert product_registry.keys() >= {
        "/audit",
        "/audit-seeds",
        "/petri",
        "/recall",
        "/self-improving",
    }


def test_product_owns_self_improving_typer_commands() -> None:
    import typer
    from core.cli import app as kernel_app
    from geode_product.cli import app as product_app

    kernel_commands = typer.main.get_command(kernel_app).commands
    product_commands = typer.main.get_command(product_app).commands

    assert "serve" not in kernel_commands
    assert "serve" in product_commands
    assert {"campaign", "outer-bundle"}.isdisjoint(kernel_commands)
    assert {"campaign", "outer-bundle"} <= product_commands.keys()


def test_daemon_composition_supplies_product_workers_tools_and_prompts(monkeypatch) -> None:
    from core.server.supervised import services
    from core.slash_routing import compose_command_registry
    from geode_product import wiring
    from geode_product.slash_commands import PRODUCT_COMMAND_SPECS
    from geode_product.tool_handlers import compose_tool_plan

    build_core = Mock(return_value="services")
    policy_sources = object()
    monkeypatch.setattr(services, "build_shared_services", build_core)
    monkeypatch.setattr(wiring, "build_policy_sources", Mock(return_value=policy_sources))

    assert wiring.build_shared_services(marker=True) == "services"
    assert build_core.call_args.kwargs == {
        "marker": True,
        "tool_plan_builder": compose_tool_plan,
        "worker_module": "geode_product.worker",
        "agent_search_dirs": (Path(wiring.__file__).parent / "seed_generation" / "agents",),
        "policy_sources": policy_sources,
        "middleware_builder": wiring.build_middleware_registry,
        "activity_sink_provider": wiring.current_activity_sink,
        "feature_hook_registrar": wiring.register_hooks,
        "command_registry": compose_command_registry(PRODUCT_COMMAND_SPECS),
    }


def test_worker_module_supplies_the_product_handler_builder(monkeypatch) -> None:
    from core.agent import worker
    from geode_product.tool_handlers import compose_tool_plan
    from geode_product.wiring import (
        bind_worker_activity,
        build_middleware_registry,
        current_activity_sink,
    )

    main = Mock()
    monkeypatch.setattr(worker, "main", main)

    runpy.run_module("geode_product.worker", run_name="__main__")

    main.assert_called_once_with(
        compose_tool_plan,
        middleware_builder=build_middleware_registry,
        activity_sink_provider=current_activity_sink,
        worker_activity_binder=bind_worker_activity,
    )


def test_mcp_entrypoint_supplies_the_product_handler_builder(monkeypatch) -> None:
    from geode_product import mcp_server
    from geode_product.self_improving.mcp import register_mcp_tools
    from geode_product.tool_handlers import compose_tool_plan

    run_mcp_server = Mock()
    monkeypatch.setattr(mcp_server, "run_mcp_server", run_mcp_server)

    mcp_server.main()

    run_mcp_server.assert_called_once_with(
        compose_tool_plan,
        agent_runner=mcp_server.run_agent,
        feature_registrar=register_mcp_tools,
    )


def test_product_mcp_runner_reuses_one_resource_lock_pool(monkeypatch) -> None:
    from geode_product import mcp_server

    captured: list[object] = []

    async def fake_run(_prompt: str, **kwargs: object) -> None:
        captured.append(kwargs["resource_lock_pool"])

    monkeypatch.setattr(mcp_server, "arun_agentic_oneshot", fake_run)

    asyncio.run(mcp_server.run_agent("one"))
    asyncio.run(mcp_server.run_agent("two"))

    assert captured == [mcp_server._RESOURCE_LOCK_POOL, mcp_server._RESOURCE_LOCK_POOL]


def test_model_definitions_and_execution_surfaces_have_exact_parity() -> None:
    from core.agent.tool_executor.executor import SPECIAL_EXECUTION_BINDINGS
    from core.tools.base import load_all_tool_definitions
    from geode_product.tool_handlers import compose_tool_plan

    definitions = {item["name"] for item in load_all_tool_definitions()}
    bound, transient_handlers = compose_tool_plan()
    handlers = set(bound.handlers)
    special_bindings = set(SPECIAL_EXECUTION_BINDINGS)
    executable = handlers | special_bindings

    assert handlers.isdisjoint(special_bindings)
    assert executable == definitions == set(bound.tool_names)
    assert set(transient_handlers) == _INTERNAL_ONLY_HANDLERS


def test_product_handlers_retain_their_composition_origins() -> None:
    from geode_product.tool_handlers import compose_tool_plan

    bound, _transient_handlers = compose_tool_plan()
    assert {
        name: bound.execution_map[name].origin for name in _PRODUCT_HANDLER_ORIGINS
    } == _PRODUCT_HANDLER_ORIGINS


def test_product_handler_collision_fails_before_catalog_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.tools.handlers.registration import UniqueEntries
    from geode_product import tool_handlers

    conflicting_groups = (
        *tool_handlers.product_handler_groups(),
        ("product-conflict", UniqueEntries((("petri_audit", _handler),))),
    )
    monkeypatch.setattr(tool_handlers, "product_handler_groups", lambda: conflicting_groups)

    with pytest.raises(
        ValueError,
        match=(
            r"duplicate tool handler registration: 'petri_audit' "
            r"\(product-audit vs product-conflict\)"
        ),
    ):
        tool_handlers.compose_tool_plan()


def test_product_composition_rejects_non_callable_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.tools.handlers.registration import UniqueEntries
    from geode_product.tool_handlers import compose_tool_plan

    monkeypatch.setattr(
        "core.tools.handlers.neutral_handler_groups",
        lambda **_kwargs: (("broken-source", UniqueEntries((("broken", None),))),),
    )

    with pytest.raises(TypeError, match="tool handlers must be callable: broken"):
        compose_tool_plan()


def test_provider_tool_projections_preserve_existing_wire_payloads() -> None:
    from core.llm.adapters._anthropic_common import translate_tool as translate_anthropic_tool
    from core.llm.adapters._openai_common import translate_tool as translate_openai_tool
    from core.llm.adapters.base import ToolSpec
    from core.tools.base import load_all_tool_definitions

    definitions = load_all_tool_definitions()
    specs = tuple(
        ToolSpec(
            name=item["name"],
            description=item["description"],
            input_schema=item["input_schema"],
        )
        for item in definitions
    )

    assert list(map(translate_anthropic_tool, specs)) == [
        {
            "name": item["name"],
            "description": item["description"],
            "input_schema": item["input_schema"],
        }
        for item in definitions
    ]
    assert list(map(translate_openai_tool, specs)) == [
        {
            "type": "function",
            "function": {
                "name": item["name"],
                "description": item["description"],
                "parameters": item["input_schema"],
            },
        }
        for item in definitions
    ]


def test_product_composition_compiles_one_lossless_immutable_plan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.agent.tool_executor.executor import SPECIAL_EXECUTION_BINDINGS
    from core.tools.base import load_all_tool_definitions
    from core.tools.google_capabilities import GOOGLE_TOOL_BINDINGS
    from core.tools.plan import (
        ApprovalPolicy,
        DataClassification,
        PersistenceRule,
        ProfileRestriction,
        ToolEffect,
    )
    from geode_product.tool_handlers import compose_tool_plan

    definitions = load_all_tool_definitions()
    bound, transient_handlers = compose_tool_plan()
    rebuilt, rebuilt_transient = compose_tool_plan(previous=bound)
    plan = bound.plan

    assert rebuilt.plan is plan
    assert list(plan.schema_map) == [item["name"] for item in definitions]
    assert set(plan.schema_map) == set(plan.execution_map)
    assert list(bound.handlers) == [
        name for name, binding in plan.execution_map.items() if binding.route == "handler"
    ]
    assert list(rebuilt.handlers) == list(bound.handlers)
    assert set(transient_handlers) == set(rebuilt_transient) == _INTERNAL_ONLY_HANDLERS
    assert {
        name for name, binding in plan.execution_map.items() if binding.route == "special"
    } == set(SPECIAL_EXECUTION_BINDINGS)
    assert plan.execution_map["petri_audit"].origin == "product-audit"

    policies = {item.spec.name: item.safety for item in plan.registrations}
    assert policies["run_bash"].effect is ToolEffect.EXECUTE
    assert policies["edit_file"].effect is ToolEffect.MUTATE
    assert policies["gmail_send"].effect is ToolEffect.COMMUNICATE
    assert policies["manage_auth"].effect is ToolEffect.ADMINISTRATIVE
    assert policies["gmail_search"].data_class is DataClassification.PERSONAL
    assert policies["gmail_search"].persistence is PersistenceRule.REDACT
    assert policies["gmail_search"].approval is ApprovalPolicy.PER_INVOCATION
    assert policies["gmail_search"].consent_required is True
    assert policies["gmail_search"].approval_cacheable is False
    assert policies["gmail_search"].allow_headless is False
    assert policies["gmail_search"].allow_subagents is False
    assert policies["computer_use"].allow_headless is True
    assert policies["run_bash"].profile_restrictions == (ProfileRestriction.DANGEROUS,)
    assert policies["memory_save"].profile_restrictions == (ProfileRestriction.WRITE,)
    assert policies["petri_audit"].profile_restrictions == (ProfileRestriction.EXPENSIVE,)

    from core.tools.policy import ProfilePolicy, apply_profile_policy

    default_profile = apply_profile_policy(bound, ProfilePolicy())
    assert "run_bash" not in default_profile.tool_names
    assert "memory_save" in default_profile.tool_names
    restricted_profile = apply_profile_policy(
        bound,
        ProfilePolicy(allow_expensive=False, allow_write=False, allow_dangerous=True),
    )
    assert "run_bash" in restricted_profile.tool_names
    assert "memory_save" not in restricted_profile.tool_names
    assert "petri_audit" not in restricted_profile.tool_names

    resource_names = {
        name for name, binding in plan.execution_map.items() if binding.resource_strategy != "none"
    }
    assert set(bound.resource_key_resolvers) == resource_names
    file_path = str(tmp_path / "private.txt")
    assert bound.resource_keys("edit_file", {"file_path": file_path}) == bound.resource_keys(
        "write_file", {"file_path": file_path}
    )
    edit_keys = bound.resource_keys("edit_file", {"file_path": file_path})
    assert edit_keys == bound.resource_keys(
        "edit_file",
        {"file_path": file_path, "old_string": "private-a", "new_string": "private-b"},
    )
    assert edit_keys != bound.resource_keys("edit_file", {"file_path": str(tmp_path / "other.txt")})
    monkeypatch.chdir(tmp_path)
    assert edit_keys == bound.resource_keys("write_file", {"file_path": "./private.txt"})
    assert file_path not in "".join(edit_keys)
    assert rebuilt.resource_keys("edit_file", {"file_path": file_path}) == bound.resource_keys(
        "edit_file", {"file_path": file_path}
    )
    assert set(bound.resource_keys("generate_report", {"subject": "a"})) & set(
        bound.resource_keys("export_json", {"output_dir": tmp_path})
    )
    assert bound.resource_keys("eval_inspect_viz", {"chart": "cost"}) == bound.resource_keys(
        "eval_inspect_viz",
        {"output_path": "./reports/cost.png"},
    )
    sidecar = str(tmp_path / "seed.debate.jsonl")
    assert bound.resource_keys(
        "seed_debate_turn", {"sidecar_path": sidecar}
    ) == bound.resource_keys("seed_debate_turn", {"sidecar_path": f" {sidecar} "})
    assert bound.resource_keys("memory_save", {"key": "a"}) == bound.resource_keys(
        "note_save", {"key": "b"}
    )
    assert bound.resource_keys("manage_rule", {"name": "Foo Bar"}) == bound.resource_keys(
        "manage_rule", {"name": "foo-bar"}
    )
    assert bound.resource_keys("create_plan", {}) == bound.resource_keys(
        "modify_plan", {"plan_id": "plan-a"}
    )
    assert bound.resource_keys("reject_plan", {"plan_id": "missing-a"}) == bound.resource_keys(
        "modify_plan", {"plan_id": ""}
    )
    assert bound.resource_keys("schedule_job", {"expression": "daily"}) == bound.resource_keys(
        "schedule_job", {"target_id": "job-1"}
    )
    assert bound.resource_keys("send_notification", {"channel": "slack"}) == bound.resource_keys(
        "send_notification", {"channel": "slack", "recipient": "default"}
    )
    sync_keys = set(bound.resource_keys("calendar_sync_scheduler", {}))
    assert sync_keys & set(bound.resource_keys("schedule_job", {"target_id": "job-1"}))
    assert sync_keys & set(bound.resource_keys("calendar_create_event", {}))
    absolute_export = str(tmp_path / "shared.json")
    assert bound.resource_keys(
        "export_json", {"output_dir": tmp_path / "one", "filename": absolute_export}
    ) == bound.resource_keys(
        "export_json", {"output_dir": tmp_path / "two", "filename": absolute_export}
    )
    assert bound.resource_keys(
        "google_docs_write", {"document_id": " doc-1 ", "title": "old"}
    ) == bound.resource_keys("google_docs_write", {"document_id": "doc-1", "title": "new"})
    assert bound.resource_keys(
        "google_docs_write", {"action": "create", "document_id": "ignored-a"}
    ) == bound.resource_keys("google_docs_write", {"action": "create", "document_id": "ignored-b"})
    assert bound.resource_keys("google_drive_create", {"name": " x "}) == bound.resource_keys(
        "google_drive_create", {"parent_id": "", "name": "x"}
    )
    assert bound.resource_keys(
        "google_drive_create", {"parent_id": " root ", "name": "x"}
    ) == bound.resource_keys("google_drive_create", {"parent_id": "root", "name": " x "})
    assert bound.resource_keys(
        "google_sheets_write", {"spreadsheet_id": "sheet-1", "title": "old"}
    ) == bound.resource_keys("google_sheets_write", {"spreadsheet_id": "sheet-1", "title": "new"})
    assert bound.resource_keys(
        "google_sheets_write", {"action": "create", "spreadsheet_id": "ignored-a"}
    ) == bound.resource_keys(
        "google_sheets_write", {"action": "create", "spreadsheet_id": "ignored-b"}
    )
    assert bound.resource_keys(
        "google_tasks_write", {"tasklist_id": "list-1", "task_id": "task-1", "title": "old"}
    ) == bound.resource_keys(
        "google_tasks_write", {"tasklist_id": "list-1", "task_id": "task-1", "title": "new"}
    )
    assert bound.resource_keys(
        "google_tasks_write",
        {"action": "create", "tasklist_id": "list-1", "task_id": "ignored-a"},
    ) == bound.resource_keys(
        "google_tasks_write",
        {"action": "create", "tasklist_id": "list-1", "task_id": "ignored-b"},
    )

    capabilities = {item.spec.name: item.capability for item in plan.registrations}
    for name, binding in GOOGLE_TOOL_BINDINGS.items():
        if binding.handler_class is None:
            assert capabilities[name].services == ()
            assert capabilities[name].auth == ()
        else:
            assert capabilities[name].services == tuple(
                sorted({*binding.read_services, *binding.write_services})
            )
            assert capabilities[name].auth == ("google-oauth",)
        assert capabilities[name].available is True
        assert plan.outcomes[name].value == "enabled"
