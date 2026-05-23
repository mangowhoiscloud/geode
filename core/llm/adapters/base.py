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

from collections.abc import AsyncIterator, Sequence
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
    """

    role: str
    content: str | list[dict[str, Any]]
    tool_use_id: str | None = None


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
    """

    text: str
    usage: UsageSummary
    stop_reason: str
    tool_uses: tuple[dict[str, Any], ...] = ()
    raw_response: Any = None


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


__all__ = [
    "CONCRETE_SOURCES",
    "SOURCE_ADAPTER",
    "SOURCE_AUTO",
    "SOURCE_PAYG",
    "SOURCE_SUBSCRIPTION",
    "AdapterBillingType",
    "AdapterCallRequest",
    "AdapterCallResult",
    "CredentialDetection",
    "EnvironmentReport",
    "LLMAdapter",
    "Message",
    "ModelSpec",
    "QuotaWindows",
    "StreamEvent",
    "ToolSpec",
    "UsageSummary",
]
