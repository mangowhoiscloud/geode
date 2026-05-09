"""Typer + slash entry points for the Petri audit runner.

Both ``geode audit`` (Typer subcommand registered from
``core/cli/__init__.py``) and ``/audit`` (slash command registered in
``core/cli/routing.py``) call ``runner.run_audit`` and render the
``AuditReport`` through :func:`_render_report` so the two paths stay
in lockstep on output.
"""

from __future__ import annotations

import argparse
import shlex

import typer
from core.ui.console import console

from plugins.petri_audit.runner import AuditReport, format_cost, run_audit

__all__ = ["audit", "cmd_audit_slash"]


def _render_report(report: AuditReport) -> None:
    """Print the constructed command + estimated cost + run outcome."""
    cost_label, _ = format_cost(report.estimated_usd)
    console.print()
    console.print("  [header]Petri audit[/header]")
    console.print(f"  command:  [dim]{' '.join(report.command)}[/dim]")
    console.print(f"  estimate: {cost_label}")
    if report.dry_run:
        console.print("  status:   [yellow]dry-run — subprocess not executed[/yellow]")
    elif report.aborted:
        notes = "; ".join(report.notes) if report.notes else "aborted"
        console.print(f"  status:   [red]aborted[/red] ({notes})")
    elif report.returncode == 0:
        console.print("  status:   [green]ok[/green]")
        if report.stdout:
            console.print(report.stdout)
    else:
        console.print(f"  status:   [red]failed (rc={report.returncode})[/red]")
        if report.stderr:
            console.print(f"[red]{report.stderr}[/red]")
    console.print()


def audit(
    judge: str = typer.Option(
        "claude-haiku-4-5-20251001",
        "--judge",
        "-j",
        help="Judge model (GEODE id, e.g. claude-sonnet-4-6, gpt-5.4-mini, glm-5).",
    ),
    auditor: str = typer.Option(
        "claude-sonnet-4-6",
        "--auditor",
        "-a",
        help="Auditor model (GEODE id).",
    ),
    target: str = typer.Option(
        "claude-opus-4-7",
        "--target",
        "-t",
        help="Target base model. Always wrapped as geode/<model> so the audit "
        "exercises GEODE's whole stack.",
    ),
    seeds: int = typer.Option(1, "--seeds", "-s", help="Sample count (--limit)."),
    max_turns: int = typer.Option(5, "--max-turns", "-m", help="Petri max_turns."),
    tags: str = typer.Option(
        None,
        "--tags",
        help="Petri seed_instructions tags filter (e.g. sycophancy).",
    ),
    cache: bool = typer.Option(True, "--cache/--no-cache", help="Petri cache parameter."),
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--live",
        help="Default: print the constructed command without spending. "
        "Pass --live to actually invoke `inspect eval`.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Skip the confirm prompt before a live run.",
    ),
) -> None:
    """Petri × GEODE alignment audit (P3-b-2 prep)."""
    report = run_audit(
        judge=judge,
        auditor=auditor,
        target=target,
        seeds=seeds,
        max_turns=max_turns,
        tags=tags or None,
        cache=cache,
        dry_run=dry_run,
        yes=yes,
    )
    _render_report(report)


def _build_slash_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="/audit", add_help=False, allow_abbrev=False)
    parser.add_argument("--judge", "-j", default="claude-haiku-4-5-20251001")
    parser.add_argument("--auditor", "-a", default="claude-sonnet-4-6")
    parser.add_argument("--target", "-t", default="claude-opus-4-7")
    parser.add_argument("--seeds", "-s", type=int, default=1)
    parser.add_argument("--max-turns", "-m", type=int, default=5, dest="max_turns")
    parser.add_argument("--tags", default=None)
    parser.add_argument("--no-cache", action="store_false", dest="cache", default=True)
    parser.add_argument("--live", action="store_false", dest="dry_run", default=True)
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("--yes", "-y", action="store_true", default=False)
    parser.add_argument("--help", "-h", action="store_true", default=False)
    return parser


def cmd_audit_slash(args: str) -> None:
    """Handle ``/audit`` slash command. ``args`` is the raw post-slash string."""
    parser = _build_slash_parser()
    try:
        ns = parser.parse_args(shlex.split(args)) if args else parser.parse_args([])
    except SystemExit:
        # argparse calls sys.exit on parse error; intercept so the REPL stays alive.
        console.print("  [red]invalid /audit arguments — see /help[/red]")
        return

    if ns.help:
        console.print(parser.format_help())
        return

    report = run_audit(
        judge=ns.judge,
        auditor=ns.auditor,
        target=ns.target,
        seeds=ns.seeds,
        max_turns=ns.max_turns,
        tags=ns.tags or None,
        cache=ns.cache,
        dry_run=ns.dry_run,
        yes=ns.yes,
    )
    _render_report(report)
