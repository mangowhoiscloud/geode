"""Model-derived context budget policy.

This module is the single home for context-window-derived budgets.  Callers
should resolve a :class:`ContextBudgetPolicy` instead of reintroducing local
percentage or token ceilings.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil

DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000

ABSOLUTE_TOKEN_CEILING = 200_000
TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4
DEFAULT_TOOLS_OVERHEAD_TOKENS = 10_000

SAFETY_MARGIN_MULTIPLIER = 1.20
DEFAULT_OUTPUT_RESERVE_TOKENS = 20_000
MIN_PROMPT_BUDGET_TOKENS = 8_000

SMALL_CONTEXT_MAX_TOKENS = 256_000
STANDARD_CONTEXT_MAX_TOKENS = 512_000

SMALL_WARNING_THRESHOLD_PCT = 50.0
SMALL_CRITICAL_THRESHOLD_PCT = 90.0
STANDARD_WARNING_THRESHOLD_PCT = 70.0
STANDARD_CRITICAL_THRESHOLD_PCT = 90.0
LARGE_WARNING_THRESHOLD_PCT = 80.0
LARGE_CRITICAL_THRESHOLD_PCT = 90.0

SMALL_KEEP_RECENT_CAP = 5
STANDARD_KEEP_RECENT_CAP = 8
AGGRESSIVE_KEEP_RECENT_FLOOR = 3
PRUNE_ACTIVATION_MESSAGE_COUNT = 30

TOOL_SUMMARY_CONTEXT_SHARE = 0.02
TOOL_RESULT_CONTEXT_SHARE = 0.05
ANTHROPIC_COMPACT_TRIGGER_FLOOR_TOKENS = 50_000

SUMMARY_MIN_TOKENS = 2_000
SUMMARY_TARGET_RATIO = 0.20
SUMMARY_CONTEXT_SHARE = 0.05
SUMMARY_TOKENS_CEILING = 12_000
SUMMARY_INPUT_MESSAGE_MAX_CHARS = 6_000
SUMMARY_INPUT_MESSAGE_HEAD_CHARS = 4_000
SUMMARY_INPUT_MESSAGE_TAIL_CHARS = 1_500
SUMMARY_TOOL_ARGS_MAX_CHARS = 1_500
SUMMARY_TOOL_ARGS_HEAD_CHARS = 1_200
SUMMARY_OVERFLOW_RETRIES = 2
TOOL_ARG_STRING_HEAD_CHARS = 200
TOOL_RESULT_SUMMARY_MIN_CHARS = 200


@dataclass(frozen=True, slots=True)
class ContextBudgetTier:
    """Tier thresholds for a resolved context window."""

    name: str
    max_context_window: int | None
    warning_threshold_pct: float
    critical_threshold_pct: float
    keep_recent_cap: int | None

    def matches(self, context_window: int) -> bool:
        return self.max_context_window is None or context_window <= self.max_context_window


CONTEXT_BUDGET_TIERS: tuple[ContextBudgetTier, ...] = (
    ContextBudgetTier(
        name="small",
        max_context_window=SMALL_CONTEXT_MAX_TOKENS,
        warning_threshold_pct=SMALL_WARNING_THRESHOLD_PCT,
        critical_threshold_pct=SMALL_CRITICAL_THRESHOLD_PCT,
        keep_recent_cap=SMALL_KEEP_RECENT_CAP,
    ),
    ContextBudgetTier(
        name="standard",
        max_context_window=STANDARD_CONTEXT_MAX_TOKENS,
        warning_threshold_pct=STANDARD_WARNING_THRESHOLD_PCT,
        critical_threshold_pct=STANDARD_CRITICAL_THRESHOLD_PCT,
        keep_recent_cap=STANDARD_KEEP_RECENT_CAP,
    ),
    ContextBudgetTier(
        name="large",
        max_context_window=None,
        warning_threshold_pct=LARGE_WARNING_THRESHOLD_PCT,
        critical_threshold_pct=LARGE_CRITICAL_THRESHOLD_PCT,
        keep_recent_cap=None,
    ),
)


@dataclass(frozen=True, slots=True)
class ContextBudgetPolicy:
    """Resolved context budget for one model/window."""

    model: str
    context_window: int
    tier: ContextBudgetTier
    output_reserve_tokens: int
    safety_margin: float
    default_tools_overhead_tokens: int
    absolute_ceiling_tokens: int

    @property
    def effective_prompt_budget_tokens(self) -> int:
        return max(self.context_window - self.output_reserve_tokens, 1)

    @property
    def warning_threshold_pct(self) -> float:
        return self.tier.warning_threshold_pct

    @property
    def critical_threshold_pct(self) -> float:
        return self.tier.critical_threshold_pct

    @property
    def warning_tokens(self) -> int:
        return max(1, int(self.effective_prompt_budget_tokens * self.warning_threshold_pct / 100))

    @property
    def critical_tokens(self) -> int:
        threshold = int(self.effective_prompt_budget_tokens * self.critical_threshold_pct / 100)
        return max(self.warning_tokens + 1, threshold)

    @property
    def prune_budget_tokens(self) -> int:
        return self.warning_tokens

    @property
    def tool_summary_threshold_tokens(self) -> int:
        return max(1, int(self.effective_prompt_budget_tokens * TOOL_SUMMARY_CONTEXT_SHARE))

    @property
    def per_tool_result_limit_tokens(self) -> int:
        return max(1, int(self.context_window * TOOL_RESULT_CONTEXT_SHARE))

    @property
    def anthropic_compact_trigger_tokens(self) -> int:
        return max(ANTHROPIC_COMPACT_TRIGGER_FLOOR_TOKENS, self.warning_tokens)

    @property
    def max_summary_tokens(self) -> int:
        return max(
            SUMMARY_MIN_TOKENS,
            min(int(self.context_window * SUMMARY_CONTEXT_SHARE), SUMMARY_TOKENS_CEILING),
        )

    @property
    def summary_input_message_max_chars(self) -> int:
        return SUMMARY_INPUT_MESSAGE_MAX_CHARS

    @property
    def summary_input_message_head_chars(self) -> int:
        return SUMMARY_INPUT_MESSAGE_HEAD_CHARS

    @property
    def summary_input_message_tail_chars(self) -> int:
        return SUMMARY_INPUT_MESSAGE_TAIL_CHARS

    @property
    def summary_tool_args_max_chars(self) -> int:
        return SUMMARY_TOOL_ARGS_MAX_CHARS

    @property
    def summary_tool_args_head_chars(self) -> int:
        return SUMMARY_TOOL_ARGS_HEAD_CHARS

    @property
    def summary_overflow_retries(self) -> int:
        return SUMMARY_OVERFLOW_RETRIES

    def summary_output_tokens(self, source_tokens: int | None = None) -> int:
        if source_tokens is None:
            return self.max_summary_tokens
        target = int(max(0, source_tokens) * SUMMARY_TARGET_RATIO)
        return max(SUMMARY_MIN_TOKENS, min(target, self.max_summary_tokens))

    def apply_safety_margin(self, raw_tokens: int) -> int:
        return ceil(raw_tokens * self.safety_margin)

    def resolve_keep_recent(self, requested: int) -> int:
        cap = self.tier.keep_recent_cap
        if cap is None:
            return requested
        return min(requested, cap)

    def resolve_aggressive_keep_recent(self, requested: int) -> int:
        return max(AGGRESSIVE_KEEP_RECENT_FLOOR, self.resolve_keep_recent(requested) // 2)


def _resolve_context_window(model: str, context_window: int | None = None) -> int:
    # Floor at 1 — a zero/negative window (bad catalog entry or caller bug)
    # must degrade to tiny-budget behaviour, never a ZeroDivisionError in
    # check_context's usage-percentage math.
    if context_window is not None:
        return max(1, int(context_window))
    try:
        from core.llm.token_tracker import MODEL_CONTEXT_WINDOW

        window = MODEL_CONTEXT_WINDOW.get(model, DEFAULT_CONTEXT_WINDOW_TOKENS)
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_CONTEXT_WINDOW_TOKENS
    # Trust only real positive ints — a mocked module (tests patch
    # sys.modules['core.llm.token_tracker']) or a garbage catalog entry
    # otherwise coerces to a 1-token window and every loop turn trips
    # context-exhausted before its actual assertion.
    if not isinstance(window, int) or isinstance(window, bool) or window < 1:
        return DEFAULT_CONTEXT_WINDOW_TOKENS
    return window


def _resolve_tier(context_window: int) -> ContextBudgetTier:
    for tier in CONTEXT_BUDGET_TIERS:
        if tier.matches(context_window):
            return tier
    return CONTEXT_BUDGET_TIERS[-1]


def _resolve_output_reserve(context_window: int) -> int:
    max_reserve = max(context_window - MIN_PROMPT_BUDGET_TOKENS, 0)
    return min(DEFAULT_OUTPUT_RESERVE_TOKENS, max_reserve)


def resolve_context_budget_policy(
    model: str = "unknown",
    *,
    context_window: int | None = None,
) -> ContextBudgetPolicy:
    """Resolve model/window-derived context policy."""

    resolved_window = _resolve_context_window(model, context_window)
    return ContextBudgetPolicy(
        model=model,
        context_window=resolved_window,
        tier=_resolve_tier(resolved_window),
        output_reserve_tokens=_resolve_output_reserve(resolved_window),
        safety_margin=SAFETY_MARGIN_MULTIPLIER,
        default_tools_overhead_tokens=DEFAULT_TOOLS_OVERHEAD_TOKENS,
        absolute_ceiling_tokens=ABSOLUTE_TOKEN_CEILING,
    )
