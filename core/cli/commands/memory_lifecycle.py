"""``geode memory-lifecycle`` — weekly project-memory decay + promotion pass.

Thin Typer command over :mod:`core.memory.memory_lifecycle`:

* **Decay** — entries whose ``resolution.guard_test`` still exists in the
  tree are archived to ``.geode/memory/_archive/``; entries whose guard
  test vanished resurface (WARNING). No time-based decay.
* **Promotion proposals** — dream artifacts (``context_artifacts`` rows
  written by the dreaming service) + active memory entries are clustered;
  clusters spanning >= 3 distinct sessions become HITL proposal files under
  ``.geode/memory/_proposals/``. Rules are never written automatically.

Dry-run by default; ``--apply`` moves files, writes proposals, and fires
``MEMORY_PROMOTION_PROPOSED`` into a RunLog-wired HookSystem.
"""

from __future__ import annotations

import logging
from pathlib import Path

import typer

log = logging.getLogger(__name__)

_APPLY_OPTION = typer.Option(
    False,
    "--apply",
    help="Apply verdicts (move files) and write proposal files. Default: dry-run report only.",
)
_MEMORY_DIR_OPTION = typer.Option(
    None,
    "--memory-dir",
    help=(
        "Memory entry directory (default: ./.geode/memory/). Point at "
        "~/.geode/memory/recall/ to run the lifecycle over the recall pool."
    ),
)
_MIN_SESSIONS_OPTION = typer.Option(
    None,
    "--min-sessions",
    help="Distinct-session gate for promotion proposals (default: 3).",
)


def memory_lifecycle(
    apply: bool = _APPLY_OPTION,
    memory_dir: Path | None = _MEMORY_DIR_OPTION,
    min_sessions: int | None = _MIN_SESSIONS_OPTION,
) -> None:
    """Run project-memory decay verdicts + dedup promotion proposals."""
    from rich.console import Console

    from core.memory.memory_lifecycle import (
        DEFAULT_MIN_SESSIONS,
        apply_decay,
        evaluate_decay,
        load_lifecycle_entries,
        propose_memory_promotions,
    )
    from core.memory.session_manager import SessionManager
    from core.paths import PROJECT_MEMORY_DIR

    console = Console()
    root = Path.cwd()
    target_dir = memory_dir if memory_dir is not None else root / PROJECT_MEMORY_DIR
    gate = min_sessions if min_sessions is not None else DEFAULT_MIN_SESSIONS
    mode = "apply" if apply else "dry-run"
    console.print(f"[cyan]memory-lifecycle[/cyan] dir={target_dir} mode={mode}")

    # --- Decay ------------------------------------------------------------
    entries = load_lifecycle_entries(target_dir)
    verdicts = evaluate_decay(entries, repo_root=root)
    pending = [
        v
        for v in verdicts
        if (v.verdict == "archived" and not v.entry.archived)
        or (v.verdict == "resurface" and v.entry.archived)
    ]
    for verdict in verdicts:
        marker = "->" if verdict in pending else "=="
        console.print(
            f"  {marker} {verdict.verdict:<9} {verdict.entry.path.name}  "
            f"[dim]{verdict.reason}[/dim]"
        )
    if apply and pending:
        moves = apply_decay(verdicts, memory_dir=target_dir)
        console.print(f"[green]decay: moved {len(moves)} entr(y/ies)[/green]")
    else:
        console.print(
            f"decay: {len(pending)} pending move(s), {len(verdicts)} entr(y/ies) evaluated"
        )

    # --- Promotion proposals ------------------------------------------------
    hooks = None
    if apply:
        import uuid

        from core.wiring.bootstrap import build_hooks

        hooks, _run_log, _latency = build_hooks(
            session_key="memory-lifecycle",
            run_id=uuid.uuid4().hex[:12],
            log_dir=None,
        )
    try:
        session_manager = SessionManager()
    except Exception as exc:  # pragma: no cover — env-specific sqlite failure
        console.print(f"[red]sessions.db unavailable:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    try:
        proposals = propose_memory_promotions(
            memory_dir=target_dir,
            session_manager=session_manager,
            min_sessions=gate,
            apply=apply,
            hooks=hooks,
        )
    finally:
        session_manager.close()

    for proposal in proposals:
        console.print(
            f"  proposal {proposal.slug}: {len(proposal.session_ids)} sessions, "
            f"{len(proposal.sources)} sources -> {proposal.path}"
        )
    verb = "wrote" if apply else "would write"
    console.print(f"promotions: {verb} {len(proposals)} proposal(s) (gate: >={gate} sessions)")
