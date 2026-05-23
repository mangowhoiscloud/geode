"""Shared Anthropic-side helpers for the v0.99.39 LLMAdapter built-ins.

Lives next to the concrete Anthropic adapters (``anthropic_payg.py``,
``anthropic_oauth.py``, ``claude_cli.py``) and holds:

1. ``build_async_anthropic_client(api_key)`` — creates a NEW
   :class:`anthropic.AsyncAnthropic` per adapter rather than reusing the
   module-level singleton from ``core.llm.providers.anthropic``. The singleton
   path caches the first caller's api_key, so passing a fresh key from a
   different adapter (PAYG api_key vs OAuth token) silently returns the
   already-cached client and the source boundary collapses. Codex MCP review
   2026-05-23 flagged this as a BLOCKER for the source/billing guarantee.
2. ``build_messages`` / ``translate_response`` / ``translate_tool`` / etc. —
   the request and response shape helpers shared across the three Anthropic
   adapters. Moving them here removes the prior cross-adapter import
   (``anthropic_oauth`` → ``anthropic_payg``) flagged as MEDIUM layering smell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    ToolSpec,
    UsageSummary,
)

if TYPE_CHECKING:
    import anthropic


def build_async_anthropic_client(api_key: str) -> anthropic.AsyncAnthropic:
    """Construct a fresh ``AsyncAnthropic`` bound to ``api_key``.

    Each adapter owns its client — bypassing the module-level singleton in
    ``core.llm.providers.anthropic`` which is keyed solely by the first
    caller's resolved key. Same httpx limits/timeout/event-hooks as the
    singleton so the response-header banner pipeline keeps working.
    """
    if not api_key:
        raise ValueError("build_async_anthropic_client: api_key is empty")
    import anthropic
    import httpx

    from core.llm.providers.anthropic import (
        _async_response_hook,
        _build_httpx_limits,
        _build_httpx_timeout,
    )

    http_client = httpx.AsyncClient(
        limits=_build_httpx_limits(),
        timeout=_build_httpx_timeout(),
        event_hooks={"response": [_async_response_hook]},
    )
    return anthropic.AsyncAnthropic(
        api_key=api_key,
        max_retries=0,  # app-level retry handles this
        http_client=http_client,
    )


def build_messages(req: AdapterCallRequest) -> list[dict[str, Any]]:
    """Translate adapter-neutral Message list → Anthropic ``messages`` payload."""
    out: list[dict[str, Any]] = []
    for m in req.messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": m.tool_use_id or "",
                            "content": m.content if isinstance(m.content, str) else "",
                        }
                    ],
                }
            )
            continue
        out.append({"role": m.role, "content": m.content})
    return out


def translate_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema,
    }


def build_create_kwargs(req: AdapterCallRequest) -> dict[str, Any]:
    """Shared ``messages.create`` kwargs for both PAYG + OAuth Anthropic adapters."""
    kwargs: dict[str, Any] = {
        "model": req.model,
        "system": req.system_prompt,
        "messages": build_messages(req),
        "max_tokens": req.max_tokens,
    }
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.tools:
        kwargs["tools"] = [translate_tool(t) for t in req.tools]
    if req.stop_sequences:
        kwargs["stop_sequences"] = list(req.stop_sequences)
    if req.thinking_budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": req.thinking_budget}
    return kwargs


def build_stream_kwargs(req: AdapterCallRequest) -> dict[str, Any]:
    """Variant of :func:`build_create_kwargs` for ``messages.stream``.

    Streaming does not accept ``thinking`` / ``stop_sequences`` for the
    same models as ``create``, so the kwargs are trimmed.
    """
    kwargs: dict[str, Any] = {
        "model": req.model,
        "system": req.system_prompt,
        "messages": build_messages(req),
        "max_tokens": req.max_tokens,
    }
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.tools:
        kwargs["tools"] = [translate_tool(t) for t in req.tools]
    return kwargs


def translate_response(response: Any) -> AdapterCallResult:
    """Anthropic SDK Message → :class:`AdapterCallResult`."""
    text_blocks: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_blocks.append(getattr(block, "text", ""))
        elif block_type == "tool_use":
            tool_uses.append(
                {
                    "id": getattr(block, "id", ""),
                    "name": getattr(block, "name", ""),
                    "input": getattr(block, "input", {}),
                }
            )
    usage = getattr(response, "usage", None)
    return AdapterCallResult(
        text="".join(text_blocks),
        usage=UsageSummary(
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) if usage else 0,
        ),
        stop_reason=getattr(response, "stop_reason", "end_turn") or "end_turn",
        tool_uses=tuple(tool_uses),
        raw_response=response,
    )


__all__ = [
    "build_async_anthropic_client",
    "build_create_kwargs",
    "build_messages",
    "build_stream_kwargs",
    "translate_response",
    "translate_tool",
]
