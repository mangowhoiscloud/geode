"""``/tasks`` slash command — show user task list.

Hosts ``cmd_tasks``. Extracted from the monolithic
``core/cli/commands.py`` (Tier 3 #9) — every function body is preserved
byte-identical from the legacy module.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def cmd_tasks(args: str) -> None:
    """Show user task list.

    Usage:
        /tasks            — show all tasks
        /tasks pending    — show pending only
        /tasks done       — show completed tasks
    """
    from core.cli import commands as _pkg
    from core.cli.session_state import _get_user_task_graph
    from core.orchestration.task_system import TaskStatus

    _STATUS_LABEL: dict[TaskStatus, tuple[str, str]] = {
        TaskStatus.PENDING: ("○", "muted"),
        TaskStatus.READY: ("○", "muted"),
        TaskStatus.RUNNING: ("▶", "value"),
        TaskStatus.COMPLETED: ("✓", "success"),
        TaskStatus.FAILED: ("✗", "error"),
        TaskStatus.SKIPPED: ("–", "muted"),
    }

    filter_arg = args.strip().lower()
    graph = _get_user_task_graph()
    all_tasks = [graph.get_task(tid) for batch in graph.topological_order() for tid in batch]
    all_tasks = [t for t in all_tasks if t is not None]

    # Apply filter
    if filter_arg in ("pending", "todo"):
        all_tasks = [t for t in all_tasks if t.status in (TaskStatus.PENDING, TaskStatus.READY)]
    elif filter_arg in ("done", "completed"):
        all_tasks = [t for t in all_tasks if t.status == TaskStatus.COMPLETED]
    elif filter_arg in ("active", "running"):
        all_tasks = [t for t in all_tasks if t.status == TaskStatus.RUNNING]

    _pkg.console.print()
    if not all_tasks:
        _pkg.console.print("  [muted]No tasks.[/muted]")
        _pkg.console.print()
        return

    # Sort: running first, then pending, then completed/failed
    _order = {
        TaskStatus.RUNNING: 0,
        TaskStatus.READY: 1,
        TaskStatus.PENDING: 1,
        TaskStatus.FAILED: 2,
        TaskStatus.SKIPPED: 2,
        TaskStatus.COMPLETED: 3,
    }
    all_tasks.sort(key=lambda t: _order.get(t.status, 9))

    _pkg.console.print("  [header]Tasks[/header]")
    for task in all_tasks:
        icon, style = _STATUS_LABEL.get(task.status, ("?", "muted"))
        owner = task.metadata.get("owner", "")
        owner_tag = f"  [muted]{owner}[/muted]" if owner else ""
        elapsed = f"  [muted]{task.elapsed_s:.1f}s[/muted]" if task.elapsed_s else ""
        _pkg.console.print(
            f"  [{style}]{icon}[/{style}]  [{style}]{task.task_id}[/{style}]"
            f"  {task.name}{owner_tag}{elapsed}"
        )
    _pkg.console.print()
    running = sum(1 for t in all_tasks if t.status == TaskStatus.RUNNING)
    pending = sum(1 for t in all_tasks if t.status in (TaskStatus.PENDING, TaskStatus.READY))
    done = sum(1 for t in all_tasks if t.status == TaskStatus.COMPLETED)
    _pkg.console.print(
        f"  [muted]{len(all_tasks)} total"
        f"  ▶ {running} active  ○ {pending} pending  ✓ {done} done[/muted]"
    )
    _pkg.console.print()
