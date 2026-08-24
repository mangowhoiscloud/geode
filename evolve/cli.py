"""Scaffold-search and Crucible command-line surface."""

from __future__ import annotations

import typer

from evolve.scaffold_search.cli_commands import cmd_self_improving, register_commands
from evolve.scaffold_search.recall_cli import cmd_recall

app = typer.Typer(name="geode-evolve", help="GEODE scaffold search and hill-climbing.")
register_commands(app)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def scaffold(ctx: typer.Context) -> None:
    """Inspect or run the scaffold-search loop."""
    cmd_self_improving(" ".join(ctx.args))


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def recall(ctx: typer.Context) -> None:
    """List, inspect, or update scaffold-search recall entries."""
    cmd_recall(" ".join(ctx.args))


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def crucible(ctx: typer.Context) -> None:
    """Run the existing Crucible command parser."""
    from evolve.crucible.cli import main

    raise typer.Exit(main(list(ctx.args)))


@app.command()
def mcp() -> None:
    """Expose scaffold-search controls over a local stdio MCP server."""
    from core.mcp_server import create_mcp_server

    from evolve.scaffold_search.mcp import register_mcp_tools

    create_mcp_server(feature_registrar=register_mcp_tools).run()


if __name__ == "__main__":
    app()


__all__ = ["app"]
