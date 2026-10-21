"""Model-derived context budget policy.

This module is the single home for context-window-derived budgets.  Callers
should resolve a :class:`ContextBudgetPolicy` instead of reintroducing local
percentage or token ceilings.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from core.llm.adapters.base import AdapterCallRequest, UsageSummary

DEFAULT_CONTEXT_WINDOW_TOKENS = 200_000

# Local maintenance preference, not a universal provider/rate-limit boundary.
# Retain the historical name for callers; crossing it never establishes overflow.
ABSOLUTE_TOKEN_CEILING = 200_000
TOKEN_ESTIMATE_CHARS_PER_TOKEN = 4
# Smallest supported positive tool-result limit (guard and offload threshold,
# in tokens). Lower configured values are raised to it so a short refusal,
# such as read_session_messages' limit error, reaches the model intact
# instead of being truncated to ``{}``; 0 still disables either limit.
MIN_TOOL_RESULT_TOKENS = 32
DEFAULT_TOOLS_OVERHEAD_TOKENS = 10_000

SAFETY_MARGIN_MULTIPLIER = 1.20
# Provider-reported prompt tokens per heuristic token. Dense text such as hex
# digests tokenizes at about 2 chars/token, so 4 chars/token plus the static
# margin can hide half of the real context. A smaller request is too small to
# calibrate; the cap bounds malformed usage.
TOKEN_RATIO_MIN_SAMPLE_TOKENS = 8_000
MAX_OBSERVED_TOKEN_RATIO = 8.0
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
    provider: str = ""
    source: str = ""
    max_input_tokens: int | None = None
    context_origin: Literal["provider_catalog", "client_default", "fallback", "override"] = (
        "fallback"
    )
    observed_token_ratio: float = 0.0
    """Latest provider-reported prompt tokens per heuristic token; 0 is unobserved."""

    @property
    def estimate_multiplier(self) -> float:
        """Static safety margin, raised to the observed provider/heuristic ratio."""
        return max(self.safety_margin, self.observed_token_ratio)

    @property
    def effective_prompt_budget_tokens(self) -> int:
        planned = max(self.context_window - self.output_reserve_tokens, 1)
        return min(planned, self.max_input_tokens) if self.max_input_tokens is not None else planned

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
        # Adaptive prune counts unmargined heuristic message tokens; dividing by
        # the estimate multiplier lands the pruned history at the warning level
        # as measured, rather than up to 1.2x (or the observed ratio) above it.
        return max(1, int(self.warning_tokens / self.estimate_multiplier))

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
        return ceil(raw_tokens * self.estimate_multiplier)

    def resolve_keep_recent(self, requested: int) -> int:
        cap = self.tier.keep_recent_cap
        if cap is None:
            return requested
        return min(requested, cap)

    def resolve_aggressive_keep_recent(self, requested: int) -> int:
        return max(AGGRESSIVE_KEEP_RECENT_FLOOR, self.resolve_keep_recent(requested) // 2)


def observed_prompt_tokens(usage: UsageSummary, *, provider: str) -> int | None:
    """Return the provider-reported prompt size, or None when it was not reported.

    Anthropic reports cache reads and writes beside ``input_tokens``; OpenAI,
    Codex and Chat Completions routes already include cached input.
    """
    if not usage.input_tokens_present:
        return None
    from core.llm.model_catalog import normalize_model_provider

    tokens = usage.input_tokens
    if normalize_model_provider(provider) == "anthropic":
        tokens += usage.cached_input_tokens + usage.cache_write_tokens
    return tokens


def calibrate_token_ratio(observed_tokens: int, raw_estimated_tokens: int) -> float | None:
    """Calibrate the heuristic from one request large enough to measure."""
    if raw_estimated_tokens < TOKEN_RATIO_MIN_SAMPLE_TOKENS or observed_tokens <= 0:
        return None
    return min(observed_tokens / raw_estimated_tokens, MAX_OBSERVED_TOKEN_RATIO)


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
    provider: str | None = None,
    source: str | None = None,
    output_reserve_tokens: int | None = None,
) -> ContextBudgetPolicy:
    """Resolve one route's conservative planning policy, not account entitlement."""
    from core.llm.model_catalog import get_model_catalog_spec

    spec = get_model_catalog_spec(model, provider, source=source)
    resolved_window = spec.context_window
    if context_window is not None:
        resolved_window = max(1, int(context_window))
        if spec.max_context_window is not None:
            resolved_window = min(resolved_window, spec.max_context_window)
    if output_reserve_tokens is not None and output_reserve_tokens < 0:
        raise ValueError("output_reserve_tokens must be non-negative")
    return ContextBudgetPolicy(
        model=model,
        context_window=resolved_window,
        tier=_resolve_tier(resolved_window),
        output_reserve_tokens=(
            _resolve_output_reserve(resolved_window)
            if output_reserve_tokens is None
            else output_reserve_tokens
        ),
        safety_margin=SAFETY_MARGIN_MULTIPLIER,
        default_tools_overhead_tokens=DEFAULT_TOOLS_OVERHEAD_TOKENS,
        absolute_ceiling_tokens=ABSOLUTE_TOKEN_CEILING,
        provider=spec.provider,
        source=spec.source,
        max_input_tokens=spec.max_input_tokens,
        context_origin="override" if context_window is not None else spec.context_origin,
    )


def resolve_request_context_budget(
    request: AdapterCallRequest, *, provider: str, source: str
) -> ContextBudgetPolicy:
    """Use the provider's wire output arithmetic for the final selected request.

    Codex omits its output cap. Its reserve remains an explicit local default,
    not a claim about the subscription backend's output allowance.
    """
    from core.llm.model_catalog import normalize_model_provider

    provider = normalize_model_provider(provider)
    output: int | None = request.max_tokens
    if provider == "openai":
        from core.llm.adapters._openai_common import effective_output_tokens

        output = effective_output_tokens(
            request, backend="codex" if source == "subscription" else "platform"
        )
    elif provider == "anthropic":
        from core.llm.adapters._anthropic_common import effective_output_tokens as anthropic_output

        output = anthropic_output(request)
    elif provider == "glm":
        from core.llm.providers.glm import effective_output_tokens as glm_output

        output = glm_output(request)
    return resolve_context_budget_policy(
        request.model, provider=provider, source=source, output_reserve_tokens=output
    )
