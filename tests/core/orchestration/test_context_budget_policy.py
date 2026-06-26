"""Tests for model-derived context budget policy."""

from __future__ import annotations

from core.orchestration.context_budget import (
    ABSOLUTE_TOKEN_CEILING,
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    DEFAULT_TOOLS_OVERHEAD_TOKENS,
    SAFETY_MARGIN_MULTIPLIER,
    resolve_context_budget_policy,
)


def test_glm_52_resolves_conservative_payg_window() -> None:
    policy = resolve_context_budget_policy("glm-5.2")

    # 202_752, not 1M: the plain PAYG id keeps the conservative window (0.99.246
    # decision — 1M is the DevPack ``[1m]`` alias surface; funded live test required)
    assert policy.context_window == 202_752
    assert policy.tier.name == "small"
    assert policy.output_reserve_tokens == DEFAULT_OUTPUT_RESERVE_TOKENS
    assert policy.warning_tokens < policy.critical_tokens < policy.effective_prompt_budget_tokens


def test_large_window_keeps_absolute_ceiling_and_output_reserve() -> None:
    policy = resolve_context_budget_policy("claude-opus-4-6")

    assert policy.tier.name == "large"
    assert policy.absolute_ceiling_tokens == ABSOLUTE_TOKEN_CEILING
    assert policy.output_reserve_tokens == DEFAULT_OUTPUT_RESERVE_TOKENS
    assert policy.anthropic_compact_trigger_tokens == policy.warning_tokens


def test_small_window_caps_keep_recent_and_tool_result_size() -> None:
    policy = resolve_context_budget_policy("glm-5")

    assert policy.resolve_keep_recent(10) == 5
    assert policy.resolve_aggressive_keep_recent(10) == 3
    assert policy.per_tool_result_limit_tokens > 0


def test_policy_carries_estimation_margin_and_tool_overhead() -> None:
    policy = resolve_context_budget_policy("unknown-model")

    assert policy.default_tools_overhead_tokens == DEFAULT_TOOLS_OVERHEAD_TOKENS
    assert policy.safety_margin == SAFETY_MARGIN_MULTIPLIER
    assert policy.apply_safety_margin(100) == 120
