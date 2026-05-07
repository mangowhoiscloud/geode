"""``/trigger`` slash command — manage event/cron triggers.

Hosts ``cmd_trigger``. Extracted from the monolithic
``core/cli/commands.py`` (Tier 3 #9) — every function body is preserved
byte-identical from the legacy module.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def cmd_trigger(args: str) -> None:
    """Handle /trigger command — manage event/cron triggers.

    /trigger           → list active triggers
    /trigger list      → list active triggers
    /trigger fire <ev> → manually fire an event
    """
    from core.cli import commands as _pkg

    arg = args.strip().lower()

    if not arg or arg == "list":
        _pkg.console.print()
        _pkg.console.print("  [header]Trigger Manager[/header]")
        _pkg.console.print("  [muted]Triggers are wired to HookSystem at priority 70.[/muted]")
        _pkg.console.print()
        _pkg.console.print("  Event-based: CUSUM drift → auto-snapshot, model evaluation")
        _pkg.console.print("  Cron-based:  Managed via /schedule templates")
        _pkg.console.print()
        _pkg.console.print("  [muted]Use /trigger fire <event> to manually dispatch.[/muted]")
        _pkg.console.print()
        return

    parts = arg.split(None, 1)
    if parts[0] == "fire" and len(parts) > 1:
        event_name = parts[1]
        _pkg.console.print(f"  [warning]Cannot fire event: {event_name}[/warning]")
        _pkg.console.print(
            "  [muted]Manual event dispatch requires a running TriggerManager "
            "instance (available in GeodeRuntime, not standalone REPL).[/muted]"
        )
        _pkg.console.print()
        return

    _pkg.console.print("  [warning]Usage: /trigger [list|fire <event>][/warning]")
    _pkg.console.print()
