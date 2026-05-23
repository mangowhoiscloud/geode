"""CLI subcommand: ``geode adapters`` — inspect registered LLM adapters.

v0.99.40 Follow-up D of the paperclip-style LLMAdapter abstraction
(``docs/plans/2026-05-23-llm-adapter-abstraction.md``). Surface the
:class:`core.llm.adapters.LLMAdapter` registry so operators can see what
PAYG / Subscription / Adapter paths are available + verify each path's
environment before scheduling a seed-generation run.

Two read-only subcommands:

- ``geode adapters list`` — enumerate registered adapters with
  ``billing_type``, ``test_environment`` summary, and supported model
  count.
- ``geode adapters detect-model <adapter>`` — paperclip ``detectModel``
  equivalent; reports the currently configured model + provenance from
  the adapter's ``detect_credential()`` hook.

UI: dense aligned table, plain text. No box-card / no emoji (per
``feedback_no_box_ui_no_emoji`` memory).
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="adapters",
    help="Inspect registered LLM adapters (PAYG / Subscription / Adapter paths).",
    no_args_is_help=True,
    add_completion=False,
)


@app.command("list")
def adapters_list() -> None:
    """List all registered adapters with billing_type + environment status."""
    from core.llm.adapters import bootstrap_builtins, list_adapters

    bootstrap_builtins()
    adapters = list_adapters()
    if not adapters:
        typer.echo("No LLM adapters registered.")
        raise typer.Exit()

    header = f"{'NAME':<20} {'PROVIDER':<10} {'SOURCE':<14} {'BILLING':<22} STATUS"
    typer.echo(header)
    typer.echo("-" * len(header))
    for a in adapters:
        report = a.test_environment()
        status = "ok" if report.ok else "missing — " + (report.hints[0] if report.hints else "")
        typer.echo(
            f"{a.name:<20} {a.provider:<10} {a.source:<14} {a.billing_type.value:<22} {status}"
        )
    typer.echo(f"\n{len(adapters)} adapter(s) registered.")
    typer.echo(
        'Override per role via ~/.geode/config.toml [seed_generation.role.<role>] source = "..."'
    )


@app.command("detect-model")
def adapters_detect_model(name: str) -> None:
    """Report the currently configured model + provenance for ``name``."""
    from core.llm.adapters import AdapterNotFoundError, bootstrap_builtins, get_adapter

    bootstrap_builtins()
    try:
        adapter = get_adapter(name)
    except AdapterNotFoundError as exc:
        typer.echo(f"adapter {name!r} not registered: {exc}")
        raise typer.Exit(code=1) from exc

    detection = adapter.detect_credential()
    if detection is None:
        typer.echo(f"{name}: no credential detected — run ``geode adapters list`` for hints.")
        raise typer.Exit(code=2)
    typer.echo(f"{name}: model={detection.model} provider={detection.provider}")
    typer.echo(f"  source: {detection.source_path}")
    if detection.candidates:
        typer.echo(f"  candidates: {', '.join(detection.candidates)}")


__all__ = ["app"]
