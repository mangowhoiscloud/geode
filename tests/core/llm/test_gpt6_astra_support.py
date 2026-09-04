"""GPT-6 Astra model-contract guards (official docs retrieved 2026-09-04)."""

from __future__ import annotations

import tomllib
from pathlib import Path

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

    profile = {row.id: row for row in get_model_profiles()}[MODEL]
    assert profile.provider == "openai"

    from core.llm.token_tracker import MODEL_PRICING

    assert MODEL_PRICING[MODEL].cache_write == 12.5 / 1_000_000

    for manifest in (
        REPO_ROOT / "evals" / "petri" / "petri.plugin.toml",
        REPO_ROOT / "evals" / "seed_generation" / "seed_generation.plugin.toml",
    ):
        assert MODEL in manifest.read_text()
