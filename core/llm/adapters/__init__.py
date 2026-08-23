"""LLM Adapter abstraction — paperclip pattern adoption (v0.99.39).

Layer 4 of the design in
``docs/plans/2026-05-23-llm-adapter-abstraction.md``:

- :mod:`core.llm.adapters.base` — :class:`LLMAdapter` Protocol + request /
  result / billing-type dataclasses (paperclip ``ServerAdapterModule`` mirror).
- :mod:`core.llm.adapters.registry` — generation-bound immutable discovery
  snapshots (``reload_adapters`` / ``resolve_for`` / ``bootstrap_builtins``).

Layer 3 concrete adapters (one per provider × source pair):

- ``anthropic_payg``
- ``openai_payg`` / ``codex_oauth``

External packages expose a no-argument :class:`LLMAdapter` factory in the
``geode.llm_adapters`` package entry-point group.

PR-LLMCLIENTPORT-COLLAPSE (2026-05-28) — the parallel ``LLMClientPort``
hierarchy (sync ``ClaudeAdapter`` / ``OpenAIAdapter.generate*`` surface
+ ``LLMJsonCallable`` / ``LLMTextCallable`` / ``LLMParsedCallable``
node-DI Protocols + the ``set_llm_callable`` / ``get_llm_json`` ContextVar
chain + ``cross_llm.py`` re-score) is gone. The :class:`LLMAdapter`
Protocol + central dispatch (``core.llm.adapters.dispatch``) is the
single registry / call surface.
"""

from core.llm.adapters._openai_common import (
    build_responses_kwargs as build_openai_responses_kwargs,
)
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
    CredentialDetectionCapable,
    EnvironmentDiagnosticCapable,
    EnvironmentReport,
    LLMAdapter,
    Message,
    ModelListingCapable,
    ModelSpec,
    QuotaInspectionCapable,
    QuotaWindows,
    StreamEvent,
    StreamingCapable,
    ToolSpec,
    UsageSummary,
)
from core.llm.adapters.provider_inference import infer_provider_from_model
from core.llm.adapters.registry import (
    ADAPTER_ENTRY_POINT_GROUP,
    AdapterAlreadyRegisteredError,
    AdapterNotFoundError,
    AdapterOverride,
    AdapterRegistrySnapshot,
    AdapterValidationReport,
    active_registry_snapshot,
    adapter_health,
    bootstrap_builtins,
    get_adapter,
    list_adapters,
    register_adapter,
    registry_snapshot,
    reload_adapters,
    resolve_for,
    unregister_adapter,
    use_registry_snapshot,
)

__all__ = [
    "ADAPTER_ENTRY_POINT_GROUP",
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
    "AdapterOverride",
    "AdapterRegistrySnapshot",
    "AdapterValidationReport",
    "CredentialDetection",
    "CredentialDetectionCapable",
    "EnvironmentDiagnosticCapable",
    "EnvironmentReport",
    "LLMAdapter",
    "Message",
    "ModelListingCapable",
    "ModelSpec",
    "QuotaInspectionCapable",
    "QuotaWindows",
    "StreamEvent",
    "StreamingCapable",
    "ToolSpec",
    "UsageSummary",
    "active_registry_snapshot",
    "adapter_health",
    "bootstrap_builtins",
    "build_openai_responses_kwargs",
    "get_adapter",
    "infer_provider_from_model",
    "list_adapters",
    "register_adapter",
    "registry_snapshot",
    "reload_adapters",
    "resolve_for",
    "unregister_adapter",
    "use_registry_snapshot",
]
