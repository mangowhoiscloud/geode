"""core.hooks.dispatch — the single hook-firing implementation for all layers.

Every emit site fires through these helpers (PR-HOOK-TAXONOMY D6) instead of
re-implementing the ``if hooks is None / try / except`` rail per module. The
helpers add two cross-cutting behaviours no local copy had:

* graceful degradation — a failing dispatch is logged (WARNING once per
  event, then DEBUG) and never breaks the surrounding call;
* payload-contract validation (D7) — payloads are checked against
  :data:`core.hooks.catalog.REQUIRED_PAYLOAD_KEYS` and missing keys are
  logged at WARNING with the emitting caller, never raised.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from core.hooks.system import (
    HookEvent,
    HookResult,
    HookSystem,
    InterceptResult,
    resolve_event_value,
)

log = logging.getLogger(__name__)

_DISPATCH_FAILURE_WARNED: set[str] = set()


def _emitting_caller() -> str:
    """Best-effort ``module:lineno`` of the first frame outside core.hooks.

    Only invoked on the (rare) missing-keys warning path, so the frame walk
    costs nothing in normal operation.
    """
    frame = sys._getframe(1)
    for _hop in range(8):
        frame_back = frame.f_back
        if frame_back is None:
            break
        frame = frame_back
        module = frame.f_globals.get("__name__", "")
        if not module.startswith("core.hooks"):
            return f"{module}:{frame.f_lineno}"
    return "<unknown>"


def _validate_payload(event: HookEvent, data: dict[str, Any]) -> None:
    """Warn (never raise) when a payload misses its contract keys."""
    from core.hooks.catalog import REQUIRED_PAYLOAD_KEYS

    required = REQUIRED_PAYLOAD_KEYS.get(event)
    if not required:
        return
    missing = sorted(required - data.keys())
    if missing:
        log.warning(
            "Hook payload contract: %s emitted without required keys %s (caller %s)",
            event.value,
            missing,
            _emitting_caller(),
        )


def _coerce_event(event: HookEvent | str) -> HookEvent:
    if isinstance(event, str):
        return resolve_event_value(event)
    return event


def _warn_dispatch_failure(event: HookEvent | str) -> None:
    # PR-OBS-CONTRACT — a failing hook dispatch is an observability
    # outage, not a debug detail (silent-fallback anti-pattern).
    # WARN once per event name; repeats stay at debug to avoid
    # hot-loop spam.
    event_name = event.value if isinstance(event, HookEvent) else str(event)
    if event_name not in _DISPATCH_FAILURE_WARNED:
        _DISPATCH_FAILURE_WARNED.add(event_name)
        log.warning("Hook trigger failed for %s (suppressing repeats)", event_name, exc_info=True)
    else:
        log.debug("Hook trigger failed: %s", event_name, exc_info=True)


def fire_hook(
    hooks: HookSystem | None,
    event: HookEvent | str,
    data: dict[str, Any],
) -> None:
    """Fire an observer hook event with graceful degradation.

    No-op when ``hooks`` is ``None``. Errors from handlers are logged and
    never raised — hook failures must not break the surrounding call
    (LLM dispatch, tool execution, CLI lifecycle).
    """
    if hooks is None:
        return
    try:
        resolved = _coerce_event(event)
        _validate_payload(resolved, data)
        hooks.trigger(resolved, data)
    except Exception:
        _warn_dispatch_failure(event)


async def fire_hook_async(
    hooks: HookSystem | None,
    event: HookEvent | str,
    data: dict[str, Any],
) -> None:
    """Async variant of :func:`fire_hook` (awaits async handlers)."""
    if hooks is None:
        return
    try:
        resolved = _coerce_event(event)
        _validate_payload(resolved, data)
        await hooks.trigger_async(resolved, data)
    except Exception:
        _warn_dispatch_failure(event)


async def fire_interceptor_async(
    hooks: HookSystem | None,
    event: HookEvent | str,
    data: dict[str, Any],
) -> InterceptResult | None:
    """Fire an interceptor chain (block/modify semantics), gracefully.

    Returns the :class:`InterceptResult` when hooks are configured and the
    dispatch succeeded, ``None`` otherwise — callers treat ``None`` as
    "not blocked, unmodified".
    """
    if hooks is None:
        return None
    try:
        resolved = _coerce_event(event)
        _validate_payload(resolved, data)
        return await hooks.trigger_interceptor_async(resolved, data)
    except Exception:
        _warn_dispatch_failure(event)
        return None


async def fire_with_result_async(
    hooks: HookSystem | None,
    event: HookEvent | str,
    data: dict[str, Any],
) -> list[HookResult]:
    """Fire a feedback hook capturing handler return values, gracefully.

    Returns an empty list when hooks are unset or the dispatch failed.
    """
    if hooks is None:
        return []
    try:
        resolved = _coerce_event(event)
        _validate_payload(resolved, data)
        return await hooks.trigger_with_result_async(resolved, data)
    except Exception:
        _warn_dispatch_failure(event)
        return []


__all__ = [
    "fire_hook",
    "fire_hook_async",
    "fire_interceptor_async",
    "fire_with_result_async",
]
