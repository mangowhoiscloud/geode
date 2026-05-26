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

PR-DRIFT-CUT (2026-05-24) — adds shared spec helpers (model-family
detection + tools-array cap) for the OpenAI / Codex / GLM adapter
family so spec quirks (max_completion_tokens, 128 tool cap, reasoning
sampling-param ban) are honoured uniformly. Triggered by the post-v0.99.52
smoke that hit both ``Unsupported parameter: 'max_tokens'`` and
``array_above_max_length`` 400 in a single gpt-5.5 turn.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    Message,
    ToolSpec,
    UsageSummary,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cross-adapter spec constants — verified 2026-05-24 against public docs
# ---------------------------------------------------------------------------
# OpenAI Chat Completions + Codex Responses both reject ``tools`` arrays
# longer than 128 entries with 400 ``array_above_max_length``. The cap
# is empirical (gpt-5.5 + gpt-5-mini both hit 129 → 400 in production
# evidence). GLM endpoints (z.ai) are OpenAI-compatible and have not
# published a cap, but we apply the same defensive limit to keep
# behaviour predictable across the OpenAI-family adapter set.
OPENAI_TOOLS_MAX = 128


# ---------------------------------------------------------------------------
# Explicit per-model spec registry — replaces the brittle prefix-match
# (``startswith("gpt-5")``) approach. Grounded 2026-05-24 against:
#   * https://developers.openai.com/api/docs/models
#   * https://developers.openai.com/codex/models
#   * https://developers.openai.com/api/docs/guides/reasoning
# Add a new entry whenever GEODE wires a new OpenAI / Codex model — the
# default (``_OPENAI_LEGACY_DEFAULT``) emits a WARNING on first use so
# silent drift is impossible.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OpenAIModelSpec:
    """Per-model API quirks for the OpenAI Chat Completions + Codex Responses surface."""

    model_id: str
    uses_max_completion_tokens: bool
    """True → API expects ``max_completion_tokens`` (GPT-5.x + o-series).
    False → legacy ``max_tokens`` (gpt-4.x and earlier)."""

    accepts_temperature: bool
    """False → API rejects ``temperature`` (reasoning models with active reasoning).
    True → caller may pass ``temperature`` freely."""

    reasoning_effort_values: tuple[str, ...] | None
    """Valid values for ``reasoning_effort`` / ``reasoning.effort``.
    ``None`` → parameter not supported by this model."""

    context_window: int
    """Total context window (input + output) in tokens — for guard logging only."""


# Registry — keep alphabetically sorted within each family for stable diffs.
_OPENAI_MODELS: dict[str, OpenAIModelSpec] = {
    # ── GPT-5 family (reasoning, max_completion_tokens, temperature blocked) ──
    "gpt-5.3-codex": OpenAIModelSpec(
        model_id="gpt-5.3-codex",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=200_000,
    ),
    "gpt-5.4": OpenAIModelSpec(
        model_id="gpt-5.4",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=1_050_000,
    ),
    "gpt-5.4-mini": OpenAIModelSpec(
        model_id="gpt-5.4-mini",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=1_050_000,
    ),
    "gpt-5.5": OpenAIModelSpec(
        model_id="gpt-5.5",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=1_050_000,
    ),
    # ── o-series (always-on reasoning, no temperature, no "none" effort) ──
    "o3": OpenAIModelSpec(
        model_id="o3",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("low", "medium", "high"),
        context_window=200_000,
    ),
    "o4-mini": OpenAIModelSpec(
        model_id="o4-mini",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("low", "medium", "high"),
        context_window=200_000,
    ),
}


_OPENAI_LEGACY_DEFAULT = OpenAIModelSpec(
    # Used when a model id isn't in the registry — assumes legacy gpt-4.x
    # semantics (``max_tokens`` + ``temperature`` allowed). Warned on first
    # use per (model_id, process) so adding a new model can't silently drift.
    model_id="<unknown>",
    uses_max_completion_tokens=False,
    accepts_temperature=True,
    reasoning_effort_values=None,
    context_window=128_000,
)

# Process-scoped dedup so the warning fires once per unknown model_id,
# not on every LLM call.
_UNKNOWN_MODEL_WARNED: set[str] = set()


def get_openai_model_spec(model_id: str) -> OpenAIModelSpec:
    """Look up the explicit spec for an OpenAI / Codex model.

    Unknown models fall back to :data:`_OPENAI_LEGACY_DEFAULT` with a
    one-shot WARNING per ``model_id`` — the warning is the operator's
    cue to add a registry entry. The fallback assumes gpt-4.x semantics
    because that surface is the older, more permissive one and least
    likely to break a brand-new model that the registry doesn't know.
    """
    spec = _OPENAI_MODELS.get(model_id)
    if spec is not None:
        return spec
    if model_id not in _UNKNOWN_MODEL_WARNED:
        _UNKNOWN_MODEL_WARNED.add(model_id)
        log.warning(
            "OpenAI model %r not in _OPENAI_MODELS registry — falling back "
            "to legacy gpt-4.x defaults (max_tokens + temperature). Add a "
            "spec entry to core/llm/adapters/_openai_common.py for "
            "deterministic behaviour.",
            model_id,
        )
    return _OPENAI_LEGACY_DEFAULT


def cap_tools(
    tools: list[dict[str, Any]], *, model: str, adapter_name: str
) -> list[dict[str, Any]]:
    """Truncate ``tools`` to :data:`OPENAI_TOOLS_MAX` with a logged warning.

    Defensive guard at the adapter edge — the registry layer should
    already deliver ≤128 tools, but a slow MCP-aggregation regression
    or a per-session MCP burst can still push the array over. Hitting
    this path means the operator should prune MCP servers in
    ``~/.geode/config.toml [mcp.servers.*]`` or
    ``.claude/mcp_servers.json``.
    """
    if len(tools) <= OPENAI_TOOLS_MAX:
        return tools
    log.warning(
        "%s: tools array length %d > %d cap for model=%s — truncating to "
        "first %d. Operator action: prune MCP servers in "
        "``~/.geode/config.toml [mcp.servers.*]`` or "
        "``.claude/mcp_servers.json``.",
        adapter_name,
        len(tools),
        OPENAI_TOOLS_MAX,
        model,
        OPENAI_TOOLS_MAX,
    )
    return tools[:OPENAI_TOOLS_MAX]


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
    from core.llm.providers.codex import build_codex_oauth_headers

    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url=CODEX_BASE_URL,
        default_headers=build_codex_oauth_headers(api_key),
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
                replayed = {k: v for k, v in ri.items() if k != "id"}
                # PR-CODEX-MULTITURN-SUMMARY-PRESERVE (2026-05-26,
                # Codex MCP catch) — defensive injection at the
                # replay layer. The capture-path fix at
                # ``translate_codex_response`` now always emits
                # ``summary`` on newly captured items, but legacy
                # ``codex_reasoning_items`` dicts (persisted across
                # process restarts, deserialised from older state
                # snapshots, or constructed by external callers) may
                # still lack the field. The OpenAI Responses API
                # rejects with ``"Missing required parameter:
                # 'input[N].summary'"`` whenever it's absent, so we
                # inject ``summary: []`` here too — defence in depth
                # against both the capture-time and the persisted-
                # data drift surfaces.
                replayed.setdefault("summary", [])
                out.append(replayed)
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
    # PR-CODEX-OAUTH-MESSAGE-FROM-ACCUMULATED (Sprint H2, 2026-05-26)
    # — codex-oauth + gpt-5.x streaming has a documented discrepancy
    # where SSE delivers ``response.output_item.done`` events with
    # ``type=message role=assistant content=[ResponseOutputText(text=…)]``
    # but the aggregated ``stream.get_final_response().output[]`` is
    # empty (so ``response.output_text`` is also empty). Pre-fix the
    # loop below only walked items_source for ``function_call`` +
    # ``reasoning`` types — the message text was dropped on the
    # floor every voter call returned ``output_text=""`` even though
    # the model had emitted a complete response. The minimal probe at
    # ``scripts/probes/probe_codex_oauth_message_recovery.py``
    # ("Say hello world") reproduces this with input=25 / output=17
    # tokens. Smoke 20/21/22 ranker voter quorum collapse (97
    # codex-oauth-empty-text dumps in smoke 22 alone) all trace here.
    # When ``response.output_text`` is empty AND accumulated items
    # carry a message item, reconstruct the text from the
    # SSE-delivered ``output_text`` content blocks.
    fallback_text_parts: list[str] = []
    for item in items_source:
        itype = getattr(item, "type", "") if not isinstance(item, dict) else item.get("type", "")
        if itype == "message" and not text:
            content = _attr_or_key(item, "content") or []
            for block in content:
                block_type = _attr_or_key(block, "type")
                # Per the OpenAI Python SDK, ``ResponseOutputMessage.content``
                # contains either ``ResponseOutputText`` (visible model
                # answer) or ``ResponseOutputRefusal`` (visible refusal
                # message). Both carry user-facing text — extract from
                # whichever variant the model emitted. Codex MCP catch
                # (Sprint H2, 2026-05-26) — pre-fold the refusal path was
                # silently dropped, so a streamed refusal would have
                # surfaced as ``text=""`` (i.e. classified as transport
                # failure instead of a real model refusal).
                if block_type == "output_text":
                    block_text = _attr_or_key(block, "text") or ""
                    if block_text:
                        fallback_text_parts.append(block_text)
                elif block_type == "refusal":
                    refusal_text = _attr_or_key(block, "refusal") or ""
                    if refusal_text:
                        fallback_text_parts.append(refusal_text)
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
            # PR-CODEX-MULTITURN-SUMMARY-PRESERVE (2026-05-26) —
            # ALWAYS include ``summary`` (default to empty list when
            # gpt-5.x didn't emit one). Pre-fix the field was only
            # populated when ``summary`` was truthy; on replay the
            # OpenAI Responses API requires every reasoning item to
            # carry ``summary`` (even ``[]``) and rejects with
            # ``"Missing required parameter: 'input[N].summary'"``
            # when it's absent (smoke 19 evidence:
            # vote-m000-openai.openai-codex/dialogue.jsonl turn 2 +
            # ~10 voter failures across the ranker phase). Per
            # ctx7-grounded Responses API docs (``/websites/
            # developers_openai_api`` "Keeping reasoning items in
            # context") the field is structurally required even when
            # there's no chain-of-thought summary to surface.
            summary = _attr_or_key(item, "summary")
            entry["summary"] = summary if summary else []
            if summary and isinstance(summary, list):
                for s in summary:
                    t = s.get("text", "") if isinstance(s, dict) else getattr(s, "text", "") or ""
                    if t:
                        reasoning_summaries.append(t)
            iid = _attr_or_key(item, "id")
            if iid:
                entry["id"] = iid
            reasoning_items.append(entry)
    # PR-CODEX-OAUTH-MESSAGE-FROM-ACCUMULATED (Sprint H2, 2026-05-26) —
    # promote the SSE-walked message text only when ``response.output_text``
    # was empty. Skips a no-op concat when the aggregated value was
    # already populated (non-streaming callers, non-defective backends).
    if not text and fallback_text_parts:
        text = "".join(fallback_text_parts)
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
