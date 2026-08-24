"""Behavioral checks for the runtime, evaluation, and evolution roots."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

EVALUATION_TOOLS = {
    "petri_audit",
    "eval_inspect_viz",
    "eval_dspy_optimize",
    "geode_seed_pool_search",
    "seed_debate_turn",
    "freeze_paper_snapshot",
}
_INTERNAL_ONLY_HANDLERS = {"computer", "doctor_slack", "recall_tool_result"}
_EVALUATION_HANDLER_ORIGINS = {
    "eval_dspy_optimize": "eval-audit",
    "eval_inspect_viz": "eval-audit",
    "freeze_paper_snapshot": "eval-seed",
    "geode_seed_pool_search": "eval-seed",
    "petri_audit": "eval-audit",
    "seed_debate_turn": "eval-seed",
}


def _handler(**_: Any) -> dict[str, bool]:
    return {"ok": True}


def test_evaluation_tools_are_added_only_by_evaluation_composition() -> None:
    from core.cli.tool_handlers import _build_tool_handlers
    from core.tools.composition import build_tool_handlers as build_native_handlers
    from evals.composition import build_tool_handlers as build_evaluation_handlers

    assert EVALUATION_TOOLS.isdisjoint(_build_tool_handlers())
    assert EVALUATION_TOOLS.isdisjoint(build_native_handlers())
    assert build_evaluation_handlers().keys() >= EVALUATION_TOOLS


def test_evaluation_cli_owns_migration_commands() -> None:
    from core.cli.commands.config import build_config_app
    from evals import cli

    assert {command.name for command in build_config_app().registered_commands} == {"explain"}
    assert {command.name for command in cli.config_app.registered_commands} == {
        "explain",
        "migrate-petri-toml",
    }


def test_evaluation_show_help_uses_only_evaluation_commands() -> None:
    from core.tools.composition import build_tool_handlers as build_native_handlers
    from evals.composition import build_tool_handlers as build_evaluation_handlers

    native = build_native_handlers()["show_help"]()
    result = build_evaluation_handlers()["show_help"]()

    assert {"/audit", "/geo", "/self-improving"}.isdisjoint(native["commands"])
    assert set(result["commands"]) >= {
        "/audit",
        "/audit-seeds",
        "/geo",
        "/petri",
    }
    assert {"/recall", "/self-improving"}.isdisjoint(result["commands"])


def test_outer_slash_commands_do_not_mutate_runtime_registry() -> None:
    from core.cli.routing import COMMAND_REGISTRY, compose_command_registry
    from evals.slash_commands import EVAL_COMMAND_SPECS
    from evolve.slash_commands import EVOLVE_COMMAND_SPECS

    evaluation_registry = compose_command_registry(EVAL_COMMAND_SPECS)
    evolution_registry = compose_command_registry(EVOLVE_COMMAND_SPECS)
    assert {"/audit", "/recall", "/self-improving"}.isdisjoint(COMMAND_REGISTRY)
    assert evaluation_registry.keys() >= {
        "/audit",
        "/audit-seeds",
        "/petri",
    }
    assert evolution_registry.keys() >= {"/recall", "/self-improving"}


def test_three_cli_entrypoints_have_disjoint_ownership() -> None:
    import typer
    from core.cli import app as runtime_app
    from evals.cli import app as evaluation_app
    from evolve.cli import app as evolution_app

    runtime_commands = typer.main.get_command(runtime_app).commands
    evaluation_commands = typer.main.get_command(evaluation_app).commands
    evolution_commands = typer.main.get_command(evolution_app).commands

    assert "serve" in runtime_commands
    assert {"audit", "audit-seeds", "benchmark", "petri"} <= evaluation_commands.keys()
    assert {
        "campaign",
        "outer-bundle",
        "crucible",
        "mcp",
        "recall",
        "scaffold",
    } <= evolution_commands.keys()
    assert {"audit", "campaign", "outer-bundle"}.isdisjoint(runtime_commands)


def test_evolution_scaffold_command_forwards_existing_actions(monkeypatch) -> None:
    from evolve import cli
    from typer.testing import CliRunner

    dispatched: list[str] = []
    monkeypatch.setattr(cli, "cmd_self_improving", dispatched.append)

    result = CliRunner().invoke(cli.app, ["scaffold", "status"])

    assert result.exit_code == 0
    assert dispatched == ["status"]


@pytest.mark.parametrize(
    ("module_name", "command", "handler_name", "args"),
    (
        ("evals.cli", "petri", "cmd_petri", ("model", "judge", "gpt-5.5")),
        ("evolve.cli", "recall", "cmd_recall", ("show", "operator-notes")),
    ),
)
def test_outer_cli_commands_forward_existing_dispatchers(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    command: str,
    handler_name: str,
    args: tuple[str, ...],
) -> None:
    import importlib

    from typer.testing import CliRunner

    module = importlib.import_module(module_name)
    dispatched: list[str] = []
    monkeypatch.setattr(module, handler_name, dispatched.append)

    result = CliRunner().invoke(module.app, [command, *args])

    assert result.exit_code == 0
    assert dispatched == [" ".join(args)]


def test_daemon_composition_supplies_only_native_workers_and_tools(monkeypatch) -> None:
    from core.cli import commands as cli_commands
    from core.server.supervised import services
    from core.tools.composition import compose_tool_plan
    from core.wiring import runtime as wiring

    build_core = Mock(return_value="services")
    policy_sources = object()
    monkeypatch.setattr(services, "build_shared_services", build_core)
    monkeypatch.setattr(wiring, "build_policy_sources", Mock(return_value=policy_sources))
    monkeypatch.setattr(cli_commands, "_get_cost_budget", lambda: 7.5)

    assert wiring.build_shared_services(marker=True) == "services"
    assert build_core.call_args.kwargs == {
        "marker": True,
        "tool_plan_builder": compose_tool_plan,
        "worker_module": "core.worker",
        "policy_sources": policy_sources,
        "middleware_builder": wiring.build_middleware_registry,
        "cost_budget": 7.5,
    }


def test_worker_module_supplies_native_composition(monkeypatch) -> None:
    from core import worker
    from core.tools.composition import compose_tool_plan
    from core.wiring.runtime import build_middleware_registry

    worker_main = Mock()
    monkeypatch.setattr(worker, "run_worker", worker_main)

    worker.main()

    worker_main.assert_called_once_with(
        compose_tool_plan,
        middleware_builder=build_middleware_registry,
    )


def test_eval_worker_supplies_evaluation_composition(monkeypatch) -> None:
    from core.wiring.runtime import build_middleware_registry
    from evals import worker
    from evals.composition import compose_tool_plan

    worker_main = Mock()
    monkeypatch.setattr(worker, "run_worker", worker_main)

    worker.main()

    worker_main.assert_called_once_with(
        compose_tool_plan,
        middleware_builder=build_middleware_registry,
        activity_sink_provider=worker.current_run_timeline,
        worker_activity_binder=worker._bind_activity,
    )


def test_mcp_entrypoint_defaults_to_the_native_runner(monkeypatch) -> None:
    from core import mcp_server

    server = Mock()
    create = Mock(return_value=server)
    monkeypatch.setattr(mcp_server, "create_mcp_server", create)
    monkeypatch.setattr("sys.argv", ["geode-mcp"])

    mcp_server.main()

    create.assert_called_once_with(
        agent_tool_plan_builder=None,
        agent_runner=None,
        feature_registrar=None,
    )
    server.run.assert_called_once_with()


def test_native_mcp_runner_reuses_one_resource_lock_pool(monkeypatch) -> None:
    from core import mcp_server
    from core.cli import bootstrap

    captured: list[object] = []

    async def fake_run(_prompt: str, **kwargs: object) -> None:
        captured.append(kwargs["resource_lock_pool"])

    monkeypatch.setattr(bootstrap, "arun_agentic_oneshot", fake_run)
    monkeypatch.setattr(mcp_server, "_RESOURCE_LOCK_POOL", None)

    asyncio.run(mcp_server._run_agent("one"))
    asyncio.run(mcp_server._run_agent("two"))

    assert captured == [mcp_server._RESOURCE_LOCK_POOL, mcp_server._RESOURCE_LOCK_POOL]


def test_evaluation_definitions_and_execution_surfaces_have_exact_parity() -> None:
    from core.agent.tool_executor.executor import SPECIAL_EXECUTION_BINDINGS
    from core.tools.base import load_all_tool_definitions
    from evals.composition import compose_tool_plan

    definitions = {item["name"] for item in load_all_tool_definitions()}
    bound, transient_handlers = compose_tool_plan()
    handlers = set(bound.handlers)
    special_bindings = set(SPECIAL_EXECUTION_BINDINGS)
    executable = handlers | special_bindings

    assert handlers.isdisjoint(special_bindings)
    assert executable == definitions == set(bound.tool_names)
    assert set(transient_handlers) == _INTERNAL_ONLY_HANDLERS


def test_evaluation_handlers_retain_their_composition_origins() -> None:
    from evals.composition import compose_tool_plan

    bound, _transient_handlers = compose_tool_plan()
    assert {
        name: bound.execution_map[name].origin for name in _EVALUATION_HANDLER_ORIGINS
    } == _EVALUATION_HANDLER_ORIGINS


def test_evaluation_handler_collision_fails_before_catalog_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.tools.handlers.registration import UniqueEntries
    from evals import composition

    conflicting_groups = (
        *composition.evaluation_handler_groups(),
        ("eval-conflict", UniqueEntries((("petri_audit", _handler),))),
    )
    monkeypatch.setattr(composition, "evaluation_handler_groups", lambda: conflicting_groups)

    with pytest.raises(
        ValueError,
        match=(
            r"duplicate tool handler registration: 'petri_audit' "
            r"\(eval-audit vs eval-conflict\)"
        ),
    ):
        composition.compose_tool_plan()


def test_runtime_composition_rejects_non_callable_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.tools.composition import compose_tool_plan
    from core.tools.handlers.registration import UniqueEntries

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


def test_evaluation_composition_compiles_one_lossless_immutable_plan(
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
    from evals.composition import compose_tool_plan

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
    assert plan.execution_map["petri_audit"].origin == "eval-audit"

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
