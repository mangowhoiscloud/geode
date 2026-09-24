"""Shared Anthropic-side helpers for the v0.99.39 LLMAdapter built-ins.

Lives next to the concrete Anthropic adapters and holds:

1. ``build_async_anthropic_client(api_key)`` — creates a NEW
   :class:`anthropic.AsyncAnthropic` per adapter rather than reusing the
   module-level singleton from ``core.llm.providers.anthropic``. The singleton
   path caches the first caller's api_key. Codex MCP review 2026-05-23 flagged
   this as a BLOCKER for the source/billing guarantee.
2. ``build_messages`` / ``translate_response`` / ``translate_tool`` / etc. —
   request and response shape helpers for the Anthropic API-key adapter.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    ToolSpec,
    UsageSummary,
)
from core.llm.agentic_response import normalize_stop_details
from core.llm.errors import LLMRequestValidationError, LLMResponseValidationError
from core.llm.model_capabilities import anthropic_base_model, get_anthropic_model_spec

# Computer-use display dims live in the harness module (single SoT) so the
# injected tool DEFINITION and the local executor never drift.
from core.tools.computer_use import TARGET_HEIGHT as _COMPUTER_DISPLAY_HEIGHT
from core.tools.computer_use import TARGET_WIDTH as _COMPUTER_DISPLAY_WIDTH
from core.tools.plan import thaw_tool_schema

if TYPE_CHECKING:
    import anthropic

log = logging.getLogger(__name__)


def build_async_anthropic_client(api_key: str) -> anthropic.AsyncAnthropic:
    """Construct a fresh ``AsyncAnthropic`` bound to an API key.

    Each adapter owns its client — bypassing the module-level singleton in
    ``core.llm.providers.anthropic`` which is keyed solely by the first
    caller's resolved key. Same httpx limits/timeout/event-hooks as the
    singleton so the response-header banner pipeline keeps working.

    """
    if not api_key:
        raise ValueError("build_async_anthropic_client: api_key is required")
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
    computer_call_ids: set[str] = set()
    for m in req.messages:
        if m.role == "tool":
            content: Any = [
                {
                    "type": "tool_result",
                    "tool_use_id": m.tool_use_id or "",
                    "content": m.content,
                }
            ]
        else:
            content = (
                list(m.anthropic_content)
                if m.role == "assistant" and m.anthropic_content
                else m.content
            )
        if isinstance(content, list):
            shaped = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use" and block.get("toolset_name") == "computer":
                        computer_call_ids.add(block["id"])
                    elif (
                        block.get("type") == "tool_result"
                        and block.get("tool_use_id") in computer_call_ids
                    ):
                        block = {**block, "toolset_name": "computer"}
                shaped.append(block)
            content = shaped
        out.append({"role": "user" if m.role == "tool" else m.role, "content": content})
    return out


def translate_tool(tool: ToolSpec) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "input_schema": thaw_tool_schema(tool.input_schema),
    }


# Native computer generations require an explicit verified model contract.
_COMPUTER_USE_CURRENT = ("computer_20251124", "computer-use-2025-11-24")
_COMPUTER_USE_LEGACY = ("computer_20250124", "computer-use-2025-01-24")
# Both native tool types — used for dedup (either generation counts as present).
_COMPUTER_USE_TOOLSET = "computer_toolset_20260801"
_COMPUTER_USE_TYPES = frozenset(
    {_COMPUTER_USE_CURRENT[0], _COMPUTER_USE_LEGACY[0], _COMPUTER_USE_TOOLSET}
)


def _computer_use_spec(model: str) -> tuple[str, str]:
    """Resolve only verified computer-use generations."""
    spec = get_anthropic_model_spec(model)
    if spec is None:
        raise LLMRequestValidationError(f"Computer use is not verified for {model}")
    if spec.computer_tool == _COMPUTER_USE_TOOLSET:
        return _COMPUTER_USE_TOOLSET, ""
    return (
        _COMPUTER_USE_LEGACY
        if spec.computer_tool == _COMPUTER_USE_LEGACY[0]
        else _COMPUTER_USE_CURRENT
    )


def anthropic_computer_tool_param(
    display_width: int, display_height: int, tool_type: str = _COMPUTER_USE_CURRENT[0]
) -> dict[str, Any]:
    """Anthropic computer-use tool definition (ComputerUseCapable).

    Legacy definitions declare the harness screenshot dimensions. The GA
    toolset infers geometry from those screenshots and rejects display fields.
    """
    if tool_type == _COMPUTER_USE_TOOLSET:
        from core.tools.computer_use import UNSUPPORTED_COMPUTER_MEMBERS

        return {
            "type": tool_type,
            "configs": {name: {"enabled": False} for name in UNSUPPORTED_COMPUTER_MEMBERS},
        }
    return {
        "type": tool_type,
        "name": "computer",
        "display_width_px": display_width,
        "display_height_px": display_height,
    }


def _maybe_inject_computer_use(kwargs: dict[str, Any], req: AdapterCallRequest) -> None:
    """Inject the model's computer tool, including legacy beta headers.

    The tool is type-carrying so it is exempt from tool-search defer. It is
    appended here (not inside ``_shape_tools``) so it also injects when the
    request carries no registry tools.
    """
    from core.llm.providers.anthropic import is_computer_use_enabled

    if (
        not is_computer_use_enabled()
        or "computer" not in req.executable_tool_names
        or "computer" in req.denied_tool_names
        or "computer_use" in req.denied_tool_names
        or (req.allowed_tool_names is not None and "computer" not in req.allowed_tool_names)
    ):
        return
    tool_type, beta = _computer_use_spec(req.model)
    tools = list(kwargs.get("tools") or [])
    if tool_type == _COMPUTER_USE_TOOLSET:
        # The native toolset replaces the registry's computer schema. The API
        # rejects a toolset beside any other tool named computer.
        tools = [t for t in tools if t.get("name") != "computer"]
        kwargs["tools"] = tools
        choice = dict(
            kwargs.get("tool_choice") or _translate_tool_choice(req.tool_choice) or {"type": "auto"}
        )
        if choice.get("type") != "none":
            choice["disable_parallel_tool_use"] = True
        kwargs["tool_choice"] = choice
    # Dedup by the NATIVE type (either generation), not the name: a caller's
    # custom same-name tool must not suppress native injection, and re-entrancy
    # must not double it.
    if not any(t.get("type") in _COMPUTER_USE_TYPES for t in tools):
        tools.append(
            anthropic_computer_tool_param(
                _COMPUTER_DISPLAY_WIDTH, _COMPUTER_DISPLAY_HEIGHT, tool_type
            )
        )
        kwargs["tools"] = tools
    # Always ensure the model's beta token when the native tool is present.
    if beta:
        _merge_beta(kwargs, beta)


def _base_model(model: str) -> str:
    """Use the capability owner's snapshot/alias normalization."""
    return anthropic_base_model(model)


def _merge_beta(kwargs: dict[str, Any], *betas: str) -> None:
    """Merge beta tokens into ``anthropic-beta`` — never clobber the header.

    Live incident (probe, 2026-07-29): replacing ``extra_headers`` wholesale
    dropped computer-use's beta token and 400'd on the computer tool tag.
    """
    headers = dict(kwargs.get("extra_headers") or {})
    tokens: list[str] = []
    for raw in [*headers.get("anthropic-beta", "").split(","), *betas]:
        token = raw.strip()
        if token and token not in tokens:
            tokens.append(token)
    headers["anthropic-beta"] = ",".join(tokens)
    kwargs["extra_headers"] = headers


def _maybe_inject_context_management(kwargs: dict[str, Any]) -> None:
    """Context editing and compaction have separate provider capability gates."""
    from core.llm.model_capabilities import ANTHROPIC_COMPACTION_MODELS
    from core.llm.providers.anthropic import _CONTEXT_MGMT_MODELS

    model = _base_model(str(kwargs.get("model", "")))
    if model not in _CONTEXT_MGMT_MODELS:
        return
    from core.llm.token_tracker import MODEL_CONTEXT_WINDOW
    from core.orchestration.context_budget import resolve_context_budget_policy

    trigger = resolve_context_budget_policy(
        model, context_window=MODEL_CONTEXT_WINDOW.get(model)
    ).anthropic_compact_trigger_tokens
    _merge_beta(kwargs, "context-management-2025-06-27")
    body = dict(kwargs.get("extra_body") or {})
    edits: list[dict[str, Any]] = [
        {"type": "clear_tool_uses_20250919", "keep": {"type": "tool_uses", "value": 5}}
    ]
    if model in ANTHROPIC_COMPACTION_MODELS:
        _merge_beta(kwargs, "compact-2026-01-12")
        edits.append(
            {"type": "compact_20260112", "trigger": {"type": "input_tokens", "value": trigger}}
        )
    body["context_management"] = {"edits": edits}
    kwargs["extra_body"] = body


def _inject_native_web_tools(kwargs: dict[str, Any], req: AdapterCallRequest) -> None:
    """Append Anthropic-hosted web_search / web_fetch server tools.

    Hosted rounds surface through final text; their raw native blocks stay
    available for replay. Current contracts are sourced in the refresh note.

    Three gates, all required (Codex review 2026-07-29):

    1. **Opt-in** (``settings.anthropic_native_web_tools``, default False).
       The server runs these itself, so an explicit request allowlist is
       checked here before provider translation. GEODE's own
       ``general_web_search`` / ``web_fetch`` handlers stay the default path.
    2. **Model support** — the verified model record gates search and fetch
       independently; the dated dynamic tools are not supported by Haiku.
    3. **Tool surface present** — the caller declared tools; plain text
       completions stay tool-free.
    """
    from core.config import settings
    from core.llm.model_capabilities import ANTHROPIC_WEB_SEARCH_MODELS
    from core.llm.providers.anthropic import _ANTHROPIC_NATIVE_TOOLS

    if not getattr(settings, "anthropic_native_web_tools", False):
        return
    if _base_model(str(kwargs.get("model", ""))) not in ANTHROPIC_WEB_SEARCH_MODELS:
        return
    if not req.tools:
        return
    tools = kwargs.get("tools")
    if not isinstance(tools, list):
        return
    # Appended AFTER _shape_tools so hosted server tools are excluded from
    # the defer threshold (they are never deferrable — the server owns them).
    existing = {t.get("name") for t in tools if isinstance(t, dict)}
    spec = get_anthropic_model_spec(req.model)
    for native in _ANTHROPIC_NATIVE_TOOLS:
        if native["name"] == "web_fetch" and (spec is None or not spec.dynamic_web_fetch):
            continue
        if native["name"] in req.denied_tool_names:
            continue
        if req.allowed_tool_names is not None and native["name"] not in req.allowed_tool_names:
            continue
        if native["name"] not in existing:
            tools.append(dict(native))


def _cache_shaped_system(system: str) -> str | list[dict[str, Any]]:
    """STATIC/DYNAMIC prompt-cache split for the LIVE adapter path.

    Static prefix (before ``<dynamic_context>``) gets the 1h-TTL
    ``cache_control``; the dynamic tail stays unmarked. Unlike the dead
    original, the boundary tag itself is KEPT in the dynamic block so the
    ``<dynamic_context>…</dynamic_context>`` envelope stays balanced on
    the wire. No boundary → plain string passthrough.
    """
    from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY
    from core.llm.providers.anthropic import _static_system_cache_control

    if not system or PROMPT_CACHE_BOUNDARY not in system:
        return system
    static_part, dynamic_part = system.split(PROMPT_CACHE_BOUNDARY, 1)
    static_text = static_part.rstrip()
    dynamic_text = (PROMPT_CACHE_BOUNDARY + dynamic_part).strip()
    if static_text and dynamic_text:
        return [
            {"type": "text", "text": static_text, "cache_control": _static_system_cache_control()},
            {"type": "text", "text": dynamic_text},
        ]
    if dynamic_text:
        # Audit-mode strip can empty the static half (G-A2): an empty text
        # block with cache_control is an Anthropic 400 — mark the dynamic
        # side with the 5-minute default instead.
        return [{"type": "text", "text": dynamic_text, "cache_control": {"type": "ephemeral"}}]
    if static_text:
        return [
            {"type": "text", "text": static_text, "cache_control": _static_system_cache_control()}
        ]
    return system


def _system_and_messages(req: AdapterCallRequest) -> tuple[Any, list[dict[str, Any]]]:
    """Shared system/messages shaping after composed request middleware."""
    from core.llm.providers.anthropic import (
        MAX_MESSAGE_CACHE_BREAKPOINTS,
        apply_messages_cache_control,
    )

    messages = build_messages(req)
    system = req.system_prompt
    # ADR-013 T5 — cache-breakpoint policy SoT governs the message budget
    # (was likewise stranded in the dead adapter).
    raw_breakpoints = req.provider_options.get(
        "cache_message_breakpoints",
        MAX_MESSAGE_CACHE_BREAKPOINTS,
    )
    n_breakpoints = (
        raw_breakpoints
        if isinstance(raw_breakpoints, int) and not isinstance(raw_breakpoints, bool)
        else MAX_MESSAGE_CACHE_BREAKPOINTS
    )
    return _cache_shaped_system(system), apply_messages_cache_control(
        messages, n_breakpoints=n_breakpoints
    )


def build_create_kwargs(
    req: AdapterCallRequest, *, base_url: str = "https://api.anthropic.com"
) -> dict[str, Any]:
    """Build ``messages.create`` kwargs for the Anthropic PAYG adapter."""
    if req.max_tokens < 1:
        raise LLMRequestValidationError("Anthropic max_tokens must be positive")
    system, messages = _system_and_messages(req)
    kwargs: dict[str, Any] = {
        "model": req.model,
        "system": system,
        "messages": messages,
        "max_tokens": req.max_tokens,
    }
    spec = get_anthropic_model_spec(req.model)
    if spec is not None and spec.adaptive_thinking:
        thinking: dict[str, Any] = {"type": "adaptive", "display": "summarized"}
        if spec.binds_thinking:
            # GEODE refreshes dynamic system context between turns. Preserve
            # valid signed blocks and let the API report blocks invalidated by
            # those edits, rather than failing new accounts with a 400.
            thinking["block_binding"] = {"prefix_mismatch_behavior": "drop_block"}
            _merge_beta(kwargs, "thinking-binding-controls-2026-08-01")
        kwargs["thinking"] = thinking
    elif req.thinking_budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": req.thinking_budget}
        kwargs["max_tokens"] = req.max_tokens + req.thinking_budget
        kwargs["temperature"] = 1.0
    elif req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if spec is not None and spec.effort_values:
        # Match Claude Code: an unsupported level never increases spend.
        effort = (
            "high" if req.effort == "xhigh" and "xhigh" not in spec.effort_values else req.effort
        )
        if effort not in spec.effort_values:
            raise LLMRequestValidationError(f"{req.model} does not support effort {req.effort!r}")
        kwargs["output_config"] = {"effort": effort}
    if spec is not None and kwargs["max_tokens"] > spec.max_output_tokens:
        raise LLMRequestValidationError(
            f"{req.model} requires max_tokens between 1 and {spec.max_output_tokens}, "
            "including any thinking budget"
        )
    if req.response_schema is not None:
        if spec is None:
            raise LLMRequestValidationError(f"Structured output is not verified for {req.model}")
        if req.response_schema.get("type") != "object":
            raise LLMRequestValidationError("Anthropic response_schema requires an object root")
        kwargs.setdefault("output_config", {})["format"] = {
            "type": "json_schema",
            "schema": deepcopy(req.response_schema),
        }
    tc = _translate_tool_choice(req.tool_choice)
    if (
        spec is not None
        and not spec.forced_tool_choice
        and tc
        and tc.get("type") in {"any", "tool"}
    ):
        raise LLMRequestValidationError(
            f"{req.model} does not support forced tool_choice; use auto or none"
        )
    if (
        tc
        and tc.get("type") in {"any", "tool"}
        and kwargs.get("thinking", {}).get("type") == "enabled"
    ):
        raise LLMRequestValidationError(
            "Manual thinking does not support forced tool_choice; use auto or none"
        )
    if req.tools:
        kwargs["tools"] = _shape_tools(req, tc, base_url=base_url)
        if tc is not None:
            kwargs["tool_choice"] = tc
    if req.stop_sequences:
        kwargs["stop_sequences"] = list(req.stop_sequences)
    _maybe_inject_computer_use(kwargs, req)
    _inject_native_web_tools(kwargs, req)
    _maybe_inject_context_management(kwargs)
    return kwargs


def _shape_tools(
    req: AdapterCallRequest, tc: dict[str, Any] | None, *, base_url: str
) -> list[dict[str, Any]]:
    """Translate + apply hosted tool-search defer on the LIVE adapter path.

    Shaping is skipped under a forced single-tool ``tool_choice`` (the
    official docs do not state that a forced DEFERRED tool resolves, so
    we do not gamble a 400 on it).
    """
    from core.config import settings as _settings
    from core.llm.model_capabilities import ANTHROPIC_TOOL_SEARCH_MODELS
    from core.llm.providers.anthropic import apply_tool_search_defer

    translated = [translate_tool(t) for t in req.tools]
    if tc is not None and tc.get("type") == "tool":
        return translated
    return apply_tool_search_defer(
        translated,
        deferred_tool_names=req.deferred_tool_names,
        enabled=(
            _settings.tool_search_defer
            and _base_model(req.model) in ANTHROPIC_TOOL_SEARCH_MODELS
            and base_url.rstrip("/") == "https://api.anthropic.com"
        ),
    )


def _translate_tool_choice(tc: str | dict[str, Any]) -> dict[str, Any] | None:
    """Adapter-neutral ``tool_choice`` → Anthropic ``tool_choice`` payload.

    Anthropic accepts ``{"type": "auto" | "any" | "none" | "tool", "name": ...}``.
    The loop emits ``{"type": "none"}`` during wrap-up to forbid tool calls;
    without explicit translation the SDK silently allows tool use and the
    wrap-up safety net is defeated (Codex MCP 2026-05-23 MEDIUM 1).
    """
    if isinstance(tc, dict):
        return tc
    if tc in ("auto", "any", "none"):
        return {"type": tc}
    if tc == "required":
        return {"type": "any"}
    return None  # unknown literal — let Anthropic default apply


def build_stream_kwargs(
    req: AdapterCallRequest, *, base_url: str = "https://api.anthropic.com"
) -> dict[str, Any]:
    """Streaming uses the same Messages contract, including thinking and stops."""
    return build_create_kwargs(req, base_url=base_url)


def report_input_transformations(response: Any) -> None:
    """Surface provider-confirmed reasoning loss without logging signed content."""
    transformations = getattr(response, "input_transformations", None) or []
    for reason in ("prefix_binding_mismatch", "model_binding_mismatch"):
        count = sum(
            (entry.get("reason") if isinstance(entry, dict) else getattr(entry, "reason", None))
            == reason
            for entry in transformations
        )
        if count:
            log.warning("Anthropic thinking transformations: reason=%s blocks=%d", reason, count)


def translate_response(response: Any) -> AdapterCallResult:
    """Anthropic SDK Message → :class:`AdapterCallResult`."""
    report_input_transformations(response)
    text_blocks: list[str] = []
    tool_uses: list[dict[str, Any]] = []
    # SDK serialization retains native blocks/signatures in their original order.
    # Lightweight legacy response doubles without this surface keep normalized replay.
    dump = getattr(response, "model_dump", None)
    anthropic_content = (
        tuple(dump(mode="json", exclude_none=True)["content"]) if callable(dump) else ()
    )
    for block in getattr(response, "content", []) or []:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            text_blocks.append(getattr(block, "text", ""))
        elif block_type == "tool_use":
            name = getattr(block, "name", "")
            tool_input = getattr(block, "input", {})
            if getattr(block, "toolset_name", None) == "computer":
                # Execution is normalized; the raw native blocks above remain
                # intact for signed replay and toolset result correlation.
                tool_input = {**tool_input, "action": name}
                name = "computer"
            tool_uses.append(
                {
                    "id": getattr(block, "id", ""),
                    "name": name,
                    "input": tool_input,
                }
            )
    usage = getattr(response, "usage", None)
    output_details = getattr(usage, "output_tokens_details", None) if usage else None
    cached_tokens = getattr(usage, "cache_read_input_tokens", None)
    cache_write_tokens = getattr(usage, "cache_creation_input_tokens", None)
    result = AdapterCallResult(
        text="".join(text_blocks),
        usage=UsageSummary(
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
            input_tokens_present=getattr(usage, "input_tokens", None) is not None,
            output_tokens_present=getattr(usage, "output_tokens", None) is not None,
            cached_input_tokens=int(cached_tokens or 0),
            cached_input_tokens_present=cached_tokens is not None,
            reasoning_tokens=int(getattr(output_details, "thinking_tokens", 0) or 0),
            reasoning_tokens_present=getattr(output_details, "thinking_tokens", None) is not None,
            cache_write_tokens=int(cache_write_tokens or 0),
            cache_write_tokens_present=cache_write_tokens is not None,
        ),
        stop_reason=getattr(response, "stop_reason", "end_turn") or "end_turn",
        stop_details=(
            normalize_stop_details(getattr(response, "stop_details", None))
            if getattr(response, "stop_reason", None) == "refusal"
            else None
        ),
        tool_uses=tuple(tool_uses),
        raw_response=response,
        anthropic_content=anthropic_content,
    )
    if (
        any(
            getattr(b, "toolset_name", None) == "computer"
            for b in getattr(response, "content", []) or []
        )
        and len(tool_uses) > 1
    ):
        raise LLMResponseValidationError(
            "Computer toolset returned multiple actions despite disable_parallel_tool_use",
            completed_result=result,
        )
    return result


__all__ = [
    "anthropic_computer_tool_param",
    "build_async_anthropic_client",
    "build_create_kwargs",
    "build_messages",
    "build_stream_kwargs",
    "translate_response",
    "translate_tool",
]
