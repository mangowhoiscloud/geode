"""LLM Router — provider-aware dispatching for all LLM calls.

Replaces the monolithic client.py. Routes to the correct provider SDK

Data types (ToolCallRecord, ToolUseResult) and re-exports from
token_tracker are kept here for backward compatibility.

This package was split from a single 1,046-line ``router.py`` into focused
sub-modules. The public surface is preserved via re-exports below; production
code keeps importing from ``core.llm.router`` and tests can target leaf
modules (``core.llm.router.calls``, ``.tracing``) when monkeypatching
internals that one call function uses to dispatch to another.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # v0.88.0 — re-exports preserved through the lazy ``__getattr__`` at the
    # end of this module.  ``from core.llm.router import LLMRateLimitError``
    # keeps working without paying the 248 ms anthropic load at module
    # import — only IDE / mypy use this branch.
    from core.llm.errors import (
        LLMAPIStatusError as LLMAPIStatusError,
    )
    from core.llm.errors import (
        LLMAuthenticationError as LLMAuthenticationError,
    )
    from core.llm.errors import (
        LLMBadRequestError as LLMBadRequestError,
    )
    from core.llm.errors import (
        LLMConnectionError as LLMConnectionError,
    )
    from core.llm.errors import (
        LLMInternalServerError as LLMInternalServerError,
    )
    from core.llm.errors import (
        LLMRateLimitError as LLMRateLimitError,
    )
    from core.llm.errors import (
        LLMTimeoutError as LLMTimeoutError,
    )

# Re-export the resolver fallback for backwards compatibility — legacy uses of
# ``monkeypatch.setattr("core.llm.router._resolve_provider", ...)`` still find a
# name on the package. ``calls._route_provider`` calls the leaf binding from
# ``core.config`` directly, so the supported test path is the leaf module.
from core.config import _resolve_provider as _resolve_provider
from core.llm.adapters import CROSS_PROVIDER_FALLBACK as CROSS_PROVIDER_FALLBACK
from core.llm.adapters import AgenticLLMPort as AgenticLLMPort
from core.llm.adapters import ClaudeAdapter as ClaudeAdapter
from core.llm.adapters import LLMClientPort as LLMClientPort
from core.llm.adapters import LLMJsonCallable as LLMJsonCallable
from core.llm.adapters import LLMParsedCallable as LLMParsedCallable
from core.llm.adapters import LLMTextCallable as LLMTextCallable
from core.llm.adapters import LLMToolCallable as LLMToolCallable
from core.llm.adapters import resolve_agentic_adapter as resolve_agentic_adapter

# v0.88.0 — LLM*Error re-exports (LLMAPIStatusError, LLMAuthenticationError,
# LLMBadRequestError, LLMConnectionError, LLMInternalServerError,
# LLMRateLimitError, LLMTimeoutError) used to live here as eager
# ``from core.llm.errors import X as X`` lines.  Each one ran
# ``core.llm.errors.__getattr__`` at module load and pulled the 248 ms
# anthropic SDK graph into the cold-start path, even though nothing in
# the codebase imports these names from ``core.llm.router`` (verified
# 2026-05-08 grep — only ``LLMClientPort`` / ``LLM*Callable`` /
# ``LLMUsageAccumulator`` are pulled from this package).  Public API
# preserved via the module-level ``__getattr__`` hook below: any future
# ``from core.llm.router import LLMRateLimitError`` still resolves on
# demand, deferring the SDK load until first access.
from core.llm.fallback import MAX_RETRIES as MAX_RETRIES
from core.llm.fallback import RETRY_BASE_DELAY as RETRY_BASE_DELAY
from core.llm.fallback import RETRY_MAX_DELAY as RETRY_MAX_DELAY
from core.llm.fallback import CircuitBreaker as CircuitBreaker
from core.llm.fallback import retry_with_backoff_generic as retry_with_backoff_generic
from core.llm.provider_dispatch import _cross_provider_dispatch as _cross_provider_dispatch
from core.llm.provider_dispatch import _get_fallback_chain as _get_fallback_chain
from core.llm.provider_dispatch import _get_provider_client as _get_provider_client
from core.llm.provider_dispatch import _retry_provider_aware as _retry_provider_aware
from core.llm.providers.anthropic import (
    FALLBACK_MODELS as FALLBACK_MODELS,
)
from core.llm.providers.anthropic import (
    _build_httpx_limits as _build_httpx_limits,
)
from core.llm.providers.anthropic import (
    _build_httpx_timeout as _build_httpx_timeout,
)
from core.llm.providers.anthropic import (
    get_anthropic_client as get_anthropic_client,
)
from core.llm.providers.anthropic import (
    get_async_anthropic_client as get_async_anthropic_client,
)
from core.llm.providers.anthropic import (
    reset_clients as reset_clients,
)
from core.llm.token_tracker import MODEL_PRICING as MODEL_PRICING
from core.llm.token_tracker import LLMUsage as LLMUsage
from core.llm.token_tracker import LLMUsageAccumulator as LLMUsageAccumulator
from core.llm.token_tracker import calculate_cost as calculate_cost
from core.llm.token_tracker import get_usage_accumulator as get_usage_accumulator
from core.llm.token_tracker import reset_usage_accumulator as reset_usage_accumulator
from core.llm.token_tracker import track_token_usage as track_token_usage

# Local sub-module re-exports
from ._di import (
    _llm_json_ctx as _llm_json_ctx,
)
from ._di import (
    _llm_parsed_ctx as _llm_parsed_ctx,
)
from ._di import (
    _llm_tool_ctx as _llm_tool_ctx,
)
from ._di import (
    _secondary_llm_json_ctx as _secondary_llm_json_ctx,
)
from ._di import (
    _secondary_llm_parsed_ctx as _secondary_llm_parsed_ctx,
)
from ._di import (
    get_llm_json as get_llm_json,
)
from ._di import (
    get_llm_parsed as get_llm_parsed,
)
from ._di import (
    get_llm_tool as get_llm_tool,
)
from ._di import (
    get_secondary_llm_json as get_secondary_llm_json,
)
from ._di import (
    get_secondary_llm_parsed as get_secondary_llm_parsed,
)
from ._di import (
    set_llm_callable as set_llm_callable,
)
from ._hooks import (
    _fire_hook as _fire_hook,
)
from ._hooks import (
    _hooks_ctx as _hooks_ctx,
)
from ._hooks import (
    set_router_hooks as set_router_hooks,
)
from ._usage import (
    _record_openai_usage as _record_openai_usage,
)
from ._usage import (
    _record_response_usage as _record_response_usage,
)
from .calls import (
    _route_provider as _route_provider,
)
from .calls import (
    call_llm as call_llm,
)
from .calls import (
    call_llm_json as call_llm_json,
)
from .calls import (
    call_llm_parsed as call_llm_parsed,
)
from .calls import (
    call_llm_streaming as call_llm_streaming,
)
from .calls import (
    call_llm_with_tools as call_llm_with_tools,
)
from .calls import (
    call_with_failover as call_with_failover,
)
from .models import (
    ToolCallRecord as ToolCallRecord,
)
from .models import (
    ToolUseResult as ToolUseResult,
)

# v0.88.0 — module-level ``__getattr__`` for lazy LLM*Error re-exports.
# Placed after all eager imports so ruff E402 stays happy.  The
# ``_LAZY_ERROR_NAMES`` set is the runtime mirror of the TYPE_CHECKING
# block at the top of the file.
_LAZY_ERROR_NAMES = frozenset(
    {
        "LLMAPIStatusError",
        "LLMAuthenticationError",
        "LLMBadRequestError",
        "LLMConnectionError",
        "LLMInternalServerError",
        "LLMRateLimitError",
        "LLMTimeoutError",
    }
)


def __getattr__(name: str) -> Any:
    """PEP 562 hook — resolve lazy LLM*Error re-exports on first access."""
    if name in _LAZY_ERROR_NAMES:
        from core.llm import errors

        cls = getattr(errors, name)
        globals()[name] = cls
        return cls
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
