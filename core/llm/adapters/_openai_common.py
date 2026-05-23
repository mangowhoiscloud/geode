"""Shared OpenAI-side helpers for the v0.99.39 LLMAdapter built-ins.

Mirror of :mod:`core.llm.adapters._anthropic_common` for the OpenAI provider:
fresh-client builder (PAYG vs Codex OAuth must not share the module-level
singleton in ``core.llm.providers.openai``) + multi-turn request translation
+ response normalisation.

A2 (v0.99.44) — ports the multi-turn converters from
``core.llm.providers.openai`` so :class:`Message` content lists carrying
Anthropic-shape tool blocks re-encode correctly into either the Chat
Completions wire shape (``tool_calls`` on assistant + ``role: tool`` with
``tool_call_id`` on user) or the Codex Responses API wire shape
(``function_call`` / ``function_call_output`` typed items). Pre-A2 the
adapter passed Anthropic content lists through verbatim → OpenAI/Codex
SDK rejected with 400. Codex MCP review 2026-05-23 BLOCKER 2.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    Message,
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


# ---------------------------------------------------------------------------
# Tool definition shape — Chat vs Responses API
# ---------------------------------------------------------------------------


def translate_tool(tool: ToolSpec) -> dict[str, Any]:
    """Anthropic ToolSpec → OpenAI Chat Completions nested ``function`` shape."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def translate_tool_for_codex(tool: ToolSpec) -> dict[str, Any]:
    """Anthropic ToolSpec → Codex Responses API flat shape.

    Mirrors :func:`core.llm.providers.openai._tools_to_openai` — top-level
    ``type/name/description/parameters`` rather than nested under
    ``function``. Required by ``chatgpt.com/backend-api/codex/responses``.
    """
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }


# ---------------------------------------------------------------------------
# Multi-turn message converters — Anthropic content blocks → provider shape
# ---------------------------------------------------------------------------


def build_messages(req: AdapterCallRequest) -> list[dict[str, Any]]:
    """Translate :class:`Message` list → OpenAI Chat Completions ``messages``.

    Handles three content shapes per message:

    - ``str`` — direct text body, emitted unchanged.
    - ``list[dict]`` carrying Anthropic blocks (``{"type": "tool_use", ...}``
      on assistant, ``{"type": "tool_result", "tool_use_id": ...}`` on user)
      — re-encoded into OpenAI's flat ``tool_calls`` (on assistant) +
      ``role: tool`` follow-ups (with ``tool_call_id``).
    - Anything else — stringified.

    A2 (v0.99.44, Codex MCP BLOCKER 2): pre-fix this helper emitted the
    content list raw, so the OpenAI SDK rejected with 400. Now re-encodes
    via :func:`_convert_assistant_msg_to_chat` and
    :func:`_convert_user_msg_to_chat`.
    """
    out: list[dict[str, Any]] = []
    if req.system_prompt:
        out.append({"role": "system", "content": req.system_prompt})
    for m in req.messages:
        if m.role == "tool":
            # Adapter-emitted tool result (rare; multi-turn loops use Anthropic
            # blocks on the user role instead).
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_use_id or "",
                    "content": m.content if isinstance(m.content, str) else "",
                }
            )
            continue
        if m.role == "assistant":
            out.append(_convert_assistant_msg_to_chat(m.content))
            continue
        if m.role == "user":
            out.extend(_convert_user_msg_to_chat(m.content))
            continue
        out.append({"role": m.role, "content": _stringify(m.content)})
    return out


def build_codex_input(req: AdapterCallRequest) -> list[dict[str, Any]]:
    """Translate :class:`Message` list → Codex Responses API ``input`` array.

    Differences from Chat shape:

    - Codex uses ``instructions`` field (passed separately) for the system
      prompt — this function does NOT prepend a ``role: system`` entry.
      Callers must thread ``req.system_prompt`` into the ``instructions``
      kwarg of ``responses.stream(...)``.
    - Assistant ``tool_use`` blocks → ``{"type": "function_call", "call_id",
      "name", "arguments"}`` typed items.
    - User ``tool_result`` blocks → ``{"type": "function_call_output",
      "call_id", "output"}`` typed items.

    A2 (v0.99.44): when an assistant :class:`Message` carries
    ``codex_reasoning_items`` (captured from a prior Codex turn), those
    items are prepended **immediately before** that assistant's entries
    so gpt-5.x can resume its chain of thought at the correct ordinal
    position. Flattening to a single tuple at the top of ``input`` would
    misattribute reasoning across multi-assistant histories — Codex MCP
    A2 BLOCKER 3.

    Mirrors :func:`core.llm.providers.openai._convert_messages_to_responses`
    composed with :func:`core.llm.agentic_response.inject_reasoning_replay`.
    """
    out: list[dict[str, Any]] = []
    for m in req.messages:
        if m.role == "assistant":
            # Replay this turn's encrypted reasoning items (id-stripped)
            # right before the assistant's converted entries.
            for ri in m.codex_reasoning_items:
                if not isinstance(ri, dict) or not ri.get("encrypted_content"):
                    continue
                out.append({k: v for k, v in ri.items() if k != "id"})
            out.extend(_convert_assistant_msg_to_responses(m.content))
            continue
        if m.role == "user":
            out.extend(_convert_user_msg_to_responses(m.content))
            continue
        out.append({"role": m.role, "content": _stringify(m.content)})
    return out


# ---------------------------------------------------------------------------
# Chat Completions per-message conversion
# ---------------------------------------------------------------------------


def _convert_assistant_msg_to_chat(content: Any) -> dict[str, Any]:
    """Anthropic assistant content → Chat Completions ``assistant`` shape.

    When the content list contains ``tool_use`` blocks they translate into
    OpenAI's nested ``tool_calls`` array; text blocks concatenate into the
    ``content`` field (or ``None`` when only tool_calls).
    """
    if isinstance(content, str):
        return {"role": "assistant", "content": content}
    if not isinstance(content, list):
        return {"role": "assistant", "content": _stringify(content)}
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    },
                }
            )
    msg: dict[str, Any] = {"role": "assistant"}
    msg["content"] = "\n".join(text_parts) if text_parts else None
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _convert_user_msg_to_chat(content: Any) -> list[dict[str, Any]]:
    """Anthropic user content → Chat Completions entries.

    ``tool_result`` blocks split off into separate ``{"role": "tool",
    "tool_call_id": ...}`` messages. Text blocks merge into a single
    ``{"role": "user", "content": "..."}`` follow-up.
    """
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    if not isinstance(content, list):
        return [{"role": "user", "content": _stringify(content)}]
    result: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            text_parts.append(_stringify(block))
            continue
        btype = block.get("type")
        if btype == "tool_result":
            raw = block.get("content", "")
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": block.get("tool_use_id", ""),
                    "content": raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False),
                }
            )
        elif btype == "text":
            text_parts.append(block.get("text", ""))
        else:
            text_parts.append(_stringify(block))
    if text_parts:
        result.append({"role": "user", "content": "\n".join(text_parts)})
    return result if result else [{"role": "user", "content": ""}]


# ---------------------------------------------------------------------------
# Codex Responses API per-message conversion
# ---------------------------------------------------------------------------


def _convert_assistant_msg_to_responses(content: Any) -> list[dict[str, Any]]:
    """Anthropic assistant content → Responses API typed items.

    Splits text + tool_use into separate items (text becomes
    ``{"role": "assistant", "content": ...}``, tool_use becomes
    ``{"type": "function_call", "call_id", "name", "arguments"}``) preserving
    the original ordering so the next-turn pairing with ``function_call_output``
    matches by ``call_id``.
    """
    if isinstance(content, str):
        return [{"role": "assistant", "content": content}]
    if not isinstance(content, list):
        return [{"role": "assistant", "content": _stringify(content)}]
    items: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            if text_parts:
                items.append({"role": "assistant", "content": "\n".join(text_parts)})
                text_parts = []
            items.append(
                {
                    "type": "function_call",
                    "call_id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                }
            )
    if text_parts:
        items.append({"role": "assistant", "content": "\n".join(text_parts)})
    return items if items else [{"role": "assistant", "content": ""}]


def _convert_user_msg_to_responses(content: Any) -> list[dict[str, Any]]:
    """Anthropic user content → Responses API typed items.

    ``tool_result`` blocks become ``{"type": "function_call_output",
    "call_id", "output"}`` items; text blocks aggregate into a follow-up
    ``{"role": "user", "content": ...}`` entry.
    """
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    if not isinstance(content, list):
        return [{"role": "user", "content": _stringify(content)}]
    items: list[dict[str, Any]] = []
    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            text_parts.append(_stringify(block))
            continue
        btype = block.get("type")
        if btype == "tool_result":
            raw = block.get("content", "")
            output = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": block.get("tool_use_id", ""),
                    "output": output,
                }
            )
        elif btype == "text":
            text_parts.append(block.get("text", ""))
        else:
            text_parts.append(_stringify(block))
    if text_parts:
        items.append({"role": "user", "content": "\n".join(text_parts)})
    return items if items else [{"role": "user", "content": ""}]


def _stringify(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


# ---------------------------------------------------------------------------
# Response normalisation
# ---------------------------------------------------------------------------


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


def translate_codex_response(
    response: Any,
    *,
    accumulated_items: list[Any] | None = None,
) -> AdapterCallResult:
    """Codex ``Response`` → :class:`AdapterCallResult`.

    Codex uses ``output_text`` (concatenated) + ``output`` (typed items)
    instead of OpenAI Chat ``message.content``. When the caller streams the
    response, ``accumulated_items`` should be the SSE-collected
    ``response.output_item.done`` items — we walk those for reasoning items
    + function_call extraction. Non-streaming callers pass ``None`` and we
    fall back to ``response.output``.

    A2 (v0.99.44): populates ``reasoning_items`` so the bridge can forward
    encrypted-reasoning replay to the next turn for gpt-5.x models.
    """
    text = getattr(response, "output_text", "") or ""
    items_source: list[Any] = (
        accumulated_items if accumulated_items else (getattr(response, "output", []) or [])
    )
    tool_uses: list[dict[str, Any]] = []
    reasoning_items: list[dict[str, Any]] = []
    reasoning_summaries: list[str] = []
    for item in items_source:
        itype = getattr(item, "type", "") if not isinstance(item, dict) else item.get("type", "")
        if itype == "function_call":
            # Codex backend assigns ``call_id`` as the durable identifier — the
            # ``function_call_output`` reply on the next turn MUST reference
            # this ``call_id`` (not ``id``, which is server-internal and
            # unstable under ``store=False``). Mirrors the legacy normaliser
            # at ``core/llm/providers/openai.py`` — Codex MCP A2 BLOCKER 1.
            tool_uses.append(
                {
                    "id": _attr_or_key(item, "call_id") or _attr_or_key(item, "id"),
                    "name": _attr_or_key(item, "name"),
                    "input": _attr_or_key(item, "arguments") or "{}",
                }
            )
        elif itype == "reasoning":
            entry: dict[str, Any] = {"type": "reasoning"}
            enc = _attr_or_key(item, "encrypted_content")
            if enc:
                entry["encrypted_content"] = enc
            summary = _attr_or_key(item, "summary")
            if summary:
                entry["summary"] = summary
                if isinstance(summary, list):
                    for s in summary:
                        t = (
                            s.get("text", "")
                            if isinstance(s, dict)
                            else getattr(s, "text", "") or ""
                        )
                        if t:
                            reasoning_summaries.append(t)
            iid = _attr_or_key(item, "id")
            if iid:
                entry["id"] = iid
            reasoning_items.append(entry)
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
        reasoning_items=tuple(reasoning_items),
        reasoning_summaries=tuple(reasoning_summaries),
    )


def _attr_or_key(item: Any, name: str) -> Any:
    """Read ``item.name`` whether ``item`` is an SDK object or a dict."""
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


__all__ = [
    "Message",
    "build_async_codex_client",
    "build_async_openai_client",
    "build_codex_input",
    "build_messages",
    "translate_chat_response",
    "translate_codex_response",
    "translate_tool",
    "translate_tool_for_codex",
]
