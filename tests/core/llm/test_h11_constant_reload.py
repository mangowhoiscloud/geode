"""H11-tail: provider + agent model constants read ``core.config`` live.

``reload_settings_from_disk`` calls ``reload_routing_constants`` which rebinds
``core.config.*`` in place. Function-local ``from core.config import X`` reads
re-resolve the module attribute each call, so a ``routing.toml`` reload is
reflected without a process restart. Pre-H11-tail the provider module aliases
(``DEFAULT_*_MODEL`` / ``*_FALLBACK_MODELS``) and the ``AgentDefinition.model``
default froze at import. These pin the de-frozen behaviour by patching the
``core.config`` attribute and asserting consumers see the new value.
"""

from __future__ import annotations

from unittest.mock import patch

import core.config


def test_agent_definition_model_default_reads_live() -> None:
    from core.skills.agents import AgentDefinition

    with patch.object(core.config, "ANTHROPIC_SECONDARY", "claude-h11-live"):
        agent = AgentDefinition(name="x", role="r", system_prompt="p")
        assert agent.model == "claude-h11-live"


def test_default_agent_specs_model_reads_live() -> None:
    # The built-in _DEFAULT_AGENTS specs no longer pin a frozen model; the
    # AgentDefinition default_factory fills the live value at load_defaults().
    from core.skills.agents import AgentRegistry

    with patch.object(core.config, "ANTHROPIC_SECONDARY", "claude-h11-defaults"):
        reg = AgentRegistry()
        reg.load_defaults()
        ra = reg.get("research_assistant")
        assert ra is not None
        assert ra.model == "claude-h11-defaults"


def test_openai_adapter_default_model_reads_live() -> None:
    from core.llm.providers.openai import OpenAIAdapter

    with patch.object(core.config, "OPENAI_PRIMARY", "gpt-h11-live"):
        assert OpenAIAdapter()._default_model == "gpt-h11-live"
