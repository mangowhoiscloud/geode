"""Behavioral boundary checks for the first-party product shell."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace
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
        "/petri",
        "/recall",
        "/self-improving",
    }


def test_product_slash_commands_do_not_mutate_kernel_registry() -> None:
    from core.cli.routing import COMMAND_REGISTRY, compose_command_registry
    from geode_product.cli import PRODUCT_COMMAND_SPECS

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

    assert {"campaign", "outer-bundle"}.isdisjoint(kernel_commands)
    assert {"campaign", "outer-bundle"} <= product_commands.keys()


def test_daemon_composition_supplies_product_workers_tools_and_prompts(monkeypatch) -> None:
    from core.server.supervised import services
    from geode_product import wiring
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
    }


def test_worker_module_supplies_the_product_handler_builder(monkeypatch) -> None:
    from core.agent import worker
    from geode_product.tool_handlers import build_tool_handlers
    from geode_product.wiring import (
        bind_worker_activity,
        build_middleware_registry,
        current_activity_sink,
    )

    main = Mock()
    monkeypatch.setattr(worker, "main", main)

    runpy.run_module("geode_product.worker", run_name="__main__")

    main.assert_called_once_with(
        build_tool_handlers,
        middleware_builder=build_middleware_registry,
        activity_sink_provider=current_activity_sink,
        worker_activity_binder=bind_worker_activity,
    )


def test_mcp_entrypoint_supplies_the_product_handler_builder(monkeypatch) -> None:
    from geode_product import mcp_server
    from geode_product.self_improving.mcp import register_mcp_tools
    from geode_product.tool_handlers import build_tool_handlers

    run_mcp_server = Mock()
    monkeypatch.setattr(mcp_server, "run_mcp_server", run_mcp_server)

    mcp_server.main()

    run_mcp_server.assert_called_once_with(
        build_tool_handlers,
        agent_runner=mcp_server.run_agent,
        feature_registrar=register_mcp_tools,
    )


def test_model_definitions_and_execution_surfaces_have_exact_parity() -> None:
    from core.agent.tool_executor.executor import SPECIAL_EXECUTION_BINDINGS
    from core.cli.tool_handlers import _build_tool_handler_catalog
    from core.tools.base import load_all_tool_definitions
    from geode_product.tool_handlers import product_handler_groups

    definitions = {item["name"] for item in load_all_tool_definitions()}
    catalog = _build_tool_handler_catalog(extra_groups=product_handler_groups())
    handlers = set(catalog.handlers)
    special_bindings = set(SPECIAL_EXECUTION_BINDINGS)
    executable = handlers | special_bindings

    assert handlers.isdisjoint(special_bindings)
    assert definitions - executable == set()
    assert executable - definitions == _INTERNAL_ONLY_HANDLERS


def test_product_handlers_retain_their_composition_origins() -> None:
    from core.cli.tool_handlers import _build_tool_handler_catalog
    from geode_product.tool_handlers import product_handler_groups

    catalog = _build_tool_handler_catalog(extra_groups=product_handler_groups())

    assert {
        name: catalog.origins[name] for name in _PRODUCT_HANDLER_ORIGINS
    } == _PRODUCT_HANDLER_ORIGINS
    assert set(catalog.handlers) == set(catalog.origins)


def test_product_handler_collision_fails_before_catalog_snapshot() -> None:
    from core.cli.tool_handlers import _build_tool_handler_catalog
    from core.cli.tool_handlers.registration import UniqueEntries
    from geode_product.tool_handlers import product_handler_groups

    conflicting_groups = (
        *product_handler_groups(),
        ("product-conflict", UniqueEntries((("petri_audit", _handler),))),
    )

    with pytest.raises(
        ValueError,
        match=(
            r"duplicate tool handler registration: 'petri_audit' "
            r"\(product-audit vs product-conflict\)"
        ),
    ):
        _build_tool_handler_catalog(extra_groups=conflicting_groups)


def test_product_composition_rejects_non_callable_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from geode_product.tool_handlers import compose_tool_plan

    monkeypatch.setattr(
        "core.cli.tool_handlers._build_tool_handler_catalog",
        lambda **_kwargs: SimpleNamespace(
            handlers={"broken": None},
            origins={"broken": "broken-source"},
        ),
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


def test_product_composition_compiles_one_lossless_immutable_plan() -> None:
    from core.agent.tool_executor.executor import SPECIAL_EXECUTION_BINDINGS
    from core.cli.tool_handlers import _build_tool_handler_catalog
    from core.tools.base import load_all_tool_definitions
    from geode_product.tool_handlers import compose_tool_plan, product_handler_groups

    definitions = load_all_tool_definitions()
    catalog = _build_tool_handler_catalog(extra_groups=product_handler_groups())
    plan, handlers = compose_tool_plan()
    same, rebuilt_handlers = compose_tool_plan(previous=plan)

    assert same is plan
    assert list(plan.schema_map) == [item["name"] for item in definitions]
    assert set(plan.schema_map) == set(plan.execution_map)
    assert list(handlers) == list(rebuilt_handlers) == list(catalog.handlers)
    assert set(handlers) - set(plan.execution_map) == _INTERNAL_ONLY_HANDLERS
    assert {
        name for name, binding in plan.execution_map.items() if binding.route == "special"
    } == set(SPECIAL_EXECUTION_BINDINGS)
    assert plan.execution_map["petri_audit"].origin == "product-audit"

    policies = {item.spec.name: item.safety for item in plan.registrations}
    assert policies["run_bash"].effect == "system"
    assert policies["gmail_search"].data_class == "personal"
    assert policies["gmail_search"].consent_required is True
    assert policies["gmail_search"].allow_headless is False
    assert policies["gmail_search"].allow_subagents is False
