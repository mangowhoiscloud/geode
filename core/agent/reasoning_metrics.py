"""Reasoning efficiency metrics — DTR-inspired observability.

Tracks per-session reasoning quality signals:
- Thinking token ratio (thinking / output, input excluded — GEODE variant,
  not the layer-wise JSD ratio from the original DTR paper)
- Empty rounds (text-only rounds flagged as overthinking, counted once each)
- Overthinking detection
- Cost per tool call (None when no tool was called)

Inspired by "Think Deep, Not Just Long" (arXiv 2602.13517) — depth-aware
budgeting. The metric definitions here diverge from the paper; see field
docstrings for exact semantics.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ReasoningMetrics:
    """Per-session reasoning efficiency snapshot."""

    total_rounds: int = 0
    thinking_tokens: int = 0
    output_tokens: int = 0
    thinking_ratio: float = 0.0
    tool_calls_total: int = 0
    empty_rounds: int = 0
    cost_usd: float = 0.0
    cost_per_tool_call: float | None = None
    overthinking_detected: bool = False

    def compute_derived(self) -> None:
        """Recompute derived fields from raw counters."""
        total = self.thinking_tokens + self.output_tokens
        self.thinking_ratio = self.thinking_tokens / total if total > 0 else 0.0
        self.cost_per_tool_call = (
            self.cost_usd / self.tool_calls_total if self.tool_calls_total > 0 else None
        )

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "total_rounds": self.total_rounds,
            "thinking_tokens": self.thinking_tokens,
            "output_tokens": self.output_tokens,
            "thinking_ratio": round(self.thinking_ratio, 4),
            "tool_calls_total": self.tool_calls_total,
            "empty_rounds": self.empty_rounds,
            "cost_usd": round(self.cost_usd, 6),
            "overthinking_detected": self.overthinking_detected,
        }
        if self.cost_per_tool_call is not None:
            d["cost_per_tool_call"] = round(self.cost_per_tool_call, 6)
        return d
