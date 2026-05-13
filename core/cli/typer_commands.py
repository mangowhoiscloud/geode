"""Typer command implementations for the GEODE CLI.

Extracted from ``core/cli/__init__.py`` (Tier 3 God Object split). Hosts
every Typer subcommand except ``init`` and ``serve`` (which live in
``typer_init`` and ``typer_serve`` respectively). The Typer ``app``
registers each function from the package ``__init__``; no decorators
here so that the import edge stays acyclic.
"""

from __future__ import annotations

from pathlib import Path

import typer

from core import __version__
from core.cli.pipeline_executor import _run_analysis
from core.cli.report_renderer import _generate_report
from core.cli.search_render import _render_search_results
from core.cli.session_state import _get_search_engine
from core.ui.console import console


def analyze(
    ip_name: str = typer.Argument(..., help="IP name to analyze (e.g. 'Cowboy Bebop')"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Run without LLM calls (fixture data only)"
    ),
    skip_verification: bool = typer.Option(
        False, "--skip-verification", help="Skip guardrails and BiasBuster"
    ),
    pipeline: str = typer.Option("full_pipeline", "--pipeline", "-p", help="Pipeline mode"),
    stream: bool = typer.Option(False, "--stream", help="Enable streaming output"),
    domain: str = typer.Option("game_ip", "--domain", "-d", help="Domain adapter name"),
) -> None:
    """Analyze an IP for undervaluation potential."""
    _run_analysis(
        ip_name,
        dry_run=dry_run,
        verbose=verbose,
        skip_verification=skip_verification,
        stream=stream,
        domain_name=domain,
    )


def report(
    ip_name: str = typer.Argument(..., help="IP name to generate report for"),
    fmt: str = typer.Option("md", "--format", "-f", help="Output format: md, html, json"),
    template: str = typer.Option(
        "summary", "--template", "-t", help="summary, detailed, executive"
    ),
    output: str = typer.Option(None, "--output", "-o", help="Save report to file"),
    dry_run: bool = typer.Option(False, "--dry-run/--no-dry-run", help="Use fixture data (no LLM)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed output"),
) -> None:
    """Generate a report for an IP analysis."""
    resolved_fmt = "markdown" if fmt == "md" else fmt
    _generate_report(
        ip_name,
        fmt=resolved_fmt,
        template=template,
        output=output or None,
        dry_run=dry_run,
        verbose=verbose,
    )


def search(
    query: str = typer.Argument(..., help="Search query (e.g. 'dark fantasy', '소울라이크')"),
) -> None:
    """Search IPs by keyword or genre."""
    results = _get_search_engine().search(query)
    _render_search_results(query, results)


def version() -> None:
    """Show GEODE version."""
    console.print(f"GEODE v{__version__}")


def about() -> None:
    """Show what GEODE is currently using.

    One-screen summary: version, active model + provider, registered
    auth profiles (no secrets), ``.geode`` paths, daemon socket status.
    Use this when you want to know "what am I running right now?" without
    digging through logs.
    """
    from core.config import _resolve_provider, settings

    console.print()
    console.print(f"  [header]GEODE v{__version__}[/header]")
    console.print()

    # Active model + provider
    model = settings.model
    provider = _resolve_provider(model)
    console.print(f"  [bold]Model[/bold]      [value]{model}[/value]  [muted]({provider})[/muted]")

    # Auth profiles (mask all keys)
    try:
        from core.wiring.container import ensure_profile_store

        store = ensure_profile_store()
        profiles = [p for p in store.list_all() if p.key]
    except Exception:
        profiles = []

    if profiles:
        console.print(
            f"  [bold]Auth[/bold]       {len(profiles)} profile(s) — "
            f"[muted]{', '.join(sorted({p.provider for p in profiles}))}[/muted]"
        )
    else:
        console.print(
            "  [bold]Auth[/bold]       [warning]none — run [cyan]geode setup[/cyan][/warning]"
        )

    # Paths
    from core.paths import GEODE_HOME, PROJECT_GEODE_DIR

    geode_home = GEODE_HOME
    project_geode = PROJECT_GEODE_DIR
    console.print(f"  [bold]User home[/bold]  [muted]{geode_home}[/muted]")
    console.print(
        f"  [bold]Project[/bold]    [muted]{project_geode}"
        f"{' (present)' if project_geode.exists() else ' (none)'}[/muted]"
    )

    # Daemon socket
    sock_path = Path("~/.geode/cli.sock").expanduser()
    if sock_path.exists():
        console.print(
            f"  [bold]Daemon[/bold]     [success]running[/success]  [muted]({sock_path})[/muted]"
        )
    else:
        console.print(
            "  [bold]Daemon[/bold]     [muted]not started "
            "— auto-launches on next [cyan]geode[/cyan][/muted]"
        )

    console.print()
    console.print(
        "  [muted]Diagnose with [cyan]geode doctor[/cyan]  ·  "
        "Configure with [cyan]geode setup[/cyan][/muted]"
    )
    console.print()


def setup(
    reset: bool = typer.Option(
        False,
        "--reset",
        "-r",
        help="Wipe ~/.geode/.env and re-run from scratch",
    ),
) -> None:
    """Re-run the first-time setup wizard.

    Detects ChatGPT subscription OAuth (`~/.codex/auth.json`) before
    prompting for API keys. Use ``--reset`` to clear existing
    credentials and start over.
    """
    from core.cli.onboarding import env_setup_wizard
    from core.wiring.startup import _has_any_llm_key, detect_subscription_oauth

    if reset:
        env_path = Path("~/.geode/.env").expanduser()
        if env_path.exists():
            env_path.unlink()
            console.print(f"  [muted]Removed {env_path}[/muted]")

    oauth_provider = detect_subscription_oauth()
    if oauth_provider:
        console.print(f"  [success]OAuth detected: {oauth_provider}[/success]")
        console.print("  [muted]No further setup needed. Run [cyan]geode[/cyan] to start.[/muted]")
        return

    if _has_any_llm_key() and not reset:
        console.print(
            "  [success]API key already configured.[/success]\n"
            "  [muted]Run [cyan]geode[/cyan] to start, or [cyan]geode setup --reset[/cyan] "
            "to start over.[/muted]"
        )
        return

    env_setup_wizard()


def doctor(
    target: str = typer.Argument("bootstrap", help="Diagnostic target (bootstrap | slack)"),
) -> None:
    """Run diagnostic checks.

    ``geode doctor`` (default ``bootstrap``) verifies the first-run
    surface — Python version, ``geode`` PATH, ``~/.geode/.env`` state,
    OAuth credentials, API key validity, serve daemon status. Useful
    when ``geode`` doesn't behave as expected.

    ``geode doctor slack`` checks Slack Gateway integration only.
    """
    if target == "bootstrap":
        from core.cli.doctor_bootstrap import format_bootstrap_report, run_bootstrap_doctor

        boot_report = run_bootstrap_doctor()
        console.print(format_bootstrap_report(boot_report))
    elif target == "slack":
        from core.cli.doctor import format_doctor_report, run_doctor_slack

        slack_report = run_doctor_slack()
        console.print(format_doctor_report(slack_report))
    else:
        console.print(f"Unknown target: {target}. Available: bootstrap, slack")


def list_ips() -> None:
    """List available IP fixtures."""
    from plugins.game_ip.fixtures import FIXTURE_MAP as _FIXTURE_MAP

    console.print("[header]Available IPs:[/header]")
    for name in _FIXTURE_MAP:
        console.print(f"  - {name.title()}")


def batch(
    top: int = typer.Option(10, help="Number of IPs to analyze"),
    genre: str = typer.Option(None, help="Filter by genre"),
    concurrency: int = typer.Option(2, help="Parallel workers"),
    dry_run: bool = typer.Option(False, "--dry-run/--live", help="Use dry-run mode"),
) -> None:
    """Run batch analysis on multiple IPs."""
    from plugins.game_ip.cli.batch import render_batch_table, run_batch

    results = run_batch(top=top, genre=genre, concurrency=concurrency, dry_run=dry_run)
    if results:
        render_batch_table(results)


def history(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of recent entries to show"),
    month: str = typer.Option(None, "--month", "-m", help="Month to show (YYYY-MM)"),
) -> None:
    """Show execution history and cost summary."""
    from datetime import date

    from rich.table import Table

    from core.llm.usage_store import UsageStore

    store = UsageStore()

    # Parse month
    if month:
        try:
            parts = month.split("-")
            year, mon = int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            console.print(f"  [warning]Invalid month format: {month} (use YYYY-MM)[/warning]")
            return
    else:
        today = date.today()
        year, mon = today.year, today.month

    # Monthly summary
    summary = store.get_monthly_summary(year, mon)
    console.print()
    console.print(f"  [header]GEODE Usage Report -- {year:04d}-{mon:02d}[/header]")
    console.print()

    if summary["total_calls"] == 0:
        console.print("  [muted]No usage data for this month.[/muted]")
        console.print()
        return

    # Model breakdown table
    table = Table(show_header=True, padding=(0, 2), box=None)
    table.add_column("Model", style="label", min_width=22)
    table.add_column("Calls", justify="right", style="value")
    table.add_column("Input", justify="right")
    table.add_column("Output", justify="right")
    table.add_column("Cost", justify="right", style="bold")

    for model_name, stats in sorted(summary["by_model"].items()):
        in_k = stats["in"] / 1000
        out_k = stats["out"] / 1000
        table.add_row(
            model_name,
            str(int(stats["calls"])),
            f"{in_k:.1f}K",
            f"{out_k:.1f}K",
            f"${stats['cost']:.2f}",
        )

    # Total row
    table.add_section()
    total_in_k = summary["total_input_tokens"] / 1000
    total_out_k = summary["total_output_tokens"] / 1000
    table.add_row(
        "Total",
        str(summary["total_calls"]),
        f"{total_in_k:.1f}K",
        f"{total_out_k:.1f}K",
        f"${summary['total_cost']:.2f}",
    )

    console.print(table)
    console.print()

    # Recent records
    recent = store.get_recent_records(limit=limit)
    if recent:
        from datetime import datetime

        console.print(f"  [header]Recent LLM Calls (last {min(limit, len(recent))})[/header]")
        console.print()
        recent_table = Table(show_header=True, padding=(0, 2), box=None)
        recent_table.add_column("Time", style="muted", min_width=16)
        recent_table.add_column("Model", style="label", min_width=22)
        recent_table.add_column("In", justify="right")
        recent_table.add_column("Out", justify="right")
        recent_table.add_column("Cost", justify="right", style="bold")

        for rec in recent:
            dt = datetime.fromtimestamp(rec.ts)
            recent_table.add_row(
                dt.strftime("%m-%d %H:%M:%S"),
                rec.model,
                str(rec.input_tokens),
                str(rec.output_tokens),
                f"${rec.cost_usd:.4f}",
            )
        console.print(recent_table)
        console.print()
