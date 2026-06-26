"""Session-state slash commands.

Hosts ``cmd_resume`` (session checkpoint loader), ``cmd_apply`` (job
application tracker), ``cmd_context`` (assembled-context viewer),
``cmd_compact`` (Karpathy P6 context compaction), and ``cmd_clear``
(history wipe). Extracted from the monolithic ``core/cli/commands.py``
(Tier 3 #9) — every function body is preserved byte-identical from the
legacy module.

Tests that monkeypatch ``core.cli.commands.console`` /
``core.cli.commands.get_conversation_context`` reach the call sites here
through the deferred ``import core.cli.commands as _pkg`` lookup,
mirroring the pattern used by ``core/ui/agentic_ui``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.memory.session_checkpoint import SessionState

log = logging.getLogger(__name__)


def _format_cognitive_state_summary(snapshot: dict[str, Any]) -> str:
    """Render a compact operator-facing cognitive state summary."""
    if not snapshot:
        return ""

    parts: list[str] = []
    round_count = snapshot.get("round_count")
    if isinstance(round_count, int) and not isinstance(round_count, bool):
        parts.append(f"round={round_count}")

    confidence = snapshot.get("confidence")
    if isinstance(confidence, int | float) and not isinstance(confidence, bool):
        parts.append(f"confidence={float(confidence):.2f}")

    last_action = snapshot.get("last_action")
    if isinstance(last_action, str) and last_action:
        parts.append(f"last={last_action[:40]}")

    hypotheses = snapshot.get("hypotheses")
    if isinstance(hypotheses, list) and hypotheses:
        parts.append(f"hypotheses={len(hypotheses)}")

    return " | ".join(parts)


def _parse_last_flag(args: list[str], *, default: int = 10) -> tuple[list[str], int]:
    """Parse ``--last N`` from a small slash-command argv list."""
    cleaned: list[str] = []
    limit = default
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--last" and i + 1 < len(args):
            try:
                limit = max(0, int(args[i + 1]))
            except ValueError:
                limit = default
            i += 2
            continue
        cleaned.append(arg)
        i += 1
    return cleaned, limit


def cmd_resume(args: str) -> SessionState | None:
    """Handle /resume [session_id] — resume an interrupted session.

    Returns the full SessionState (with messages) for the caller to restore
    into ConversationContext, or None if no session was selected.
    """
    from core.cli import commands as _pkg
    from core.memory.session_checkpoint import SessionCheckpoint

    checkpoint = SessionCheckpoint()

    if args.strip():
        # Explicit session ID
        state = checkpoint.load(args.strip())
        if state is None:
            _pkg.console.print(f"  [warning]Session not found: {args.strip()}[/warning]")
            _pkg.console.print()
            return None
        if state.status not in ("active", "paused"):
            _pkg.console.print(
                f"  [warning]Session {args.strip()} is {state.status} (not resumable)[/warning]"
            )
            _pkg.console.print()
            return None
        _pkg.console.print(f"  [success]Resuming session: {state.session_id}[/success]")
        if state.user_input:
            _pkg.console.print(f"  [muted]Original input: {state.user_input[:80]}[/muted]")
        _pkg.console.print(
            f"  [muted]Round: {state.round_idx} | Messages: {len(state.messages)}[/muted]"
        )
        cognitive_summary = _format_cognitive_state_summary(state.cognitive_state)
        if cognitive_summary:
            _pkg.console.print(f"  [muted]Cognitive: {cognitive_summary}[/muted]")
        _pkg.console.print()
        return state

    # No args: list resumable sessions
    sessions = checkpoint.list_resumable()
    if not sessions:
        _pkg.console.print("  [muted]No resumable sessions found.[/muted]")
        _pkg.console.print()
        return None

    import time as _time

    _pkg.console.print()
    _pkg.console.print("  [header]Resumable Sessions[/header]")
    for i, s in enumerate(sessions[:10], 1):
        age_min = (_time.time() - s.updated_at) / 60
        age_str = f"{age_min:.0f}m ago" if age_min < 60 else f"{age_min / 60:.1f}h ago"
        label = s.user_input[:50] if s.user_input else "(no input)"
        cognitive_summary = _format_cognitive_state_summary(s.cognitive_state)
        suffix = f" | {cognitive_summary}" if cognitive_summary else ""
        _pkg.console.print(
            f"  {i}. [bold]{s.session_id}[/bold] [{s.status}] {age_str}{suffix}"
        )
        _pkg.console.print(f"     [muted]{label}[/muted]")
    _pkg.console.print()
    _pkg.console.print("  [muted]Usage: /resume <session_id>[/muted]")
    _pkg.console.print()
    return None


def cmd_cognitive(args: str) -> None:
    """Show persisted cognitive state for a resumable session.

    Usage:
        /cognitive <session_id> [--last N]
    """
    from core.cli import commands as _pkg
    from core.memory.cognitive_state_store import CognitiveStateStore
    from core.memory.session_checkpoint import SessionCheckpoint

    parts, limit = _parse_last_flag(args.strip().split())
    if not parts:
        _pkg.console.print("  [warning]Usage: /cognitive <session_id> [--last N][/warning]")
        _pkg.console.print("  [muted]/resume lists available session ids.[/muted]")
        _pkg.console.print()
        return

    session_id = parts[0]
    checkpoint = SessionCheckpoint()
    state = checkpoint.load(session_id)
    if state is None:
        _pkg.console.print(f"  [warning]Session not found: {session_id}[/warning]")
        _pkg.console.print()
        return

    snapshot = state.cognitive_state
    _pkg.console.print()
    _pkg.console.print(f"  [header]Cognitive State[/header] [muted]{session_id}[/muted]")
    summary = _format_cognitive_state_summary(snapshot)
    if summary:
        _pkg.console.print(f"  [muted]{summary}[/muted]")
    else:
        _pkg.console.print("  [muted]No persisted cognitive snapshot.[/muted]")

    goal = snapshot.get("goal") if isinstance(snapshot, dict) else ""
    if isinstance(goal, str) and goal:
        _pkg.console.print(f"  [label]Goal:[/label] {goal[:160]}")

    observations = snapshot.get("observations") if isinstance(snapshot, dict) else None
    if isinstance(observations, list) and observations:
        _pkg.console.print("  [label]Recent observations:[/label]")
        for item in observations[-5:]:
            if isinstance(item, str):
                _pkg.console.print(f"    - {item[:160]}")

    hypotheses = snapshot.get("hypotheses") if isinstance(snapshot, dict) else None
    if isinstance(hypotheses, list) and hypotheses:
        _pkg.console.print("  [label]Hypotheses:[/label]")
        for item in hypotheses[-5:]:
            if isinstance(item, str):
                _pkg.console.print(f"    - {item[:160]}")

    store = CognitiveStateStore(checkpoint.session_dir / "sessions.db")
    try:
        events = store.recent_events(session_id, limit=limit)
        _pkg.console.print(f"  [label]Events:[/label] {store.event_count(session_id)} persisted")
        for event in events:
            event_summary = _format_cognitive_state_summary(event.snapshot)
            suffix = f" — {event_summary}" if event_summary else ""
            _pkg.console.print(f"    - #{event.id} {event.phase}{suffix}")
    finally:
        store.close()
    _pkg.console.print()


def cmd_apply(args: str) -> None:
    """Manage job applications via tracker.json.

    /apply                          -> list all applications
    /apply add <company> <position> -> add new application
    /apply status <company> <status> -> update status
    /apply remove <company>         -> remove application
    """
    from core.cli import commands as _pkg
    from core.memory.vault import ApplicationEntry, ApplicationTracker

    tracker = ApplicationTracker()
    parts = args.strip().split() if args.strip() else []

    # /apply (no args) -> list
    if not parts:
        entries = tracker.list()
        if not entries:
            _pkg.console.print("  [muted]No applications tracked.[/muted]")
            _pkg.console.print("  [muted]Usage: /apply add <company> <position>[/muted]")
            _pkg.console.print()
            return
        _pkg.console.print()
        _pkg.console.print(f"  [header]Applications ({len(entries)})[/header]")
        for e in entries:
            status_style = {
                "draft": "muted",
                "applied": "label",
                "interview": "warning",
                "offer": "success",
                "rejected": "error",
            }.get(e.status, "muted")
            _pkg.console.print(
                f"  [{status_style}]{e.status:<12}[/{status_style}] "
                f"[value]{e.company}[/value] — {e.position}"
            )
        _pkg.console.print()
        return

    sub = parts[0].lower()

    # /apply add <company> <position>
    if sub == "add":
        if len(parts) < 3:
            _pkg.console.print("  [warning]Usage: /apply add <company> <position>[/warning]")
            _pkg.console.print()
            return
        company = parts[1]
        position = " ".join(parts[2:])
        tracker.add(ApplicationEntry(company=company, position=position))
        _pkg.console.print(f"  [success]Added: {company} — {position}[/success]")
        _pkg.console.print()
        return

    # /apply status <company> <status>
    if sub == "status":
        if len(parts) < 3:
            _pkg.console.print("  [warning]Usage: /apply status <company> <status>[/warning]")
            _pkg.console.print(
                f"  [muted]Valid statuses: {', '.join(ApplicationTracker.VALID_STATUSES)}[/muted]"
            )
            _pkg.console.print()
            return
        company = parts[1]
        status = parts[2].lower()
        if status not in ApplicationTracker.VALID_STATUSES:
            _pkg.console.print(f"  [warning]Invalid status: {status}[/warning]")
            _pkg.console.print(
                f"  [muted]Valid: {', '.join(ApplicationTracker.VALID_STATUSES)}[/muted]"
            )
            _pkg.console.print()
            return
        if tracker.update_status(company, status):
            _pkg.console.print(f"  [success]{company}: {status}[/success]")
        else:
            _pkg.console.print(f"  [warning]Not found: {company}[/warning]")
        _pkg.console.print()
        return

    # /apply remove <company>
    if sub == "remove":
        if len(parts) < 2:
            _pkg.console.print("  [warning]Usage: /apply remove <company>[/warning]")
            _pkg.console.print()
            return
        company = parts[1]
        if tracker.remove(company):
            _pkg.console.print(f"  [success]Removed: {company}[/success]")
        else:
            _pkg.console.print(f"  [warning]Not found: {company}[/warning]")
        _pkg.console.print()
        return

    _pkg.console.print("  [warning]Usage: /apply [add|status|remove] ...[/warning]")
    _pkg.console.print()


def cmd_context(args: str) -> None:
    """Show assembled context from all tiers.

    /context           -> show all tier summaries
    /context career    -> show career identity
    /context profile   -> show user profile
    """
    from core.cli import commands as _pkg

    sub = args.strip().lower()

    # Career sub-command
    if sub == "career":
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        career = profile.load_career()
        if not career:
            _pkg.console.print(
                "  [muted]No career data. Edit ~/.geode/identity/career.toml[/muted]"
            )
            _pkg.console.print()
            return
        _pkg.console.print()
        _pkg.console.print("  [header]Career Identity[/header]")
        identity = career.get("identity", {})
        for k, v in identity.items():
            _pkg.console.print(f"  [label]{k}:[/label] {v}")
        goals = career.get("goals", {})
        if goals:
            _pkg.console.print()
            _pkg.console.print("  [header]Goals[/header]")
            for k, v in goals.items():
                _pkg.console.print(f"  [label]{k}:[/label] {v}")
        _pkg.console.print()
        return

    # Profile sub-command
    if sub == "profile":
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        data = profile.load_profile()
        if not data:
            _pkg.console.print("  [muted]No profile data. Run `geode init`.[/muted]")
            _pkg.console.print()
            return
        _pkg.console.print()
        _pkg.console.print("  [header]User Profile[/header]")
        for k, v in data.items():
            if k == "preferences":
                continue
            if k == "learned_patterns":
                continue
            if v:
                _pkg.console.print(f"  [label]{k}:[/label] {v}")
        _pkg.console.print()
        return

    # Default: show all tier summaries
    _pkg.console.print()
    _pkg.console.print("  [header]Context Tiers[/header]")

    # Tier 0: SOUL
    try:
        from core.memory.organization import MonoLakeOrganizationMemory

        org = MonoLakeOrganizationMemory()
        soul = org.get_soul()
        if soul:
            preview = soul.split("\n")[0][:80] if soul else "(empty)"
            _pkg.console.print(f"  [label]T0 SOUL:[/label] {preview}")
        else:
            _pkg.console.print("  [label]T0 SOUL:[/label] [muted]not found[/muted]")
    except Exception as exc:
        err = type(exc).__name__
        _pkg.console.print(f"  [label]T0 SOUL:[/label] [muted]unavailable ({err})[/muted]")

    # Tier 0.5: User Profile
    try:
        from core.memory.user_profile import FileBasedUserProfile

        profile = FileBasedUserProfile()
        summary = profile.get_context_summary()
        _pkg.console.print(f"  [label]T0.5 Profile:[/label] {summary or '[muted]empty[/muted]'}")
        career_summary = profile.get_career_summary()
        if career_summary:
            _pkg.console.print(f"  [label]T0.5 Career:[/label] {career_summary}")
    except Exception as exc:
        err = type(exc).__name__
        _pkg.console.print(f"  [label]T0.5 Profile:[/label] [muted]unavailable ({err})[/muted]")

    # Tier 1: Project Memory
    try:
        from core.memory.project import ProjectMemory

        mem = ProjectMemory()
        if mem.exists():
            rules = mem.list_rules()
            _pkg.console.print(f"  [label]T1 Project:[/label] {len(rules)} rules")
        else:
            _pkg.console.print("  [label]T1 Project:[/label] [muted]not initialized[/muted]")
    except Exception as exc:
        err = type(exc).__name__
        _pkg.console.print(f"  [label]T1 Project:[/label] [muted]unavailable ({err})[/muted]")

    # Vault
    try:
        from core.memory.vault import Vault

        vault = Vault()
        vs = vault.get_context_summary()
        _pkg.console.print(f"  [label]V0 Vault:[/label] {vs or '[muted]empty[/muted]'}")
    except Exception as exc:
        err = type(exc).__name__
        _pkg.console.print(f"  [label]V0 Vault:[/label] [muted]unavailable ({err})[/muted]")

    _pkg.console.print()
    _pkg.console.print("  [muted]Subcommands: /context career | /context profile[/muted]")
    _pkg.console.print()


# ---------------------------------------------------------------------------
# /compact — Context Budget compaction (Karpathy P6)
# ---------------------------------------------------------------------------


def cmd_compact(args: str) -> None:
    """Compact conversation context to fit within model budget.

    /compact         -> compact to current model's 70% budget
    /compact --hard  -> keep only last 1 turn
    """
    from core.cli import commands as _pkg
    from core.config import settings
    from core.orchestration.context_monitor import (
        adaptive_prune,
        check_context,
        summarize_tool_results,
    )

    ctx = _pkg.get_conversation_context()
    if ctx is None or not ctx.messages:
        _pkg.console.print("  [muted]Nothing to compact.[/muted]")
        _pkg.console.print()
        return

    before = check_context(ctx.messages, settings.model)
    _pkg.console.print()
    _pkg.console.print(
        f"  [label]Before:[/label] {before.estimated_tokens:,} tokens "
        f"({before.usage_pct:.0f}% of {settings.model} "
        f"{before.context_window:,})"
    )

    hard = "--hard" in args
    if hard:
        last_pair = ctx.messages[-2:] if len(ctx.messages) >= 2 else list(ctx.messages)
        ctx.messages.clear()
        ctx.messages.extend(last_pair)
    else:
        summarize_tool_results(ctx.messages, before.context_window)
        compacted = adaptive_prune(ctx.messages, before.context_window)
        ctx.messages.clear()
        ctx.messages.extend(compacted)

    ctx._sanitize_tool_pairs()

    after = check_context(ctx.messages, settings.model)
    _pkg.console.print(
        f"  [label]After:[/label]  {after.estimated_tokens:,} tokens "
        f"({after.usage_pct:.0f}% of {settings.model} "
        f"{after.context_window:,})"
    )
    _pkg.console.print(
        f"  [success]Compacted[/success]  "
        f"{before.estimated_tokens:,} → {after.estimated_tokens:,} tokens"
    )
    _pkg.console.print()


# ---------------------------------------------------------------------------
# /clear — Clear conversation history
# ---------------------------------------------------------------------------


def cmd_clear(args: str) -> None:
    """Clear conversation context entirely.

    /clear         -> confirm prompt before clearing
    /clear --force -> clear without confirmation
    """
    from core.cli import commands as _pkg

    ctx = _pkg.get_conversation_context()
    if ctx is None or not ctx.messages:
        _pkg.console.print("  [muted]Conversation already empty.[/muted]")
        _pkg.console.print()
        return

    msg_count = len(ctx.messages)
    _pkg.console.print()

    if "--force" not in args:
        # v0.51.1: in IPC mode, native input() blocks the daemon and never
        # reaches the thin client REPL. Detect via the IPC writer thread-local
        # and require an explicit --force flag instead.
        from core.ui.agentic_ui import _ipc_writer_local

        in_ipc_mode = getattr(_ipc_writer_local, "writer", None) is not None
        if in_ipc_mode:
            _pkg.console.print(
                f"  [warning]Refusing to clear {msg_count} messages without --force.[/warning]"
            )
            _pkg.console.print(
                "  [muted]Run /clear --force to confirm "
                "(IPC mode disables interactive prompts).[/muted]"
            )
            _pkg.console.print()
            return
        _pkg.console.print(f"  Clear all {msg_count} messages? (y/N): ", end="")
        try:
            answer = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        if answer != "y":
            _pkg.console.print("  [muted]Cancelled.[/muted]")
            _pkg.console.print()
            return

    ctx.clear()

    # Reset token tracker so stale cost/token counts don't persist
    from core.llm.token_tracker import reset_tracker

    reset_tracker()

    _pkg.console.print(f"  [success]Conversation cleared[/success] ({msg_count} messages removed)")
    _pkg.console.print()
