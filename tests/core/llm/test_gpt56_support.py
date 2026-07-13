"""GPT-5.6 family support guards (2026-07-13).

Pins the doc-verified surface (refs cited in the production modules):
adapter request-shaping spec (max_completion_tokens / no temperature /
effort levels incl. the new "max"), pricing + 1.05M context windows,
Codex-lane routing for the three full slugs, picker availability, and
the deliberately-unverified computer-use GA exclusion.

Official refs:
- https://developers.openai.com/api/docs/models (GA 2026-07-09; effort levels)
- https://developers.openai.com/api/docs/models/gpt-5.6-{sol,terra,luna}
- openai/codex codex-rs/models-manager/models.json (Codex slugs; ctx7)
"""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SLUGS = ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
ALL_IDS = ("gpt-5.6", *SLUGS)


def test_adapter_spec_registry() -> None:
    from core.llm.adapters._openai_common import _OPENAI_MODELS, get_openai_model_spec

    for model_id in ALL_IDS:
        assert model_id in _OPENAI_MODELS, model_id  # no legacy-fallback drift
        spec = get_openai_model_spec(model_id)
        assert spec.uses_max_completion_tokens is True
        assert spec.accepts_temperature is False
        assert spec.reasoning_effort_values == (
            "none",
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        )
        assert spec.supports_tool_search is True
        assert spec.context_window == 1_050_000


def test_gpt56_pricing_and_context_windows() -> None:
    data = tomllib.loads((REPO_ROOT / "core" / "llm" / "model_pricing.toml").read_text())
    sol = data["pricing"]["openai"]["gpt-5.6-sol"]
    assert sol["input_per_mtok"] == 5.0 and sol["output_per_mtok"] == 30.0
    terra = data["pricing"]["openai"]["gpt-5.6-terra"]
    assert terra["input_per_mtok"] == 2.5 and terra["output_per_mtok"] == 15.0
    luna = data["pricing"]["openai"]["gpt-5.6-luna"]
    assert luna["input_per_mtok"] == 1.0 and luna["output_per_mtok"] == 6.0
    # Bare alias bills at sol rates (documented alias → routes to sol).
    alias = data["pricing"]["openai"]["gpt-5.6"]
    assert alias == sol
    for model_id in ALL_IDS:
        assert data["context_windows"][model_id] == 1_050_000


def test_dual_lane_routing() -> None:
    """gpt-5.6 is served by BOTH backends (Platform API GA + Codex
    models.json), so the slugs must stay OFF codex_only_models — the gpt-
    prefix resolves them to the "openai" family and infer_source (login
    state) picks oauth vs api_key per call. Membership in codex_only would
    force the OAuth lane and cut off documented API access."""
    from core.config.routing_manifest import resolve_provider

    manifest = tomllib.loads((REPO_ROOT / "core" / "config" / "routing.toml").read_text())
    codex_only = manifest["routing"]["codex_only_models"]
    for model_id in ALL_IDS:
        assert model_id not in codex_only, model_id
        assert resolve_provider(model_id) == "openai"


def test_model_picker_offers_gpt56_family() -> None:
    from core.cli.commands._state import get_model_profiles

    profiles = {p.id: p for p in get_model_profiles()}
    for slug in SLUGS:
        assert slug in profiles, slug
        # Provider label must match resolve_provider — "openai" family
        # (dual-lane; the credential source picks the backend).
        assert profiles[slug].provider == "openai"
    assert "gpt-5.6" not in profiles  # sol alias — redundant picker row


def test_effort_picker_offers_max() -> None:
    from core.cli.effort_picker import default_effort, supported_efforts

    for slug in SLUGS:
        efforts = supported_efforts(slug, "openai-codex")
        assert efforts[-1] == "max"
        assert "xhigh" in efforts
        assert default_effort(slug, "openai-codex") == "medium"
    # Older gpt-5.x families must NOT gain "max" from the 5.6 branch.
    assert "max" not in supported_efforts("gpt-5.5", "openai-codex")


def test_capability_graph_context_window() -> None:
    from core.agent.capability_graph import _context_window

    for slug in SLUGS:
        assert _context_window(slug, "openai-codex") == 1_000_000


def test_plugin_allowlists_include_gpt56() -> None:
    for rel in (
        "plugins/seed_generation/seed_generation.plugin.toml",
        "plugins/petri_audit/petri.plugin.toml",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "gpt-5.6-sol" in text, rel


def test_reasoning_effort_clamped_to_spec() -> None:
    """Effort persists across model switches — the wire must never carry a
    level the target spec excludes (Codex MCP review finding 1). Below-first
    clamp: nearest weaker supported level wins."""
    from core.llm.adapters._openai_common import (
        clamp_reasoning_effort,
        get_openai_model_spec,
    )

    gpt55 = get_openai_model_spec("gpt-5.5")
    assert clamp_reasoning_effort("max", spec=gpt55) == "xhigh"  # 5.6-only level
    sol = get_openai_model_spec("gpt-5.6-sol")
    assert clamp_reasoning_effort("max", spec=sol) == "max"  # supported → untouched
    assert clamp_reasoning_effort("minimal", spec=sol) == "none"  # below-first rule
    assert clamp_reasoning_effort(None, spec=sol) is None


def test_computer_use_ga_exclusion_is_deliberate() -> None:
    """Platform acceptance of {type:"computer"} on gpt-5.6 is unverified —
    the docs tool-catalog row was not sufficient for gpt-5.4 either (live
    reject). Pin the exclusion until the Phase-C live round-trip runs; if
    that verification lands, flip this assertion together with the
    frozenset (see _openai_common.py comment)."""
    from core.llm.adapters._openai_common import _OPENAI_COMPUTER_USE_GA_MODELS

    for model_id in ALL_IDS:
        assert model_id not in _OPENAI_COMPUTER_USE_GA_MODELS
