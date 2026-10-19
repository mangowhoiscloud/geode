"""``/trigger`` slash command — list or manually fire registered triggers.

Renders the composed :class:`TriggerManager` (owned by the runtime's
SchedulerService); the console output is display only, never the dispatch.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def cmd_trigger(args: str, *, scheduler_service: Any = None) -> None:
    """Handle /trigger command.

    /trigger           → list registered triggers
    /trigger list      → list registered triggers
    /trigger fire <id> → manually fire a registered trigger
    """
    from core.cli import commands as _pkg

    console = _pkg.console
    manager = getattr(scheduler_service, "trigger_manager", None)
    parts = args.strip().split(None, 1)
    sub = parts[0].lower() if parts else "list"

    if sub not in ("list", "fire") or (sub == "fire" and len(parts) < 2):
        console.print("  [warning]Usage: /trigger [list|fire <trigger_id>][/warning]")
        console.print()
        return
    if manager is None:
        console.print("  [warning]Trigger manager not available[/warning]")
        console.print()
        return

    if sub == "list":
        triggers = manager.inventory()
        console.print()
        console.print("  [header]Triggers[/header]")
        if not triggers:
            console.print("  [muted]No triggers registered.[/muted]")
        for t in triggers:
            state = "[success]ON[/success]" if t["enabled"] else "[muted]OFF[/muted]"
            detail = t["cron_expr"] or t["event_name"]
            console.print(f"  {state}  [label]{t['trigger_id']}[/label] {t['type']} {detail}")
        console.print()
        return

    trigger_id = parts[1].strip()
    try:
        result = manager.fire_manual(trigger_id)
    except KeyError:
        console.print(f"  [warning]Unknown trigger: {trigger_id}[/warning]")
        console.print()
        return
    if result.success:
        console.print(f"  [success]Fired: {trigger_id}[/success]")
    else:
        console.print(f"  [warning]Trigger failed: {result.error}[/warning]")
    console.print()
