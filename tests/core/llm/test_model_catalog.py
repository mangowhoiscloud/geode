"""Central model catalogue invariants."""

from __future__ import annotations

import pytest
from core.llm.model_catalog import (
    context_window_for,
    get_model_catalog_spec,
    model_source_unavailable_reason,
    model_spec_for_adapter,
    normalize_model_provider,
)


def test_context_window_comes_from_pricing_catalogue() -> None:
    assert context_window_for("gpt-5.5") == 1_050_000
    assert context_window_for("gpt-5.2") == 400_000
    assert context_window_for("gpt-5.4-mini") == 400_000
    assert context_window_for("gpt-5.4-nano") == 400_000
    assert context_window_for("gpt-5-mini") == 400_000
    assert context_window_for("gpt-5-nano") == 400_000
    assert context_window_for("o4-mini") == 200_000
    assert context_window_for("claude-opus-4-8") == 1_000_000
    assert context_window_for("glm-5.2") == 202_752  # PAYG conservative guard (0.99.246)


def test_codex_routing_alias_normalizes_to_openai_capabilities() -> None:
    spec = get_model_catalog_spec("gpt-5.5")

    assert normalize_model_provider("openai-codex") == "openai"
    assert spec.provider == "openai"
    assert spec.supports_thinking is True
    assert spec.supports_tool_search is True


def test_adapter_model_spec_uses_catalogue_values() -> None:
    spec = model_spec_for_adapter("glm-5.2", provider="glm")

    assert spec.context_tokens == 202_752  # PAYG conservative guard (0.99.246)
    assert spec.supports_thinking is False
    assert spec.supports_tools is True


@pytest.mark.parametrize("model", ["gpt-5.4", "gpt-5.4-mini", "gpt-5.2", "gpt-5.3-codex"])
def test_retirement_is_subscription_specific(model: str) -> None:
    reason = model_source_unavailable_reason(model, provider="openai", source="subscription")
    assert reason is not None and model in reason
    assert "explicitly" in reason and "billing sources automatically" in reason
    assert model_source_unavailable_reason(model, provider="openai", source="payg") is None
    assert (
        model_source_unavailable_reason(model, provider="openrouter", source="subscription") is None
    )


@pytest.mark.parametrize(
    "model", ["gpt-5.5", "gpt-6-astra", "gpt-5.6", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"]
)
def test_current_subscription_models_not_retired_early(model: str) -> None:
    assert (
        model_source_unavailable_reason(model, provider="openai-codex", source="subscription")
        is None
    )


@pytest.mark.parametrize(
    "model",
    [
        "claude-opus-4-1",
        "claude-opus-4-1-20250805",
        "claude-opus-4-20250514",
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-20241022",
        "claude-3-haiku-20240307",
    ],
)
def test_anthropic_retirement_is_direct_api_specific(
    monkeypatch: pytest.MonkeyPatch, model: str
) -> None:
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    reason = model_source_unavailable_reason(model, provider="anthropic", source="payg")
    assert reason is not None and "retired" in reason and "Anthropic API" in reason
    assert model_source_unavailable_reason(model, provider="openrouter", source="payg") is None
    assert model_source_unavailable_reason(model, provider="anthropic", source="adapter") is None


@pytest.mark.parametrize(
    "configured_url,actual_url,blocked",
    [
        ("https://api.anthropic.com", None, True),
        ("https://gateway.example.test", None, False),
        ("https://api.anthropic.com", "https://gateway.example.test", False),
        ("https://gateway.example.test", "https://api.anthropic.com/", True),
        ("https://api.anthropic.com.example.test", None, False),
    ],
)
def test_anthropic_endpoint_authority_is_exact_and_actual_url_wins(
    monkeypatch: pytest.MonkeyPatch, configured_url: str, actual_url: str | None, blocked: bool
) -> None:
    monkeypatch.setenv("ANTHROPIC_BASE_URL", configured_url)
    reason = model_source_unavailable_reason(
        "claude-sonnet-4-20250514", provider="anthropic", source="payg", base_url=actual_url
    )
    assert (reason is not None) is blocked


@pytest.mark.parametrize(
    "model",
    [
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-opus-4-7",
        "claude-opus-4-6",
        "claude-opus-4-5",
        "claude-opus-4-5-20251101",
        "claude-sonnet-4-6",
        "claude-sonnet-4-5-20250929",
        "claude-haiku-4-5-20251001",
    ],
)
def test_legacy_or_earliest_future_retirement_date_is_not_retired(model: str) -> None:
    assert model_source_unavailable_reason(model, provider="anthropic", source="payg") is None
