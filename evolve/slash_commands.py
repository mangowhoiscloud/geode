"""Scaffold-search slash-command contributions."""

from core.slash_routing import CommandSpec, RunLocation

EVOLVE_COMMAND_SPECS = (
    CommandSpec(
        name="/self-improving",
        aliases=("/sil",),
        location=RunLocation.THIN,
        description="Scaffold-search status, execution, and configuration",
        handler_path="evolve.scaffold_search.cli_commands:cmd_self_improving",
    ),
    CommandSpec(
        name="/recall",
        location=RunLocation.THIN,
        description="Memory-recall pool — list/show/save persistent memory entries",
        handler_path="evolve.scaffold_search.recall_cli:cmd_recall",
    ),
)

__all__ = ["EVOLVE_COMMAND_SPECS"]
