"""Bootstrap Hook — pre-execution node configuration system.

Allows hooks to modify node configuration (prompts, parameters) before
each node executes, enabling per-IP or per-genre customization without
modifying core node code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from core.hooks import HookEvent, HookSystem

log = logging.getLogger(__name__)


@dataclass
class BootstrapContext:
    """Configuration context prepared before node execution.

    Hooks modify this context in-place via the NODE_BOOTSTRAP event
    to customize node behavior per-IP or per-genre.
    """

    node_name: str
    ip_name: str
    prompt_overrides: dict[str, str] = field(default_factory=dict)
    extra_instructions: list[str] = field(default_factory=list)
    parameters: dict[str, Any] = field(default_factory=dict)
    skip: bool = False


class BootstrapManager:
    """Manages NODE_BOOTSTRAP lifecycle for node configuration.

    Usage:
        mgr = BootstrapManager(hooks)
        mgr.register_override("router", lambda ctx: ctx.extra_instructions.append("Focus on RPG"))
        ctx = mgr.prepare_node("router", "Berserk", state)
        if not ctx.skip:
            state = mgr.apply_context(state, ctx)
            # ... execute node
    """

    def __init__(self, hooks: HookSystem) -> None:
        self._hooks = hooks

    def prepare_node(self, node_name: str, ip_name: str, state: dict[str, Any]) -> BootstrapContext:
        """Create a BootstrapContext and trigger NODE_BOOTSTRAP.

        Hooks registered for NODE_BOOTSTRAP can modify the context in-place
        via ``data["bootstrap_context"]``.

        Args:
            node_name: Name of the node about to execute.
            ip_name: IP name from pipeline state.
            state: Current pipeline state dict (read-only reference for hooks).

        Returns:
            The (possibly modified) BootstrapContext.
        """
        ctx = BootstrapContext(node_name=node_name, ip_name=ip_name)

        hook_data: dict[str, Any] = {
            "node": node_name,
            "ip_name": ip_name,
            "bootstrap_context": ctx,
        }

        self._hooks.trigger(HookEvent.NODE_BOOTSTRAP, hook_data)

        return ctx

    def register_override(
        self,
        node_name: str,
        override_fn: Callable[[BootstrapContext], None],
        *,
        name: str | None = None,
        priority: int = 100,
    ) -> None:
        """Convenience: register a NODE_BOOTSTRAP handler for a specific node.

        The handler only fires when ``data["node"]`` matches *node_name*.

        Args:
            node_name: Target node name (e.g. "router", "analyst").
            override_fn: Callable that receives BootstrapContext and modifies it in-place.
            name: Optional handler name for unregistration.
            priority: Hook priority (lower = higher priority, runs first).
        """
        handler_name = name or f"bootstrap_{node_name}_{id(override_fn)}"

        def _handler(event: HookEvent, data: dict[str, Any]) -> None:
            if data.get("node") != node_name:
                return
            ctx = data.get("bootstrap_context")
            if isinstance(ctx, BootstrapContext):
                override_fn(ctx)

        self._hooks.register(
            HookEvent.NODE_BOOTSTRAP,
            _handler,
            name=handler_name,
            priority=priority,
        )

    @staticmethod
    def apply_context(state: dict[str, Any], context: BootstrapContext) -> dict[str, Any]:
        """Merge BootstrapContext overrides into pipeline state.

        Creates a shallow copy of state and applies:
        - ``prompt_overrides`` → stored under ``"_prompt_overrides"``
        - ``extra_instructions`` → stored under ``"_extra_instructions"``
        - ``parameters`` → stored under ``"_bootstrap_parameters"``

        Downstream nodes can read these keys to adjust their behavior.

        Args:
            state: Current pipeline state dict.
            context: The prepared BootstrapContext.

        Returns:
            New state dict with overrides merged in.
        """
        merged = dict(state)

        if context.prompt_overrides:
            merged["_prompt_overrides"] = context.prompt_overrides

        if context.extra_instructions:
            merged["_extra_instructions"] = context.extra_instructions

        if context.parameters:
            merged["_bootstrap_parameters"] = context.parameters

        return merged
