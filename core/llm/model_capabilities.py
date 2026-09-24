"""Verified Anthropic Messages capabilities, retrieved 2026-09-24.

One immutable row owns each model's request contract. Existing feature-set
consumers use projections of these rows; unknown models gain no native tools.
Sources: docs/research/provider-refresh-20260924-claude.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal


@dataclass(frozen=True, slots=True)
class AnthropicModelSpec:
    """Model capabilities, independent of credentials and account availability."""

    max_output_tokens: int = 128_000
    adaptive_thinking: bool = True
    effort_values: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max")
    default_effort: str | None = "high"
    tool_search: bool = True
    context_editing: bool = True
    compaction: bool = True
    dynamic_web_search: bool = True
    dynamic_web_fetch: bool = True
    computer_tool: Literal[
        "computer_20250124", "computer_20251124", "computer_toolset_20260801"
    ] = "computer_20251124"
    forced_tool_choice: bool = True
    binds_thinking: bool = False


_MODERN = AnthropicModelSpec()
_EXTENDED = AnthropicModelSpec(
    max_output_tokens=64_000,
    adaptive_thinking=False,
    effort_values=(),
    default_effort=None,
    compaction=False,
    dynamic_web_search=False,
    dynamic_web_fetch=False,
    computer_tool="computer_20250124",
)
ANTHROPIC_MODEL_SPECS: dict[str, AnthropicModelSpec] = {
    "claude-fable-5-1": replace(_MODERN, forced_tool_choice=False, binds_thinking=True),
    "claude-fable-5": _MODERN,
    "claude-opus-5-5": replace(
        _MODERN,
        default_effort="medium",
        computer_tool="computer_toolset_20260801",
        forced_tool_choice=False,
        binds_thinking=True,
        dynamic_web_fetch=False,
    ),
    "claude-opus-5": replace(_MODERN, dynamic_web_fetch=False),
    "claude-opus-4-8": _MODERN,
    "claude-opus-4-7": _MODERN,
    "claude-opus-4-6": replace(_MODERN, effort_values=("low", "medium", "high", "max")),
    "claude-opus-4-5": replace(
        _EXTENDED,
        effort_values=("low", "medium", "high"),
        default_effort="high",
        computer_tool="computer_20251124",
    ),
    # The published tool-search compatibility table omits Sonnet 5.
    # Keep tools eager until the provider documents this pairing.
    "claude-sonnet-5": replace(_MODERN, tool_search=False),
    "claude-sonnet-4-6": replace(_MODERN, effort_values=("low", "medium", "high", "max")),
    "claude-sonnet-4-5": _EXTENDED,
    "claude-haiku-4-5": _EXTENDED,
}


def anthropic_base_model(model: str) -> str:
    """Normalize dated snapshots and released aliases without changing family."""
    model = model.removesuffix("-latest")
    head, separator, tail = model.rpartition("-")
    return head if separator and len(tail) == 8 and tail.isdigit() else model


def get_anthropic_model_spec(model: str) -> AnthropicModelSpec | None:
    """Return a verified contract; unknown models stay unverified."""
    return ANTHROPIC_MODEL_SPECS.get(anthropic_base_model(model))


ANTHROPIC_TOOL_SEARCH_MODELS = frozenset(
    model for model, spec in ANTHROPIC_MODEL_SPECS.items() if spec.tool_search
)
ANTHROPIC_CONTEXT_MGMT_MODELS = frozenset(
    model for model, spec in ANTHROPIC_MODEL_SPECS.items() if spec.context_editing
)
ANTHROPIC_COMPACTION_MODELS = frozenset(
    model for model, spec in ANTHROPIC_MODEL_SPECS.items() if spec.compaction
)
ANTHROPIC_ADAPTIVE_MODELS = frozenset(
    model for model, spec in ANTHROPIC_MODEL_SPECS.items() if spec.adaptive_thinking
)
ANTHROPIC_XHIGH_MODELS = frozenset(
    model for model, spec in ANTHROPIC_MODEL_SPECS.items() if "xhigh" in spec.effort_values
)
ANTHROPIC_WEB_SEARCH_MODELS = frozenset(
    model for model, spec in ANTHROPIC_MODEL_SPECS.items() if spec.dynamic_web_search
)
ANTHROPIC_COMPUTER_USE_LEGACY_MODELS = frozenset(
    model
    for model, spec in ANTHROPIC_MODEL_SPECS.items()
    if spec.computer_tool == "computer_20250124"
)
