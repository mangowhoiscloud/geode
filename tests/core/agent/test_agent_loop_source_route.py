"""AgenticLoop source-route behavioural invariants.

Pins:
- Empty source → legacy adapter only, no new_adapter attached.
- Concrete source + ``provider="anthropic"`` → ``resolve_for`` resolves and
  attaches a new_adapter; legacy adapter still constructed for the fallback
  surface (unused on this path).
- Concrete source + provider != anthropic → new_adapter stays None (A2
  follow-up scope); legacy adapter is the only route.
- Concrete source + unregistered (provider, source) pair → hard-fail
  (Codex MCP 2026-05-23 HIGH 2 — no silent fallback).
"""

from __future__ import annotations

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop
from core.agent.tool_executor import ToolExecutor
from core.llm.adapters.registry import _reset_for_test, bootstrap_builtins

from core.llm.adapters import AdapterNotFoundError


@pytest.fixture(autouse=True)
def _registry_with_builtins():
    _reset_for_test()
    bootstrap_builtins()
    yield
    _reset_for_test()


def _make_loop(*, source: str = "", provider: str = "anthropic") -> AgenticLoop:
    return AgenticLoop(
        ConversationContext(),
        ToolExecutor(action_handlers={}, auto_approve=True),
        provider=provider,
        source=source,
        quiet=True,
    )


def test_empty_source_leaves_new_adapter_none() -> None:
    loop = _make_loop(source="")
    assert loop._new_adapter is None
    assert loop._adapter is not None  # legacy still wired


def test_concrete_source_attaches_anthropic_adapter() -> None:
    loop = _make_loop(source="payg")
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "anthropic-payg"
    assert loop._adapter is not None  # legacy also wired for fallback


def test_concrete_source_each_anthropic_variant() -> None:
    for source, expected_name in (
        ("payg", "anthropic-payg"),
        ("subscription", "anthropic-oauth"),
        ("adapter", "claude-cli"),
    ):
        loop = _make_loop(source=source)
        assert loop._new_adapter is not None
        assert loop._new_adapter.name == expected_name


def test_non_anthropic_provider_skips_new_adapter() -> None:
    """A2 follow-up scope — OpenAI/Codex providers still use legacy."""
    loop = _make_loop(source="payg", provider="openai")
    assert loop._new_adapter is None  # not yet on adapter route
    assert loop._adapter is not None  # legacy path


def test_unregistered_pair_hard_fails() -> None:
    """Concrete source + missing adapter must raise — no silent fallback."""
    from core.llm.adapters.registry import unregister_adapter

    unregister_adapter("anthropic-payg")
    with pytest.raises(AdapterNotFoundError):
        _make_loop(source="payg")
