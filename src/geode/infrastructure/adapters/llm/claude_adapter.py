"""Claude Adapter — Anthropic API implementation of LLMClientPort.

Wraps existing geode.llm.client functions into the LLMClientPort interface,
enabling clean dependency injection and testability.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from pydantic import BaseModel

from geode.config import settings
from geode.llm.client import (
    call_llm,
    call_llm_json,
    call_llm_parsed,
    call_llm_streaming,
    call_llm_with_tools,
)

T = TypeVar("T", bound=BaseModel)


class ClaudeAdapter:
    """Anthropic Claude adapter implementing LLMClientPort.

    Wraps the existing call_llm/call_llm_json/call_llm_streaming functions
    from geode.llm.client into the port interface.
    """

    @property
    def model_name(self) -> str:
        """Return the default model name for cross-LLM verification."""
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
        return call_llm_parsed(  # type: ignore[no-any-return]
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
        from geode.llm.client import ToolUseResult

        result: ToolUseResult = call_llm_with_tools(
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
