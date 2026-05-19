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

When an audit run completes with an archived ``.eval``, the last
non-empty line of stdout is a JSON dict ``{"dim_means": {...},
"dim_stderr": {...}}`` derived from :func:`core.audit.dim_extractor.
extract_dim_aggregates`. ``autoresearch/train.py`` grep-parses this
line to compute fitness without re-reading the inspect_ai archive —
the Karpathy ``grep "^val_bpb:"`` pattern adapted for multi-dim.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
from pathlib import Path
from typing import Any

import typer
from core.ui.console import console

from plugins.petri_audit.runner import AuditReport, format_cost, run_audit

log = logging.getLogger(__name__)

__all__ = ["audit", "cmd_audit_slash", "petri_archive"]


def _render_report(report: AuditReport) -> None:
    """Print the constructed command + estimated cost + run outcome."""
    cost_label, _ = format_cost(report.estimated_usd)
    console.print()
    console.print("  [header]Petri audit[/header]")
    console.print(f"  command:  [dim]{' '.join(report.command)}[/dim]")
    console.print(f"  estimate: {cost_label}")
    # PR #8 (2026-05-14) — surface the same-provider self-preference
    # disadvantage so the human reader sees it before the score table.
    # The chip's literal ``[same-provider bias ...]`` square brackets
    # collide with Rich's markup tag parser — escape them before print.
    if report.same_provider_bias_chip:
        from rich.markup import escape as _esc

        console.print(f"  bias:     [yellow]{_esc(report.same_provider_bias_chip)}[/yellow]")
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
    _emit_dim_aggregates(report)


def _emit_dim_aggregates(report: AuditReport) -> None:
    """Print a final JSON line with per-dim mean + stderr from the archive.

    Best-effort: only fires when the audit succeeded and produced an
    archive. Any failure inside the extractor is logged and swallowed —
    the line just won't appear. ``autoresearch/train.py`` reads the
    last ``{``-prefixed line of stdout, so an empty line plus the
    surrounding console output is benign for the human reader.

    Uses the builtin ``print`` (not ``console.print``) so the JSON
    stays unwrapped and easy to grep — Karpathy ``grep "^val_bpb:"``
    pattern adapted for the multi-dim Petri fitness signal.
    """
    if report.returncode != 0 or report.dry_run or report.aborted:
        return
    if not report.archived_raw:
        return
    try:
        from core.audit.dim_extractor import extract_dim_aggregates, extract_evidence

        aggregates = extract_dim_aggregates(report.archived_raw)
        # G2 (2026-05-20) — bundle per-dim top-K evidence into the same
        # stdout JSON so ``autoresearch/train.py`` can persist it
        # alongside dim_means/dim_stderr in ``state/baseline.json``.
        # top_k=3 mirrors the agreed evidence-volume tier (~250 KB
        # per audit; runner-friendly). Empty evidence dict is fine —
        # autoresearch treats it as "no signal".
        evidence = extract_evidence(report.archived_raw, top_k=3)
    except Exception:
        log.warning(
            "petri_audit: dim aggregate emission failed for %s",
            report.archived_raw,
            exc_info=True,
        )
        return
    if not aggregates.get("dim_means"):
        return
    summary_payload: dict[str, Any] = dict(aggregates)
    if evidence:
        summary_payload["evidence"] = evidence
    print(json.dumps(summary_payload, separators=(",", ":")))


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
        None,
        "--seed-select",
        help="Petri seed_instructions selector — full inspect-petri form. "
        "When neither --seed-select nor --tags is set, defaults to "
        "`plugins/petri_audit/seeds` (the 13 curated GEODE seeds — 5-branch "
        "1→2→3→2→1 pressure curve, 7 categories). "
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
    judge_mode: str = typer.Option(
        "legacy",
        "--judge-mode",
        help="A3 judge split (2026-05-14). 'legacy' (default) — single "
        "mega-judge call scoring all 17 dims; 'split' — 5-group call "
        "structure per geode_5axes_split.yaml (broken_tool_use isolated "
        "to prevent double-counting with input_hallucination). "
        "Runtime orchestration for 'split' is staged behind upstream "
        "inspect-petri support; currently the flag drives only the cost "
        "estimator. See docs/audits/2026-05-13-petri-a3-judge-split-design.md.",
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
    use_oauth: bool = typer.Option(
        None,
        "--use-oauth/--no-oauth",
        help="Route gpt-5.x judge / auditor calls through the Codex OAuth "
        "path (ChatGPT Plus subscription quota) instead of per-token "
        "OpenAI PAYG billing. Default: auto-detect based on Codex token "
        "presence (~/.codex/auth.json or GEODE openai-codex profile). "
        "Use --no-oauth to force per-token billing even with a token. "
        "User-pinned raw ids like `openai/gpt-5.5` bypass this rewrite.",
    ),
) -> None:
    """Petri × GEODE alignment audit (P3-b-2 prep)."""
    if unrestricted:
        os.environ["GEODE_AUDIT_UNRESTRICTED"] = "1"
    # G-A1 (2026-05-12) — default to the 13 curated flat seeds when the
    # caller didn't pin a seed source. Done here (not in the typer.Option
    # default) so that --tags still works exclusively — the body keeps the
    # ``tags XOR seed_select`` contract that run_audit enforces.
    resolved_seed_select = seed_select or None
    if resolved_seed_select is None and not tags:
        resolved_seed_select = "plugins/petri_audit/seeds"
    report = run_audit(
        judge=judge,
        auditor=auditor,
        target=target or None,
        seeds=seeds,
        max_turns=max_turns,
        tags=tags or None,
        seed_select=resolved_seed_select,
        dim_set=dim_set,
        target_tools=target_tools,
        judge_mode=judge_mode,
        cache=cache,
        dry_run=dry_run,
        yes=yes,
        use_oauth=use_oauth,
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
    parser.add_argument(
        "--judge-mode",
        default="legacy",
        dest="judge_mode",
        choices=["legacy", "split"],
    )
    parser.add_argument("--no-cache", action="store_false", dest="cache", default=True)
    parser.add_argument("--live", action="store_false", dest="dry_run", default=True)
    parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("--yes", "-y", action="store_true", default=False)
    parser.add_argument("--use-oauth", action="store_true", dest="use_oauth", default=None)
    parser.add_argument("--no-oauth", action="store_false", dest="use_oauth", default=None)
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

    # G-A1 — same default-seeds rule as the typer entry point.
    slash_seed_select = ns.seed_select or None
    if slash_seed_select is None and not ns.tags:
        slash_seed_select = "plugins/petri_audit/seeds"
    report = run_audit(
        judge=ns.judge,
        auditor=ns.auditor,
        target=ns.target,
        seeds=ns.seeds,
        max_turns=ns.max_turns,
        tags=ns.tags or None,
        seed_select=slash_seed_select,
        dim_set=ns.dim_set,
        target_tools=ns.target_tools,
        judge_mode=ns.judge_mode,
        cache=ns.cache,
        dry_run=ns.dry_run,
        yes=ns.yes,
        use_oauth=ns.use_oauth,
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
