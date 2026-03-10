"""Hook System — event-driven extension points for the GEODE pipeline.

Layer 4 orchestration component that allows registering callbacks
for pipeline events (pre/post node execution, errors, etc.).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger(__name__)


class HookEvent(Enum):
    """Pipeline lifecycle events (23 events)."""

    # Pipeline level
    PIPELINE_START = "pipeline_start"
    PIPELINE_END = "pipeline_end"
    PIPELINE_ERROR = "pipeline_error"

    # Node level
    NODE_BOOTSTRAP = "node_bootstrap"
    NODE_ENTER = "node_enter"
    NODE_EXIT = "node_exit"
    NODE_ERROR = "node_error"

    # Analysis level
    ANALYST_COMPLETE = "analyst_complete"
    EVALUATOR_COMPLETE = "evaluator_complete"
    SCORING_COMPLETE = "scoring_complete"

    # Verification level
    VERIFICATION_PASS = "verification_pass"  # noqa: S105 — hook event name, not a password
    VERIFICATION_FAIL = "verification_fail"

    # L4.5 Automation level
    DRIFT_DETECTED = "drift_detected"
    OUTCOME_COLLECTED = "outcome_collected"
    MODEL_PROMOTED = "model_promoted"
    SNAPSHOT_CAPTURED = "snapshot_captured"
    TRIGGER_FIRED = "trigger_fired"
    POST_ANALYSIS = "post_analysis"

    # Memory Autonomy (P0-C → P1.5)
    MEMORY_SAVED = "memory_saved"
    RULE_CREATED = "rule_created"
    RULE_UPDATED = "rule_updated"
    RULE_DELETED = "rule_deleted"

    # Prompt Assembly (ADR-007)
    PROMPT_ASSEMBLED = "prompt_assembled"


@dataclass
class HookResult:
    """Result from a hook execution."""

    success: bool
    event: HookEvent
    handler_name: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# Type alias for hook handlers
HookHandler = Callable[[HookEvent, dict[str, Any]], None]


@dataclass
class _RegisteredHook:
    """Internal registration record."""

    handler: HookHandler
    name: str
    priority: int  # Lower = higher priority (runs first)


class HookSystem:
    """Register and trigger hooks on pipeline events.

    Hooks execute in priority order (lower number = higher priority).

    Usage:
        hooks = HookSystem()

        def on_start(event, data):
            print(f"Pipeline started for {data.get('ip_name')}")

        hooks.register(HookEvent.PIPELINE_START, on_start, priority=10)
        results = hooks.trigger(HookEvent.PIPELINE_START, {"ip_name": "Berserk"})
    """

    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[_RegisteredHook]] = {}

    def register(
        self,
        event: HookEvent,
        handler: HookHandler,
        *,
        name: str | None = None,
        priority: int = 100,
    ) -> None:
        """Register a hook handler for an event."""
        hook_name = name or handler.__name__
        entry = _RegisteredHook(handler=handler, name=hook_name, priority=priority)

        if event not in self._hooks:
            self._hooks[event] = []
        self._hooks[event].append(entry)
        # Keep sorted by priority (stable sort)
        self._hooks[event].sort(key=lambda h: h.priority)

    def unregister(self, event: HookEvent, name: str) -> bool:
        """Remove a named hook. Returns True if found and removed."""
        hooks = self._hooks.get(event, [])
        before = len(hooks)
        self._hooks[event] = [h for h in hooks if h.name != name]
        return len(self._hooks[event]) < before

    def trigger(self, event: HookEvent, data: dict[str, Any] | None = None) -> list[HookResult]:
        """Trigger all hooks for an event in priority order.

        Returns list of HookResults. Errors in one hook don't stop others.
        """
        data = data or {}
        results: list[HookResult] = []
        hooks = self._hooks.get(event, [])

        for hook in hooks:
            try:
                hook.handler(event, data)
                results.append(HookResult(success=True, event=event, handler_name=hook.name))
            except Exception as exc:
                log.warning("Hook '%s' failed on %s: %s", hook.name, event.value, exc)
                results.append(
                    HookResult(
                        success=False,
                        event=event,
                        handler_name=hook.name,
                        error=str(exc),
                    )
                )

        return results

    def list_hooks(self, event: HookEvent | None = None) -> dict[str, list[str]]:
        """List registered hook names, optionally filtered by event."""
        if event is not None:
            hooks = self._hooks.get(event, [])
            return {event.value: [h.name for h in hooks]}
        return {e.value: [h.name for h in hooks] for e, hooks in self._hooks.items() if hooks}

    def clear(self, event: HookEvent | None = None) -> None:
        """Clear hooks for a specific event, or all hooks."""
        if event is not None:
            self._hooks.pop(event, None)
        else:
            self._hooks.clear()
