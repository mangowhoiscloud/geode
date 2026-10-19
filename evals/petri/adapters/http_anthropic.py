"""HTTP API-key adapter for Anthropic — GEODE-owned inspect_ai provider.

Maps the manifest binding ``[petri.adapter.anthropic.api_key]`` to
``anthropic-platform/<model>``: inspect_ai's stock ``AnthropicAPI`` with
GEODE's verified ``AnthropicModelSpec`` governing what the stock shaping
gets wrong for current models (inspect_ai 0.3.252):

- ``reasoning_effort="none"`` sends ``thinking: disabled`` to Opus 5.5 and
  Sonnet 5.5 (both reject it) and silently keeps thinking on for Haiku 5.5.
- Any explicit ``tool_choice`` (including ``none``) is dropped while
  thinking is on, and forced choices reach models that reject them.
- Unsupported ``effort`` values are silently clamped.

Unsupported explicit options are rejected before any request; supported ones
are serialized. The endpoint is resolved once at construction. Unknown models,
Bedrock, Vertex and custom gateways keep stock behavior, as do raw
``anthropic/<model>`` ids (an explicit escape hatch that bypasses these
contracts).
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from core.llm.model_capabilities import AnthropicModelSpec

__all__ = ["INSPECT_PREFIX", "admit_anthropic_options", "is_available", "register"]

INSPECT_PREFIX = "anthropic-platform"
ANTHROPIC_API_URL = "https://api.anthropic.com"

# Per-task (generate → completion_config) hand-off; safe under concurrent samples.
_EXPLICIT_TOOL_CHOICE: ContextVar[Any] = ContextVar("geode_tool_choice", default=None)


def admit_anthropic_options(
    spec: AnthropicModelSpec,
    model: str,
    *,
    reasoning_effort: str | None,
    effort: str | None,
    forced_tool: bool,
) -> str | None:
    """Return why the model contract rejects these options, or ``None``."""
    if forced_tool and not spec.forced_tool_choice:
        return f"{model} does not support forced tool_choice; use auto or none"
    if effort is not None and effort not in spec.effort_values:
        return f"{model} does not support effort {effort!r}"
    # On adaptive models reasoning_effort becomes the native effort; on older
    # extended-thinking models inspect_ai bridges it to ``budget_tokens``.
    if (
        spec.adaptive_thinking
        and reasoning_effort not in (None, "none")
        and reasoning_effort not in spec.effort_values
    ):
        return f"{model} does not support effort {reasoning_effort!r}"
    if reasoning_effort == "none":
        if not spec.disabled_thinking:
            return f"{model} cannot turn thinking off (reasoning_effort='none')"
        if spec.disabled_thinking_high_only and effort in ("xhigh", "max"):
            return f"{model} cannot combine disabled thinking with effort {effort!r}"
    return None


def register() -> None:
    """Register ``anthropic-platform`` with inspect_ai (requires the ``[audit]`` extra)."""
    from inspect_ai.model import modelapi
    from inspect_ai.model._providers.anthropic import AnthropicAPI, message_tool_choice
    from inspect_ai.tool import ToolFunction

    @modelapi(name=INSPECT_PREFIX)
    class AnthropicPlatformAPI(AnthropicAPI):  # type: ignore[misc, unused-ignore]
        def __init__(self, model_name: str, base_url: str | None = None, **kwargs: Any) -> None:
            if "/" not in model_name:  # no bedrock/vertex service prefix
                base_url = base_url or os.environ.get("ANTHROPIC_BASE_URL") or ANTHROPIC_API_URL
                from core.llm.model_catalog import require_model_source_available

                # Direct get_model() use must not bypass the lifecycle owner; it
                # judges the actual endpoint, so custom gateways are not equated.
                require_model_source_available(
                    model_name, provider="anthropic", source="payg", base_url=base_url
                )
            super().__init__(model_name, base_url=base_url, **kwargs)

        def _geode_spec(self) -> AnthropicModelSpec | None:
            if self.is_bedrock() or self.is_vertex():
                return None
            # ``base_url`` is final: the resolved endpoint was passed explicitly.
            if self.base_url is None or urlsplit(self.base_url).hostname != "api.anthropic.com":
                return None
            from core.llm.model_capabilities import get_anthropic_model_spec

            return get_anthropic_model_spec(self.model_name)

        async def generate(self, input: Any, tools: Any, tool_choice: Any, config: Any) -> Any:
            spec = self._geode_spec()
            if spec is None:
                return await super().generate(input, tools, tool_choice, config)
            forced = bool(tools) and (tool_choice == "any" or isinstance(tool_choice, ToolFunction))
            problem = admit_anthropic_options(
                spec,
                self.model_name,
                reasoning_effort=config.reasoning_effort,
                effort=config.effort,
                forced_tool=forced,
            )
            # Follow the shaping inspect_ai will emit: manual ``enabled`` thinking
            # (a bridged or explicit budget) rejects forced tool use, as in core.
            if (
                problem is None
                and forced
                and self.is_using_thinking(config)
                and self.effort_from_reasoning_effort(config) is None
            ):
                problem = (
                    f"{self.model_name}: manual thinking does not support forced "
                    "tool_choice; use auto or none"
                )
            if problem is not None:
                raise ValueError(problem)
            explicit = bool(tools) and (forced or tool_choice == "none")
            token = _EXPLICIT_TOOL_CHOICE.set(tool_choice if explicit else None)
            try:
                return await super().generate(input, tools, tool_choice, config)
            finally:
                _EXPLICIT_TOOL_CHOICE.reset(token)

        def completion_config(self, config: Any) -> Any:
            params, extra_body, headers, betas = super().completion_config(config)
            spec = self._geode_spec()
            if spec is not None:
                if (
                    config.reasoning_effort == "none"
                    and spec.adaptive_thinking
                    and self.is_claude_4_7_or_later()
                ):
                    # Thinking is on by default here; admission already checked support.
                    params["thinking"] = {"type": "disabled"}
                # Stock shaping drops tool_choice while thinking; keep explicit ones.
                explicit = _EXPLICIT_TOOL_CHOICE.get()
                if explicit is not None and self.is_using_thinking(config):
                    params["tool_choice"] = message_tool_choice(explicit, config)
            return params, extra_body, headers, betas


def is_available() -> bool:
    """True when ``ANTHROPIC_API_KEY`` is set in the environment."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))
