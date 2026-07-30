"""core.hooks — public hooks, trusted middleware, and internal runtime events.

New code should choose the narrow surface it needs:

    from core.hooks import HookName, HookRegistry
    from core.hooks import MiddlewareRegistry
    from core.hooks import RuntimeEvent, RuntimeEventBus

``HookEvent`` and ``HookSystem`` remain compatibility aliases for the internal
event surface; neither is the public hook ABI.
"""

from core.hooks.middleware import (
    DuplicateMiddlewareError,
    InvalidMiddlewareResultError,
    LlmCallRequest,
    LlmExecutionMiddleware,
    LlmRequestMiddleware,
    MiddlewareRegistry,
    NextCallAlreadyUsedError,
    ToolCallRequest,
    ToolExecutionMiddleware,
    ToolRequestMiddleware,
)
from core.hooks.public import (
    PUBLIC_HOOK_SCHEMA_VERSION,
    DuplicateHookError,
    HookAction,
    HookCorrelation,
    HookDecision,
    HookInvocation,
    HookName,
    HookOutcome,
    HookRegistry,
    InvalidHookDecisionError,
    InvalidHookPayloadError,
    public_hook_schema,
)
from core.hooks.system import (
    COLLAPSED_EVENT_VALUES,
    LEGACY_EVENT_VALUES,
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
    RuntimeEvent,
    RuntimeEventBus,
    resolve_event_value,
)

__all__ = [
    "COLLAPSED_EVENT_VALUES",
    "LEGACY_EVENT_VALUES",
    "PUBLIC_HOOK_SCHEMA_VERSION",
    "DuplicateHookError",
    "DuplicateHookRegistrationError",
    "DuplicateMiddlewareError",
    "HookAction",
    "HookCorrelation",
    "HookDecision",
    "HookDispatch",
    "HookDispatchMode",
    "HookEvent",
    "HookExecutionTimeoutError",
    "HookInvocation",
    "HookName",
    "HookOutcome",
    "HookRegistry",
    "HookResult",
    "HookSubscription",
    "HookSystem",
    "HookTimeoutUnsupportedError",
    "InterceptResult",
    "InvalidHookDecisionError",
    "InvalidHookPayloadError",
    "InvalidMiddlewareResultError",
    "LlmCallRequest",
    "LlmExecutionMiddleware",
    "LlmRequestMiddleware",
    "MiddlewareRegistry",
    "NextCallAlreadyUsedError",
    "RuntimeEvent",
    "RuntimeEventBus",
    "ToolCallRequest",
    "ToolExecutionMiddleware",
    "ToolRequestMiddleware",
    "public_hook_schema",
    "resolve_event_value",
]
