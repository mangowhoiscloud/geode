"""LLM Adapter abstraction — paperclip pattern adoption (v0.99.39).

Layer 4 of the design in
``docs/plans/2026-05-23-llm-adapter-abstraction.md``:

- :mod:`core.llm.adapters.base` — :class:`LLMAdapter` Protocol + request /
  result / billing-type dataclasses (paperclip ``ServerAdapterModule`` mirror).
- :mod:`core.llm.adapters.registry` — mutable global registry
  (``register_adapter`` / ``resolve_for`` / ``bootstrap_builtins``).

Layer 3 concrete adapters (one per provider × source pair):

- ``anthropic_payg`` / ``anthropic_oauth`` / ``claude_cli``
- ``openai_payg`` / ``codex_oauth`` / ``codex_cli``

External plugins implement :class:`LLMAdapter` and register via
:func:`register_adapter` from their entry point.

PR-MAINPATH-67 (2026-05-24) — the legacy ``AgenticLLMPort`` /
``resolve_agentic_adapter`` / ``_ADAPTER_MAP`` surface was deleted
alongside the AgenticLoop fallback branch. Surviving paperclip
contracts moved to :mod:`core.llm.adapters.paperclip` and
:mod:`core.llm.adapters.provider_inference`; the AgenticLoop
translation helpers moved to :mod:`core.llm.adapters.translation`.
"""

from core.llm.adapters.base import (
    CONCRETE_SOURCES,
    SOURCE_ADAPTER,
    SOURCE_AUTO,
    SOURCE_PAYG,
    SOURCE_SUBSCRIPTION,
    AdapterBillingType,
    AdapterCallRequest,
    AdapterCallResult,
    CredentialDetection,
    EnvironmentReport,
    LLMAdapter,
    Message,
    ModelSpec,
    QuotaWindows,
    StreamEvent,
    ToolSpec,
    UsageSummary,
)
from core.llm.adapters.paperclip import (
    ClaudeAdapter,
    LLMClientPort,
    LLMJsonCallable,
    LLMParsedCallable,
    LLMTextCallable,
)
from core.llm.adapters.provider_inference import infer_provider_from_model
from core.llm.adapters.registry import (
    AdapterAlreadyRegisteredError,
    AdapterNotFoundError,
    adapter_health,
    bootstrap_builtins,
    get_adapter,
    list_adapters,
    register_adapter,
    resolve_for,
    unregister_adapter,
)

__all__ = [
    "CONCRETE_SOURCES",
    "SOURCE_ADAPTER",
    "SOURCE_AUTO",
    "SOURCE_PAYG",
    "SOURCE_SUBSCRIPTION",
    "AdapterAlreadyRegisteredError",
    "AdapterBillingType",
    "AdapterCallRequest",
    "AdapterCallResult",
    "AdapterNotFoundError",
    "ClaudeAdapter",
    "CredentialDetection",
    "EnvironmentReport",
    "LLMAdapter",
    "LLMClientPort",
    "LLMJsonCallable",
    "LLMParsedCallable",
    "LLMTextCallable",
    "Message",
    "ModelSpec",
    "QuotaWindows",
    "StreamEvent",
    "ToolSpec",
    "UsageSummary",
    "adapter_health",
    "bootstrap_builtins",
    "get_adapter",
    "infer_provider_from_model",
    "list_adapters",
    "register_adapter",
    "resolve_for",
    "unregister_adapter",
]
