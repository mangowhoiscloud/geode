"""Unified token tracking — local cost calculation + optional LangSmith injection.

Single-injection pattern: call ``get_tracker().record(...)`` once per LLM call.
Replaces the previous triple-call pattern::

    # Before — 3 scattered calls per LLM invocation:
    cost = calculate_cost(model, in_tok, out_tok)
    get_usage_accumulator().record(LLMUsage(...))
    track_token_usage(model, in_tok, out_tok)

    # After — 1 call:
    get_tracker().record(model, in_tok, out_tok)

Pricing verified 2026-03-14 against:
  - Anthropic: https://platform.claude.com/docs/en/docs/about-claude/pricing
  - OpenAI: https://developers.openai.com/api/docs/pricing/
"""

from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, NamedTuple

log = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────────────
# Data models
# ───────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class LLMUsage:
    """Single LLM call usage record."""

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
        }
        if self.thinking_tokens:
            d["thinking_tokens"] = self.thinking_tokens
        return d


@dataclass
class LLMUsageAccumulator:
    """Accumulates multiple LLMUsage records for session-level summary."""

    calls: list[LLMUsage] = field(default_factory=list)

    @property
    def total_input_tokens(self) -> int:
        return sum(c.input_tokens for c in self.calls)

    @property
    def total_output_tokens(self) -> int:
        return sum(c.output_tokens for c in self.calls)

    @property
    def total_thinking_tokens(self) -> int:
        return sum(c.thinking_tokens for c in self.calls)

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    def record(self, usage: LLMUsage) -> None:
        self.calls.append(usage)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "call_count": len(self.calls),
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": self.total_cost_usd,
        }
        thinking = self.total_thinking_tokens
        if thinking:
            d["total_thinking_tokens"] = thinking
        return d


# ───────────────────────────────────────────────────────────────────────────
# Model pricing — verified 2026-03-12
# ───────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """Per-token pricing for a single model.

    Anthropic: cache_write = input × 1.25, cache_read = input × 0.1
               thinking = output price (Extended Thinking billed as output)
    OpenAI:    cache_read = provider-specific fixed price (no write cost)
               thinking = output price (reasoning tokens billed as output)
    """

    input: float
    output: float
    cache_write: float = 0.0
    cache_read: float = 0.0
    thinking: float = 0.0


def _ant(input_mtok: float, output_mtok: float) -> ModelPrice:
    """Anthropic pricing with standard 5-min cache multipliers (1.25× / 0.1×).

    Extended Thinking tokens are billed at the same rate as output tokens.
    """
    inp = input_mtok / 1_000_000
    out = output_mtok / 1_000_000
    return ModelPrice(
        input=inp,
        output=out,
        cache_write=inp * 1.25,
        cache_read=inp * 0.1,
        thinking=out,
    )


def _oai(
    input_mtok: float,
    output_mtok: float,
    cached_mtok: float = 0.0,
    reasoning: bool = False,
) -> ModelPrice:
    """OpenAI pricing with optional cached-input price.

    Reasoning models (o3, o4-mini): reasoning tokens billed as output tokens.
    """
    out = output_mtok / 1_000_000
    return ModelPrice(
        input=input_mtok / 1_000_000,
        output=out,
        cache_read=cached_mtok / 1_000_000 if cached_mtok else 0.0,
        thinking=out if reasoning else 0.0,
    )


# fmt: off
MODEL_PRICING: dict[str, ModelPrice] = {
    # ── Anthropic (verified 2026-04-23) ────────────────────────────────
    # Source: https://platform.claude.com/docs/en/docs/about-claude/pricing
    "claude-opus-4-7":            _ant(5.00,  25.00),
    "claude-opus-4-6":            _ant(5.00,  25.00),
    "claude-opus-4-5":            _ant(5.00,  25.00),
    "claude-opus-4-1":            _ant(15.00, 75.00),
    "claude-opus-4":              _ant(15.00, 75.00),
    "claude-sonnet-4-6":          _ant(3.00,  15.00),
    "claude-sonnet-4-5-20250929": _ant(3.00,  15.00),
    "claude-sonnet-4":            _ant(3.00,  15.00),
    "claude-haiku-4-5-20251001":  _ant(1.00,   5.00),

    # ── OpenAI GPT-5 family (verified 2026-03-19) ─────────────────────
    # Source: https://developers.openai.com/api/docs/pricing/
    "gpt-5.4":      _oai(2.50, 15.00, cached_mtok=0.25),
    "gpt-5.2":      _oai(1.75, 14.00, cached_mtok=0.175),
    "gpt-5.1":      _oai(1.25, 10.00, cached_mtok=0.125),
    "gpt-5":        _oai(1.25, 10.00, cached_mtok=0.125),
    "gpt-5-mini":   _oai(0.25,  2.00, cached_mtok=0.025),
    "gpt-5-nano":   _oai(0.05,  0.40, cached_mtok=0.005),

    # ── OpenAI GPT-4 family (verified 2026-03-19) ─────────────────────
    "gpt-4.1":      _oai(2.00,  8.00),
    "gpt-4.1-mini": _oai(0.40,  1.60),
    "gpt-4.1-nano": _oai(0.20,  0.80, cached_mtok=0.05),

    # ── OpenAI Reasoning (verified 2026-03-19) ─────────────────────────
    "o3":       _oai(2.00,  8.00, reasoning=True),
    "o4-mini":  _oai(1.10,  4.40, cached_mtok=0.275, reasoning=True),

    # ── ZhipuAI GLM (verified 2026-04-15) ──────────────────────────────
    # Source: https://open.bigmodel.cn/pricing + https://docs.z.ai
    "glm-5.1":         _oai(0.95,  3.15),
    "glm-5":           _oai(0.72,  2.30),
    "glm-5-turbo":     _oai(1.20,  4.00),
    "glm-5v-turbo":    _oai(1.20,  4.00),
    "glm-4.7":         _oai(0.40,  1.75),
    "glm-4.7-flash":   _oai(0.00,  0.00),  # free tier

    # ── OpenAI Codex (Plus quota — no API billing) ─────────────────────
    # Uses chatgpt.com/backend-api/codex, billed against Plus subscription
    "gpt-5.4-mini":    _oai(0.00,  0.00),  # Plus quota
    "gpt-5.3-codex":   _oai(0.00,  0.00),  # Plus quota
    "gpt-5.2-codex":   _oai(0.00,  0.00),  # Plus quota
    "gpt-5.1-codex-max":  _oai(0.00,  0.00),
    "gpt-5.1-codex-mini": _oai(0.00,  0.00),
}
# fmt: on


# ───────────────────────────────────────────────────────────────────────────
# TokenTracker — single record() replaces 3 scattered calls
# ───────────────────────────────────────────────────────────────────────────


# fmt: off
MODEL_CONTEXT_WINDOW: dict[str, int] = {
    "claude-opus-4-7":          1_000_000,
    "claude-opus-4-6":          1_000_000,
    "claude-opus-4-5":            200_000,
    "claude-opus-4-1":            200_000,
    "claude-opus-4":              200_000,
    "claude-sonnet-4-6":        1_000_000,
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-sonnet-4":            200_000,
    "claude-haiku-4-5-20251001":  200_000,
    "gpt-5.4":                  1_047_576,
    "gpt-5.2":                    128_000,
    "gpt-5.1":                    128_000,
    "gpt-5":                      128_000,
    "gpt-5-mini":                 128_000,
    "gpt-5-nano":                 128_000,
    "gpt-4.1":                  1_047_576,
    "gpt-4.1-mini":             1_047_576,
    "gpt-4.1-nano":             1_047_576,
    "o3":                         200_000,
    "o4-mini":                    200_000,
    "glm-5.1":                    202_752,
    "glm-5":                      200_000,
    "glm-5-turbo":                202_752,
    "glm-5v-turbo":               202_752,
    "glm-4.7":                    200_000,
    "glm-4.7-flash":              200_000,
    "gpt-5.4-mini":             1_047_576,
    "gpt-5.3-codex":              200_000,
    "gpt-5.2-codex":              200_000,
    "gpt-5.1-codex-max":          200_000,
    "gpt-5.1-codex-mini":         200_000,
}
# fmt: on


class UsageSnapshot(NamedTuple):
    """Immutable snapshot of cumulative usage at a point in time."""

    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    call_count: int


class TokenTracker:
    """Unified token tracker — inject once, call ``record()`` everywhere.

    Usage::

        tracker = get_tracker()
        usage = tracker.record("claude-opus-4-6", 1200, 350)
        print(tracker.summary())   # session-level totals
    """

    __slots__ = ("_accumulator", "_pricing")

    def __init__(self, pricing: dict[str, ModelPrice] | None = None) -> None:
        self._pricing = pricing or MODEL_PRICING
        self._accumulator = LLMUsageAccumulator()

    # -- public API --------------------------------------------------------

    @property
    def accumulator(self) -> LLMUsageAccumulator:
        return self._accumulator

    def record(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        thinking_tokens: int = 0,
    ) -> LLMUsage:
        """Record one LLM call: cost → accumulator → optional LangSmith."""
        cost = self.calculate_cost(
            model,
            input_tokens,
            output_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            thinking_tokens=thinking_tokens,
        )
        usage = LLMUsage(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            thinking_tokens=thinking_tokens,
            cost_usd=cost,
        )
        self._accumulator.record(usage)
        self._inject_langsmith(model, input_tokens, output_tokens, cost)
        self._persist_usage(model, input_tokens, output_tokens, cost)
        return usage

    def calculate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        thinking_tokens: int = 0,
    ) -> float:
        """Calculate cost in USD for a single LLM call."""
        price = self._pricing.get(model)
        if price is None:
            log.warning("Unknown model '%s' — cost tracked as $0.00", model)
            return 0.0
        cost = input_tokens * price.input + output_tokens * price.output
        if cache_creation_tokens:
            cost += cache_creation_tokens * price.cache_write
        if cache_read_tokens:
            cost += cache_read_tokens * price.cache_read
        if thinking_tokens and price.thinking:
            cost += thinking_tokens * price.thinking
        return cost

    def reset(self) -> None:
        """Reset accumulator for a new session."""
        self._accumulator = LLMUsageAccumulator()

    def summary(self) -> dict[str, Any]:
        """Session-level totals."""
        return self._accumulator.to_dict()

    def context_usage_pct(self, model: str) -> float:
        """Approximate context window usage as a percentage."""
        max_ctx = MODEL_CONTEXT_WINDOW.get(model, 200_000)
        total_input = self._accumulator.total_input_tokens
        return min(total_input / max_ctx * 100, 100.0)

    # -- Per-turn snapshot / delta -----------------------------------------

    def snapshot(self) -> UsageSnapshot:
        """Capture current cumulative totals as an immutable snapshot."""
        acc = self._accumulator
        return UsageSnapshot(
            total_input_tokens=acc.total_input_tokens,
            total_output_tokens=acc.total_output_tokens,
            total_cost_usd=acc.total_cost_usd,
            call_count=len(acc.calls),
        )

    def delta_since(self, snap: UsageSnapshot) -> UsageSnapshot:
        """Compute delta between current state and a previous snapshot."""
        acc = self._accumulator
        return UsageSnapshot(
            total_input_tokens=acc.total_input_tokens - snap.total_input_tokens,
            total_output_tokens=acc.total_output_tokens - snap.total_output_tokens,
            total_cost_usd=acc.total_cost_usd - snap.total_cost_usd,
            call_count=len(acc.calls) - snap.call_count,
        )

    def context_usage_pct_for(self, model: str, input_tokens: int) -> float:
        """Context window usage % for a specific input token count."""
        max_ctx = MODEL_CONTEXT_WINDOW.get(model, 200_000)
        return min(input_tokens / max_ctx * 100, 100.0)

    # -- LangSmith (optional, fire-and-forget) -----------------------------

    @staticmethod
    def _inject_langsmith(
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Inject metrics into current LangSmith RunTree (no-op if disabled)."""
        try:
            tracing = os.environ.get("LANGCHAIN_TRACING_V2", "").lower() == "true"
            api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get(
                "LANGSMITH_API_KEY",
            )
            if not (tracing and api_key):
                return
            from langsmith.run_helpers import get_current_run_tree

            run_tree = get_current_run_tree()
            if run_tree is None:
                return
            if not hasattr(run_tree, "extra") or run_tree.extra is None:
                run_tree.extra = {}
            run_tree.extra["metrics"] = {
                "model": model,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
                "cost_usd": cost_usd,
            }
        except Exception:
            log.debug("LangSmith injection skipped", exc_info=True)

    # -- Persistent usage store (fire-and-forget) ---------------------------

    @staticmethod
    def _persist_usage(
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        """Persist usage to ~/.geode/usage/ JSONL (no-op on failure)."""
        try:
            from core.llm.usage_store import get_usage_store

            get_usage_store().record(model, input_tokens, output_tokens, cost_usd)
        except Exception:
            log.debug("Usage persistence skipped", exc_info=True)


# ───────────────────────────────────────────────────────────────────────────
# Context-local singleton
# ───────────────────────────────────────────────────────────────────────────

_tracker_ctx: ContextVar[TokenTracker | None] = ContextVar(
    "token_tracker",
    default=None,
)


def get_tracker() -> TokenTracker:
    """Get or create context-local TokenTracker (thread-safe)."""
    tracker = _tracker_ctx.get()
    if tracker is None:
        tracker = TokenTracker()
        _tracker_ctx.set(tracker)
    return tracker


def reset_tracker() -> None:
    """Reset context-local tracker (fresh accumulator)."""
    tracker = _tracker_ctx.get()
    if tracker is not None:
        tracker.reset()
    else:
        _tracker_ctx.set(TokenTracker())


# ───────────────────────────────────────────────────────────────────────────
# Backward-compatible aliases (thin wrappers → TokenTracker)
# ───────────────────────────────────────────────────────────────────────────


def calculate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    """Backward-compatible: delegates to ``get_tracker().calculate_cost()``."""
    return get_tracker().calculate_cost(
        model,
        input_tokens,
        output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
    )


def get_usage_accumulator() -> LLMUsageAccumulator:
    """Backward-compatible: returns ``get_tracker().accumulator``."""
    return get_tracker().accumulator


def reset_usage_accumulator() -> None:
    """Backward-compatible: delegates to ``reset_tracker()``."""
    reset_tracker()


def track_token_usage(
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Backward-compatible: full record() (accumulator + LangSmith)."""
    get_tracker().record(model, input_tokens, output_tokens)
