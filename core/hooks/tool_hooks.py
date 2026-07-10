"""Shared HookSystem injection for tool handlers (PR-PRE10-ROUND2).

A single ContextVar-bound HookSystem that tool handlers fire events through,
set once by ``core.wiring.bootstrap``. Lives in ``core.hooks`` (not a tool
package) so handlers in ANY layer — including ``core.cli.tool_handlers`` —
can fire without forcing bootstrap to import that layer (the Server-never-CLI
import contract). Mirrors the per-module ``_hooks_ctx`` pattern in
``core/tools/memory_tools.py``, generalized.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from core.hooks.dispatch import fire_hook
from core.hooks.system import HookEvent

_tool_hooks_ctx: ContextVar[Any] = ContextVar("tool_hooks", default=None)


def set_tool_hooks(hooks: Any) -> None:
    """Inject the active HookSystem so tool handlers can fire events."""
    _tool_hooks_ctx.set(hooks)


def clear_tool_hooks(expected: Any) -> bool:
    """Clear the current-context binding when it still matches ``expected``."""
    if _tool_hooks_ctx.get() is not expected:
        return False
    _tool_hooks_ctx.set(None)
    return True


def fire_tool_hook(event: HookEvent, data: dict[str, Any]) -> None:
    """Fire a hook via the ContextVar-bound HookSystem (no-op if unset)."""
    fire_hook(_tool_hooks_ctx.get(), event, data)
