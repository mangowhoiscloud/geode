"""LLM Protocol interfaces and adapter implementations.

Extracted from router.py. Contains Protocol definitions (LLMClientPort,
AgenticLLMPort, etc.), the ClaudeAdapter concrete class, and the
resolve_agentic_adapter() factory.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable, Iterator
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

    def generate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[str]: ...

    def generate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., dict[str, Any]],
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


class LLMToolCallable(Protocol):
    """Callable that runs a tool-use loop with an LLM."""

    def __call__(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., dict[str, Any]],
        model: str | None = ...,
        max_tokens: int = ...,
        temperature: float = ...,
        max_tool_rounds: int = ...,
    ) -> Any: ...


# ---------------------------------------------------------------------------
# AgenticLLMPort — Protocol interface for agentic loop LLM adapters
# ---------------------------------------------------------------------------


@runtime_checkable
class AgenticLLMPort(Protocol):
    """Protocol for agentic loop LLM calls.

    Implementations: ClaudeAgenticAdapter, OpenAIAgenticAdapter, GlmAgenticAdapter.
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

    def reset_client(self) -> None: ...


# ---------------------------------------------------------------------------
# resolve_agentic_adapter — factory + cross-provider fallback map
# ---------------------------------------------------------------------------

# Provider -> "module_path:ClassName"
_ADAPTER_MAP: dict[str, str] = {
    "anthropic": "core.llm.providers.anthropic:ClaudeAgenticAdapter",
    "openai": "core.llm.providers.openai:OpenAIAgenticAdapter",
    "glm": "core.llm.providers.glm:GlmAgenticAdapter",
    "openai-codex": "core.llm.providers.codex:CodexAgenticAdapter",
}

# v0.53.0 — Cross-provider fallback REMOVED.
# Per the v0.53.0 governance redesign: API/구독 quota 초과 시 silent
# provider switch 는 cost surprise + model behavior drift 를 만들어
# 시스템 불확실성을 키운다. 사용자에게 명시적으로 quota 안내 + system
# stop 이 정확. The v0.53.0 BillingError → quota_exhausted IPC event
# 경로가 fail-fast 를 담당. Cross-provider hint (B5 breadcrumb,
# v0.52.3) 는 LLM 이 다른 provider 존재를 알 수 있게 *정보* 만 주입 —
# 자동 swap 과 분리.
#
# Empty map preserved for back-compat with any external import; will be
# removed in a future release once all callers stop importing.
CROSS_PROVIDER_FALLBACK: dict[str, list[tuple[str, str]]] = {
    "anthropic": [],
    "openai": [],
    "glm": [],
    "openai-codex": [],
}


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
      reclassified by the family rules above.

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

    def generate_stream(
        self,
        system: str,
        user: str,
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> Iterator[str]:
        from core.llm.router import call_llm_streaming

        return call_llm_streaming(
            system, user, model=model, max_tokens=max_tokens, temperature=temperature
        )

    def generate_with_tools(
        self,
        system: str,
        user: str,
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[..., dict[str, Any]],
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        max_tool_rounds: int = 5,
    ) -> Any:
        from core.llm.router import call_llm_with_tools

        result = call_llm_with_tools(
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
