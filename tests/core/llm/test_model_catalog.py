"""Central model catalogue invariants."""

from __future__ import annotations

from core.llm.model_catalog import (
    context_window_for,
    get_model_catalog_spec,
    model_spec_for_adapter,
    normalize_model_provider,
)


def test_context_window_comes_from_pricing_catalogue() -> None:
    assert context_window_for("gpt-5.5") == 1_050_000
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
