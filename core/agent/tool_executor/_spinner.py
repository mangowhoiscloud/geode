"""Tool execution spinner — signature shimmer line during post-approval tool execution."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def _tool_spinner(label: str) -> Iterator[None]:
    """Show the signature shimmer spinner during post-approval tool execution.

    Displays ``label`` on the shared rose shimmer line (``core.ui.status.TextSpinner``,
    which renders through ``core.ui.spinner_glyph`` — the single spinner source)
    while the wrapped block runs, then clears it on exit so OperationLogger
    markers (✓/✗) render cleanly.

    Skipped in IPC mode — thin CLI has its own ToolCallTracker spinner.
    Running both causes ANSI cursor-up race → UI corruption.

    Also skipped when the active console is non-TTY (e.g. local REPL
    piped to a file, CI) — spinner ANSI frames would pollute log output.
    """
    # IPC mode: ToolCallTracker on thin CLI handles the spinner
    from core.ui.agentic_ui import _ipc_writer_local

    if getattr(_ipc_writer_local, "writer", None) is not None:
        yield
        return

    # Lookup `console` via the package namespace so tests patching
    # `core.agent.tool_executor.console` affect this code path.
    from core.agent import tool_executor as _pkg

    if not getattr(_pkg.console, "is_terminal", True):
        yield
        return

    from core.ui.status import TextSpinner

    spinner = TextSpinner(label)
    spinner.start()
    try:
        yield
    finally:
        spinner.stop()
