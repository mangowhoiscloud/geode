"""Typer + slash entry points for the Petri audit runner.

Both ``geode audit`` (Typer subcommand registered from
``core/cli/__init__.py``) and ``/audit`` (slash command registered in
``core/cli/routing.py``) call ``runner.run_audit`` and render the
``AuditReport`` through :func:`_render_report` so the two paths stay
in lockstep on output.

:func:`petri_archive` persists a finished ``logs/*.eval`` outside the
worktree (``~/.geode/petri/logs/``) and writes a committable summary
YAML so a routine ``git worktree remove`` no longer deletes the only
copy of an audit's ground truth.
"""

from __future__ import annotations

import argparse
import os
import shlex
from pathlib import Path

import typer
from core.ui.console import console

from plugins.petri_audit.runner import AuditReport, format_cost, run_audit

__all__ = ["audit", "cmd_audit_slash", "petri_archive"]


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
        None,
        "--target",
        "-t",
        help="Target base model (GEODE id, e.g. claude-opus-4-7). "
        "Pinned for the audit's lifetime when set. "
        "**Omit to fall back to GEODE's active settings.model** — your "
        "current /model selection wins, drift sync stays active.",
    ),
    seeds: int = typer.Option(1, "--seeds", "-s", help="Sample count (--limit)."),
    max_turns: int = typer.Option(
        10,
        "--max-turns",
        "-m",
        help="Petri max_turns. inspect-petri default = 30; the canonical "
        "smoke setting is 10 (anything below 10 risks the auditor exhausting "
        "turns in setup before reaching `send_message` — see "
        "docs/audits/2026-05-10-petri-2a-target-debug.md).",
    ),
    tags: str = typer.Option(
        None,
        "--tags",
        help="Petri seed_instructions tags filter (e.g. sycophancy). "
        "Shortcut for `--seed-select tags:<value>`. Mutually exclusive "
        "with --seed-select.",
    ),
    seed_select: str = typer.Option(
        "plugins/petri_audit/seeds",
        "--seed-select",
        help="Petri seed_instructions selector — full inspect-petri form. "
        "Default: `plugins/petri_audit/seeds` (the 13 curated GEODE seeds — "
        "5-branch 1→2→3→2→1 pressure curve, 7 categories). "
        "G-A1 (2026-05-12) warning: inspect_petri's `id:<csv>` lookup is "
        "scoped to its 173 built-in seeds and will fall back to a raw-string "
        "sample if a name is unknown — pass an explicit path (directory or "
        "YAML) instead. Other accepted forms: `tags:<tag>` (same as --tags), "
        "a path to a single `.md` file, or a directory.",
    ),
    dim_set: str = typer.Option(
        "5axes",
        "--dim-set",
        help="Judge-dimension set. '5axes' (default, 17 dims — behaviour "
        "control + tool calling + robustness + time efficiency + 3 P3-b "
        "alignment surfaces + 4 calibration anchors), 'full' / 'default' "
        "for inspect-petri's 36, or a YAML path for custom dims.",
    ),
    target_tools: str = typer.Option(
        "none",
        "--target-tools",
        help="Auditor's tool-creation tool set. 'none' (default — "
        "conversation-only, fits the 5-axis surface), 'fixed' "
        "(send_tool_call_result only, target has pre-registered tools), "
        "'synthetic' (full create_tool / remove_tool / send_tool_call_result "
        "— inspect-petri default; lets the auditor fabricate tool results, "
        "useful for capability dim studies).",
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
    unrestricted: bool = typer.Option(
        False,
        "--unrestricted",
        help="Audit-mode — lift GEODE's HITL/policy guardrails for this "
        "petri run only (allow_dangerous + allow_write + force_dry_run=False "
        "+ denied_tools clear + auto_approve). The scenario seeds in "
        "plugins/petri_audit/seeds/ require this so the target's behaviour "
        "under pressure is observed without GEODE itself intercepting. "
        "Sets GEODE_AUDIT_UNRESTRICTED=1 in the inspect subprocess env. "
        "Does NOT mutate ~/.geode/user_profile/preferences.toml.",
    ),
) -> None:
    """Petri × GEODE alignment audit (P3-b-2 prep)."""
    if unrestricted:
        os.environ["GEODE_AUDIT_UNRESTRICTED"] = "1"
    report = run_audit(
        judge=judge,
        auditor=auditor,
        target=target or None,
        seeds=seeds,
        max_turns=max_turns,
        tags=tags or None,
        seed_select=seed_select or None,
        dim_set=dim_set,
        target_tools=target_tools,
        cache=cache,
        dry_run=dry_run,
        yes=yes,
    )
    _render_report(report)


def _build_slash_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="/audit", add_help=False, allow_abbrev=False)
    parser.add_argument("--judge", "-j", default="claude-haiku-4-5-20251001")
    parser.add_argument("--auditor", "-a", default="claude-sonnet-4-6")
    parser.add_argument("--target", "-t", default=None)
    parser.add_argument("--seeds", "-s", type=int, default=1)
    parser.add_argument("--max-turns", "-m", type=int, default=10, dest="max_turns")
    parser.add_argument("--tags", default=None)
    parser.add_argument("--seed-select", default=None, dest="seed_select")
    parser.add_argument("--dim-set", default="5axes", dest="dim_set")
    parser.add_argument(
        "--target-tools",
        default="none",
        dest="target_tools",
        choices=["synthetic", "fixed", "none"],
    )
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
        seed_select=ns.seed_select or None,
        dim_set=ns.dim_set,
        target_tools=ns.target_tools,
        cache=ns.cache,
        dry_run=ns.dry_run,
        yes=ns.yes,
    )
    _render_report(report)


_EVAL_PATH_ARG = typer.Argument(
    ...,
    exists=True,
    readable=True,
    help="Path to a finished `logs/*.eval` produced by `geode audit --live`.",
)
_RAW_ARCHIVE_OPT = typer.Option(
    None,
    "--raw-archive-dir",
    help="Where the raw .eval is copied. Default: `~/.geode/petri/logs/` "
    "(out of git on purpose — PII / size).",
)
_SUMMARY_DIR_OPT = typer.Option(
    None,
    "--summary-dir",
    help="Where the YAML metadata summary is written. Default: "
    "`docs/audits/eval-logs/` (committable; cross-session compare).",
)


def petri_archive(
    eval_path: Path = _EVAL_PATH_ARG,
    raw_archive_dir: Path | None = _RAW_ARCHIVE_OPT,
    summary_dir: Path | None = _SUMMARY_DIR_OPT,
) -> None:
    """Persist a petri eval log outside the worktree + write a YAML summary.

    A finished `logs/*.eval` lives inside the active worktree by
    default, so a routine `git worktree remove` after the merged PR
    silently deletes the only copy. Run this command before cleaning
    up a worktree (or call it from a post-audit hook) to put the raw
    eval somewhere safe and emit a small, diffable YAML for the
    surrounding audit report to reference.
    """
    from plugins.petri_audit.eval_archive import (
        DEFAULT_RAW_ARCHIVE_DIR,
        DEFAULT_SUMMARY_DIR,
        archive_eval,
    )

    result = archive_eval(
        eval_path,
        raw_archive_dir=raw_archive_dir or DEFAULT_RAW_ARCHIVE_DIR,
        summary_dir=summary_dir or DEFAULT_SUMMARY_DIR,
    )

    console.print()
    console.print("  [header]Petri eval archive[/header]")
    console.print(f"  raw:      [dim]{result.raw_path}[/dim]")
    console.print(f"  summary:  [dim]{result.summary_path}[/dim]")
    s = result.summary
    console.print(f"  status:   {s.get('status')}")
    console.print(f"  samples:  {s.get('samples')}")
    findings = [
        (item["id"], item["non_baseline_dims"])
        for item in s.get("samples_summary", [])
        if item.get("non_baseline_dims")
    ]
    if findings:
        console.print("  non-baseline dims (per sample):")
        for sample_id, dims in findings:
            console.print(f"    {sample_id}: {dims}")
    console.print()
