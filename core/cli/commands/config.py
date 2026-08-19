"""Kernel-owned ``geode config`` command group."""

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


def build_config_app() -> typer.Typer:
    """Build an isolated config command group for one CLI composition."""
    config_app = typer.Typer(
        name="config",
        help="GEODE configuration commands.",
        no_args_is_help=True,
        add_completion=False,
    )
    config_app.command(name="explain")(explain)
    return config_app


app = build_config_app()
