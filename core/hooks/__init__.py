"""core.hooks — Cross-cutting hook system accessible by all layers.

Exposes HookSystem and HookEvent at the package root so any layer can import
without depending on core.orchestration:

    from core.hooks import HookSystem, HookEvent
"""

from core.hooks.system import (
    DuplicateHookRegistrationError,
    HookDispatch,
    HookDispatchMode,
    HookEvent,
    HookExecutionTimeoutError,
    HookResult,
    HookSubscription,
    HookSystem,
    HookTimeoutUnsupportedError,
    InterceptResult,
)

__all__ = [
    "DuplicateHookRegistrationError",
    "HookDispatch",
    "HookDispatchMode",
    "HookEvent",
    "HookExecutionTimeoutError",
    "HookResult",
    "HookSubscription",
    "HookSystem",
    "HookTimeoutUnsupportedError",
    "InterceptResult",
]
