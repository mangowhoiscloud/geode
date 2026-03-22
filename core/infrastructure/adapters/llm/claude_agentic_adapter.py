"""ClaudeAgenticAdapter — Anthropic LLM adapter for agentic loop.

Owns its own AsyncAnthropic client. Handles context management beta,
prompt caching, tool schema filtering, and BadRequest repair.
"""

from __future__ import annotations

import logging
from typing import Any

from core.cli.agentic_response import AgenticResponse, normalize_anthropic
from core.config import ANTHROPIC_FALLBACK_CHAIN, settings
from core.infrastructure.ports.agentic_llm_port import UserCancelledError
from core.llm.client import (
    LLMBadRequestError,
    call_with_failover,
    get_async_anthropic_client,
)

log = logging.getLogger(__name__)

_API_ALLOWED_KEYS = frozenset({"name", "description", "input_schema", "cache_control", "type"})


class ClaudeAgenticAdapter:
    """Anthropic agentic adapter (P1 Gateway pattern).

    Features:
    - Context management beta (clear_tool_uses)
    - Tool schema key filtering (_API_ALLOWED_KEYS)
    - BadRequest → repair_messages → retry
    - KeyboardInterrupt → UserCancelledError
    """

    def __init__(self) -> None:
        self._client: Any | None = None

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def fallback_chain(self) -> list[str]:
        return list(ANTHROPIC_FALLBACK_CHAIN)

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
        api_key = settings.anthropic_api_key
        if not api_key:
            log.warning("No Anthropic API key for agentic loop")
            return None

        if self._client is None:
            self._client = get_async_anthropic_client(api_key)

        # Anthropic tool_choice is always a dict
        if isinstance(tool_choice, str):
            tool_choice = {"type": tool_choice}

        api_tools = [{k: v for k, v in t.items() if k in _API_ALLOWED_KEYS} for t in tools]
        failover_models = [model] + [m for m in ANTHROPIC_FALLBACK_CHAIN if m != model]

        async def _do_call(m: str) -> Any:
            return await self._client.messages.create(  # type: ignore[union-attr]
                model=m,
                system=system,
                messages=messages,
                tools=api_tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_headers={
                    "anthropic-beta": "context-management-2025-06-27",
                },
                extra_body={
                    "context_management": {
                        "edits": [
                            {
                                "type": "clear_tool_uses_20250919",
                                "keep": {"type": "tool_uses", "value": 5},
                            }
                        ]
                    }
                },
            )

        try:
            response, used_model = await call_with_failover(failover_models, _do_call)
        except KeyboardInterrupt:
            raise UserCancelledError("LLM call interrupted by user") from None
        except LLMBadRequestError as exc:
            msg = str(exc)
            log.warning("Anthropic BadRequest in agentic loop: %s", msg)
            if "tool_use_id" in msg or "tool_result" in msg:
                from core.cli.agentic_loop import AgenticLoop

                AgenticLoop._repair_messages(messages)
                log.info("Repaired orphaned tool_result in conversation history")
                try:
                    response = await _do_call(model)
                    return normalize_anthropic(response)
                except Exception:
                    log.warning("Retry after repair failed", exc_info=True)
                    return None
            if "input_schema" in msg:
                log.error(
                    "Tool schema error — likely an MCP tool missing input_schema. tools=%d",
                    len(tools),
                )
            return None
        except Exception:
            log.warning("Agentic LLM call failed", exc_info=True)
            return None

        if response is None:
            return None

        if used_model and used_model != model:
            log.warning("Model failover: %s -> %s", model, used_model)

        return normalize_anthropic(response)

    def reset_client(self) -> None:
        self._client = None
