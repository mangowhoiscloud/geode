"""LLM router hook system — optional lifecycle hooks for LLM call observability.

Wires HookSystem into the router so call_llm*/call_with_failover can emit
LLM_CALL_START/END and retry_wait events without depending on hooks at
import time. ``set_router_hooks`` is invoked from runtime wiring after hooks
are built.
"""

from __future__ import annotations

import logging
from typing import Any

from core.hooks.system import HookEvent
from core.hooks.utils import fire_hook

log = logging.getLogger(__name__)

_hooks_ctx: Any = None  # HookSystem | None — set via set_router_hooks()


def set_router_hooks(hooks: Any) -> None:
    """Wire HookSystem into the LLM router for LLM_CALL_START/END events.

    Called from runtime wiring after hooks are built.
    """
    global _hooks_ctx
    _hooks_ctx = hooks


def _fire_hook(event: HookEvent, data: dict[str, Any]) -> None:
    """Fire a hook event if HookSystem is wired (or no-op)."""
    fire_hook(_hooks_ctx, event, data)
