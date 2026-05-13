"""``call_llm`` — synchronous text completion with provider-aware routing."""

from __future__ import annotations

import logging
import time

from core.hooks.system import HookEvent
from core.llm.provider_dispatch import (
    _cross_provider_dispatch,
    _get_provider_client,
    _retry_provider_aware,
)
from core.llm.providers.anthropic import get_anthropic_client
from core.llm.providers.anthropic import (
    retry_with_backoff as _retry_with_backoff,
)
from core.llm.providers.anthropic import (
    system_with_cache as _system_with_cache,
)
from core.llm.router._hooks import _fire_hook
from core.llm.router._usage import _record_openai_usage, _record_response_usage

from ._route import _route_provider

log = logging.getLogger(__name__)


def call_llm(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    seed: int | None = None,
) -> str:
    """Synchronous LLM call with provider-aware routing and failover.

    Routes to Anthropic, OpenAI, or GLM SDK based on the model name.
    Returns text content. Supports cross-provider fallback when enabled.
    """
    from core.config import settings

    target_model = model or settings.model
    provider = _route_provider(target_model)

    if seed is not None:
        log.info("Reproducibility seed=%d requested (logged for auditing)", seed)

    def _dispatch(p: str, m: str) -> str:
        _fire_hook(
            HookEvent.LLM_CALL_START,
            {"model": m, "provider": p, "function": "call_llm"},
        )
        t0 = time.monotonic()
        try:
            if p != "anthropic":
                oa_client = _get_provider_client(p)

                def _do_call_openai(*, model: str) -> str:
                    response = oa_client.chat.completions.create(
                        model=model,
                        max_completion_tokens=max_tokens,
                        temperature=temperature,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        timeout=120.0,
                    )
                    _record_openai_usage(response, model)
                    choice = response.choices[0]
                    return choice.message.content or ""

                result: str = _retry_provider_aware(_do_call_openai, model=m, provider=p)
            else:
                client = get_anthropic_client()
                system_cached = _system_with_cache(system)

                def _do_call(*, model: str) -> str:
                    response = client.messages.create(
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        system=system_cached,
                        messages=[{"role": "user", "content": user}],
                    )
                    _record_response_usage(response, model)

                    block = response.content[0]
                    if not hasattr(block, "text"):
                        raise TypeError(f"Expected TextBlock, got {type(block)}")
                    return block.text

                result = _retry_with_backoff(_do_call, model=m)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            _fire_hook(
                HookEvent.LLM_CALL_END,
                {
                    "model": m,
                    "provider": p,
                    "function": "call_llm",
                    "latency_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            raise

        elapsed_ms = (time.monotonic() - t0) * 1000
        _fire_hook(
            HookEvent.LLM_CALL_END,
            {
                "model": m,
                "provider": p,
                "function": "call_llm",
                "latency_ms": elapsed_ms,
                "error": None,
            },
        )
        return result

    return _cross_provider_dispatch(provider, target_model, _dispatch, "call_llm")


# Re-export shims so test patches like ``core.llm.router.calls.text.X`` work
# even though the production binding lives in core.llm.* modules.
__all__ = ["_get_provider_client", "call_llm", "get_anthropic_client"]
