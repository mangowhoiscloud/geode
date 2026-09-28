"""Kernel-owned ``geode config`` command group."""

from pathlib import Path

import typer


def explain(
    key: str = typer.Argument("model", help="Settings field to explain (default: model)"),
) -> None:
    """Show every config layer's candidate for KEY and which one wins."""
    from core.config.explain import explain_field

    try:
        report = explain_field(key)
    except Exception as exc:
        typer.echo(f"explain failed for {key!r}: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("")
    typer.echo(
        f"  {report.field_name}  (env var {report.env_var}"
        + (f", toml key {report.toml_key}" if report.toml_key else "")
        + ")"
    )
    typer.echo(f"  effective: {report.effective!r}")
    typer.echo("")
    typer.echo(f"  {'layer':22} {'value':28} source")
    for entry in report.layers:
        marker = "  WINNER" if entry.is_winner else ("  masked" if entry.is_masked else "")
        value = "-" if entry.value is None else repr(entry.value)
        typer.echo(f"  {entry.layer:22} {value:28} {entry.source}{marker}")
    masked = report.masked_layers
    typer.echo("")
    if masked:
        winner_layer = report.winner.layer if report.winner else "?"
        typer.echo(
            f"  {len(masked)} layer(s) masked by {winner_layer}."
            " Edit the WINNER layer (or remove its line) to change the effective value."
        )
    else:
        typer.echo("  no masking - single layer set.")
    typer.echo("")


def trust(
    path: str = typer.Argument(".", help="Project folder (default: current directory)"),
    revoke: bool = typer.Option(False, "--revoke", help="Remove trust for the folder"),
    show: bool = typer.Option(False, "--list", help="List trusted folders"),
) -> None:
    """Trust a folder so its .geode/config.toml, .env and MCP servers apply in full."""
    from core.config.project_trust import PROJECT_DENIED_KEYS, set_project_trust, trusted_projects

    if show:
        for trusted_folder in sorted(trusted_projects()):
            typer.echo(trusted_folder)
        return
    folder = Path(path).resolve()
    if not folder.is_dir():
        typer.echo(f"not a folder: {folder}", err=True)
        raise typer.Exit(code=1)
    written = set_project_trust(folder, trusted=not revoke)
    if revoke:
        typer.echo(f"Revoked trust for {folder} ({written})")
        return
    typer.echo(f"Trusted {folder} ({written})")
    typer.echo(
        "Its .geode/config.toml, .env and MCP servers apply from the next session; "
        f"{', '.join(sorted(PROJECT_DENIED_KEYS))} are never read from a project."
    )


def build_config_app() -> typer.Typer:
    """Build an isolated config command group for one CLI composition."""
    config_app = typer.Typer(
        name="config",
        help="GEODE configuration commands.",
        no_args_is_help=True,
        add_completion=False,
    )
    config_app.command(name="explain")(explain)
    config_app.command(name="trust")(trust)
    return config_app


app = build_config_app()
