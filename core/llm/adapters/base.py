"""LLM Adapter base contract — single Protocol for all call paths.

Mirrors paperclip's ``ServerAdapterModule`` (``packages/adapter-utils/src/
types.ts:349``): one interface that covers PAYG API calls, OAuth subscription
calls, and local agent-cli subprocess calls. Provider routing decisions live
inside concrete adapters (`Layer 3`) — callers above just pick a name (or
provider+source pair) and invoke ``acomplete`` / ``astream``.

The Protocol is intentionally duck-typed (PEP 544) so external plugins can
implement it without subclassing — same plug-in friendliness as paperclip's TS
interface.

See ``docs/plans/2026-05-23-llm-adapter-abstraction.md`` for the full Layer 4
design and the deprecation roster for Layer 2 direct callers.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class AdapterBillingType(str, Enum):  # noqa: UP042 — needs str+Enum for older serialisers
    """How an adapter's call gets billed.

    Mirrors paperclip ``packages/adapter-utils/src/types.ts:34-43``
    ``AdapterBillingType``. The 8-value taxonomy lets the UI surface
    ("PAYG, Subscription, Adapter") map cleanly while still capturing
    overage/credits/fixed-fee edge cases for non-Anthropic/OpenAI providers.
    """

    API = "api"
    SUBSCRIPTION = "subscription"
    METERED_API = "metered_api"
    SUBSCRIPTION_INCLUDED = "subscription_included"
    SUBSCRIPTION_OVERAGE = "subscription_overage"
    CREDITS = "credits"
    FIXED = "fixed"
    UNKNOWN = "unknown"


# Concrete source values that picker / overrides emit. Adapter implementations
# pin themselves to exactly one. ``auto`` is a picker-time sentinel only — never
# stored on a concrete adapter and never accepted by ``resolve_for``.
SOURCE_PAYG = "payg"
SOURCE_SUBSCRIPTION = "subscription"
SOURCE_ADAPTER = "adapter"
SOURCE_AUTO = "auto"  # picker sentinel

CONCRETE_SOURCES: frozenset[str] = frozenset({SOURCE_PAYG, SOURCE_SUBSCRIPTION, SOURCE_ADAPTER})


class EmptyModelOutputError(RuntimeError):
    """A completed adapter response carried neither text nor a tool call."""

    def __init__(
        self,
        message: str,
        *,
        mark_recovered: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(message)
        self._mark_recovered = mark_recovered

    def mark_recovered(self) -> None:
        """Attest that an identical retry returned usable model output."""

        if self._mark_recovered is not None:
            self._mark_recovered()


@dataclass(frozen=True)
class ToolSpec:
    """Tool descriptor passed to the adapter call.

    Provider-agnostic — adapters translate to Anthropic ``tools`` / OpenAI
    ``tools`` payload shape internally.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class Message:
    """Single conversation turn — provider-agnostic.

    ``role`` is one of ``"user" | "assistant" | "tool"``; tool messages carry a
    ``tool_use_id`` so the adapter can wire results back to the originating
    tool_use block.

    ``codex_reasoning_items`` (A2, v0.99.44): Codex backend gpt-5.x family
    runs with ``store=False`` so the server cannot resolve encrypted
    reasoning items by id across turns. Each prior assistant message that
    emitted reasoning carries the items inline here so the Codex adapter
    can replay them at the correct ordinal position when rebuilding the
    next-turn ``input`` array. Pre-A2 callers populate this from the
    AgenticLoop's per-message ``codex_reasoning_items`` annotation
    (Anthropic-shape dict key on the assistant turn).
    """

    role: str
    content: str | list[dict[str, Any]]
    tool_use_id: str | None = None
    codex_reasoning_items: tuple[dict[str, Any], ...] = ()
    # Responses API official state-management path: prior assistant output
    # items may be passed back into the next ``input`` array when the caller
    # manages state manually. Codex/OpenAI Responses adapters populate this
    # with JSON-safe copies of the previous ``response.output`` items.
    codex_output_items: tuple[dict[str, Any], ...] = ()
    # PR-CODEX-MULTITURN-PHASE-PRESERVE (Sprint H follow-up, 2026-05-26)
    # — per-message phase attribution captured from the prior Codex
    # turn. OpenAI Responses API's ``ResponseOutputMessage`` carries
    # ``phase: Literal["commentary", "final_answer"]``; that field
    # appears symmetrically on ``EasyInputMessageParam`` so the
    # adapter can replay the semantic attribution to the next turn.
    # Empty string = no phase (skip the field on output dict).
    # Codex adapter is the only producer; other adapters leave empty.
    phase: str = ""


@dataclass(frozen=True)
class AdapterCallRequest:
    """Request envelope handed to ``LLMAdapter.acomplete`` / ``astream``.

    ``tool_choice`` mirrors the Anthropic ``messages.create`` parameter shape
    (``{"type": "auto" | "any" | "none" | "tool"}`` or the strings
    ``"auto"`` / ``"any"`` / ``"none"`` / ``"required"``). Adapters translate
    to provider-specific syntax in their request builders. Default ``"auto"``
    lets the model pick whether to call a tool.

    ``provider_options`` is a pass-through dict that adapters may consult for
    provider-specific knobs without bloating the top-level schema (e.g.
    Anthropic ``priority_tier``, Codex ``parallel_tool_calls``, OpenAI
    ``response_format``). Each adapter ignores keys it doesn't recognise.
    """

    model: str
    messages: Sequence[Message]
    system_prompt: str = ""
    tools: Sequence[ToolSpec] = field(default_factory=tuple)
    tool_choice: str | dict[str, Any] = "auto"
    max_tokens: int = 8192
    temperature: float | None = None
    thinking_budget: int = 0
    effort: str = "medium"
    stop_sequences: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    provider_options: dict[str, Any] = field(default_factory=dict)
    # PR-V (2026-05-24, spec doc §3 — paperclip `--resume <sessionId>`
    # parity). When non-empty the adapter passes ``--resume <session_id>``
    # to claude-cli so the backend reuses the cached system prompt +
    # prior conversation context — paperclip ``execute.ts:680`` says
    # this saves 5-10K tokens per heartbeat. Empty = fresh session
    # (pre-PR-V behaviour). Non-claude-cli adapters ignore this field.
    resume_session_id: str = ""
    # PR-PERMS-FLAG-FIX (2026-05-25) — JSON-schema forcing parity
    # across both Anthropic + OpenAI structured-output APIs:
    # * Anthropic SDK ``messages.parse(output_format=PydanticModel)`` →
    #   ``JSONOutputFormatParam(schema=..., type="json_schema")``.
    # * OpenAI SDK ``chat.completions.parse(response_format=PydanticModel)`` →
    #   ``json_schema`` with ``strict=true``.
    # * claude-cli (``--print``) flag ``--json-schema <schema>`` (inline string).
    # * codex-cli (``exec``) flag ``--output-schema <FILE>`` (path-based).
    #
    # Set this dict (a JSON Schema object) when the caller expects a
    # validated JSON shape — eliminates the "LLM returns natural
    # language + code block instead of pure JSON" failure that
    # clipped proximity / critic / pilot / meta_reviewer in the
    # v0.99.53 smoke. Adapters that don't support structured outputs
    # ignore this field and fall back to prompt-engineered JSON
    # discipline.
    response_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class UsageSummary:
    """Token accounting block from a single LLM call.

    Mirrors paperclip ``UsageSummary`` (``types.ts:30-34``). ``cached_input``
    tracks prompt-cache hits separately so cost estimation can apply the
    discounted rate (Anthropic) without losing the gross-input figure.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0


@dataclass(frozen=True)
class AdapterCallResult:
    """Completed (non-streaming) LLM response.

    ``raw_response`` is the underlying SDK response object — adapters expose it
    so caller-side observability (token hooks, retry journals) can still extract
    provider-specific headers (Anthropic ``anthropic-priority-tier`` etc.)
    without bypassing the adapter.

    ``reasoning_items`` (A2, v0.99.44): Codex backend emits encrypted reasoning
    items (``{type: "reasoning", encrypted_content, summary?, id?}``) that the
    next-turn ``input`` array must replay verbatim so gpt-5.x can resume its
    chain of thought under ``store=False``. Codex adapters capture these from
    ``response.output_item.done`` SSE events; non-Codex adapters leave the
    tuple empty. The legacy bridge forwards this into
    :attr:`core.llm.agentic_response.AgenticResponse.codex_reasoning_items`.

    ``reasoning_summaries`` (A2, v0.99.44): Free-text reasoning summaries
    surfaced for the live "thinking..." UI. Codex populates from
    ``reasoning.summary[].text`` SSE events; Anthropic adapters populate from
    ``thinking`` content blocks when available.
    """

    text: str
    usage: UsageSummary
    stop_reason: str
    tool_uses: tuple[dict[str, Any], ...] = ()
    raw_response: Any = None
    reasoning_items: tuple[dict[str, Any], ...] = ()
    reasoning_summaries: tuple[str, ...] = ()
    # JSON-safe copy of the OpenAI Responses ``response.output`` items.
    # When present, next-turn Codex input should replay these official output
    # items instead of reconstructing assistant messages from lossy text/tool
    # blocks.
    codex_output_items: tuple[dict[str, Any], ...] = ()
    # PR-CODEX-MULTITURN-PHASE-PRESERVE (Sprint H follow-up, 2026-05-26)
    # — per-response phase attribution from the Codex Responses API
    # ``ResponseOutputMessage.phase`` field
    # (Literal["commentary", "final_answer"]). Captured by
    # ``translate_codex_response`` from the SSE-accumulated message
    # item. Empty string when the response had no phase set or the
    # adapter isn't Codex. The legacy bridge forwards this into
    # :attr:`core.llm.agentic_response.AgenticResponse.assistant_phase`
    # so the AgenticLoop can persist it on the next-turn message dict
    # for multi-turn replay.
    assistant_phase: str = ""
    # PR-V (2026-05-24, spec doc §3) — sessionId emitted by claude-cli's
    # ``system.init`` event (paperclip ``parse.ts:30``). Callers persist
    # this so the next turn can resume the same backend session via
    # ``AdapterCallRequest.resume_session_id``. Mirrors paperclip's
    # ``heartbeat_runs.sessionIdBefore/After`` capture. Empty for
    # non-claude-cli adapters (they don't have a resumable session).
    session_id: str = ""


@dataclass(frozen=True)
class StreamEvent:
    """One streaming chunk from ``LLMAdapter.astream``.

    ``kind`` is ``"text" | "tool_use" | "thinking" | "stop" | "usage"``.
    Concrete adapters translate provider stream events into this single shape so
    UI / observability code doesn't branch on provider.
    """

    kind: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ModelSpec:
    """One model the adapter can serve. Returned by ``list_models``.

    Mirrors paperclip ``AdapterModel`` — the UI uses ``label`` + ``context_tokens``
    to render selection menus.
    """

    id: str
    label: str
    context_tokens: int
    supports_thinking: bool = False
    supports_tools: bool = True


@dataclass(frozen=True)
class QuotaWindows:
    """Live quota/rate-limit windows for OAuth subscription adapters.

    Mirrors paperclip ``ProviderQuotaResult``. Adapters that don't expose quota
    (PAYG) return ``None`` from ``get_quota_windows``.
    """

    used_tokens: int
    total_tokens: int
    window_seconds: int
    reset_at: float | None = None  # unix epoch seconds


@dataclass(frozen=True)
class EnvironmentReport:
    """Result of ``test_environment`` — paperclip ``testEnvironment`` mirror.

    ``ok`` is the headline pass/fail; ``checks`` carries per-credential /
    per-binary detail rows the UI surfaces. ``hints`` are operator-facing fix
    suggestions ("set ``ANTHROPIC_API_KEY``", "run ``claude /login``").
    """

    ok: bool
    checks: tuple[tuple[str, str], ...] = ()  # (label, status_or_message)
    hints: tuple[str, ...] = ()


@dataclass(frozen=True)
class CredentialDetection:
    """``detect_credential`` result — paperclip ``detectModel`` mirror.

    Adapters that read a local config (``~/.claude/oauth-token.json`` etc.)
    return the currently configured model + provenance so the UI can show
    "currently configured: claude-sonnet-4-7 (from ~/.claude/oauth-token.json)".
    """

    model: str
    provider: str
    source_path: str
    candidates: tuple[str, ...] = ()


@runtime_checkable
class LLMAdapter(Protocol):
    """Single adapter contract — paperclip ``ServerAdapterModule`` equivalent.

    Concrete implementations live in ``core/llm/adapters/<name>.py``. External
    plugins implement this Protocol without subclassing and register via
    :func:`core.llm.adapters.registry.register_adapter`.

    Three required identity attributes (``name`` / ``provider`` / ``source``)
    plus ``billing_type`` and one async call method (``acomplete``) form the
    minimum viable adapter. Streaming + introspection methods are required by
    the Protocol but can return empty / ``None`` for adapters that don't
    support those surfaces (test_environment must always be honest).
    """

    name: str
    provider: str
    source: str  # one of CONCRETE_SOURCES (never SOURCE_AUTO)
    billing_type: AdapterBillingType

    async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult: ...

    def astream(self, req: AdapterCallRequest) -> AsyncIterator[StreamEvent]: ...

    def test_environment(self) -> EnvironmentReport: ...

    def list_models(self) -> list[ModelSpec]: ...

    def get_quota_windows(self) -> QuotaWindows | None: ...

    def detect_credential(self) -> CredentialDetection | None: ...


# ---------------------------------------------------------------------------
# Capability protocols — PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28)
# ---------------------------------------------------------------------------
# Paperclip-pattern alignment (``packages/adapter-utils/src/types.ts:349``):
# adapters declare optional capabilities (web_search, text_completion,
# instructions_bundle, ...) via mixin Protocols + explicit ``supports_*``
# boolean flags. Centralised exact-route dispatch
# (``core/llm/adapters/dispatch.py``) picks only the adapter matching the
# caller's resolved provider/source route.
#
# Why split the Protocol: the core ``LLMAdapter`` stays minimal (one method)
# so adding an adapter only requires implementing ``acomplete`` + identity
# attrs. Tool-side capabilities (web_search, text_completion) are opt-in via
# mixin so non-LLM adapters or local-CLI subprocess adapters can omit them
# without satisfying spurious stubs.


@dataclass(frozen=True)
class WebSearchResult:
    """Single web_search call result — provider-agnostic.

    ``text`` is the model's synthesised summary of search hits (titles + URLs +
    brief blurbs). ``source_urls`` is the extracted URL list when the provider
    exposes it (Anthropic ``web_search_tool_result`` blocks); other providers
    leave it empty.

    ``adapter_name`` / ``adapter_provider`` / ``adapter_source`` carry the
    routing identity forward into the tool layer so the tool's
    ``tool_exec_end`` metadata can answer "which adapter handled this"
    inline — operators no longer need to cross-correlate by timestamp
    with ``ADAPTER_DISPATCH_ATTEMPT`` events
    (PR-DISPATCH-OBS-EXT 2026-05-28). The fields default to empty
    strings so existing capability impls (which set only ``adapter_name``)
    still build a valid result; the dispatch layer enriches them with
    the selected adapter's ``provider`` / ``source`` after a successful
    call.
    """

    query: str
    text: str
    source_urls: tuple[str, ...] = ()
    adapter_name: str = ""
    adapter_provider: str = ""
    adapter_source: str = ""


@dataclass(frozen=True)
class TextCompletionResult:
    """Single-turn text completion result — used by compaction / extraction.

    Same adapter-identity fields as :class:`WebSearchResult` for the same
    reason (PR-DISPATCH-OBS-EXT 2026-05-28) — the compaction / extraction
    callers can now record which adapter actually handled the call.
    """

    text: str
    usage: UsageSummary
    adapter_name: str = ""
    adapter_provider: str = ""
    adapter_source: str = ""


@runtime_checkable
class WebSearchCapable(Protocol):
    """Mixin Protocol — adapters that natively support web search.

    Centralised dispatch (``core/llm/adapters/dispatch.web_search_via_adapters``)
    enumerates registered adapters via ``isinstance(adapter, WebSearchCapable)``
    so a tool caller never has to know which provider is configured. Operator
    switches PAYG ↔ Subscription via ``settings.{provider}_credential_source``
    + ProfileStore presence — the same ``infer_source`` flow the agent loop
    uses.
    """

    # Identity attrs shared with :class:`LLMAdapter` — included on the mixin
    # so callers narrowing via ``isinstance(adapter, WebSearchCapable)`` can
    # still read provider/source for fallback ordering.
    name: str
    provider: str
    source: str
    supports_web_search: bool

    # ``model`` is the SESSION's resolved model — a routing HINT, not a
    # command (PR-WEB-SEARCH-MODEL-HINT, 2026-06-12). Anthropic adapters
    # honour it when the model is in the documented
    # ``web_search_20260209`` support set and escalate to
    # ANTHROPIC_PRIMARY otherwise; non-Anthropic adapters currently keep
    # their provider primary (their backend's per-model web_search
    # support matrix is unverified — doc-before-behaviour, CLAUDE.md §4d).
    async def aweb_search(
        self, query: str, *, max_results: int = 5, model: str = ""
    ) -> WebSearchResult: ...


@runtime_checkable
class ComputerUseCapable(Protocol):
    """Mixin Protocol — source-level adapters whose backend exposes a native
    computer-use tool (Anthropic ``computer_20251124`` / OpenAI
    ``{type: "computer"}``).

    Same level as :class:`WebSearchCapable` (the per-(provider, source)
    adapters), so a caller can enumerate computer-use support the same way
    ``dispatch`` enumerates ``supports_web_search``. Execution is ALWAYS local
    (``core.tools.computer_use.ComputerUseHarness``); this contract covers only
    the per-provider tool DEFINITION. The tool itself is injected onto the live
    request path by the provider's request builder (Anthropic:
    ``_anthropic_common._maybe_inject_computer_use``) — ``computer_tool_param``
    returns the same param so the enumerable contract and the injected wire
    payload never drift. The harness translates each provider's action
    vocabulary (Anthropic ``left_click`` ↔ OpenAI ``click`` …).
    """

    name: str
    provider: str
    source: str
    supports_computer_use: bool

    def computer_tool_param(
        self, *, display_width: int, display_height: int
    ) -> dict[str, Any] | None:
        """Return the provider's computer-use tool param, or ``None`` if the
        adapter cannot inject one. ``display_width`` / ``display_height`` are
        the harness target dims so the tool definition and the local harness
        never drift."""
        ...


@runtime_checkable
class TextCompletionCapable(Protocol):
    """Mixin Protocol — adapters that support a one-shot ``(system, prompt) ->
    text`` call. Used by compaction (conversation summary) and learning
    extraction (Haiku-tier hooks) where a full agentic loop is overkill."""

    name: str
    provider: str
    source: str
    supports_text_completion: bool

    async def acomplete_text(
        self,
        prompt: str,
        *,
        system: str = "",
        model: str = "",
        max_tokens: int = 1024,
    ) -> TextCompletionResult: ...


__all__ = [
    "CONCRETE_SOURCES",
    "SOURCE_ADAPTER",
    "SOURCE_AUTO",
    "SOURCE_PAYG",
    "SOURCE_SUBSCRIPTION",
    "AdapterBillingType",
    "AdapterCallRequest",
    "AdapterCallResult",
    "ComputerUseCapable",
    "CredentialDetection",
    "EnvironmentReport",
    "LLMAdapter",
    "Message",
    "ModelSpec",
    "QuotaWindows",
    "StreamEvent",
    "TextCompletionCapable",
    "TextCompletionResult",
    "ToolSpec",
    "UsageSummary",
    "WebSearchCapable",
    "WebSearchResult",
]
