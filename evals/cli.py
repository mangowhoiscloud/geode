"""Evaluation command-line surface."""

from __future__ import annotations

import typer
from core.cli.commands.config import build_config_app

from evals.config_cli import register_config_commands
from evals.petri.cli import cmd_petri
from evals.petri.cli_agreement import audit_agreement_app
from evals.petri.cli_audit import audit, petri_archive
from evals.seed_generation.cli import audit_seeds_app

app = typer.Typer(name="geode-eval", help="GEODE evaluation and benchmark commands.")
app.command()(audit)
app.command(name="petri-archive")(petri_archive)
app.add_typer(audit_seeds_app, name="audit-seeds")
app.add_typer(audit_agreement_app, name="audit-agreement")

config_app = build_config_app()
register_config_commands(config_app)
app.add_typer(config_app, name="config")


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def petri(ctx: typer.Context) -> None:
    """Inspect or change Petri role bindings."""
    cmd_petri(" ".join(ctx.args))


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def benchmark(ctx: typer.Context) -> None:
    """Run the existing benchmark harness command parser."""
    from evals.benchmarks.cli import main

    raise typer.Exit(main(list(ctx.args)))


if __name__ == "__main__":
    app()


__all__ = ["app"]
