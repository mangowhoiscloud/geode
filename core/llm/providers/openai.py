"""OpenAI provider — client lifecycle + retry wrapper.

Merged from core.infrastructure.adapters.llm.openai_adapter.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from core.llm.fallback import retry_with_backoff_generic_async
from core.llm.loop_affinity import LoopAffineClientCache
from core.llm.token_tracker import LLMUsage, get_tracker

log = logging.getLogger(__name__)

# Retry policy values (max_retries / retry_base_delay / retry_max_delay) are
# resolved lazily from ``core.config.settings.llm_*`` inside
# ``retry_with_backoff_generic`` (fallback.py).  Keeping a single source of
# truth ensures runtime ``settings.llm_max_retries`` tuning reaches every
# provider — previously OpenAI/GLM passed module-local constants that pinned
# them to ``3`` regardless of configuration.

# H11-tail: DEFAULT_OPENAI_MODEL / OPENAI_FALLBACK_MODELS were boot-frozen
# module aliases of OPENAI_PRIMARY / OPENAI_FALLBACK_CHAIN. Consumers now read
# the live values from ``core.config`` via function-local imports so a
# routing.toml reload is seen without a restart.


_openai_client: Any = None  # openai.OpenAI | None — lazy import
_openai_lock = threading.Lock()
# PR-LOOP-POLLUTION-FIX (2026-06-12) — async client is per-event-loop, not
# process-global (see core/llm/loop_affinity.py).
_async_openai_clients = LoopAffineClientCache("openai-provider")


def _resolve_openai_key() -> str:
    """Resolve OpenAI API key from ProfileRotator (OAuth preferred) or settings."""
    from core.config import settings
    from core.llm.credentials import resolve_provider_key

    return resolve_provider_key("openai", settings.openai_api_key)


def _get_openai_client() -> Any:
    """Lazy import and return cached OpenAI client (thread-safe).

    PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28, Codex MCP MED) —
    ``max_retries=0`` matches the adapter-side invariant
    (``_openai_common.build_async_openai_client``) so legacy callers that
    still hit this singleton (paperclip ``OpenAIAdapter``,
    ``llm_extract_learning``, ``models.py``) don't compound SDK + app
    retry loops on stalled streams.
    """
    global _openai_client
    if _openai_client is None:
        with _openai_lock:
            if _openai_client is None:
                import openai

                _openai_client = openai.OpenAI(api_key=_resolve_openai_key(), max_retries=0)
    return _openai_client


def _get_async_openai_client() -> Any:
    """Return the async OpenAI client bound to the CURRENT event loop.

    See :func:`_get_openai_client` for the ``max_retries=0`` rationale and
    ``core/llm/loop_affinity.py`` for why the cache is per-loop.
    """

    def _build() -> Any:
        import openai

        return openai.AsyncOpenAI(api_key=_resolve_openai_key(), max_retries=0)

    return _async_openai_clients.get(_build)


def reset_openai_client() -> None:
    """Reset cached OpenAI client (e.g. after /key openai changes)."""
    global _openai_client
    with _openai_lock:
        _openai_client = None
    _async_openai_clients.invalidate()


def _get_retryable_errors() -> tuple[type[Exception], ...]:
    """Get retryable error types from openai SDK."""
    import openai

    return (
        openai.RateLimitError,
        openai.APIConnectionError,
        openai.InternalServerError,
    )


async def _run_tool_executor_async(
    tool_executor: Callable[..., Any],
    tool_name: str,
    tool_input: dict[str, Any],
) -> dict[str, Any]:
    """Run sync or async tool executors without blocking the event loop."""
    if inspect.iscoroutinefunction(tool_executor):
        raw = await tool_executor(tool_name, **tool_input)
    else:
        raw = await asyncio.to_thread(tool_executor, tool_name, **tool_input)

    if inspect.isawaitable(raw):
        raw = await raw
    return raw if isinstance(raw, dict) else {"result": raw}


class OpenAIAdapter:
    """OpenAI-compatible async tool-use orchestrator.

    Powers OpenAI + GLM tool-use paths from
    :func:`core.llm.router.calls.tools.call_llm_with_tools_async` — the legacy
    sync ``generate`` / ``generate_structured`` / ``generate_parsed`` /
    ``agenerate_stream`` surface (``LLMClientPort``) was removed in
    PR-LLMCLIENTPORT-COLLAPSE (2026-05-28); only the
    :meth:`agenerate_with_tools` orchestration is load-bearing.
    """

    def __init__(self, default_model: str = "") -> None:
        # H11-tail: resolve the empty default lazily so it tracks a live
        # routing.toml reload. A frozen ``DEFAULT_OPENAI_MODEL`` default arg
        # would pin the boot value into every instance built after a reload.
        if not default_model:
            from core.config import OPENAI_PRIMARY

            default_model = OPENAI_PRIMARY
        self._default_model = default_model

    async def agenerate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., Any],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        """OpenAI-compatible async tool-use loop."""
        from core.llm.router import ToolCallRecord, ToolUseResult

        client = _get_async_openai_client()
        target = model or self._default_model

        all_tool_calls: list[ToolCallRecord] = []
        all_usage: list[LLMUsage] = []
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        for round_idx in range(max_tool_rounds):
            is_last_round = round_idx == max_tool_rounds - 1
            tool_choice = "none" if is_last_round else "auto"

            async def _do_call(*, model: str, _tc: str = tool_choice) -> Any:
                response = client.chat.completions.create(
                    model=model,
                    max_completion_tokens=max_tokens,
                    temperature=temperature,
                    messages=messages,
                    tools=tools,
                    tool_choice=_tc,
                    timeout=120.0,
                )
                if inspect.isawaitable(response):
                    return await response
                return response

            response = await self._aretry_with_backoff(_do_call, model=target)

            if response.usage:
                in_tok = response.usage.prompt_tokens
                out_tok = response.usage.completion_tokens or 0
                usage = get_tracker().record(target, in_tok, out_tok)
                all_usage.append(usage)

            choice = response.choices[0]

            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                return ToolUseResult(
                    text=choice.message.content or "",
                    tool_calls=all_tool_calls,
                    usage=all_usage,
                    rounds=round_idx + 1,
                )

            messages.append(choice.message)
            for tc in choice.message.tool_calls:
                func_name = tc.function.name
                try:
                    func_args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    func_args = {}

                t0 = time.time()
                try:
                    result = await _run_tool_executor_async(tool_executor, func_name, func_args)
                except Exception as exc:
                    log.warning("Tool '%s' execution failed: %s", func_name, exc)
                    result = {"error": str(exc)}
                elapsed_ms = (time.time() - t0) * 1000

                all_tool_calls.append(
                    ToolCallRecord(
                        tool_name=func_name,
                        tool_input=func_args,
                        tool_result=result,
                        duration_ms=elapsed_ms,
                    )
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )

        return ToolUseResult(
            text="",
            tool_calls=all_tool_calls,
            usage=all_usage,
            rounds=max_tool_rounds,
        )

    async def _aretry_with_backoff(self, fn: Any, *, model: str) -> Any:
        """Async retry with exponential backoff + model fallback."""
        import openai

        from core.config import OPENAI_FALLBACK_CHAIN  # H11-tail: live read

        return await retry_with_backoff_generic_async(
            fn,
            model=model,
            fallback_models=list(OPENAI_FALLBACK_CHAIN),
            retryable_errors=_get_retryable_errors(),
            bad_request_error=openai.BadRequestError,
            billing_message=(
                "OpenAI API billing/credit error. Check your OpenAI account billing settings."
            ),
            provider_label="OpenAI",
        )
