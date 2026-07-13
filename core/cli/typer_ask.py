"""``geode ask`` — operator surface for pending clarification asks.

Autonomous runs (scheduled jobs) that stop with
``termination_reason="user_clarification_needed"`` persist their question
as a pending ask (:mod:`core.memory.pending_ask`) and notify the operator.
This sub-app is the terminal-side reply surface:

- ``geode ask list`` — open questions (``--all`` includes resolved ones)
- ``geode ask show <id>`` — full question + reply instructions
- ``geode ask answer <id> "<text>"`` — claim the answer (first reply wins)
  and resume the checkpointed session through the serve daemon

The channel-side reply surface (``ask <id> <answer>`` in a bound Slack /
Telegram channel) lives in the gateway processor (``typer_serve``); both
claim through the same store, so exactly one reply wins.
"""

from __future__ import annotations

import getpass
import time

import typer

from core.ui.console import console

ask_app = typer.Typer(help="Pending clarification asks from autonomous runs")


def _age(created_at: float) -> str:
    delta = max(0.0, time.time() - created_at)
    if delta < 3600:
        return f"{delta / 60:.0f}m"
    if delta < 86400:
        return f"{delta / 3600:.1f}h"
    return f"{delta / 86400:.1f}d"


@ask_app.command("list")
def list_asks(
    show_all: bool = typer.Option(False, "--all", help="Include answered/expired asks"),
) -> None:
    """List pending clarification asks."""
    from rich.table import Table

    from core.memory.pending_ask import PendingAskStore

    store = PendingAskStore()
    asks = store.list_asks() if show_all else store.list_pending()
    if not asks:
        console.print("  [muted]No pending asks.[/muted]")
        return

    table = Table(show_header=True, padding=(0, 2), box=None)
    table.add_column("id")
    table.add_column("age")
    table.add_column("status")
    table.add_column("source")
    table.add_column("question")
    for ask in asks:
        question = " ".join(ask.question.split())
        if len(question) > 70:
            question = question[:69] + "…"
        table.add_row(ask.ask_id, _age(ask.created_at), ask.status, ask.source, question)
    console.print(table)
    console.print('  [muted]Answer with: geode ask answer <id> "<text>"[/muted]')


@ask_app.command("show")
def show_ask(ask_id: str = typer.Argument(..., help="Ask id (prefix allowed)")) -> None:
    """Show one ask in full."""
    from core.memory.pending_ask import PendingAskStore, format_ask_notification

    store = PendingAskStore()
    ask = store.find(ask_id)
    if ask is None:
        console.print(f"  [error]Unknown ask id '{ask_id}'[/error]")
        raise typer.Exit(code=1)

    console.print(f"  id        {ask.ask_id}")
    console.print(f"  status    {ask.status}")
    console.print(f"  source    {ask.source}")
    console.print(f"  session   {ask.session_id}")
    console.print(f"  age       {_age(ask.created_at)}")
    if ask.notified_channel:
        console.print(f"  notified  {ask.notified_channel} → {ask.notified_recipient}")
    if ask.status == "answered":
        console.print(f"  answered  by {ask.answered_by}, {_age(ask.answered_at)} ago")
        console.print(f"  answer    {ask.answer}")
    console.print()
    if ask.status == "pending":
        console.print(format_ask_notification(ask))


@ask_app.command("answer")
def answer_ask(
    ask_id: str = typer.Argument(..., help="Ask id (prefix allowed)"),
    answer: str = typer.Argument(..., help="Answer text for the paused run"),
) -> None:
    """Answer an ask and resume its session via the serve daemon."""
    from core.cli.ipc_client import IPCClient
    from core.memory.pending_ask import ALREADY_ANSWERED, EXPIRED, RESOLVED, PendingAskStore

    store = PendingAskStore()
    ask = store.find(ask_id)
    if ask is None:
        console.print(f"  [error]Unknown ask id '{ask_id}' — see: geode ask list[/error]")
        raise typer.Exit(code=1)

    # Connect BEFORE claiming: a claim without a reachable daemon would
    # burn the one winning reply on a continuation that cannot run.
    client = IPCClient()
    if not client.connect():
        console.print(
            "  [error]serve daemon unreachable — start it (geode serve) and retry; "
            "the ask was NOT claimed.[/error]"
        )
        raise typer.Exit(code=1)

    try:
        outcome, resolved = store.resolve(
            ask.ask_id,
            answer,
            answered_by=f"cli:{getpass.getuser()}",
        )
        if outcome == ALREADY_ANSWERED and resolved is not None:
            console.print(
                f"  [warning]Ask {resolved.ask_id} was already answered by "
                f"{resolved.answered_by} (first reply wins).[/warning]"
            )
            raise typer.Exit(code=1)
        if outcome == EXPIRED:
            console.print(f"  [warning]Ask {ask.ask_id} expired — not resumed.[/warning]")
            raise typer.Exit(code=1)
        if outcome != RESOLVED or resolved is None:
            console.print(f"  [error]Ask {ask.ask_id} could not be resolved ({outcome})[/error]")
            raise typer.Exit(code=1)

        resumed = client.request_resume(session_id=resolved.session_id)
        if resumed.get("type") != "resumed":
            console.print(
                f"  [warning]Answer recorded, but session resume failed: "
                f"{resumed.get('message', 'unknown error')}[/warning]"
            )
            raise typer.Exit(code=1)

        console.print(
            f"  [muted]ask {resolved.ask_id} → session {resolved.session_id} resumed[/muted]"
        )
        result = client.send_prompt(answer)
        if result.get("type") == "result":
            text = result.get("text", "")
            if text:
                console.print(text)
        else:
            console.print(
                f"  [warning]Continuation error: {result.get('message', 'unknown')}[/warning]"
            )
            raise typer.Exit(code=1)
    finally:
        client.close()
