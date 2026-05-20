"""``/self-improving`` (and alias ``/sil``) REPL slash command.

PR-OPS-1 (2026-05-21) — smallest operator-facing surface for the
self-improving loop. Today only the ``status`` sub-action is wired:
it reads ``autoresearch/state/mutations.jsonl`` (the git-tracked
mutation audit) and the most recent ``baseline.json`` to print a
two-block summary — current baseline fitness + the last N mutations.

The ``run`` / ``history`` / ``rollback`` / ``config`` sub-actions
are reserved for PR-OPS-2/3. Invoking them today prints a
"not-yet-wired" pointer to the design doc.

Wiring path:

  REPL slash ``/self-improving status``
    → ``core/cli/routing.py`` ``COMMAND_REGISTRY`` (THIN location)
    → ``core/cli/commands/_state.py`` ``COMMAND_MAP`` action="self-improving"
    → ``core/cli/dispatcher.py`` ``_handle_command`` dispatch
    → ``cmd_self_improving(args)``  (this module)

Mode B only — this surface triggers ``SelfImprovingLoopRunner``
programmatic mutation. The Karpathy idiom (Mode A — external agent
reading ``autoresearch/program.md``) stays a parallel, manual path.
See ``docs/plans/2026-05-21-self-improving-loop-ux.md`` for the full
design.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from core.ui.console import console

__all__ = ["cmd_self_improving"]


_HISTORY_DEFAULT_N = 5
_KNOWN_ACTIONS = frozenset({"status", "run", "history", "rollback", "config"})
_DESIGN_DOC = "docs/plans/2026-05-21-self-improving-loop-ux.md"


def cmd_self_improving(args: str) -> None:
    """Dispatch the ``/self-improving`` sub-action.

    Empty args → ``status`` (default action).
    Unknown action → help-style hint listing wired vs deferred.
    """
    parts = args.split() if args else []
    action = parts[0] if parts else "status"

    if action == "status":
        _cmd_status()
        return

    if action in _KNOWN_ACTIONS:
        console.print()
        console.print(
            f"  [warning]/{action} is reserved for PR-OPS-2/3[/warning] — "
            f"see [muted]{_DESIGN_DOC}[/muted]"
        )
        console.print()
        return

    console.print()
    console.print(f"  [warning]Unknown action: /self-improving {action}[/warning]")
    console.print(
        "  [muted]Available now: [/muted]status   "
        "[muted]Coming PR-OPS-2/3:[/muted] run / history / rollback / config"
    )
    console.print()


def _cmd_status() -> None:
    """Render current baseline + recent mutations.

    Output blocks (Mode B mutator state):
      1. Baseline — ``autoresearch/state/baseline.json`` (if exists)
         · ``fitness`` scalar, ``promote_reason``, ``timestamp``
      2. Recent mutations — last N rows from
         ``autoresearch/state/mutations.jsonl``
         · per-row ``ts`` / ``mutation_id`` / ``target_kind`` /
           ``target_section`` / ``kind`` (applied | rejected | rolled_back)

    Both files are git-tracked; missing files render an empty-state
    line rather than raising so an operator can call ``status`` on a
    fresh clone before any run.
    """
    from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH

    console.print()
    console.print("  [header]Self-improving loop — status[/header]")

    baseline_path = _baseline_path()
    baseline = _load_json(baseline_path)
    console.print()
    console.print("  [bold]Baseline[/bold]")
    if baseline is None:
        console.print(f"    [muted]no baseline yet — {baseline_path} absent[/muted]")
    else:
        fitness = baseline.get("fitness")
        ts = baseline.get("timestamp") or baseline.get("ts") or "?"
        reason = baseline.get("promote_reason") or baseline.get("reason") or "?"
        fitness_str = f"{fitness:.4f}" if isinstance(fitness, int | float) else "?"
        console.print(f"    fitness  [bold]{fitness_str}[/bold]")
        console.print(f"    promoted [muted]{ts}[/muted]")
        console.print(f"    reason   [muted]{reason}[/muted]")

    audit_path = Path(MUTATION_AUDIT_LOG_PATH)
    rows = list(_tail_jsonl(audit_path, _HISTORY_DEFAULT_N))
    console.print()
    console.print(f"  [bold]Recent mutations[/bold] (last {_HISTORY_DEFAULT_N})")
    if not rows:
        console.print(f"    [muted]no mutations recorded — {audit_path} absent or empty[/muted]")
    else:
        for row in rows:
            _print_audit_row(row)
    console.print()


def _baseline_path() -> Path:
    """Resolve ``autoresearch/state/baseline.json`` relative to the
    project root. The audit ledger lives in the same dir, so we lean
    on its constant rather than reinventing root-detection here."""
    from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH

    return Path(MUTATION_AUDIT_LOG_PATH).parent / "baseline.json"


def _load_json(path: Path) -> dict[str, Any] | None:
    """Return the parsed JSON dict, or ``None`` on missing/malformed
    file. Slash output must never raise on bad input — operator may
    inspect mid-run when the file is being rewritten."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _tail_jsonl(path: Path, n: int) -> Iterable[dict[str, Any]]:
    """Yield the last ``n`` valid JSON rows from a JSONL file.

    Yields nothing on missing path. Skips malformed lines silently —
    the file is append-only so a partial last row during concurrent
    write should not break ``status``.
    """
    if not path.is_file() or n <= 0:
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    parsed: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            parsed.append(row)
    yield from parsed[-n:]


def _print_audit_row(row: dict[str, Any]) -> None:
    """Render one mutation audit row as a single line."""
    ts = str(row.get("ts") or row.get("timestamp") or "?")[:19]
    kind_label = str(row.get("kind") or "applied")
    target_kind = str(row.get("target_kind") or row.get("kind_target") or "?")
    target_section = str(row.get("target_section") or "?")
    mutation_id = str(row.get("mutation_id") or row.get("id") or "?")[:12]
    style = {
        "applied": "success",
        "rejected": "warning",
        "rolled_back": "muted",
    }.get(kind_label, "muted")
    console.print(
        f"    [{style}]{kind_label:11}[/{style}] "
        f"[muted]{ts}[/muted]  "
        f"{target_kind}.{target_section}  "
        f"[muted]id={mutation_id}[/muted]"
    )
