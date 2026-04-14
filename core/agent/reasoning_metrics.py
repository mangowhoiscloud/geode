"""Reasoning efficiency metrics — DTR-inspired observability.

Tracks per-session reasoning quality signals:
- Thinking token ratio (thinking / total output)
- Empty rounds (text-only, no tool calls)
- Overthinking detection
- Cost per tool call

Reference: "Think Deep, Not Just Long" (arXiv 2602.13517)
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
    cost_per_tool_call: float = 0.0
    overthinking_detected: bool = False

    def compute_derived(self) -> None:
        """Recompute derived fields from raw counters."""
        total = self.thinking_tokens + self.output_tokens
        self.thinking_ratio = self.thinking_tokens / total if total > 0 else 0.0
        self.cost_per_tool_call = (
            self.cost_usd / self.tool_calls_total if self.tool_calls_total > 0 else 0.0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "total_rounds": self.total_rounds,
            "thinking_tokens": self.thinking_tokens,
            "output_tokens": self.output_tokens,
            "thinking_ratio": round(self.thinking_ratio, 4),
            "tool_calls_total": self.tool_calls_total,
            "empty_rounds": self.empty_rounds,
            "cost_usd": round(self.cost_usd, 6),
            "cost_per_tool_call": round(self.cost_per_tool_call, 6),
            "overthinking_detected": self.overthinking_detected,
        }
