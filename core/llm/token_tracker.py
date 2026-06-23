"""Unified token tracking — local cost calculation + hook lifecycle emission.

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
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, NamedTuple

log = logging.getLogger(__name__)

# ───────────────────────────────────────────────────────────────────────────
# Data models
# ───────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class LLMUsage:
    """Single LLM call usage record.

    Cache fields (added 2026-05-11 for Defect A F-A2): we previously
    recorded the *cost* of cache_creation / cache_read tokens through
    ``calculate_cost`` but the token counts themselves were dropped at
    record time. That made downstream tracker snapshots invisible to
    anyone who needed cache hit rate (prompt-caching audit) or wanted
    to emit ``inspect_ai.model.ModelUsage`` with the cache fields
    populated. Keep these on the record so a snapshot delta preserves
    the full per-call shape.
    """

    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
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
        if self.cache_creation_tokens:
            d["cache_creation_tokens"] = self.cache_creation_tokens
        if self.cache_read_tokens:
            d["cache_read_tokens"] = self.cache_read_tokens
        return d


@dataclass
class LLMUsageAccumulator:
    """Accumulates multiple LLMUsage records for session-level summary."""

    calls: list[LLMUsage] = field(default_factory=list)
    # One-shot guard for the degraded-cache warning (reset per accumulator,
    # i.e. per session). Underscore-prefixed so it is not mistaken for a
    # public field; excluded from ``to_dict``.
    _warned_low_cache: bool = field(default=False, repr=False)

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
    def total_cache_creation_tokens(self) -> int:
        return sum(c.cache_creation_tokens for c in self.calls)

    @property
    def total_cache_read_tokens(self) -> int:
        return sum(c.cache_read_tokens for c in self.calls)

    @property
    def cache_hit_rate(self) -> float:
        """Fraction of cacheable input tokens served from cache.

        ``read / (read + creation)`` — 1.0 means every cacheable token was a
        cache hit, 0.0 means every one was a fresh write (the symptom of a
        silently-invalidated prefix). Returns 0.0 when there is no cache
        activity yet (avoids div-by-zero).
        """
        read = self.total_cache_read_tokens
        denom = read + self.total_cache_creation_tokens
        return read / denom if denom else 0.0

    @property
    def total_cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    def maybe_warn_low_cache_hit_rate(
        self, *, min_tokens: int = 50_000, threshold: float = 0.3
    ) -> None:
        """Emit a one-shot WARNING when the prompt-cache hit rate is degraded.

        Fires at most once per accumulator (per session) once cumulative
        cacheable tokens exceed *min_tokens* and the hit rate is below
        *threshold*. A persistently low ratio is the visible signature of a
        silent prefix-invalidator — volatile content in the cached prefix, a
        prefix below the model's minimum, or the 20-block lookback exceeded.
        Without this, a cache that has dropped to ~0% is invisible until an
        operator (or the provider) notices the bill.
        """
        if self._warned_low_cache:
            return
        read = self.total_cache_read_tokens
        denom = read + self.total_cache_creation_tokens
        # Advisory telemetry must never break a real LLM-call path. Token totals
        # are ints in production, but tests (and any future adapter that passes a
        # mocked usage object) may carry non-numeric values — skip silently
        # rather than raise from this record() hook.
        if not isinstance(denom, int) or denom < min_tokens:
            return
        rate = read / denom if denom else 0.0
        if rate < threshold:
            self._warned_low_cache = True
            log.warning(
                "prompt cache hit rate degraded: %.1f%% (read=%d, creation=%d) "
                "over %d cacheable tokens — check for volatile content in the "
                "cached prefix, a prefix below the model minimum, or a long "
                "tool-heavy turn exceeding the 20-block lookback window",
                rate * 100.0,
                read,
                self.total_cache_creation_tokens,
                denom,
            )

    def record(self, usage: LLMUsage) -> None:
        self.calls.append(usage)
        self.maybe_warn_low_cache_hit_rate()

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
        cache_w = self.total_cache_creation_tokens
        if cache_w:
            d["total_cache_creation_tokens"] = cache_w
        cache_r = self.total_cache_read_tokens
        if cache_r:
            d["total_cache_read_tokens"] = cache_r
        if cache_w or cache_r:
            d["cache_hit_rate"] = round(self.cache_hit_rate, 3)
        return d


# ───────────────────────────────────────────────────────────────────────────
# Model pricing — verified 2026-03-12
# ───────────────────────────────────────────────────────────────────────────


# P3-B (2026-05-17) — ``ModelPrice`` + pricing dict + context windows
# now live in ``core/llm/model_pricing.toml`` + ``core.llm.pricing_loader``.
# The legacy ``_ant`` / ``_oai`` helpers and inlined dict literals were
# replaced by a single ``load_pricing_catalogue()`` call at import time.
# Public surface unchanged — every consumer (``token_tracker.ModelPrice``,
# ``MODEL_PRICING``, ``MODEL_CONTEXT_WINDOW``, monkeypatched test sites)
# keeps working without modification because we re-export from here.
from core.llm.pricing_loader import (  # noqa: E402
    ModelPrice,
    load_pricing_catalogue,
)

_catalogue = load_pricing_catalogue()
MODEL_PRICING: dict[str, ModelPrice] = dict(_catalogue.pricing)
MODEL_CONTEXT_WINDOW: dict[str, int] = dict(_catalogue.context_windows)


# ───────────────────────────────────────────────────────────────────────────
# TokenTracker — single record() replaces 3 scattered calls
# ───────────────────────────────────────────────────────────────────────────


class UsageSnapshot(NamedTuple):
    """Immutable snapshot of cumulative usage at a point in time.

    Defect A F-A1 (2026-05-11): added thinking / cache fields so a
    snapshot delta carries the full per-call shape. AgenticLoop now
    captures one of these at the top of ``arun`` and the finalize path
    turns ``delta_since(snap)`` into an ``LLMUsage`` aggregate that
    GeodeModelAPI translates into ``inspect_ai.model.ModelUsage``.
    """

    total_input_tokens: int
    total_output_tokens: int
    total_thinking_tokens: int
    total_cache_creation_tokens: int
    total_cache_read_tokens: int
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
        """Record one LLM call: cost → accumulator → persistent store."""
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
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            cost_usd=cost,
        )
        self._accumulator.record(usage)
        self._persist_usage(
            model,
            input_tokens,
            output_tokens,
            cost,
            cache_creation_tokens=cache_creation_tokens,
            cache_read_tokens=cache_read_tokens,
            thinking_tokens=thinking_tokens,
        )
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
            total_thinking_tokens=acc.total_thinking_tokens,
            total_cache_creation_tokens=acc.total_cache_creation_tokens,
            total_cache_read_tokens=acc.total_cache_read_tokens,
            total_cost_usd=acc.total_cost_usd,
            call_count=len(acc.calls),
        )

    def delta_since(self, snap: UsageSnapshot) -> UsageSnapshot:
        """Compute delta between current state and a previous snapshot."""
        acc = self._accumulator
        return UsageSnapshot(
            total_input_tokens=acc.total_input_tokens - snap.total_input_tokens,
            total_output_tokens=acc.total_output_tokens - snap.total_output_tokens,
            total_thinking_tokens=acc.total_thinking_tokens - snap.total_thinking_tokens,
            total_cache_creation_tokens=acc.total_cache_creation_tokens
            - snap.total_cache_creation_tokens,
            total_cache_read_tokens=acc.total_cache_read_tokens - snap.total_cache_read_tokens,
            total_cost_usd=acc.total_cost_usd - snap.total_cost_usd,
            call_count=len(acc.calls) - snap.call_count,
        )

    def context_usage_pct_for(self, model: str, input_tokens: int) -> float:
        """Context window usage % for a specific input token count."""
        max_ctx = MODEL_CONTEXT_WINDOW.get(model, 200_000)
        return min(input_tokens / max_ctx * 100, 100.0)

    # -- Persistent usage store (fire-and-forget) ---------------------------

    @staticmethod
    def _persist_usage(
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        *,
        cache_creation_tokens: int = 0,
        cache_read_tokens: int = 0,
        thinking_tokens: int = 0,
    ) -> None:
        """Persist usage to ~/.geode/usage/ JSONL (no-op on failure).

        Cache / thinking fields added 2026-05-11 to close the F-A2 leak.
        ``record`` already populated these on the in-memory accumulator
        but ``_persist_usage`` dropped them, so the JSONL on disk and
        ``geode history`` rollups silently zero-rated prompt-cache cost.
        """
        try:
            from core.llm.usage_store import get_usage_store

            get_usage_store().record(
                model,
                input_tokens,
                output_tokens,
                cost_usd,
                cache_creation_tokens=cache_creation_tokens,
                cache_read_tokens=cache_read_tokens,
                thinking_tokens=thinking_tokens,
            )
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
    """Backward-compatible: full record() (accumulator + persistent store)."""
    get_tracker().record(model, input_tokens, output_tokens)
