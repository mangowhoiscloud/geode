"""AgenticLoop source-route behavioural invariants.

Pins:
- Empty source → PR-MAINPATH-1 (2026-05-24) cutover defaults source
  to ``"payg"``; ``_new_adapter`` is resolved through the Path-B
  registry. PR-MAINPATH-67 (2026-05-24) deleted the legacy
  ``self._adapter`` field alongside ``resolve_agentic_adapter``, so
  ``_new_adapter`` is now the sole dispatch surface.
- Concrete source + ``provider="anthropic"`` → ``resolve_for`` resolves and
  attaches a new_adapter.
- Concrete source + ``provider="openai"`` → A2 (v0.99.44) extended the
  Path-B registry beyond Anthropic; OpenAI providers now also resolve
  (`test_openai_provider_attaches_new_adapter`).
- Concrete source + unregistered (provider, source) pair → hard-fail
  (Codex MCP 2026-05-23 HIGH 2 — no silent fallback). Post-MAINPATH-67
  this is the only failure mode — there is no longer a legacy adapter
  to fall back to.
"""

from __future__ import annotations

import pytest
from core.agent.conversation import ConversationContext
from core.agent.loop import AgenticLoop
from core.agent.tool_executor import ToolExecutor
from core.llm.adapters import AdapterNotFoundError
from core.llm.adapters.registry import _reset_for_test, bootstrap_builtins


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
    resolves through the Path-B registry. PR-MAINPATH-67 (2026-05-24)
    deleted the legacy ``_adapter`` field; ``_new_adapter`` is the
    only dispatch surface.
    """
    loop = _make_loop(source="")
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "anthropic-payg"
    assert loop._source == "payg"


def test_concrete_source_attaches_anthropic_adapter() -> None:
    loop = _make_loop(source="payg")
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "anthropic-payg"


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


def test_unregistered_pair_hard_fails() -> None:
    """Concrete source + missing adapter must raise — no silent fallback."""
    from core.llm.adapters.registry import unregister_adapter

    unregister_adapter("anthropic-payg")
    with pytest.raises(AdapterNotFoundError):
        _make_loop(source="payg")


def test_runtime_model_switch_re_resolves_path_b_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PR-MAINPATH-4 (2026-05-24) — ``/model`` between providers must
    re-resolve ``_new_adapter``. PR-MAINPATH-67 (2026-05-24) deleted
    the legacy ``_adapter`` re-resolution alongside the resolver, so
    Path-B is now the sole adapter swapped on provider change.

    PR-MODEL-SWITCH-SOURCE (2026-06-12) — the source is now RE-INFERRED
    for the new provider on a cross-provider switch (the constant-source
    rule routed codex-OAuth operators through openai-payg's stale key).
    ``infer_source`` is pinned to ``payg`` here so the adapter assertion
    stays hermetic regardless of the developer machine's real OAuth
    profiles; the re-inference contract itself is pinned in
    ``test_model_switch_source_reinfer.py``.
    """
    from core.agent.loop._model_switching import _apply_model_update

    monkeypatch.setattr("core.llm.adapters._source_inference.infer_source", lambda provider: "payg")

    loop = _make_loop(provider="anthropic")
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "anthropic-payg"

    # Switch to an OpenAI model — ``_apply_model_update`` resolves
    # ``provider`` via ``_resolve_provider("gpt-5.5")`` →
    # ``openai-codex``. The Path-B helper normalises to ``openai``
    # internally; with the pinned payg source we end up on ``openai-payg``.
    _apply_model_update(loop, "gpt-5.5")

    assert loop._provider == "openai-codex"
    assert loop._new_adapter is not None
    assert loop._new_adapter.name == "openai-payg"
