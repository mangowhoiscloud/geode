"""Product-owned slash-command contributions."""

from __future__ import annotations

from typing import Any

from core.slash_routing import CommandSpec, RunLocation


def build_geo_prompt(arg: str, *, skill_registry: Any) -> str:
    """Render the bundled GEO skill for the shared AgenticLoop."""
    from core.cli.commands.skills import build_skill_prompt

    return build_skill_prompt(skill_registry, "geo", arg)


PRODUCT_COMMAND_SPECS = (
    CommandSpec(
        name="/audit",
        location=RunLocation.THIN,
        description="Petri × GEODE alignment audit",
        handler_path="geode_product.petri_audit.cli_audit:cmd_audit_slash",
    ),
    CommandSpec(
        name="/audit-seeds",
        location=RunLocation.THIN,
        description="Generate and score candidate evaluation seeds",
        handler_path="geode_product.seed_generation.cli:cmd_audit_seeds_slash",
    ),
    CommandSpec(
        name="/petri",
        location=RunLocation.THIN,
        description="Show or switch Petri role bindings",
        handler_path="geode_product.petri_audit.cli:cmd_petri",
    ),
    CommandSpec(
        name="/self-improving",
        aliases=("/sil",),
        location=RunLocation.THIN,
        description="Self-improving loop status, execution, and configuration",
        handler_path="geode_product.self_improving.cli_commands:cmd_self_improving",
    ),
    CommandSpec(
        name="/recall",
        location=RunLocation.THIN,
        description="Memory-recall pool — list/show/save persistent memory entries",
        handler_path="geode_product.self_improving.recall_cli:cmd_recall",
    ),
    CommandSpec(
        name="/geo",
        location=RunLocation.DAEMON_STREAM,
        description="Audit generative discovery, citation, absorption, and fidelity",
        handler_path="geode_product.slash_commands:build_geo_prompt",
    ),
)


__all__ = ["PRODUCT_COMMAND_SPECS", "build_geo_prompt"]
