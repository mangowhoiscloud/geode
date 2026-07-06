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

import re
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


def build_async_anthropic_client(
    api_key: str = "", *, auth_token: str = ""
) -> anthropic.AsyncAnthropic:
    """Construct a fresh ``AsyncAnthropic`` bound to ``api_key`` or ``auth_token``.

    Each adapter owns its client — bypassing the module-level singleton in
    ``core.llm.providers.anthropic`` which is keyed solely by the first
    caller's resolved key. Same httpx limits/timeout/event-hooks as the
    singleton so the response-header banner pipeline keeps working.

    ``auth_token`` routes subscription OAuth tokens as ``Authorization:
    Bearer`` + the ``oauth-2025-04-20`` beta header — the Claude.ai OAuth
    access token is NOT an API key, and sending it as ``x-api-key`` returns
    401 ``invalid x-api-key`` (sub-claude track incident, 2026-07-05).
    """
    if bool(api_key) == bool(auth_token):
        raise ValueError("build_async_anthropic_client: exactly one of api_key/auth_token required")
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
    if auth_token:
        return anthropic.AsyncAnthropic(
            auth_token=auth_token,
            default_headers={"anthropic-beta": "oauth-2025-04-20"},
            max_retries=0,  # app-level retry handles this
            http_client=http_client,
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


# Computer-use tool generation — the (tool type, beta header) pair is
# MODEL-AWARE. Verified against the Anthropic docs (CANNOT §4d):
#   https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool
#   current  (Opus 4.8/4.7/4.6, Sonnet 4.6, Opus 4.5, + future): computer_20251124
#            + "computer-use-2025-11-24"
#   legacy   (Sonnet 4.5, Haiku 4.5, deprecated 4.1/4):          computer_20250124
#            + "computer-use-2025-01-24"
# Earlier this code shipped a single ``2025-01-24`` header for ALL models — wrong
# for the default Opus 4.8 (Codex review caught it). The SDK Literal lags
# ("computer-use-2025-11-24" is sent as a plain string); the docs page is SoT.
_COMPUTER_USE_CURRENT = ("computer_20251124", "computer-use-2025-11-24")
_COMPUTER_USE_LEGACY = ("computer_20250124", "computer-use-2025-01-24")
# Both native tool types — used for dedup (either generation counts as present).
_COMPUTER_USE_TYPES = frozenset({_COMPUTER_USE_CURRENT[0], _COMPUTER_USE_LEGACY[0]})


def _computer_use_spec(model: str) -> tuple[str, str]:
    """Return ``(tool_type, beta_header)`` for the model's computer-use generation.

    Legacy models are an explicit set; every other model (incl. future ones)
    defaults to the current generation so a new model tracks the newer beta.
    The dated GEODE id suffix (e.g. ``claude-haiku-4-5-20251001``,
    ``claude-sonnet-4-5-20250929``) is stripped before the lookup so dated
    legacy ids are not mistaken for current-gen models.
    """
    from core.llm.model_capabilities import ANTHROPIC_COMPUTER_USE_LEGACY_MODELS

    base = re.sub(r"-\d{8}$", "", model)  # strip trailing -YYYYMMDD
    if base in ANTHROPIC_COMPUTER_USE_LEGACY_MODELS:
        return _COMPUTER_USE_LEGACY
    return _COMPUTER_USE_CURRENT


def anthropic_computer_tool_param(
    display_width: int, display_height: int, tool_type: str = _COMPUTER_USE_CURRENT[0]
) -> dict[str, Any]:
    """Anthropic computer-use tool definition (ComputerUseCapable).

    ``tool_type`` is the model-aware schema version (``computer_20251124`` /
    ``computer_20250124``). ``display_number`` (X11) is always omitted: the GA
    tool infers geometry from the screenshots, and the Phase-E sandbox runs its
    OWN Xvfb display *inside the container* (the host harness is a thin HTTP
    client and never targets a display number — ``core.tools.computer_use``).
    """
    return {
        "type": tool_type,
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
    tool_type, beta = _computer_use_spec(kwargs.get("model", ""))
    tools = list(kwargs.get("tools") or [])
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
    # Always ensure the model's beta token when the native tool is present
    # (merge, never clobber an existing anthropic-beta header).
    headers = dict(kwargs.get("extra_headers") or {})
    tokens = [t for t in headers.get("anthropic-beta", "").split(",") if t]
    if beta not in tokens:
        tokens.append(beta)
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
