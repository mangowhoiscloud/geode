"""Legacy LLM Protocol interfaces — pre-v0.99.39 paperclip-style abstraction.

DEPRECATED (v0.99.39, removal target: v1.0.0)
===========================================

This module holds the "PR-1 G-A" paperclip-style abstraction (referenced in
``core/agent/loop/_reflection.py:48``) that defined ``LLMClientPort`` /
``AgenticLLMPort`` / ``resolve_agentic_adapter`` for provider-agnostic agentic
calls. It is superseded by the unified :class:`core.llm.adapters.LLMAdapter`
Protocol + registry (Layer 4 of the v0.99.39 adapter abstraction) which folds
PAYG / OAuth / local-agent-cli into a single contract.

Why kept under ``_legacy``:

- Many internal callers (``core/agent/loop/_reflection.py``, ``core/llm/router``,
  ``plugins/petri_audit/*``) still call ``resolve_agentic_adapter(provider)``.
  Renaming them is out of scope for the v0.99.39 PR — the migration is
  tracked in ``docs/plans/2026-05-23-llm-adapter-abstraction.md`` § Out of
  scope.
- External plugins that import from ``core.llm.adapters`` keep working
  (``__init__.py`` re-exports the legacy symbols).
- The new :class:`LLMAdapter` is the canonical entry point for new callers.

Removal plan (v1.0.0): the in-tree call sites are migrated to
``resolve_for(provider, source)`` (which carries explicit source binding the
legacy ``resolve_agentic_adapter`` cannot express). This file is then deleted.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import AsyncIterator, Callable
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from core.llm.agentic_response import AgenticResponse

if TYPE_CHECKING:
    # Pydantic is a heavy import (~100 ms cumulative). Push it behind
    # ``TYPE_CHECKING`` so module load no longer pulls the full pydantic
    # graph into the cold-start path; ``TypeVar`` ``bound=`` accepts a
    # forward-reference string at runtime so the annotation still type-
    # checks under mypy.
    from pydantic import BaseModel

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLMClientPort — Protocol interface for LLM provider adapters
# ---------------------------------------------------------------------------

T2 = TypeVar("T2", bound="BaseModel")


@runtime_checkable
class LLMClientPort(Protocol):
    """Protocol for LLM client adapters.

    Implementations: ClaudeAdapter (router functions), OpenAIAdapter, MockAdapter.
    """

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
        ...

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str: ...

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]: ...

    def generate_parsed(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T2],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> T2: ...

    def agenerate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]: ...

    async def agenerate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., Any],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# Lightweight callable protocols for node-level DI
# ---------------------------------------------------------------------------


class LLMJsonCallable(Protocol):
    """Callable that returns parsed JSON from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> dict[str, Any]: ...


class LLMTextCallable(Protocol):
    """Callable that returns raw text from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> str: ...


class LLMParsedCallable(Protocol):
    """Callable that returns a Pydantic model instance from an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T2],
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
    ) -> T2: ...


# ---------------------------------------------------------------------------
# AgenticLLMPort — Protocol interface for agentic loop LLM adapters
# ---------------------------------------------------------------------------


@runtime_checkable
class AgenticLLMPort(Protocol):
    """Protocol for agentic loop LLM calls.

    Implementations: ClaudeAgenticAdapter, OpenAIAgenticAdapter, GlmAgenticAdapter.

    ``fallback_chain`` stays as an opt-in knob (v0.99.19): the shipped
    default in ``core/config/routing.toml`` is an empty list (no
    silent fallback), but users can populate ``~/.geode/routing.toml``
    ``[model.fallbacks]`` to explicitly opt into a same-provider chain.
    """

    @property
    def provider_name(self) -> str: ...

    @property
    def fallback_chain(self) -> list[str]: ...

    last_error: Exception | None

    async def agentic_call(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: dict[str, str] | str,
        max_tokens: int,
        temperature: float,
        thinking_budget: int = 0,
        effort: str = "high",
    ) -> AgenticResponse | None: ...

    async def areset_client(self) -> None: ...


# ---------------------------------------------------------------------------
# resolve_agentic_adapter — factory
# ---------------------------------------------------------------------------

# Provider -> "module_path:ClassName"
_ADAPTER_MAP: dict[str, str] = {
    "anthropic": "core.llm.providers.anthropic:ClaudeAgenticAdapter",
    "openai": "core.llm.providers.openai:OpenAIAgenticAdapter",
    "glm": "core.llm.providers.glm:GlmAgenticAdapter",
    "openai-codex": "core.llm.providers.codex:CodexAgenticAdapter",
}

# v0.53.0 removed cross-provider auto-swap; v0.99.19 removed the
# empty-dict back-compat shim ``CROSS_PROVIDER_FALLBACK``. Quota
# exhaustion surfaces ``BillingError`` → ``quota_exhausted`` IPC event
# and the user picks the next provider via ``/model``.


def resolve_agentic_adapter(provider: str) -> AgenticLLMPort:
    """Create an agentic adapter for the given provider.

    Uses dynamic import to avoid loading unused providers.
    """
    entry = _ADAPTER_MAP.get(provider)
    if entry is None:
        # Unknown provider -> default to OpenAI-compatible
        log.warning("Unknown provider '%s', defaulting to openai adapter", provider)
        entry = _ADAPTER_MAP["openai"]

    module_path, class_name = entry.rsplit(":", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    adapter: AgenticLLMPort = cls()
    return adapter


def infer_provider_from_model(model: str) -> str:
    """Return the agentic provider key for a model id.

    Maps a GEODE / inspect_ai model identifier to the matching
    ``_ADAPTER_MAP`` key. Used by callers that pin a model (e.g. the
    Petri audit target ``geode/gpt-5.5``) but did not pin a provider —
    without this helper, ``AgenticLoop`` falls back to its
    ``provider="anthropic"`` default and the orchestration layer
    (GoalDecomposer, extract hooks) silent-fails on ``ANTHROPIC_API_KEY``
    when the OAuth-only environment never had one.

    Rules:

    - ``gpt-*`` / ``o3`` / ``o4-mini`` → ``"openai-codex"`` when a
      Codex OAuth token is resolvable, else ``"openai"`` (PAYG path).
    - ``claude-*`` → ``"anthropic"``.
    - ``glm-*`` → ``"glm"``.
    - Provider-prefixed ids (``anthropic/...``, ``openai/...``,
      ``openai-codex/...``, ``geode/<base>``) — the prefix wins for
      ``openai-codex`` (OAuth-routed), otherwise the bare model id is
      reclassified by the provider rules above.

    The OAuth probe is read-only and tolerates a missing
    ``plugins.petri_audit`` package (the predicate lives there because
    the bridge is plugin-scoped). When the import fails the function
    falls back to the per-token ``openai`` path.
    """
    if not model:
        return "anthropic"

    raw_prefix = model.split("/", 1)[0] if "/" in model else ""
    if raw_prefix == "openai-codex":
        return "openai-codex"
    if raw_prefix == "anthropic":
        return "anthropic"
    if raw_prefix in ("openai", "openai-api"):
        return "openai"

    base = model.rsplit("/", 1)[-1]
    if base.startswith("claude-"):
        return "anthropic"
    if base.startswith("glm-"):
        return "glm"
    if base.startswith("gpt-") or base in ("o3", "o4-mini"):
        try:
            from plugins.petri_audit.codex_provider import is_codex_oauth_available

            if is_codex_oauth_available():
                return "openai-codex"
        except ImportError:
            pass
        return "openai"
    return "anthropic"


# ---------------------------------------------------------------------------
# ClaudeAdapter — thin wrapper that delegates to router functions
# ---------------------------------------------------------------------------

T = TypeVar("T", bound="BaseModel")


class ClaudeAdapter:
    """Anthropic Claude adapter implementing LLMClientPort.

    Wraps the router functions into the port interface.
    Uses lazy imports from core.llm.router to avoid circular imports.
    """

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
        from core.config import settings

        return settings.model

    def generate(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        from core.llm.router import call_llm

        result: str = call_llm(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )
        return result

    def generate_structured(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> dict[str, Any]:
        from core.llm.router import call_llm_json

        result: dict[str, Any] = call_llm_json(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )
        return result

    def generate_parsed(
        self,
        system: str,
        user: str,
        *,
        output_model: type[T],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> T:
        from core.llm.router import call_llm_parsed

        return call_llm_parsed(
            system,
            user,
            output_model=output_model,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    async def agenerate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> AsyncIterator[str]:
        from core.llm.router import call_llm_streaming_async

        async for token in call_llm_streaming_async(
            system,
            user,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        ):
            yield token

    async def agenerate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., Any],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        """Async boundary for provider tool-use calls."""
        from core.llm.router import call_llm_with_tools_async

        result = await call_llm_with_tools_async(
            system,
            user,
            tools=tools,
            tool_executor=tool_executor,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            max_tool_rounds=max_tool_rounds,
        )
        return result
