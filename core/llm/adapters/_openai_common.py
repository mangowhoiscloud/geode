"""Shared OpenAI-side helpers for the v0.99.39 LLMAdapter built-ins.

Mirror of :mod:`core.llm.adapters._anthropic_common` for the OpenAI provider:
fresh-client builder (PAYG vs Codex OAuth must not share the module-level
singleton in ``core.llm.providers.openai``) + request/response translation.

Codex MCP review 2026-05-23 flagged the singleton sharing as a BLOCKER for
the source/billing isolation guarantee — same root cause as the Anthropic
side. The fix mirrors that pattern: each adapter owns its client.
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
    import openai


def build_async_openai_client(api_key: str, *, base_url: str | None = None) -> openai.AsyncOpenAI:
    """Construct a fresh ``AsyncOpenAI`` bound to ``api_key`` (PAYG path).

    For Codex OAuth subscription routing, use
    :func:`build_async_codex_client` instead — the ``chatgpt.com/backend-api/
    codex`` endpoint requires ``originator`` + ``ChatGPT-Account-ID`` headers
    that this PAYG builder does not set.
    """
    if not api_key:
        raise ValueError("build_async_openai_client: api_key is empty")
    import openai

    if base_url:
        return openai.AsyncOpenAI(api_key=api_key, base_url=base_url)
    return openai.AsyncOpenAI(api_key=api_key)


def build_async_codex_client(api_key: str) -> openai.AsyncOpenAI:
    """Construct a fresh ``AsyncOpenAI`` bound to the Codex OAuth endpoint.

    Mirrors ``core.llm.providers.codex._get_async_codex_client`` (which uses a
    module-level singleton — the adapter must NOT reuse it, so we replicate
    the header + base_url plumbing here). The ``originator: codex_cli_rs``
    header and ``ChatGPT-Account-ID`` (extracted from the JWT) are mandatory
    — the Codex backend rejects unsigned requests with 401.
    """
    if not api_key:
        raise ValueError("build_async_codex_client: api_key is empty")
    import openai

    from core.config import CODEX_BASE_URL
    from core.llm.providers.codex import _extract_account_id

    account_id = _extract_account_id(api_key)
    headers: dict[str, str] = {"originator": "codex_cli_rs"}
    if account_id:
        headers["ChatGPT-Account-ID"] = account_id
    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url=CODEX_BASE_URL,
        default_headers=headers,
    )


def translate_tool_for_codex(tool: ToolSpec) -> dict[str, Any]:
    """Codex Responses API uses the FLAT tool shape, not Chat Completions nested.

    Mirrors :func:`core.llm.providers.openai._tools_to_openai` for the
    Responses-API call path used by ``CodexAgenticAdapter`` — top-level
    ``type/name/description/parameters`` rather than nested under ``function``.
    """
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }


def build_messages(req: AdapterCallRequest) -> list[dict[str, Any]]:
    """Translate adapter-neutral Message list → OpenAI Chat ``messages`` payload."""
    out: list[dict[str, Any]] = []
    if req.system_prompt:
        out.append({"role": "system", "content": req.system_prompt})
    for m in req.messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_use_id or "",
                    "content": m.content if isinstance(m.content, str) else "",
                }
            )
            continue
        out.append({"role": m.role, "content": m.content})
    return out


def translate_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def translate_chat_response(response: Any) -> AdapterCallResult:
    """OpenAI ``ChatCompletion`` → :class:`AdapterCallResult`."""
    choice = response.choices[0] if response.choices else None
    message = getattr(choice, "message", None) if choice else None
    text = getattr(message, "content", "") or "" if message else ""
    tool_calls = getattr(message, "tool_calls", None) if message else None
    tool_uses: list[dict[str, Any]] = []
    if tool_calls:
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            if fn is None:
                continue
            tool_uses.append(
                {
                    "id": getattr(tc, "id", ""),
                    "name": getattr(fn, "name", ""),
                    "input": getattr(fn, "arguments", "{}"),
                }
            )
    usage = getattr(response, "usage", None)
    return AdapterCallResult(
        text=text,
        usage=UsageSummary(
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
        ),
        stop_reason=getattr(choice, "finish_reason", "stop") if choice else "stop",
        tool_uses=tuple(tool_uses),
        raw_response=response,
    )


def translate_codex_response(response: Any) -> AdapterCallResult:
    """Codex ``Response`` → :class:`AdapterCallResult`.

    Codex uses ``output_text`` (concatenated) + ``output`` (typed items)
    instead of OpenAI Chat ``message.content``.
    """
    text = getattr(response, "output_text", "") or ""
    tool_uses: list[dict[str, Any]] = []
    output_items = getattr(response, "output", []) or []
    for item in output_items:
        if getattr(item, "type", "") == "function_call":
            tool_uses.append(
                {
                    "id": getattr(item, "id", "") or getattr(item, "call_id", ""),
                    "name": getattr(item, "name", ""),
                    "input": getattr(item, "arguments", "{}"),
                }
            )
    usage = getattr(response, "usage", None)
    return AdapterCallResult(
        text=text,
        usage=UsageSummary(
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
        ),
        stop_reason=getattr(response, "status", "completed") or "completed",
        tool_uses=tuple(tool_uses),
        raw_response=response,
    )


__all__ = [
    "build_async_codex_client",
    "build_async_openai_client",
    "build_messages",
    "translate_chat_response",
    "translate_codex_response",
    "translate_tool",
    "translate_tool_for_codex",
]
