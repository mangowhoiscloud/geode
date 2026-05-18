"""Verify S2-wire — AgenticLoop.system_prompt_override replaces default body."""

from __future__ import annotations

from unittest.mock import MagicMock

from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop
from core.agent.loop._context import build_system_prompt
from core.agent.tool_executor import ToolExecutor


def _make_loop(*, override: str | None = None) -> AgenticLoop:
    """Build an AgenticLoop with minimum dependencies for prompt-build test."""
    conversation = ConversationContext(max_turns=200)
    executor = ToolExecutor(action_handlers={}, auto_approve=True)
    return AgenticLoop(
        conversation,
        executor,
        system_prompt_override=override,
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
    from core.agent.loop._context import AGENTIC_SUFFIX

    loop = _make_loop(override="ROLE_BODY")
    prompt = build_system_prompt(loop)
    assert AGENTIC_SUFFIX in prompt
