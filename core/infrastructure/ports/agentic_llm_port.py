"""AgenticLLMPort — Protocol interface for agentic loop LLM adapters.

Separate from LLMClientPort (pipeline concern). Each adapter owns its
own client lifecycle and handles provider-specific message/tool conversion.

Port: REODE P1 Gateway pattern.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.cli.agentic_response import AgenticResponse


class UserCancelledError(Exception):
    """Raised when the user cancels an LLM call (e.g. Ctrl+C).

    Distinguished from API failures so that the agentic loop does NOT
    count it as a consecutive failure or trigger model escalation.
    """


@runtime_checkable
class AgenticLLMPort(Protocol):
    """Protocol for agentic loop LLM calls.

    Implementations: ClaudeAgenticAdapter, OpenAIAgenticAdapter, GlmAgenticAdapter.
    Each adapter handles its own:
    - Client lifecycle (creation, pooling, teardown)
    - Message format conversion (Anthropic ↔ OpenAI)
    - Tool schema conversion
    - Error handling and retry via call_with_failover()
    """

    @property
    def provider_name(self) -> str:
        """Provider identifier (e.g. 'anthropic', 'openai', 'glm')."""
        ...

    @property
    def fallback_chain(self) -> list[str]:
        """Ordered list of model names for intra-provider failover."""
        ...

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
    ) -> AgenticResponse | None:
        """Execute an LLM call with tools, returning a normalized response.

        Returns None on API failure (after exhausting retries/failover).
        Raises UserCancelledError on KeyboardInterrupt.
        """
        ...

    def reset_client(self) -> None:
        """Reset the underlying client (e.g. after API key change)."""
        ...
