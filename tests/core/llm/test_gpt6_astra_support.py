"""GPT-6 model-contract guards (official docs retrieved 2026-09-24)."""

from __future__ import annotations

import tomllib
from dataclasses import replace
from pathlib import Path

import pytest
from core.llm.adapters.base import AdapterCallRequest

REPO_ROOT = Path(__file__).resolve().parents[3]
MODEL = "gpt-6-astra"


def _request() -> AdapterCallRequest:
    return AdapterCallRequest(
        model=MODEL,
        system_prompt="Mode: test.",
        messages=[],
        max_tokens=32,
        effort="none",
        temperature=0.7,
    )


def test_astra_contract_and_request_shape() -> None:
    from core.llm.adapters._openai_common import (
        _OPENAI_MODELS,
        build_responses_kwargs,
        get_openai_model_spec,
    )

    assert MODEL in _OPENAI_MODELS
    spec = get_openai_model_spec(MODEL)
    assert spec.reasoning_effort_values == ("low", "medium", "high", "xhigh", "max")
    assert spec.accepts_temperature is False
    assert spec.supports_tool_search is True
    assert spec.context_window == 1_050_000

    codex = build_responses_kwargs(_request(), backend="codex", adapter_name="test")
    assert codex["reasoning"]["effort"] == "low"
    assert "temperature" not in codex
    assert "max_output_tokens" not in codex

    platform = build_responses_kwargs(_request(), backend="platform", adapter_name="test")
    assert platform["max_output_tokens"] == 32


@pytest.mark.parametrize("model", ["gpt-6-sol", "gpt-6-luna"])
def test_new_gpt6_contract_reaches_both_routes(model: str) -> None:
    from core.llm.adapters._openai_common import build_responses_kwargs, get_openai_model_spec
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    spec = get_openai_model_spec(model)
    assert spec.reasoning_effort_values == ("none", "low", "medium", "high", "xhigh", "max")
    assert spec.context_window == 1_050_000
    assert spec.max_output_tokens == 128_000
    assert spec.supports_tool_search
    request = replace(_request(), model=model, max_tokens=200_000)
    platform = build_responses_kwargs(request, backend="platform", adapter_name="test")
    codex = build_responses_kwargs(request, backend="codex", adapter_name="test")
    assert platform["max_output_tokens"] == 128_000
    assert platform["reasoning"]["effort"] == codex["reasoning"]["effort"] == "none"
    assert platform["temperature"] == 0.7
    assert "temperature" not in codex and "max_output_tokens" not in codex

    reasoning = build_responses_kwargs(
        replace(request, effort="high"), backend="platform", adapter_name="test"
    )
    assert "temperature" not in reasoning
    for adapter in (OpenAIPaygAdapter(), CodexOAuthAdapter()):
        assert model in {row.id for row in adapter.list_models()}


@pytest.mark.parametrize("max_tokens", [0, -1])
def test_platform_rejects_nonpositive_output_budget(max_tokens: int) -> None:
    from core.llm.adapters._openai_common import build_responses_kwargs
    from core.llm.errors import LLMRequestValidationError

    with pytest.raises(LLMRequestValidationError, match="must be positive"):
        build_responses_kwargs(
            replace(_request(), max_tokens=max_tokens), backend="platform", adapter_name="test"
        )


@pytest.mark.parametrize(
    "model, efforts, limit",
    [
        ("gpt-5.3-codex", ("low", "medium", "high", "xhigh"), 128_000),
        ("gpt-5-mini", ("minimal", "low", "medium", "high"), 128_000),
        ("gpt-5-nano", ("minimal", "low", "medium", "high"), 128_000),
        ("o3", ("low", "medium", "high"), 100_000),
    ],
)
def test_retained_api_models_keep_their_exact_effort_and_output_contract(
    model: str, efforts: tuple[str, ...], limit: int
) -> None:
    from core.llm.adapters._openai_common import build_responses_kwargs, get_openai_model_spec

    spec = get_openai_model_spec(model)
    assert spec.reasoning_effort_values == efforts
    result = build_responses_kwargs(
        replace(_request(), model=model, max_tokens=200_000),
        backend="platform",
        adapter_name="test",
    )
    assert result["max_output_tokens"] == limit
    assert result["reasoning"]["effort"] == efforts[0]
    assert "temperature" not in result


def test_astra_catalogue_route_and_picker() -> None:
    from core.agent.capability_graph import _context_window
    from core.cli.commands._state import get_model_profiles
    from core.config.routing_manifest import resolve_provider

    data = tomllib.loads((REPO_ROOT / "core" / "llm" / "model_pricing.toml").read_text())
    assert data["pricing"]["openai"][MODEL] == {
        "input_per_mtok": 10.0,
        "output_per_mtok": 50.0,
        "cached_per_mtok": 1.0,
        "cache_write_per_mtok": 12.5,
        "long_context_threshold": 272_000,
        "long_context_input_multiplier": 2.0,
        "long_context_output_multiplier": 1.5,
    }
    assert data["context_windows"][MODEL] == 1_050_000
    assert (
        MODEL
        not in tomllib.loads((REPO_ROOT / "core" / "config" / "routing.toml").read_text())[
            "routing"
        ]["codex_only_models"]
    )
    assert resolve_provider(MODEL) == "openai"
    assert _context_window(MODEL, "openai-codex") == 1_050_000

    profile = {row.id: row for row in get_model_profiles(openai_source="payg")}[MODEL]
    assert profile.provider == "openai"

    from core.llm.token_tracker import MODEL_PRICING

    assert MODEL_PRICING[MODEL].cache_write == 12.5 / 1_000_000

    for manifest in (
        REPO_ROOT / "evals" / "petri" / "petri.plugin.toml",
        REPO_ROOT / "evals" / "seed_generation" / "seed_generation.plugin.toml",
    ):
        assert MODEL in manifest.read_text()
