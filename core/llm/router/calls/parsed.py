"""``call_llm_parsed`` — structured-output LLM call with provider routing."""

from __future__ import annotations

import logging
import time
from typing import TypeVar, cast

from pydantic import BaseModel

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

T = TypeVar("T", bound=BaseModel)


def call_llm_parsed(  # noqa: UP047 — PEP695 syntax requires Python 3.12+
    system: str,
    user: str,
    *,
    output_model: type[T],
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> T:
    """LLM call with provider-aware structured output routing.

    Supports cross-provider fallback when enabled.
    """
    from core.config import settings

    target_model = model or settings.model
    provider = _route_provider(target_model)

    def _dispatch(p: str, m: str) -> T:
        _fire_hook(
            "llm_call_start",
            {"model": m, "provider": p, "function": "call_llm_parsed"},
        )
        t0 = time.monotonic()
        try:
            if p != "anthropic":
                oa_client = _get_provider_client(p)

                def _do_call_openai(*, model: str) -> T:
                    response = oa_client.beta.chat.completions.parse(
                        model=model,
                        max_completion_tokens=max_tokens,
                        temperature=temperature,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        response_format=output_model,
                        timeout=120.0,
                    )
                    _record_openai_usage(response, model, label="parsed")

                    choice = response.choices[0]
                    if choice.message.parsed is None:
                        raise ValueError(
                            "LLM returned no structured output. "
                            "Verify the prompt constrains the response format "
                            "and the Pydantic model matches the schema."
                        )
                    return cast(T, choice.message.parsed)

                result: T = _retry_provider_aware(_do_call_openai, model=m, provider=p)
            else:
                client = get_anthropic_client()
                system_cached = _system_with_cache(system)

                def _do_call(*, model: str) -> T:
                    response = client.messages.parse(
                        model=model,
                        max_tokens=max_tokens,
                        temperature=temperature,
                        system=system_cached,
                        messages=[{"role": "user", "content": user}],
                        output_format=output_model,
                    )
                    _record_response_usage(response, model, label="parsed")

                    if response.parsed_output is None:
                        raise ValueError(
                            "LLM returned no structured output. "
                            "Verify the prompt constrains the response format "
                            "and the Pydantic model matches the schema."
                        )
                    return response.parsed_output

                result = _retry_with_backoff(_do_call, model=m)
        except Exception as exc:
            elapsed_ms = (time.monotonic() - t0) * 1000
            _fire_hook(
                "llm_call_end",
                {
                    "model": m,
                    "provider": p,
                    "function": "call_llm_parsed",
                    "latency_ms": elapsed_ms,
                    "error": str(exc),
                },
            )
            raise

        elapsed_ms = (time.monotonic() - t0) * 1000
        _fire_hook(
            "llm_call_end",
            {
                "model": m,
                "provider": p,
                "function": "call_llm_parsed",
                "latency_ms": elapsed_ms,
                "error": None,
            },
        )
        return result

    return _cross_provider_dispatch(provider, target_model, _dispatch, "call_llm_parsed")


__all__ = ["_get_provider_client", "call_llm_parsed", "get_anthropic_client"]
