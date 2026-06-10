"""``geode seeds`` / ``geode hub`` — operator pipeline entry points.

S-3 (2026-06-11) scripts→CLI promotion: ``scripts/assemble_seed_pool.py``
and ``scripts/build_self_improving_hub.py`` are operating-procedure steps
(campaign-entry: assemble → baseline → arms; hub publish), but they were
only reachable as ``uv run python scripts/...`` while everything else in
the procedure is a ``geode`` subcommand. These thin Typer wrappers make
the CLI the single entry point; the script modules remain the
implementation home (and stay directly runnable for CI / automation).
"""

from __future__ import annotations

import typer

seeds_app = typer.Typer(name="seeds", help="Seed-pool operations (assemble cycle-input pool)")
hub_app = typer.Typer(name="hub", help="Self-improving hub artifacts (build static pages)")


@seeds_app.command(
    name="assemble",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def seeds_assemble(ctx: typer.Context) -> None:
    """Assemble the cycle-input seed pool (wraps scripts/assemble_seed_pool.py).

    All flags pass through verbatim — run ``geode seeds assemble -- --help``
    for the underlying options.
    """
    try:
        from scripts.assemble_seed_pool import main as assemble_main
    except ImportError as exc:  # wheel ships core+plugins only — repo-only command
        typer.echo(
            f"geode seeds assemble requires a repo checkout (scripts/ package): {exc}", err=True
        )
        raise typer.Exit(code=2) from exc

    raise typer.Exit(code=assemble_main(list(ctx.args)))


@hub_app.command(
    name="build",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def hub_build(ctx: typer.Context) -> None:
    """Build the self-improving hub pages (wraps scripts/build_self_improving_hub.py).

    All flags pass through verbatim — run ``geode hub build -- --help``
    for the underlying options.
    """
    try:
        from scripts.build_self_improving_hub import main as hub_main
    except ImportError as exc:  # wheel ships core+plugins only — repo-only command
        typer.echo(f"geode hub build requires a repo checkout (scripts/ package): {exc}", err=True)
        raise typer.Exit(code=2) from exc

    raise typer.Exit(code=hub_main(list(ctx.args)))
