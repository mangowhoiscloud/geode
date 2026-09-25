"""Tests for model-derived context budget policy."""

from __future__ import annotations

from core.orchestration.context_budget import (
    ABSOLUTE_TOKEN_CEILING,
    DEFAULT_OUTPUT_RESERVE_TOKENS,
    DEFAULT_TOOLS_OVERHEAD_TOKENS,
    SAFETY_MARGIN_MULTIPLIER,
    resolve_context_budget_policy,
)


def test_glm_52_resolves_current_documented_window() -> None:
    policy = resolve_context_budget_policy("glm-5.2")

    # Current direct Z.AI model guide publishes 1M; no inferred [1m] alias.
    assert policy.context_window == 1_000_000
    assert policy.tier.name == "large"
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


def test_route_budget_separates_platform_input_limit_and_codex_client_default() -> None:
    platform = resolve_context_budget_policy(
        "gpt-6-astra", provider="openai", source="payg", output_reserve_tokens=8_192
    )
    codex = resolve_context_budget_policy("gpt-6-astra", provider="openai", source="subscription")
    configured = resolve_context_budget_policy(
        "gpt-6-astra", provider="openai", source="subscription", context_window=1_050_000
    )
    assert platform.context_window == 1_050_000
    assert platform.max_input_tokens == 922_000
    assert platform.effective_prompt_budget_tokens == 922_000
    assert platform.output_reserve_tokens == 8_192
    assert platform.context_origin == "provider_catalog"
    assert codex.context_window == 272_000
    assert codex.max_input_tokens is None
    assert codex.context_origin == "client_default"
    assert configured.context_window == 872_000


def test_route_budget_openrouter_never_inherits_direct_contract() -> None:
    policy = resolve_context_budget_policy(
        "gpt-6-astra", provider="openrouter", source="payg", output_reserve_tokens=4_096
    )
    assert policy.provider == "openrouter"
    assert policy.context_window == 200_000
    assert policy.context_origin == "fallback"
    assert policy.max_input_tokens is None


def test_request_output_reserve_matches_provider_wire() -> None:
    from core.llm.adapters._anthropic_common import build_create_kwargs
    from core.llm.adapters._openai_common import build_responses_kwargs
    from core.llm.adapters.base import AdapterCallRequest
    from core.llm.providers.glm import build_glm_chat_kwargs
    from core.orchestration.context_budget import resolve_request_context_budget

    for model, provider, source, output, thinking in (
        ("gpt-6-astra", "openai", "payg", 200_000, 0),
        ("gpt-6-astra", "openai", "subscription", 1, 0),
        ("claude-opus-4-5", "anthropic", "payg", 4_096, 1_024),
        ("claude-opus-5-5", "anthropic", "payg", 4_096, 1_024),
        ("glm-5.3", "glm", "payg", 200_000, 0),
    ):
        req = AdapterCallRequest(
            model=model, messages=(), max_tokens=output, thinking_budget=thinking
        )
        policy = resolve_request_context_budget(req, provider=provider, source=source)
        if provider == "openai":
            kwargs = build_responses_kwargs(
                req,
                backend="codex" if source == "subscription" else "platform",
                adapter_name="codex-oauth" if source == "subscription" else "openai-payg",
            )
            if source == "subscription":
                assert "max_output_tokens" not in kwargs
                assert policy.output_reserve_tokens == DEFAULT_OUTPUT_RESERVE_TOKENS
                continue
            wire_output = kwargs["max_output_tokens"]
        elif provider == "anthropic":
            wire_output = build_create_kwargs(req)["max_tokens"]
        else:
            wire_output = build_glm_chat_kwargs(req, source=source, adapter_name="glm-payg")[
                "max_tokens"
            ]
        assert policy.output_reserve_tokens == wire_output
