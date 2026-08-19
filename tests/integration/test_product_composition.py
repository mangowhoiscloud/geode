"""Behavioral boundary checks for the first-party product shell."""

from __future__ import annotations

import runpy
from pathlib import Path
from unittest.mock import Mock

PRODUCT_TOOLS = {
    "petri_audit",
    "eval_inspect_viz",
    "eval_dspy_optimize",
    "geode_seed_pool_search",
    "seed_debate_turn",
    "freeze_paper_snapshot",
}


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

    assert set(result["commands"]) >= {"/audit", "/audit-seeds", "/petri"}


def test_product_slash_commands_do_not_mutate_kernel_registry() -> None:
    from core.cli.routing import COMMAND_REGISTRY, compose_command_registry
    from geode_product.cli import PRODUCT_COMMAND_SPECS

    product_registry = compose_command_registry(PRODUCT_COMMAND_SPECS)
    assert "/audit" not in COMMAND_REGISTRY
    assert product_registry.keys() >= {"/audit", "/audit-seeds", "/petri"}


def test_daemon_composition_supplies_product_workers_tools_and_prompts(monkeypatch) -> None:
    from core.server.supervised import services
    from geode_product import wiring
    from geode_product.tool_handlers import build_tool_handlers

    build_core = Mock(return_value="services")
    monkeypatch.setattr(services, "build_shared_services", build_core)

    assert wiring.build_shared_services(marker=True) == "services"
    assert build_core.call_args.kwargs == {
        "marker": True,
        "tool_handler_builder": build_tool_handlers,
        "worker_module": "geode_product.worker",
        "agent_search_dirs": (Path(wiring.__file__).parent / "seed_generation" / "agents",),
    }


def test_worker_module_supplies_the_product_handler_builder(monkeypatch) -> None:
    from core.agent import worker
    from geode_product.tool_handlers import build_tool_handlers

    main = Mock()
    monkeypatch.setattr(worker, "main", main)

    runpy.run_module("geode_product.worker", run_name="__main__")

    main.assert_called_once_with(build_tool_handlers)


def test_mcp_entrypoint_supplies_the_product_handler_builder(monkeypatch) -> None:
    from geode_product import mcp_server
    from geode_product.tool_handlers import build_tool_handlers

    run_mcp_server = Mock()
    monkeypatch.setattr(mcp_server, "run_mcp_server", run_mcp_server)

    mcp_server.main()

    run_mcp_server.assert_called_once_with(build_tool_handlers)
