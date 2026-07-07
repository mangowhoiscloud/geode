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

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.llm.adapters.base import (
    AdapterCallRequest,
    AdapterCallResult,
    Message,
    ToolSpec,
    UsageSummary,
)
from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

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


def _catalog_context_window(model_id: str) -> int:
    """Read context windows from the central pricing/context catalogue."""
    return MODEL_CONTEXT_WINDOW[model_id]


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

    supports_tool_search: bool = False
    """True → model accepts ``{"type": "tool_search"}`` + ``defer_loading``
    on the Responses API ("only gpt-5.4 and later models support
    tool_search" — developers.openai.com/api/docs/guides/tools-tool-search).
    Default False so unknown/legacy models never gamble a 400."""


# Registry — keep alphabetically sorted within each family for stable diffs.
_OPENAI_MODELS: dict[str, OpenAIModelSpec] = {
    # ── GPT-5 family (reasoning, max_completion_tokens, temperature blocked) ──
    "gpt-5.3-codex": OpenAIModelSpec(
        model_id="gpt-5.3-codex",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5.3-codex"),
    ),
    "gpt-5.4": OpenAIModelSpec(
        model_id="gpt-5.4",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5.4"),
        supports_tool_search=True,
    ),
    "gpt-5.4-mini": OpenAIModelSpec(
        model_id="gpt-5.4-mini",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5.4-mini"),
        supports_tool_search=True,
    ),
    "gpt-5.4-nano": OpenAIModelSpec(
        model_id="gpt-5.4-nano",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5.4-nano"),
    ),
    "gpt-5.2": OpenAIModelSpec(
        model_id="gpt-5.2",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5.2"),
    ),
    "gpt-5.5": OpenAIModelSpec(
        model_id="gpt-5.5",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5.5"),
        supports_tool_search=True,
    ),
    "gpt-5-mini": OpenAIModelSpec(
        model_id="gpt-5-mini",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5-mini"),
    ),
    "gpt-5-nano": OpenAIModelSpec(
        model_id="gpt-5-nano",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("none", "low", "medium", "high", "xhigh"),
        context_window=_catalog_context_window("gpt-5-nano"),
    ),
    # ── o-series (always-on reasoning, no temperature, no "none" effort) ──
    "o3": OpenAIModelSpec(
        model_id="o3",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("low", "medium", "high"),
        context_window=_catalog_context_window("o3"),
    ),
    "o4-mini": OpenAIModelSpec(
        model_id="o4-mini",
        uses_max_completion_tokens=True,
        accepts_temperature=False,
        reasoning_effort_values=("low", "medium", "high"),
        context_window=_catalog_context_window("o4-mini"),
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

    _ensure_sdk_observability_installed()
    http_client = _build_async_httpx_client()
    # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28, Codex MCP BLOCKER) —
    # ``max_retries=0`` disables the SDK-internal retry loop. Without this,
    # SDK retry x app retry compounds: 300s read-timeout * 2 SDK attempts +
    # GEODE's own ``_LLM_RETRY_CAP`` retries = 10+ minute spin under stall.
    # Anthropic adapter applies the same invariant
    # (``_anthropic_common.py:60``). Single source of retry truth =
    # AgenticLoop's ``_call_llm`` retry path.
    if base_url:
        return openai.AsyncOpenAI(
            api_key=api_key, base_url=base_url, http_client=http_client, max_retries=0
        )
    return openai.AsyncOpenAI(api_key=api_key, http_client=http_client, max_retries=0)


def build_async_codex_client(api_key: str) -> openai.AsyncOpenAI:
    """Construct a fresh ``AsyncOpenAI`` bound to the Codex OAuth endpoint.

    Mirrors ``core.llm.providers.codex._get_async_codex_client`` (which uses a
    module-level singleton — the adapter must NOT reuse it, so we replicate
    the header + base_url plumbing here). The ``originator: codex_cli_rs``
    header and ``ChatGPT-Account-ID`` (extracted from the JWT) are mandatory
    — the Codex backend rejects unsigned requests with 401.

    PR-CODEX-NO-KEEPALIVE (2026-05-28) — the Codex backend
    (``chatgpt.com/backend-api/codex/responses``) closes idle HTTP/2
    connections aggressively (sub-second to a few-second window)
    without sending a GOAWAY frame the client can observe in time.
    First call after an idle period silently reuses a stale connection
    from httpx's keep-alive pool → ``httpx.WriteError`` → openai SDK
    ``APIConnectionError`` in ~4ms (no roundtrip). Observed pattern:
    4 parallel ``web_search`` calls right after a slower LLM call —
    first one fails instantly, next three open fresh connections and
    succeed (12-19s typical). Traced via PR-DISPATCH-OBS-EXT's
    ``adapter_dispatch_attempt`` events 2026-05-28 15:44:37 KST.

    Fix: this client overrides ``max_keepalive_connections=0`` so every
    Codex backend call opens a fresh TCP+TLS connection. Costs
    ~100-300ms TLS handshake per call but eliminates the stale-
    connection failure mode entirely. Other OpenAI-family endpoints
    (api.openai.com PAYG, api.z.ai GLM PAYG, GLM Coding Plan) keep the
    default keep-alive policy via :func:`_build_async_httpx_client` —
    they have proper server-side idle timeout policies + GOAWAY signaling.
    """
    if not api_key:
        raise ValueError("build_async_codex_client: api_key is empty")
    import httpx
    import openai

    from core.config import CODEX_BASE_URL, settings
    from core.llm.adapters._codex_sdk_workaround import install as _install_codex_workaround
    from core.llm.providers.codex import build_codex_oauth_headers

    # PR-CODEX-OUTPUT-NULL (2026-05-28) — install the SDK parse_response
    # workaround before the first Codex backend call. Idempotent across
    # process lifetime; only patches when the openai SDK is importable.
    _install_codex_workaround()
    _ensure_sdk_observability_installed()

    # PR-CODEX-NO-KEEPALIVE (2026-05-28) — Codex-specific httpx client
    # with ``max_keepalive_connections=0`` (see method docstring for the
    # stale-connection rationale). Other timeout / pool settings mirror
    # :func:`_build_async_httpx_client` so operators tune both with the
    # same ``settings.llm_*`` knobs.
    codex_http_client = httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.llm_max_connections,
            max_keepalive_connections=0,
            keepalive_expiry=settings.llm_keepalive_expiry,
        ),
        timeout=httpx.Timeout(
            connect=settings.llm_connect_timeout,
            read=settings.llm_read_timeout,
            write=settings.llm_write_timeout,
            pool=settings.llm_pool_timeout,
        ),
    )

    return openai.AsyncOpenAI(
        api_key=api_key,
        base_url=CODEX_BASE_URL,
        default_headers=build_codex_oauth_headers(api_key),
        http_client=codex_http_client,
        # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION — see ``build_async_openai_client``
        # for the retry-compound rationale (Codex MCP BLOCKER 2026-05-28).
        max_retries=0,
    )


def _ensure_sdk_observability_installed() -> None:
    """Install the SDK retry → UI bridge once. Safe to call repeatedly."""
    from core.llm.adapters._sdk_retry_visibility import install as _install_retry_bridge

    _install_retry_bridge()


def _build_async_httpx_client() -> Any:
    """PR-ADAPTER-TIMEOUT (2026-05-28) — share Anthropic adapter's timeout
    policy with every OpenAI-family client (PAYG OpenAI, Codex OAuth, GLM
    PAYG, GLM Coding Plan).

    Without an explicit ``http_client``, ``AsyncOpenAI`` uses the SDK's
    default httpx instance whose read-timeout defaults are long enough that
    a stalled ``responses.stream`` on the Codex backend silently waited
    ~10 minutes before the SDK's retry loop kicked in (operator-observed
    incident 2026-05-28 11:06→11:16, 620062 ms latency). Pinning
    ``settings.llm_read_timeout`` here caps the stall window — the
    SDK's ``max_retries`` (default 2) then triggers within minutes
    instead of hours.

    Reads the same ``llm_*_timeout`` / ``llm_*_connections`` settings the
    Anthropic adapter consumes so operators tune both providers with one
    knob (``config.toml [llm]`` or ``GEODE_LLM_READ_TIMEOUT``).
    """
    import httpx

    from core.config import settings

    return httpx.AsyncClient(
        limits=httpx.Limits(
            max_connections=settings.llm_max_connections,
            max_keepalive_connections=settings.llm_max_keepalive_connections,
            keepalive_expiry=settings.llm_keepalive_expiry,
        ),
        timeout=httpx.Timeout(
            connect=settings.llm_connect_timeout,
            read=settings.llm_read_timeout,
            write=settings.llm_write_timeout,
            pool=settings.llm_pool_timeout,
        ),
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

    Official Responses API state management: when an assistant
    :class:`Message` carries ``codex_output_items`` copied from a prior
    ``response.output``, those output items are replayed directly. This keeps
    reasoning, message, and function_call output items in the same structure
    the API returned.

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
    disable_output_replay = os.environ.get(
        "GEODE_CODEX_DISABLE_OUTPUT_REPLAY", ""
    ).strip().lower() in {"1", "true", "yes", "on"}
    for m in req.messages:
        if m.role == "assistant":
            if m.codex_output_items and not disable_output_replay:
                out.extend(_responses_input_safe_output_item(item) for item in m.codex_output_items)
                continue
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
            out.extend(_convert_assistant_msg_to_responses(m.content, phase=m.phase))
            continue
        if m.role == "user":
            out.extend(_convert_user_msg_to_responses(m.content))
            continue
        out.append({"role": m.role, "content": _stringify(m.content)})
    return out


# ---------------------------------------------------------------------------
# Computer-use tool (OpenAI Responses API, GA `{type: "computer"}`)
# ---------------------------------------------------------------------------
# OpenAI computer-use went GA on the Responses API with model ``gpt-5.5`` and
# the BARE request tool shape ``{type: "computer"}``. The GA tool takes NO
# params — display geometry is inferred from the screenshots the agent returns.
# ``display_width`` / ``display_height`` / ``environment`` belong to the
# deprecated PREVIEW tool (``{type: "computer_use_preview"}`` on the
# ``computer-use-preview`` model); the SDK keeps them as distinct union members
# (``ComputerToolParam`` vs ``ComputerUsePreviewToolParam``). We emit GA only.
#
# ref: ctx7 ``/websites/developers_openai_api`` guides/tools-computer-use
# (verified 2026-06-17). ctx7 confirms the SDK/API CONTRACT; backend ACCEPTANCE
# was then live-verified per-backend (2026-06-17 operator-authorized E2E): the
# OpenAI Platform (PAYG) backend ACCEPTS GEODE's request (full round-trip), while
# the ChatGPT-subscription Codex backend REJECTS it (400) and is excluded.
#
# GA gate: only models in this frozenset get the tool. A non-GA OpenAI model
# (e.g. gpt-5.4) must never be offered ``{type: "computer"}`` — the backend
# rejects it, and the preview shape is deliberately out of scope.
_OPENAI_COMPUTER_USE_GA_MODELS: frozenset[str] = frozenset({"gpt-5.5"})


def openai_computer_tool_param() -> dict[str, Any]:
    """OpenAI Responses GA computer-use tool definition (ComputerUseCapable).

    Returns the BARE GA tool ``{"type": "computer"}``. The GA tool takes no
    parameters — the display geometry is inferred from the screenshots the
    agent sends back, NOT declared on the tool. ``display_width`` /
    ``display_height`` / ``environment`` belong to the deprecated PREVIEW tool
    (``{"type": "computer_use_preview"}``); emitting them on the GA tool is
    rejected. The SDK reflects this split — ``ComputerToolParam`` (GA) vs
    ``ComputerUsePreviewToolParam`` (preview) are distinct union members.

    # ref: ctx7 /websites/developers_openai_api guides/tools-computer-use
    #      (GA migration table: tools=[{type:"computer"}], dims/env preview-only)
    #      + openai-python ComputerToolParam
    # backend acceptance: platform live-verified 2026-06-17 (codex rejects)
    """
    return {"type": "computer"}


def _maybe_inject_openai_computer_use(kwargs: dict[str, Any], *, model: str, backend: str) -> None:
    """Inject the OpenAI GA computer-use tool on the LIVE Responses path.

    Mirrors ``_anthropic_common._maybe_inject_computer_use`` (Phase A) for the
    OpenAI Responses API (Phase C). Returns early unless computer-use is enabled
    (``core.llm.providers.anthropic.is_computer_use_enabled`` — the provider-
    agnostic opt-in + pyautogui guard, shared so both providers gate on one
    SoT), ``backend`` is the platform (PAYG) endpoint, AND ``model`` is
    GA-capable (``_OPENAI_COMPUTER_USE_GA_MODELS``). The tool is appended to
    ``kwargs["tools"]`` (creating the list when the request carried no registry
    tools — injection is not gated on ``req.tools``).

    Backend gating (2026-06-17 live E2E, operator-authorized):

    - ``backend="codex"`` — the ChatGPT-subscription Codex endpoint
      live-REJECTS the computer tool with ``400 Unsupported tool type:
      computer``. The ctx7 GA docs describe the OpenAI *Platform* API, not the
      Codex subscription backend (same ambiguity class as PR-NO-FALLBACK
      #1839's web_search). NEVER inject — proven reject.
    - ``backend="platform"`` — the documented GA surface, now **live-verified**
      (2026-06-17, operator-authorized): the OpenAI Platform (PAYG) backend
      ACCEPTS ``{type:"computer"}`` on gpt-5.5, the model emits a
      ``computer_call``, and a full screenshot round-trip completes (gpt-5.5
      read real on-screen pixels back from the ``computer_call_output``). ctx7
      confirms the contract; the live test confirms backend acceptance. INJECT.

    Idempotent: dedup by ``t.get("type") == "computer"`` so re-entrancy never
    doubles it. The OpenAI Responses API has no per-tool beta header (unlike
    Anthropic's ``anthropic-beta`` token), so none is set.
    """
    from core.llm.providers.anthropic import is_computer_use_enabled

    if not is_computer_use_enabled():
        return
    if backend == "codex":
        # ChatGPT-subscription Codex backend proven-rejects {type:"computer"}
        # with 400 ``Unsupported tool type: computer`` (2026-06-17 live E2E).
        # ctx7 GA docs are Platform-only. Never inject on this backend.
        return
    base = re.sub(r"-\d{8}$", "", model)  # strip a dated id suffix, if any
    if base not in _OPENAI_COMPUTER_USE_GA_MODELS:
        # Non-GA OpenAI model — the GA ``{type: "computer"}`` tool would be
        # rejected, and the preview shape is out of scope. Never inject.
        return
    tools = list(kwargs.get("tools") or [])
    if not any(isinstance(t, dict) and t.get("type") == "computer" for t in tools):
        tools.append(openai_computer_tool_param())
        kwargs["tools"] = tools


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


def _convert_assistant_msg_to_responses(
    content: Any,
    *,
    phase: str = "",
) -> list[dict[str, Any]]:
    """Anthropic assistant content → Responses API typed items.

    Splits text + tool_use into separate items (text becomes
    ``{"role": "assistant", "content": ...}``, tool_use becomes
    ``{"type": "function_call", "call_id", "name", "arguments"}``) preserving
    the original ordering so the next-turn pairing with ``function_call_output``
    matches by ``call_id``.

    ``phase`` (PR-CODEX-MULTITURN-PHASE-PRESERVE, Sprint H follow-up,
    2026-05-26): when non-empty, attached to each text-bearing
    ``{role: "assistant", ...}`` item so the OpenAI Responses API
    ``EasyInputMessageParam.phase`` slot is populated. Empty (the
    default) skips the field — back-compat with every non-Codex caller.
    """
    if isinstance(content, str):
        out: dict[str, Any] = {"role": "assistant", "content": content}
        if phase:
            out["phase"] = phase
        return [out]
    if not isinstance(content, list):
        out = {"role": "assistant", "content": _stringify(content)}
        if phase:
            out["phase"] = phase
        return [out]
    items: list[dict[str, Any]] = []
    text_parts: list[str] = []

    def _emit_text_item() -> None:
        out = {"role": "assistant", "content": "\n".join(text_parts)}
        if phase:
            out["phase"] = phase
        items.append(out)

    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            text_parts.append(block.get("text", ""))
        elif btype == "tool_use":
            if text_parts:
                _emit_text_item()
                text_parts = []
            if block.get("name") == "computer":
                # GA computer-use replay: the prior assistant turn's
                # ``computer_call`` MUST be re-emitted as ``computer_call`` (NOT
                # ``function_call``) so it pairs with the next-turn
                # ``computer_call_output`` by ``call_id``. Replaying it as a
                # function_call leaves the computer_call_output unpaired (the
                # half-wired failure Phase A fixed for Anthropic). The stored
                # ``input`` dict carries ``actions[]`` (+ optional
                # ``pending_safety_checks``) from ``_normalize_computer_call``.
                # backend acceptance: platform live-verified 2026-06-17 (codex rejects)
                cinput = block.get("input")
                cinput = cinput if isinstance(cinput, dict) else {}
                computer_call: dict[str, Any] = {
                    "type": "computer_call",
                    "call_id": block.get("id", ""),
                    "actions": cinput.get("actions", []),
                }
                if cinput.get("pending_safety_checks"):
                    computer_call["pending_safety_checks"] = cinput["pending_safety_checks"]
                items.append(computer_call)
            else:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": block.get("id", ""),
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {}), ensure_ascii=False),
                    }
                )
    if text_parts:
        _emit_text_item()
    if items:
        return items
    fallback = {"role": "assistant", "content": ""}
    if phase:
        fallback["phase"] = phase
    return [fallback]


def _maybe_computer_call_output(block: dict[str, Any]) -> dict[str, Any] | None:
    """If a ``tool_result`` block carries a computer-use screenshot, return the
    OpenAI Responses GA ``computer_call_output`` item; otherwise ``None``.

    The computer harness is the ONLY tool whose ``tool_result.content`` is a
    content-block LIST holding a base64 ``image`` block
    (``core.agent.tool_executor.processor._serialize_computer_result``), so that
    shape is a reliable, name-free signal at INPUT-build time (the tool name is
    not carried on the ``tool_result`` block). Ordinary tools keep their
    ``function_call_output`` shape.

    Per the GA contract the output object is ``{"type": "computer_screenshot",
    "image_url": <url>}``. The harness encodes JPEG, so the base64 data is
    wrapped as a ``data:image/jpeg;base64,...`` data URL for ``image_url``. Any
    safety checks acknowledged on the originating ``tool_result`` (carried via
    the meta text block as ``acknowledged_safety_checks``) are echoed back so
    the backend's ``pending_safety_checks`` are cleared.

    # ref: ctx7 /websites/developers_openai_api guides/tools-computer-use
    # backend acceptance: platform live-verified 2026-06-17 (codex rejects)
    """
    raw = block.get("content")
    if not isinstance(raw, list):
        return None
    image_data: str | None = None
    media_type = "image/jpeg"  # harness encodes JPEG (computer_use.screenshot)
    acknowledged: Any = None
    for part in raw:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "image":
            source = part.get("source")
            if isinstance(source, dict) and source.get("type") == "base64" and source.get("data"):
                image_data = str(source["data"])
                media_type = str(source.get("media_type") or media_type)
        elif part.get("type") == "text":
            # The meta text block is JSON of the non-screenshot harness fields;
            # surface any acknowledged safety checks the agent echoed back.
            try:
                meta = json.loads(part.get("text") or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                meta = {}
            if isinstance(meta, dict) and meta.get("acknowledged_safety_checks"):
                acknowledged = meta["acknowledged_safety_checks"]
    if image_data is None:
        return None
    output_item: dict[str, Any] = {
        "type": "computer_call_output",
        "call_id": block.get("tool_use_id", ""),
        "output": {
            "type": "computer_screenshot",
            "image_url": f"data:{media_type};base64,{image_data}",
        },
    }
    if acknowledged:
        output_item["acknowledged_safety_checks"] = acknowledged
    return output_item


def _convert_user_msg_to_responses(content: Any) -> list[dict[str, Any]]:
    """Anthropic user content → Responses API typed items.

    ``tool_result`` blocks become ``{"type": "function_call_output",
    "call_id", "output"}`` items — EXCEPT a computer-use screenshot result,
    which becomes a ``{"type": "computer_call_output", ...}`` item carrying a
    ``computer_screenshot`` (see :func:`_maybe_computer_call_output`). Text
    blocks aggregate into a follow-up ``{"role": "user", "content": ...}`` entry.
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
            computer_output = _maybe_computer_call_output(block)
            if computer_output is not None:
                items.append(computer_output)
                continue
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
    # GLM / OpenAI Chat Completions report the cached-prefix hit under
    # ``usage.prompt_tokens_details.cached_tokens`` (a subset of prompt_tokens).
    # Surface it so the cached-input discount is applied; cost math subtracts it
    # from the billable input (cache_inclusive_input). Previously dropped, so
    # GLM cached tokens were billed at the full input rate.
    cached_tokens = 0
    if usage is not None:
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = int(getattr(prompt_details, "cached_tokens", 0) or 0)
    return AdapterCallResult(
        text=text,
        usage=UsageSummary(
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            cached_input_tokens=cached_tokens,
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
    # PR-CODEX-MULTITURN-PHASE-PRESERVE (Sprint H follow-up, 2026-05-26)
    # — capture per-response ``phase`` attribution from the Codex
    # message item. ``ResponseOutputMessage.phase`` is
    # ``Optional[Literal["commentary", "final_answer"]]`` and appears
    # symmetrically on ``EasyInputMessageParam`` so the replay path
    # can carry the semantic attribution. Multiple message items per
    # response are rare; LAST one wins (matches the last-message-wins
    # shape of ``response.output_text``).
    assistant_phase: str = ""
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
        if itype == "message":
            # Capture phase regardless of whether ``text`` was already
            # populated by ``response.output_text`` — phase lives on
            # the item, not on the aggregated text accessor.
            phase_value = _attr_or_key(item, "phase")
            if isinstance(phase_value, str) and phase_value:
                assistant_phase = phase_value
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
        elif itype == "computer_call":
            # OpenAI Responses GA computer-use (Phase C). The GA ``computer_call``
            # carries a BATCHED ``actions[]`` array (the preview used a single
            # ``action`` object) correlated by ``call_id`` — the next-turn
            # ``computer_call_output`` MUST reference this same ``call_id`` (the
            # ``id`` is server-internal, unstable under ``store=False``; same
            # constraint as ``function_call``). We map it onto the uniform
            # GEODE tool-call shape for the local ``computer`` tool: ``input`` is
            # a DICT (``translation.py`` passes dict inputs straight through to
            # the handler's kwargs) carrying ``actions`` (a list, even if the
            # backend ever sends a single ``action`` we wrap it) plus any
            # ``pending_safety_checks`` so the handler can iterate and the
            # next-turn output can acknowledge them.
            # ref: ctx7 /websites/developers_openai_api guides/tools-computer-use
            # backend acceptance: platform live-verified 2026-06-17 (codex rejects)
            tool_uses.append(_normalize_computer_call(item))
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
            # PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28) — the OpenAI
            # SDK returns ``summary`` as a list of ``ResponseReasoningItem.
            # Summary`` Pydantic objects. Storing them verbatim in
            # ``entry["summary"]`` propagates the SDK type all the way into
            # ``AgenticResponse.codex_reasoning_items`` and then into the
            # SQLite session mirror, which fails with
            # ``TypeError: Object of type Summary is not JSON serializable``
            # (operator log 2026-05-28 11:16:39 — session_manager.py:433).
            # JSON checkpoint survived (separate writer), but per-turn
            # message mirror was lost. Normalise to plain ``dict``
            # (``{"type": "summary_text", "text": ...}``) so downstream
            # persistence sees only JSON-safe primitives.
            entry["summary"] = _normalize_summary_list(summary)
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
    # Codex review of PR-OPENAI-RESPONSES (2026-06-13): Responses reports
    # prompt-cache hits under ``input_tokens_details.cached_tokens`` —
    # dropping it under-reported cache reads/cost on BOTH backends (the
    # codex path had always dropped it). Same path the legacy normalizer
    # reads in ``core/llm/agentic_response.py``.
    cached_tokens = 0
    if usage is not None:
        input_details = getattr(usage, "input_tokens_details", None)
        cached_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)
    return AdapterCallResult(
        text=text,
        usage=UsageSummary(
            input_tokens=getattr(usage, "input_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "output_tokens", 0) if usage else 0,
            cached_input_tokens=cached_tokens,
        ),
        stop_reason=getattr(response, "status", "completed") or "completed",
        tool_uses=tuple(tool_uses),
        raw_response=response,
        reasoning_items=tuple(reasoning_items),
        reasoning_summaries=tuple(reasoning_summaries),
        codex_output_items=tuple(_json_safe(item) for item in items_source),
        assistant_phase=assistant_phase,
    )


def _normalize_summary_list(summary: Any) -> list[dict[str, Any]]:
    """PR-ADAPTER-TIMEOUT-AND-SERIALIZATION (2026-05-28) — convert OpenAI
    SDK ``Summary`` Pydantic objects (or dicts, or unknown) to a list of
    plain ``{"type": "summary_text", "text": ...}`` dicts so the result
    is JSON-serialisable downstream (SQLite session mirror, JSON
    checkpoint, IPC payload).

    Returns ``[]`` for missing / falsy input — matches the original
    ``summary if summary else []`` shape so the Responses API replay
    (``build_codex_input``) keeps accepting it.
    """
    if not summary or not isinstance(summary, list):
        return []
    out: list[dict[str, Any]] = []
    for item in summary:
        if isinstance(item, dict):
            out.append(dict(item))
            continue
        # Pydantic v2 SDK object — prefer ``model_dump(mode="json")`` so
        # nested types (e.g. datetime, IntEnum) also coerce to JSON-safe
        # primitives. Fall back to plain ``model_dump()`` if a future SDK
        # variant doesn't accept the kwarg, and finally to manual
        # ``.text`` / ``.type`` extraction. Codex MCP review (2026-05-28).
        dump = getattr(item, "model_dump", None)
        if callable(dump):
            dumped: dict[str, Any] | None = None
            for kwargs in ({"mode": "json"}, {}):
                try:
                    dumped = dict(dump(**kwargs))
                    break
                except Exception as exc:
                    log.debug("Summary.model_dump(%r) failed: %s", kwargs, exc)
            if dumped is not None:
                out.append(dumped)
                continue
        text = getattr(item, "text", "") or ""
        kind = getattr(item, "type", "summary_text") or "summary_text"
        out.append({"type": str(kind), "text": str(text)})
    return out


def _json_safe(value: Any) -> Any:
    """Coerce an OpenAI SDK object (or nested list/dict) to JSON-safe
    primitives so a parsed item survives the IPC / SQLite session mirror
    downstream (same hazard the reasoning ``Summary`` normalisation guards).

    Pydantic v2 objects expose ``model_dump(mode="json")``; lists/dicts are
    recursed; everything else passes through unchanged.
    """
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        for kwargs in ({"mode": "json"}, {}):
            try:
                return _json_safe(dict(dump(**kwargs)))
            except Exception as exc:
                log.debug("%s.model_dump(%r) failed: %s", type(value).__name__, kwargs, exc)
    raw_dict = getattr(value, "__dict__", None)
    if isinstance(raw_dict, dict):
        return {k: _json_safe(v) for k, v in raw_dict.items() if not k.startswith("_")}
    return value


def _responses_input_safe_output_item(item: dict[str, Any]) -> dict[str, Any]:
    """Return a prior Responses output item in the shape Codex accepts as input.

    OpenAI documents manual context management as passing prior ``response.output``
    items into the next ``input`` array. The Codex subscription validator rejects
    top-level ``status`` on replayed reasoning items, even though that field is
    populated on API-returned output items. Preserve the semantic payload and
    item ids, but drop return-only lifecycle metadata before sending it back.
    """
    safe = _json_safe(dict(item))
    if isinstance(safe, dict):
        return {k: v for k, v in safe.items() if k != "status" and v is not None}
    return dict(item)


def _normalize_computer_call(item: Any) -> dict[str, Any]:
    """OpenAI Responses GA ``computer_call`` typed item → uniform GEODE
    tool-call dict for the local ``computer`` tool.

    The GA ``computer_call`` carries ``call_id`` + a BATCHED ``actions[]``
    array (the preview used a single ``action`` object) + optional
    ``pending_safety_checks``. ``input`` is emitted as a DICT (``translation.py``
    passes dict tool inputs straight through to the handler kwargs) so the
    handler receives ``{"actions": [...], "pending_safety_checks": [...]}`` and
    can iterate the batch + acknowledge the safety checks in the next-turn
    ``computer_call_output``. A lone ``action`` (defensive — should not occur on
    GA) is wrapped into a single-element ``actions`` list so the handler's batch
    path is the only code path.

    SDK objects are coerced to JSON-safe primitives (``_json_safe``) so the
    payload survives the session mirror / IPC downstream.

    # ref: ctx7 /websites/developers_openai_api guides/tools-computer-use
    # backend acceptance: platform live-verified 2026-06-17 (codex rejects)
    """
    actions = _attr_or_key(item, "actions")
    if actions is None:
        # Defensive: a single ``action`` (preview shape / partial SDK) → wrap.
        single = _attr_or_key(item, "action")
        actions = [single] if single is not None else []
    if not isinstance(actions, (list, tuple)):
        actions = [actions]
    tool_input: dict[str, Any] = {"actions": _json_safe(list(actions))}
    safety = _attr_or_key(item, "pending_safety_checks")
    if safety:
        tool_input["pending_safety_checks"] = _json_safe(safety)
    return {
        "id": _attr_or_key(item, "call_id") or _attr_or_key(item, "id"),
        "name": "computer",
        "input": tool_input,
    }


def _apply_openai_tool_search_defer(
    tools: list[dict[str, Any]],
    *,
    backend: str,
    spec: OpenAIModelSpec,
    adapter_name: str,
) -> list[dict[str, Any]]:
    """OpenAI Responses deferred tool loading — official mechanism.

    Marks non-core function tools with the official ``defer_loading: true``
    field and appends the hosted ``{"type": "tool_search"}`` tool, mirroring
    the Anthropic wiring (policy SoT: ``core.llm.tool_defer``).
    ref: https://developers.openai.com/api/docs/guides/tools-tool-search
    (Responses-only; "only gpt-5.4 and later models support tool_search").

    Backend gating:

    - ``platform`` — documented supported; enabled by
      ``settings.tool_search_defer`` (same kill switch as Anthropic).
    - ``codex`` — the docs cover the platform API only (same ambiguity
      class as PR-NO-FALLBACK #1839), so Codex backend acceptance was
      gated on a live call: verified 2026-06-13 (20 deferred defs +
      tool_search on gpt-5.5 → normal completion). Kill switch:
      ``settings.tool_search_defer_codex`` (default True post-gate).

    Never defers: the model lacks ``supports_tool_search``, hosted entries
    (anything whose ``type`` is not ``"function"``), the always-loaded core
    set, and names in ``OPENAI_DEFER_NAME_BLOCKLIST`` (upstream 500 when a
    deferred function named "web" rides with tool_search + web_search).
    Idempotent: already-shaped input passes through unchanged.
    """
    from core.config import settings as _settings
    from core.llm.tool_defer import (
        OPENAI_DEFER_NAME_BLOCKLIST,
        TOOL_DEFER_THRESHOLD,
        TOOL_SEARCH_ALWAYS_LOADED,
    )

    if not spec.supports_tool_search or len(tools) <= TOOL_DEFER_THRESHOLD:
        return tools
    if backend == "codex":
        if not getattr(_settings, "tool_search_defer_codex", False):
            return tools
    elif not getattr(_settings, "tool_search_defer", True):
        return tools
    if any(t.get("type") == "tool_search" or t.get("defer_loading") for t in tools):
        return tools  # already shaped — idempotent pass-through
    shaped: list[dict[str, Any]] = []
    deferred_count = 0
    for tool in tools:
        name = str(tool.get("name", ""))
        if (
            tool.get("type") != "function"
            or name in TOOL_SEARCH_ALWAYS_LOADED
            or name in OPENAI_DEFER_NAME_BLOCKLIST
        ):
            shaped.append(tool)
            continue
        deferred_tool = dict(tool)
        deferred_tool["defer_loading"] = True
        shaped.append(deferred_tool)
        deferred_count += 1
    if not deferred_count:
        return tools
    log.info(
        "%s: openai tool_search defer active — %d/%d tool defs deferred",
        adapter_name,
        deferred_count,
        len(shaped) + 1,
    )
    return [*shaped, {"type": "tool_search"}]


def _prompt_cache_key(system_prompt: str) -> str:
    """Stable OpenAI ``prompt_cache_key`` derived from the static system prefix.

    OpenAI routes same-``prompt_cache_key`` traffic onto the same cache machine
    (combined with the prefix hash), improving cache-hit rate for requests that
    share a common prefix. We key on the STATIC system prefix — everything
    before ``<dynamic_context>`` — so the key is byte-stable across a session's
    turns (the dynamic suffix: date / recalled memory / user context changes per
    turn and must not perturb the routing key). Returns ``""`` when there is no
    system prompt (nothing to group on).

    Accepted on both surfaces: the platform Responses API (openai 2.30.0 exposes
    ``prompt_cache_key``) and the Codex subscription backend — live-verified
    2026-06-23: a streamed ``responses.stream`` call carrying the param returned
    200 + usage. That live call was the gate (PR-NO-FALLBACK rule) because the
    Codex backend is reverse-engineered and its parameter acceptance is
    undocumented (the same backend 400s on ``max_output_tokens``).
    """
    if not system_prompt:
        return ""
    from core.agent.system_prompt import PROMPT_CACHE_BOUNDARY

    static = system_prompt.split(PROMPT_CACHE_BOUNDARY, 1)[0]
    digest = hashlib.sha256(static.encode("utf-8")).hexdigest()[:16]
    return f"geode-{digest}"


def build_responses_kwargs(
    req: AdapterCallRequest, *, backend: str, adapter_name: str
) -> dict[str, Any]:
    """Shared OpenAI Responses API kwargs — platform (openai-payg) + Codex backends.

    PR-OPENAI-RESPONSES (2026-06-13): extracted from codex_oauth's
    ``_build_codex_call_kwargs`` so openai-payg's ``acomplete``/``astream``
    leave Chat Completions and join the Responses surface this module's
    ``acomplete_text``/``aweb_search`` already use (Responses is OpenAI's
    forward-going API; new features such as tool_search are Responses-only).

    Backend deltas:

    - ``backend="codex"`` — ``max_output_tokens`` FORBIDDEN (Subscription
      manages it server-side; sending it returns 400).
    - ``backend="platform"`` — ``max_output_tokens`` supported and sent
      from ``req.max_tokens``.
    - ``store=False`` on both (stateless requests; reasoning replays inline).

    Naming debt (deliberate, scheduled for a cleanup PR): the helpers
    ``build_codex_input`` / ``translate_tool_for_codex`` keep their codex-
    prefixed names although the platform backend now shares them — the
    rename touches a 12-file radius that does not belong in a migration
    diff.

    Critical Codex backend constraints (from
    ``docs/research/codex-oauth-request-spec.md``):

    - ``instructions`` carries the system prompt (not ``input[].role:system``)
    - ``input`` is the user/assistant/tool array — built via
      :func:`build_codex_input` which re-encodes Anthropic content blocks
      into Codex typed items (``function_call`` / ``function_call_output``)
    - ``store=False`` is mandatory
    - ``max_output_tokens`` is FORBIDDEN — Subscription manages it
      server-side, sending the field returns 400
    - Tools use the FLAT shape (``translate_tool_for_codex``)
    - Reasoning models (per
      :func:`core.llm.adapters._openai_common.get_openai_model_spec`)
      omit ``temperature`` and add ``reasoning`` + ``include:
      ["reasoning.encrypted_content"]``
    - Official Responses state management: previous-turn ``response.output``
      items replay inline via :func:`build_codex_input` when an assistant
      :class:`Message` carries ``codex_output_items``. Legacy
      ``codex_reasoning_items`` replay remains as a fallback for transcripts
      created before full output-item capture.
    - PR-DRIFT-CUT (2026-05-24): replaced ``req.model.startswith("gpt-5")``
      heuristic with explicit registry lookup so o3 / o4-mini / new
      reasoning models go through the same branch automatically.
    """
    spec = get_openai_model_spec(req.model)
    resp_input = build_codex_input(req)
    kwargs: dict[str, Any] = {
        "model": req.model,
        "instructions": req.system_prompt or "Mode: general assistance.",
        "input": resp_input or [{"role": "user", "content": "hello"}],
        "store": False,
    }
    # OpenAI ``prompt_cache_key`` — cache-routing hint on both backends (each
    # verified: platform documented + openai 2.30.0 SDK, Codex live-2026-06-23).
    # Keyed on the static system prefix so it stays stable across a session's
    # turns. Kill switch: settings.prompt_cache_key_enabled.
    from core.config import settings as _settings

    if getattr(_settings, "prompt_cache_key_enabled", True):
        cache_key = _prompt_cache_key(req.system_prompt)
        if cache_key:
            kwargs["prompt_cache_key"] = cache_key
    if backend == "platform":
        kwargs["max_output_tokens"] = req.max_tokens
    if req.stop_sequences:
        # Responses API exposes no ``stop`` parameter (Chat Completions
        # did). Observable drop instead of a silent one — Codex review of
        # PR-OPENAI-RESPONSES, finding 2.
        log.warning(
            "%s: stop_sequences unsupported on the Responses API — ignoring %d entr%s",
            adapter_name,
            len(req.stop_sequences),
            "y" if len(req.stop_sequences) == 1 else "ies",
        )
    if req.tools:
        translated = [translate_tool_for_codex(t) for t in req.tools]
        capped = cap_tools(translated, model=req.model, adapter_name=adapter_name)
        kwargs["tools"] = _apply_openai_tool_search_defer(
            capped, backend=backend, spec=spec, adapter_name=adapter_name
        )
        kwargs["tool_choice"] = translate_responses_tool_choice(req.tool_choice)
        kwargs["parallel_tool_calls"] = True
    # Computer-use (Phase C) — injected AFTER the tools assembly so the GA
    # ``{type: "computer"}`` tool reaches the model even when ``req.tools`` is
    # empty (it creates the list). Gated on the opt-in + a GA-capable model +
    # the platform backend (the codex subscription backend proven-rejects it).
    _maybe_inject_openai_computer_use(kwargs, model=req.model, backend=backend)
    if spec.reasoning_effort_values is not None:
        # Reasoning-model branch — encrypted reasoning passthrough +
        # reasoning effort. Temperature is dropped per spec.
        kwargs["include"] = ["reasoning.encrypted_content"]
        kwargs["reasoning"] = {"effort": req.effort, "summary": "auto"}
    elif req.temperature is not None and spec.accepts_temperature:
        kwargs["temperature"] = req.temperature
    # PR-CODEX-OAUTH-RESPONSE-SCHEMA (2026-05-25) — Responses API
    # structured-output enforcement. PR-JSON-WIRE (#79) routed
    # ``req.response_schema`` through claude-cli (--json-schema) and
    # codex-cli (--output-schema <FILE>) but silently dropped the
    # codex-oauth path. Without API-level schema enforcement, gpt-5.x
    # reasoning models can return ``stop_reason=completed`` with the
    # entire output budget spent on encrypted reasoning items + empty
    # ``output_text`` (smoke 17: 20+ codex-oauth-empty-text dumps,
    # ~10 per match). Adding ``text.format = {type:"json_schema", ...}``
    # forwards the schema for server-side enforcement. Spec: OpenAI
    # Responses API ``text.format`` (replaces Chat Completions
    # ``response_format``).
    #
    # Codex MCP review of PR #1687: ``strict: True`` requires the schema
    # to satisfy OpenAI's Structured Outputs subset (all object schemas
    # set ``additionalProperties: false`` AND every property listed in
    # ``required``). GEODE's seed-generation schemas in
    # ``plugins/seed_generation/json_schemas.py`` intentionally use the
    # additive helper that omits both, so unconditional strict=True would
    # cause the server to **reject the request** (400) before generation
    # — a worse retry storm than the empty-text path. Auto-detect strict
    # compatibility per schema and fall through to ``strict: False`` for
    # non-compatible schemas (still forwards the shape as a strong hint,
    # but server treats it as informational rather than gated).
    if req.response_schema is not None:
        schema_name = str(req.response_schema.get("title") or "response")
        kwargs["text"] = {
            "format": {
                "type": "json_schema",
                "name": schema_name,
                "strict": _is_openai_strict_compatible(req.response_schema),
                "schema": req.response_schema,
            }
        }
    return kwargs


def _is_openai_strict_compatible(schema: Any) -> bool:
    """Check whether ``schema`` satisfies OpenAI's strict Structured Outputs subset.

    Provider-specific (OpenAI Responses API only). Do NOT reuse from
    other adapters without verifying the target API's subset rules —
    Anthropic Structured Outputs (Claude API) shares the
    ``additionalProperties: false`` constraint but DIVERGES on:

    - ``required`` completeness: OpenAI requires every property key to
      appear in ``required``; Anthropic allows up to 24 optional
      properties.
    - ``oneOf``: OpenAI supports; Anthropic does not.
    - Numerical / string constraints (``minimum`` / ``maxLength`` …):
      OpenAI supports; Anthropic does not.

    Codex OAuth hits the OpenAI Responses API, so this helper enforces
    OpenAI's stricter rule set. Per OpenAI docs (ctx7 `/websites/
    developers_openai_api`, responses-vs-chat-completions guide),
    ``strict: True`` requires every ``type: "object"`` subschema:

    - sets ``additionalProperties: false`` (typed-additional or True is rejected)
    - lists ALL declared property keys in ``required``

    Plus array ``items`` and nested objects must satisfy the same recursively.
    ``oneOf`` / ``anyOf`` / ``allOf`` branches must each be strict-compatible.

    Returns ``True`` when the schema is safe to send with ``strict: True``;
    ``False`` when ``strict: False`` should be used instead. This keeps
    legacy GEODE schemas (designed for additive-output tolerance) from
    causing 400 rejections while still forwarding the schema shape as a
    server hint.
    """
    if not isinstance(schema, dict):
        return True
    schema_type = schema.get("type")
    if schema_type == "object":
        if schema.get("additionalProperties") is not False:
            return False
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        if set(properties.keys()) != required:
            return False
        for prop_schema in properties.values():
            if not _is_openai_strict_compatible(prop_schema):
                return False
    if "items" in schema and not _is_openai_strict_compatible(schema["items"]):
        return False
    for combinator_key in ("oneOf", "anyOf", "allOf"):
        # Combinators are accepted only when every branch is strict-compatible.
        branches = schema.get(combinator_key)
        if isinstance(branches, list):
            for branch in branches:
                if not _is_openai_strict_compatible(branch):
                    return False
    return True


def translate_responses_tool_choice(tc: str | dict[str, Any]) -> str | dict[str, Any]:
    """Adapter-neutral ``tool_choice`` → Responses API wire shape (platform + Codex).

    Routes through :func:`core.llm.tool_choice.normalize` with
    ``provider="openai"`` — Responses API uses the FLAT shape
    ``{"type": "function", "name": "..."}`` (not the Chat nested
    ``function`` wrapper). The legacy helper accepts the Anthropic-shape
    dicts the AgenticLoop emits (``{"type": "auto"}`` / ``{"type":
    "none"}`` / ``{"type": "any"}`` / ``{"type": "tool", "name": "..."}``)
    and returns the Codex-correct payload (Codex MCP A2 BLOCKER 2).
    """
    from core.llm.tool_choice import normalize

    normalised = normalize("openai", tc)
    return normalised if normalised is not None else "auto"


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
    "openai_computer_tool_param",
    "translate_chat_response",
    "translate_codex_response",
    "translate_tool",
    "translate_tool_for_codex",
]
