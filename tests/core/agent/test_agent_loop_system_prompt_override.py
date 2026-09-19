"""Verify S2-wire — AgenticLoop.system_prompt_override replaces default body."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop, AgenticLoopConfig
from core.agent.loop._context import build_system_prompt
from core.agent.tool_executor import ToolExecutor
from core.config.policy_source import PolicySourceBundle, PolicySourcePaths
from core.llm.prompts import AGENTIC_SUFFIX


def _make_loop(
    *, override: str | None = None, policy_sources: PolicySourceBundle | None = None
) -> AgenticLoop:
    """Build an AgenticLoop with minimum dependencies for prompt-build test."""
    conversation = ConversationContext(max_turns=200)
    executor = ToolExecutor(action_handlers={}, auto_approve=True)
    return AgenticLoop(
        conversation,
        executor,
        config=AgenticLoopConfig(system_prompt_override=override),
        policy_sources=policy_sources,
    )


def test_override_replaces_default_system_body() -> None:
    """When set, override is used as the system body."""
    loop = _make_loop(override="ROLE_BODY_FROM_AGENT_DEFINITION")
    prompt = build_system_prompt(loop)
    assert "ROLE_BODY_FROM_AGENT_DEFINITION" in prompt


def test_override_does_not_include_default_prompt_template() -> None:
    """The default ``_build_system_prompt(model=...)`` body must NOT leak in."""
    loop = _make_loop(override="ROLE_BODY")
    prompt = build_system_prompt(loop)
    assert "ROLE_BODY" in prompt
    assert "{skill_context}" not in prompt


def test_override_none_uses_default_path() -> None:
    """When override is None, the legacy build path runs."""
    loop = _make_loop(override=None)
    prompt = build_system_prompt(loop)
    assert prompt
    assert "ROLE_BODY_FROM_AGENT_DEFINITION" not in prompt


def test_override_with_skill_registry_appends_skills() -> None:
    """Skill context is still surfaced when override is set."""
    fake_registry = MagicMock()
    fake_registry.get_context_block.return_value = "<skill_x />"
    loop = _make_loop(override="ROLE_BODY")
    loop._skill_registry = fake_registry  # type: ignore[assignment]
    prompt = build_system_prompt(loop)
    assert "ROLE_BODY" in prompt
    assert "<skill_x />" in prompt


def test_agentic_suffix_present_with_override() -> None:
    """Tool-calling contract must be preserved across override path."""
    loop = _make_loop(override="ROLE_BODY")
    prompt = build_system_prompt(loop)
    assert AGENTIC_SUFFIX in prompt


def test_skill_slot_does_not_replace_literal_context_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.agent import system_prompt

    monkeypatch.setenv("GEODE_PERSONA", "on")
    monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "0")
    monkeypatch.setattr(system_prompt, "_generic_static_prefix", lambda: "Skills: {skill_context}")
    monkeypatch.setattr(
        system_prompt, "_build_identity_context", lambda: "Identity literal: {skill_context}"
    )
    monkeypatch.setattr(
        system_prompt, "_build_user_context", lambda _profile: "User literal: {skill_context}"
    )

    prompt = build_system_prompt(_make_loop())

    assert 'Skills: <available_skills status="empty" />' in prompt
    assert "Identity literal: {skill_context}" in prompt
    assert "User literal: {skill_context}" in prompt


@pytest.mark.parametrize(
    "mode", ["default", "persona_off", "audit", "wrapper", "audit_wrapper", "agent_definition"]
)
def test_common_suffix_survives_prompt_mode_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    """Exercise real loop assembly; no model call or completion decision is made."""
    for variable in ("GEODE_WRAPPER_OVERRIDE", "GEODE_PERSONA", "GEODE_AUDIT_UNRESTRICTED"):
        monkeypatch.delenv(variable, raising=False)
    if mode == "persona_off":
        monkeypatch.setenv("GEODE_PERSONA", "off")
    if mode in {"audit", "audit_wrapper"}:
        monkeypatch.setenv("GEODE_AUDIT_UNRESTRICTED", "1")
    if mode in {"wrapper", "audit_wrapper"}:
        wrapper = tmp_path / "wrapper.json"
        wrapper.write_text(json.dumps({"role": "CUSTOM_WRAPPER"}), encoding="utf-8")
        monkeypatch.setenv("GEODE_WRAPPER_OVERRIDE", str(wrapper))
    loop = _make_loop(
        override="AGENT_DEFINITION_BODY" if mode == "agent_definition" else None,
        policy_sources={
            "wrapper_sections": PolicySourcePaths("GEODE_WRAPPER_OVERRIDE", override_is_strict=True)
        },
    )

    prompt = build_system_prompt(loop)

    assert prompt.count(AGENTIC_SUFFIX) == 1
    assert "{skill_context}" not in prompt
    if mode in {"persona_off", "audit", "audit_wrapper", "agent_definition"}:
        assert "<agent_identity>" not in prompt
    else:
        assert "<agent_identity>" in prompt
    if mode in {"wrapper", "audit_wrapper"}:
        assert "CUSTOM_WRAPPER" in prompt
        assert "GEODE handles autonomous execution" not in prompt
    if mode == "agent_definition":
        assert prompt.startswith("AGENT_DEFINITION_BODY\n")
    else:
        assert prompt.index(AGENTIC_SUFFIX) < prompt.index("<dynamic_context>")
