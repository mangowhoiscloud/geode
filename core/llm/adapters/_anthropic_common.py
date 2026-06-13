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

# Computer-use display dims live in the harness module (single SoT) so the
# injected tool DEFINITION and the local executor never drift.
from core.tools.computer_use import TARGET_HEIGHT as _COMPUTER_DISPLAY_HEIGHT
from core.tools.computer_use import TARGET_WIDTH as _COMPUTER_DISPLAY_WIDTH

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


# Anthropic beta-header token for the computer-use tool.
#
# Two SEPARATE versioning axes (do not conflate):
#   * tool SCHEMA version — ``computer_20251124`` (Nov 2025), the current
#     action set / params (ctx7 ``beta_tool_computer_use_20251124_param.py``:
#     display_width_px / display_height_px / display_number).
#   * feature-gate beta HEADER — ``computer-use-2025-01-24``, held stable by
#     Anthropic. ctx7 ``anthropic_beta_param.py`` is fresh to 2026-06 (carries
#     ``server-side-fallback-2026-06-01`` …) yet the ONLY computer-use strings
#     remain ``2024-10-22`` / ``2025-01-24`` — there is no ``computer-use-2026-*``.
#     So the low date is the CURRENT (only) gate, not a stale pick; it pairs
#     with the latest ``_20251124`` schema.
# Residual: the header↔schema pairing is strongly inferred (no paired ctx7
# example) → ``unverified — live test required`` (CLAUDE.md §4d). Safe to ship:
# computer-use never reached this LIVE path at all (it was wired only into the
# legacy ``ClaudeAgenticAdapter.agentic_call`` that PR-MAINPATH-67 deleted), so
# any working injection is strictly better than the current dead state, and a
# recognized-but-unneeded beta is a server-side no-op.
_COMPUTER_USE_BETA = "computer-use-2025-01-24"


def anthropic_computer_tool_param(display_width: int, display_height: int) -> dict[str, Any]:
    """Anthropic ``computer_20251124`` tool definition (ComputerUseCapable).

    ``display_number`` (X11) is omitted on the host path; the Xvfb sandbox
    (Phase E) sets it to the virtual display number.
    """
    return {
        "type": "computer_20251124",
        "name": "computer",
        "display_width_px": display_width,
        "display_height_px": display_height,
    }


def _maybe_inject_computer_use(kwargs: dict[str, Any]) -> None:
    """Inject the computer-use tool + beta header on the LIVE adapter path.

    Computer-use was wired only into the now-deleted legacy
    ``ClaudeAgenticAdapter.agentic_call`` (PR-MAINPATH-67, 2026-05-24 removed
    that branch), so it never reached production through ``build_*_kwargs`` —
    the model was never even offered the tool. This restores it on the live
    path. The tool is type-carrying so it is exempt from tool-search defer; it
    is appended here (not inside ``_shape_tools``) so it also injects when the
    request carries no registry tools.
    """
    from core.llm.providers.anthropic import is_computer_use_enabled

    if not is_computer_use_enabled():
        return
    tools = list(kwargs.get("tools") or [])
    if any(t.get("name") == "computer" for t in tools):
        return
    tools.append(anthropic_computer_tool_param(_COMPUTER_DISPLAY_WIDTH, _COMPUTER_DISPLAY_HEIGHT))
    kwargs["tools"] = tools
    # Merge the beta token (never clobber an existing anthropic-beta header).
    headers = dict(kwargs.get("extra_headers") or {})
    tokens = [t for t in headers.get("anthropic-beta", "").split(",") if t]
    if _COMPUTER_USE_BETA not in tokens:
        tokens.append(_COMPUTER_USE_BETA)
    headers["anthropic-beta"] = ",".join(tokens)
    kwargs["extra_headers"] = headers


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
        tc = _translate_tool_choice(req.tool_choice)
        kwargs["tools"] = _shape_tools(req, tc)
        if tc is not None:
            kwargs["tool_choice"] = tc
    if req.stop_sequences:
        kwargs["stop_sequences"] = list(req.stop_sequences)
    if req.thinking_budget > 0:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": req.thinking_budget}
    _maybe_inject_computer_use(kwargs)
    return kwargs


def _shape_tools(req: AdapterCallRequest, tc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Translate + apply hosted tool-search defer on the LIVE adapter path.

    PR-TOOL-SEARCH-WIRE Codex review finding 1 (2026-06-13): the defer
    shaping was first wired into the legacy ``ClaudeAgenticAdapter``
    request builder, but the production AgenticLoop reaches Anthropic
    through ``build_create_kwargs`` / ``build_stream_kwargs`` here — the
    exact docstring-vs-live-path class of bug this PR set out to fix.
    Shaping is skipped under a forced single-tool ``tool_choice`` (the
    official docs do not state that a forced DEFERRED tool resolves, so
    we do not gamble a 400 on it).
    """
    from core.config import settings as _settings
    from core.llm.providers.anthropic import apply_tool_search_defer

    translated = [translate_tool(t) for t in req.tools]
    if tc is not None and tc.get("type") == "tool":
        return translated
    return apply_tool_search_defer(
        translated, enabled=getattr(_settings, "tool_search_defer", True)
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
        tc = _translate_tool_choice(req.tool_choice)
        kwargs["tools"] = _shape_tools(req, tc)
        if tc is not None:
            kwargs["tool_choice"] = tc
    _maybe_inject_computer_use(kwargs)
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
    "anthropic_computer_tool_param",
    "build_async_anthropic_client",
    "build_create_kwargs",
    "build_messages",
    "build_stream_kwargs",
    "translate_response",
    "translate_tool",
]
