"""``geode seeds`` — operator pipeline entry point.

S-3 (2026-06-11) scripts→CLI promotion: ``scripts/assemble_seed_pool.py`` is
an operating-procedure step (campaign entry: assemble → baseline → arms), so a
thin Typer wrapper makes the CLI the single entry point; the script module
remains the implementation home (and stays directly runnable for automation).
The self-improving hub pages are rendered by the downstream site from the
publication bundle, so GEODE no longer has a ``geode hub`` command.
"""

from __future__ import annotations

import typer

seeds_app = typer.Typer(name="seeds", help="Seed-pool operations (assemble cycle-input pool)")


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
