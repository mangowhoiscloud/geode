"""Routing reloads update live defaults without pinning inherited agent models.

``reload_settings_from_disk`` calls ``reload_routing_constants`` which rebinds
``core.config.*`` in place. Function-local ``from core.config import X`` reads
re-resolve the module attribute each call, so a ``routing.toml`` reload is
reflected without a process restart. Pre-H11-tail the provider module aliases
(``DEFAULT_*_MODEL`` / ``*_FALLBACK_MODELS``) froze at import. Agent definitions
with no explicit model now preserve inheritance rather than selecting a
provider-specific constant before the parent model is known.
"""

from __future__ import annotations

from unittest.mock import patch

import core.config
import pytest


def test_agent_definition_model_omission_remains_inherited_during_reload() -> None:
    from core.skills.agents import AgentDefinition

    with patch.object(core.config, "ANTHROPIC_SECONDARY", "claude-h11-live"):
        agent = AgentDefinition(name="x", role="r", system_prompt="p")
        assert agent.model == ""


def test_default_agent_specs_do_not_capture_provider_default_during_reload() -> None:
    from core.skills.agents import AgentRegistry

    with patch.object(core.config, "ANTHROPIC_SECONDARY", "claude-h11-defaults"):
        reg = AgentRegistry()
        reg.load_defaults()
        ra = reg.get("research_assistant")
        assert ra is not None
        assert ra.model == ""


def test_openai_primary_constant_reads_live() -> None:
    # 2026-07-29: OpenAIAdapter deleted; the H11 invariant (routing constants
    # are read live, never boot-frozen) is pinned on the config surface the
    # live adapters consume.
    with patch.object(core.config, "OPENAI_PRIMARY", "gpt-h11-live"):
        assert core.config.OPENAI_PRIMARY == "gpt-h11-live"


def test_model_picker_list_reads_live() -> None:
    # /model picker list was the last boot-frozen routing-constant site;
    # get_model_profiles now re-reads core.config per call.
    from core.cli.commands._state import get_model_profiles

    with patch.object(core.config, "ANTHROPIC_SECONDARY", "claude-picker-live"):
        ids = [p.id for p in get_model_profiles(openai_source="payg")]
        assert "claude-picker-live" in ids


def test_model_picker_index_reads_live() -> None:
    from core.cli.commands._state import get_model_index

    with (
        patch.object(core.config, "GLM_PRIMARY", "glm-picker-live"),
        patch("core.cli.commands._state._selected_openai_source", return_value="payg"),
    ):
        assert "glm-picker-live" in get_model_index()


def test_openai_default_override_does_not_duplicate_fixed_picker_rows() -> None:
    """A curated override reuses the canonical row rather than duplicating it."""
    from core.cli.commands._state import get_model_profiles

    with patch.object(core.config, "OPENAI_PRIMARY", "gpt-5.6-sol"):
        profiles = get_model_profiles(openai_source="payg")

    matches = [profile for profile in profiles if profile.id == "gpt-5.6-sol"]
    assert matches == [
        next(
            profile
            for profile in profiles
            if profile.provider == "openai" and profile.label == "GPT-5.6 Sol"
        )
    ]


@pytest.mark.parametrize(
    "source,expected_label",
    [
        ("payg", "gpt-5.2 (Configured)"),
        ("subscription", "gpt-5.2 (Unavailable on subscription)"),
    ],
)
def test_openai_default_override_outside_surface_remains_manageable(
    source: str, expected_label: str
) -> None:
    """A live override stays one management row, labelled for its selected source."""
    from core.cli.commands._state import get_model_profiles

    with patch.object(core.config, "OPENAI_PRIMARY", "gpt-5.2"):
        profiles = get_model_profiles(openai_source=source)

    matches = [profile for profile in profiles if profile.id == "gpt-5.2"]
    assert len(matches) == 1
    assert matches[0].provider == "openai"
    assert matches[0].label == expected_label
