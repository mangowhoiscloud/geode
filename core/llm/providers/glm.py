"""Z.AI Chat Completions model contracts and shared request/stream translation."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.llm.adapters.base import AdapterCallRequest, StreamEvent

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GlmModelSpec:
    """Documented model capabilities, independent of credential eligibility."""

    reasoning_effort_values: tuple[str, ...]
    always_enabled: bool
    default_effort: str = "max"
    max_output_tokens: int = 131_072
    supports_vision: bool = False
    supports_thinking: bool = True


# Retrieved 2026-09-24: https://docs.z.ai/api-reference/llm/chat-completion
_GLM_52_REASONING = GlmModelSpec(
    ("none", "minimal", "low", "medium", "high", "xhigh", "max"), False
)
_GLM_53_REASONING = GlmModelSpec(("low", "high", "max"), True)
_GLM_53_FLASH_REASONING = GlmModelSpec(("low", "high", "max"), True, supports_vision=True)
_GLM_HYBRID = GlmModelSpec((), False, default_effort="")
_GLM_MODEL_SPECS = {
    "glm-5.1": _GLM_HYBRID,
    "glm-5": _GLM_HYBRID,
    "glm-4.7": _GLM_HYBRID,
    "glm-4.7-flash": _GLM_HYBRID,
    "glm-4.7-flashx": _GLM_HYBRID,
    "glm-5.2": _GLM_52_REASONING,
    "glm-5.3": _GLM_53_REASONING,
    "glm-5.3-flash": _GLM_53_FLASH_REASONING,
    "glm-5.3-flashx": _GLM_53_FLASH_REASONING,
}


def get_glm_model_spec(model: str) -> GlmModelSpec | None:
    """Return documented controls only for an exact supported model ID."""
    return _GLM_MODEL_SPECS.get(model)


def build_glm_reasoning_extra_body(
    model: str, *, effort: str | None = None
) -> dict[str, Any] | None:
    """Translate GEODE effort to the model's documented native controls.

    A request effort takes precedence over the GLM setting. Missing controls
    leave the server default intact. GLM-5.3 always reasons: generic
    none/minimal map to low, medium to high, and xhigh to max. These are GEODE
    normalization decisions, not additional Z.AI API values. Unknown values
    retain the existing warning-and-omit behavior.
    """
    from core.config import settings

    spec = get_glm_model_spec(model)
    effort = (effort if effort is not None else settings.glm_reasoning_effort).strip().lower()
    if not effort or spec is None or not spec.reasoning_effort_values:
        return None
    if spec.always_enabled:
        normalized = {"none": "low", "minimal": "low", "medium": "high", "xhigh": "max"}.get(
            effort, effort
        )
        if normalized != effort:
            log.warning("GLM effort %r mapped to %r for %s", effort, normalized, model)
        effort = normalized
    if effort not in spec.reasoning_effort_values:
        log.warning(
            "glm_reasoning_effort=%r is not a valid z.ai value %s — ignoring",
            effort,
            spec.reasoning_effort_values,
        )
        return None
    return {
        "reasoning_effort": effort,
        "thinking": {
            "type": "disabled"
            if not spec.always_enabled and effort in {"none", "minimal"}
            else "enabled"
        },
    }


def build_glm_chat_kwargs(
    req: AdapterCallRequest, *, adapter_name: str, source: str, stream: bool = False
) -> dict[str, Any]:
    """Use one request policy for GLM completion, text, and streaming paths."""
    from core.llm.adapters._openai_common import build_chat_completion_kwargs
    from core.llm.errors import LLMRequestValidationError
    from core.llm.model_catalog import require_model_source_available

    require_model_source_available(req.model, provider="glm", source=source)
    kwargs = build_chat_completion_kwargs(
        req,
        model=req.model,
        provider="glm",
        adapter_name=adapter_name,
        extra_body=build_glm_reasoning_extra_body(req.model, effort=req.effort or None),
    )
    if req.max_tokens <= 0:
        raise LLMRequestValidationError("GLM max_tokens must be positive")
    spec = get_glm_model_spec(req.model)
    if spec is not None:
        kwargs["max_tokens"] = min(req.max_tokens, spec.max_output_tokens)
    choice = kwargs.get("tool_choice")
    if choice == "none":
        # Z.AI documents auto only. Omitting definitions enforces the caller's
        # no-tool turn without sending an unsupported wire value.
        kwargs.pop("tools", None)
        kwargs.pop("tool_choice", None)
    elif choice is not None and choice != "auto":
        raise LLMRequestValidationError("GLM only supports automatic tool selection")
    if stream:
        kwargs["stream"] = True
        if kwargs.get("tools"):
            kwargs.setdefault("extra_body", {})["tool_stream"] = True
    return kwargs


@dataclass(slots=True)
class _StreamingTool:
    id: str = ""
    name: str = ""
    arguments: str = ""


async def translate_glm_stream(chunks: AsyncIterator[Any]) -> AsyncIterator[StreamEvent]:
    """Preserve thinking and assemble indexed function arguments before emission."""
    from core.llm.adapters._openai_common import translate_chat_response
    from core.llm.adapters.base import StreamEvent

    pending: dict[int, _StreamingTool] = {}
    stop_reason: str | None = None
    async for chunk in chunks:
        if getattr(chunk, "usage", None) is not None:
            yield StreamEvent(kind="usage", payload=asdict(translate_chat_response(chunk).usage))
        choice = chunk.choices[0] if chunk.choices else None
        if choice is None:
            continue
        delta = getattr(choice, "delta", None)
        if delta is not None:
            for field, kind in (("reasoning_content", "thinking"), ("content", "text")):
                value = getattr(delta, field, None)
                if value:
                    yield StreamEvent(kind=kind, payload={"text": value})
            for call in getattr(delta, "tool_calls", None) or ():
                tool = pending.setdefault(call.index, _StreamingTool())
                tool.id = getattr(call, "id", None) or tool.id
                function = getattr(call, "function", None)
                if function is not None:
                    tool.name += getattr(function, "name", None) or ""
                    tool.arguments += getattr(function, "arguments", None) or ""
        finish_reason = getattr(choice, "finish_reason", None)
        if finish_reason is not None:
            if finish_reason == "tool_calls":
                for index in sorted(pending):
                    tool = pending[index]
                    yield StreamEvent(
                        kind="tool_use",
                        payload={"id": tool.id, "name": tool.name, "input": tool.arguments},
                    )
            pending.clear()
            stop_reason = finish_reason
    if stop_reason is None:
        raise RuntimeError("GLM stream ended without a finish reason")
    yield StreamEvent(kind="stop", payload={"stop_reason": stop_reason})
