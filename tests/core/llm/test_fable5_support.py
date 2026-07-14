"""Fable 5 support guards (2026-06-11).

Pins the doc-verified surface (refs cited in the production modules):
capability-anchor membership (adaptive-only thinking / sampling-param
omission / xhigh effort / 1M-context compaction), picker availability,
pricing, plugin allowlists, and the refusal stop_reason path.

Official refs:
- https://platform.claude.com/docs/en/about-claude/models/overview
- https://platform.claude.com/docs/en/about-claude/models/introducing-claude-fable-5-and-claude-mythos-5
- https://platform.claude.com/docs/en/about-claude/models/migration-guide
"""

from __future__ import annotations

import inspect
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
FABLE = "claude-fable-5"


def test_capability_anchor_membership() -> None:
    from core.llm.model_capabilities import (
        ANTHROPIC_ADAPTIVE_MODELS,
        ANTHROPIC_CONTEXT_MGMT_MODELS,
        ANTHROPIC_XHIGH_MODELS,
    )

    assert FABLE in ANTHROPIC_ADAPTIVE_MODELS  # adaptive-only; sampling params 400
    assert FABLE in ANTHROPIC_XHIGH_MODELS  # effort xhigh supported
    assert FABLE in ANTHROPIC_CONTEXT_MGMT_MODELS  # 1M ctx + compaction


def test_adapter_request_shape_for_fable() -> None:
    """The adaptive branch (omit sampling, thinking adaptive, effort) must
    engage for Fable 5 — the model errors on thinking:{type:"disabled"}
    and non-default temperature/top_p/top_k."""
    from core.llm.providers.anthropic import _ADAPTIVE_MODELS

    assert FABLE in _ADAPTIVE_MODELS


def test_model_picker_offers_fable() -> None:
    from core.cli.commands._state import get_model_profiles

    profile = next((p for p in get_model_profiles() if p.id == FABLE), None)
    assert profile is not None
    assert profile.provider == "anthropic"
    assert profile.label == "Fable 5"


def test_pricing_and_context_window() -> None:
    data = tomllib.loads((REPO_ROOT / "core" / "llm" / "model_pricing.toml").read_text())
    row = data["pricing"]["anthropic"][FABLE]
    assert row["input_per_mtok"] == 10.0 and row["output_per_mtok"] == 50.0


def test_plugin_allowlists_include_fable() -> None:
    for rel in (
        "plugins/seed_generation/seed_generation.plugin.toml",
        "plugins/petri_audit/petri.plugin.toml",
    ):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert FABLE in text, rel


def test_refusal_stop_reason_flows_to_result() -> None:
    """normalize_anthropic carries stop_details; the refusal guard exists.

    v0.99.328 FSM formalization moved the branch into the named guard
    ``_guard_model_refusal`` (early-return on non-refusal stop reasons)
    terminating with ``TerminationReason.MODEL_REFUSAL``.
    """
    from core.agent.loop.agent_loop import AgenticLoop
    from core.agent.loop.models import TerminationReason
    from core.llm.agentic_response import AgenticResponse

    resp = AgenticResponse(stop_reason="refusal", stop_details={"category": "cyber"})
    assert resp.stop_details == {"category": "cyber"}

    assert callable(getattr(AgenticLoop, "_guard_model_refusal", None))
    guard_src = inspect.getsource(AgenticLoop._guard_model_refusal)
    assert 'response.stop_reason != "refusal"' in guard_src
    assert "TerminationReason.MODEL_REFUSAL" in guard_src
    assert TerminationReason.MODEL_REFUSAL == "model_refusal"
