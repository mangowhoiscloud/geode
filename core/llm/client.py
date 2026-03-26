"""LLM client — backward-compatible re-export module.

All functionality has been split into:
- core.llm.router — main API (call_llm, call_llm_parsed, etc.)
- core.llm.fallback — CircuitBreaker, retry_with_backoff_generic
- core.llm.errors — BillingError, UserCancelledError, LLM*Error aliases
- core.llm.providers.anthropic — Anthropic client lifecycle
- core.llm.providers.openai — OpenAI client lifecycle + OpenAIAdapter
- core.llm.providers.glm — GLM client lifecycle

This file re-exports everything for backward compatibility.
Prefer importing from the specific modules directly.
"""

from __future__ import annotations

# Re-export from errors
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

# Re-export from fallback
from core.llm.fallback import (
    CircuitBreaker as CircuitBreaker,
)
from core.llm.fallback import (
    retry_with_backoff_generic as retry_with_backoff_generic,
)
from core.llm.providers.anthropic import (
    _build_httpx_limits as _build_httpx_limits,
)
from core.llm.providers.anthropic import (
    _build_httpx_timeout as _build_httpx_timeout,
)
from core.llm.providers.anthropic import (  # noqa: F401
    retry_with_backoff as _retry_with_backoff,
)

# Re-export everything from router (main API)
from core.llm.router import (
    FALLBACK_MODELS as FALLBACK_MODELS,
)
from core.llm.router import (
    MAX_RETRIES as MAX_RETRIES,
)
from core.llm.router import (
    MODEL_PRICING as MODEL_PRICING,
)
from core.llm.router import (
    RETRY_BASE_DELAY as RETRY_BASE_DELAY,
)
from core.llm.router import (
    RETRY_MAX_DELAY as RETRY_MAX_DELAY,
)
from core.llm.router import (
    LLMUsage as LLMUsage,
)
from core.llm.router import (
    LLMUsageAccumulator as LLMUsageAccumulator,
)
from core.llm.router import (
    ToolCallRecord as ToolCallRecord,
)
from core.llm.router import (
    ToolUseResult as ToolUseResult,
)
from core.llm.router import (
    _record_openai_usage as _record_openai_usage,
)
from core.llm.router import (
    _record_response_usage as _record_response_usage,
)
from core.llm.router import (
    calculate_cost as calculate_cost,
)
from core.llm.router import (
    call_llm as call_llm,
)
from core.llm.router import (
    call_llm_json as call_llm_json,
)
from core.llm.router import (
    call_llm_parsed as call_llm_parsed,
)
from core.llm.router import (
    call_llm_streaming as call_llm_streaming,
)
from core.llm.router import (
    call_llm_with_tools as call_llm_with_tools,
)
from core.llm.router import (
    call_with_failover as call_with_failover,
)
from core.llm.router import (
    get_anthropic_client as get_anthropic_client,
)
from core.llm.router import (
    get_async_anthropic_client as get_async_anthropic_client,
)
from core.llm.router import (
    get_usage_accumulator as get_usage_accumulator,
)
from core.llm.router import (
    is_langsmith_enabled as is_langsmith_enabled,
)
from core.llm.router import (
    maybe_traceable as maybe_traceable,
)
from core.llm.router import (
    reset_clients as reset_clients,
)
from core.llm.router import (
    reset_usage_accumulator as reset_usage_accumulator,
)
from core.llm.router import (
    track_token_usage as track_token_usage,
)
