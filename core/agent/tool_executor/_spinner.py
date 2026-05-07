"""Tool execution spinner — Rich dots spinner during post-approval tool execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def _tool_spinner(label: str) -> Iterator[None]:
    """Show a Rich dots spinner during post-approval tool execution.

    Displays ``label`` with a spinner while the wrapped block runs,
    then clears it on exit so OperationLogger markers (✓/✗) render cleanly.

    Skipped in IPC mode — thin CLI has its own ToolCallTracker spinner.
    Running both causes ANSI cursor-up race → UI corruption.
    """
    # IPC mode: ToolCallTracker on thin CLI handles the spinner
    from core.ui.agentic_ui import _ipc_writer_local

    if getattr(_ipc_writer_local, "writer", None) is not None:
        yield
        return

    # Lookup `console` via the package namespace so tests patching
    # `core.agent.tool_executor.console` affect this code path.
    from core.agent import tool_executor as _pkg

    status = _pkg.console.status(f"  [dim]✢ {label}[/dim]", spinner="dots", spinner_style="cyan")
    status.start()
    try:
        yield
    finally:
        status.stop()
