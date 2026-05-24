"""AgenticLoop source-route behavioural invariants.

Pins:
- Empty source → PR-MAINPATH-1 (2026-05-24) cutover defaults source
  to ``"payg"``; ``_new_adapter`` is resolved through the Path-B
  registry. Pre-cutover, empty source meant ``_new_adapter is None``
  and the loop ran on the legacy ``resolve_agentic_adapter`` route.
- Concrete source + ``provider="anthropic"`` → ``resolve_for`` resolves and
  attaches a new_adapter; legacy adapter still constructed for the fallback
  surface (unused on this path).
- Concrete source + ``provider="openai"`` → A2 (v0.99.44) extended the
  Path-B registry beyond Anthropic; OpenAI providers now also resolve
  (`test_openai_provider_attaches_new_adapter`). The pre-A2 "anthropic
  only" claim that lived in this docstring header is gone.
- Concrete source + unregistered (provider, source) pair → hard-fail
  (Codex MCP 2026-05-23 HIGH 2 — no silent fallback). The cutover preserves
  this contract: if the Path-B default ``"payg"`` doesn't match a
  registered adapter for the requested provider, ``AgenticLoop.__init__``
  raises rather than silently routing through the legacy adapter.
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


def test_empty_source_defaults_to_payg_after_mainpath_cutover() -> None:
    """PR-MAINPATH-1 (2026-05-24) — empty source defaults to "payg" and
    resolves through the Path-B registry. Pre-cutover, this test asserted
    the opposite (``_new_adapter is None``) because empty source landed
    on the legacy ``resolve_agentic_adapter`` route.
    """
    loop = _make_loop(source="")
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "anthropic-payg"
    assert loop._source == "payg"
    assert loop._adapter is not None  # legacy still wired for error surface


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


def test_openai_provider_attaches_new_adapter() -> None:
    """A2 (v0.99.44) — OpenAI providers now resolve through the adapter
    registry too. Pre-A2 the route was Anthropic-only; A2 ported the
    multi-turn converters + Codex reasoning replay so the guard is gone."""
    loop = _make_loop(source="payg", provider="openai")
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "openai-payg"
    assert loop._adapter is not None  # legacy adapter still wired as fallback


def test_unregistered_pair_hard_fails() -> None:
    """Concrete source + missing adapter must raise — no silent fallback."""
    from core.llm.adapters.registry import unregister_adapter

    unregister_adapter("anthropic-payg")
    with pytest.raises(AdapterNotFoundError):
        _make_loop(source="payg")


def test_runtime_model_switch_re_resolves_path_b_adapter() -> None:
    """PR-MAINPATH-4 (2026-05-24) — ``/model`` between providers must
    re-resolve ``_new_adapter`` alongside the legacy ``_adapter``.

    Pre-PR-MAINPATH-4 the runtime switch only updated ``_adapter``
    (legacy ``resolve_agentic_adapter`` route); ``_new_adapter``
    stayed pointed at the previous provider's Path-B adapter, so the
    next ``_call_llm`` would dispatch to the wrong API. This test
    pins the dual-adapter re-resolution invariant.
    """
    from core.agent.loop._model_switching import _apply_model_update

    loop = _make_loop(provider="anthropic")
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "anthropic-payg"

    # Switch to an OpenAI model — ``_apply_model_update`` resolves
    # ``provider`` via ``_resolve_provider("gpt-5.5")`` →
    # ``openai-codex``. The Path-B helper normalises to ``openai``
    # internally, so we end up on ``openai-payg``.
    _apply_model_update(loop, "gpt-5.5")

    assert loop._provider == "openai-codex"
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "openai-payg"
    assert loop._adapter is not None  # legacy adapter also updated
