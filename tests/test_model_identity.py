"""v0.52.8 — model identity must not leak across `/model` switches.

v0.99.5 (2026-05-17) — added autouse fixture to clear
``_build_model_card`` ``@lru_cache(maxsize=8)`` before each test. After
the async-only refactor (main 2026-05-17 db2a2bf3), some other test in
the same xdist `loadfile` worker can trigger ``_build_model_card`` 's
exception path (``return ""`` at the bottom of the ``try``) when a
``core.config`` lazy import is mocked or fails; that empty result lands
in the lru_cache and a later run of ``test_model_card_for_anthropic_model``
hits the cached ``""``. Clearing the cache per test isolates the unit
behavior under test from any cross-test cache pollution.

Production incident 2026-04-27: User issued ``/model gpt-5.5`` and the
LLM (running on gpt-5.5, daemon log confirmed) responded
"현재 사용 중인 모델은 gpt-5.4-mini" (claimed to be the previous model).

Root cause (Agent A audit): the v0.52.5 ``_prompt_dirty`` rebuild
correctly updated the system prompt model card, but the conversation
history still contained an earlier ``Understood. I am now gpt-5.4-mini.``
assistant ack from a *prior* model switch. gpt-5.5 read that historical
assistant message and inherited the wrong identity.

Verified via OpenAI's gpt-5.5 system card (deploymentsafety.openai.com):
"should identify itself as GPT-5.5". So the model itself is capable;
the bug was our breadcrumb pollution.

Two invariants pinned here:

  1. ``_build_model_card(model)`` returns a strong identity assertion
     (explicit + repeated + override of stale acks) — combats both
     recency bias and any backend system-layer claim.

  2. ``AgenticLoop.update_model`` purges prior ``"Understood. I am now
     <prev>."`` assistant acks BEFORE adding the new one. Each switch
     leaves exactly one active ack.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

import core.agent.loop as _loop_mod
from core.agent.system_prompt import _build_model_card


@pytest.fixture(autouse=True)
def _clear_model_card_cache() -> Any:
    """Isolate ``_build_model_card`` 's ``@lru_cache`` between tests.

    See module docstring for the cross-test cache pollution this guards
    against. Clear on both setup and teardown so neighbours can't poison
    each other regardless of test order.
    """
    _build_model_card.cache_clear()
    yield
    _build_model_card.cache_clear()

# ---------------------------------------------------------------------------
# Contract 1 — model card asserts identity strongly
# ---------------------------------------------------------------------------


def test_model_card_asserts_active_identity_for_gpt_5_5() -> None:
    """The model card must contain the exact model name in a non-negotiable
    assertion; pre-fix wording was a single soft "You are powered by..."
    that lost out to history pollution."""
    card = _build_model_card("gpt-5.5")
    # Strong identity assertion present.
    # G1 (2026-05-12) — the "## ACTIVE MODEL IDENTITY" markdown heading is
    # now the <model_card> XML wrapper + a non-negotiable first sentence.
    assert "<model_card>" in card
    assert "non-negotiable" in card, (
        "model card must use the strong-assertion header — pre-fix "
        "wording was too soft and lost to prior history claims"
    )
    # Model name appears multiple times for repetition reinforcement.
    assert card.count("gpt-5.5") >= 2, (
        f"model name must repeat in the card, got {card.count('gpt-5.5')} times"
    )
    # Explicit override of stale history acks.
    assert "stale" in card.lower() or "earlier assistant message" in card.lower(), (
        "card must explicitly tell the LLM to ignore stale acks from prior "
        "switches in the same conversation"
    )


def test_model_card_includes_provider() -> None:
    """Sanity: the model card still names the provider for context."""
    card = _build_model_card("gpt-5.5")
    assert "openai" in card.lower()


def test_model_card_for_anthropic_model() -> None:
    """Same shape for Anthropic models — identity assertion is provider-agnostic."""
    card = _build_model_card("claude-opus-4-7")
    # G1 (2026-05-12) — the "## ACTIVE MODEL IDENTITY" markdown heading is
    # now the <model_card> XML wrapper + a non-negotiable first sentence.
    assert "<model_card>" in card
    assert "non-negotiable" in card
    assert "claude-opus-4-7" in card
    assert card.count("claude-opus-4-7") >= 2


# ---------------------------------------------------------------------------
# Contract 2 — _purge_stale_model_switch_acks removes only our breadcrumb acks
# ---------------------------------------------------------------------------


def _make_loop_stub_with_history(messages: list[dict[str, Any]]) -> MagicMock:
    """Build an AgenticLoop stub with a controlled conversation history."""
    stub = MagicMock()
    stub.context = MagicMock()
    stub.context.messages = list(messages)
    # Bind the real method so we test the actual logic.
    stub._purge_stale_model_switch_acks = (
        _loop_mod.AgenticLoop._purge_stale_model_switch_acks.__get__(stub)
    )
    return stub


def test_purge_removes_understood_ack_from_history() -> None:
    """The exact prior-switch ack 'Understood. I am now gpt-5.4-mini.' must
    be removed before the next ack is added."""
    stub = _make_loop_stub_with_history(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
            {"role": "user", "content": "[system] Model switched: gpt-5.4 -> gpt-5.4-mini. ..."},
            {"role": "assistant", "content": "Understood. I am now gpt-5.4-mini."},
            {"role": "user", "content": "thanks"},
            {"role": "assistant", "content": "you're welcome"},
        ]
    )
    stub._purge_stale_model_switch_acks()
    msgs = stub.context.messages
    # The ack is gone.
    assert all(
        not (msg["role"] == "assistant" and "Understood. I am now" in msg.get("content", ""))
        for msg in msgs
    )
    # Other messages preserved.
    assert any(msg.get("content") == "hello!" for msg in msgs)
    assert any(msg.get("content") == "you're welcome" for msg in msgs)


def test_purge_removes_multiple_stale_acks() -> None:
    """Multiple switches in one session ⇒ multiple stale acks. All gone."""
    stub = _make_loop_stub_with_history(
        [
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "Understood. I am now gpt-5.4."},
            {"role": "user", "content": "Q2"},
            {"role": "assistant", "content": "Understood. I am now gpt-5.4-mini."},
            {"role": "user", "content": "Q3"},
            {"role": "assistant", "content": "Understood. I am now gpt-5.3-codex."},
        ]
    )
    stub._purge_stale_model_switch_acks()
    msgs = stub.context.messages
    assert not any(
        msg["role"] == "assistant" and "Understood. I am now" in msg.get("content", "")
        for msg in msgs
    ), "all stale acks must be removed"
    # User messages preserved.
    assert sum(1 for m in msgs if m["role"] == "user") == 3


def test_purge_does_not_touch_user_messages() -> None:
    """Even if a user message contains the ack prefix verbatim (extremely
    unlikely), we never touch user content. Only assistant role."""
    stub = _make_loop_stub_with_history(
        [
            {"role": "user", "content": "Understood. I am now testing this."},
            {"role": "assistant", "content": "ok"},
        ]
    )
    stub._purge_stale_model_switch_acks()
    msgs = stub.context.messages
    # The user message is preserved despite matching the prefix.
    assert msgs[0]["role"] == "user"
    assert "Understood. I am now testing this." in msgs[0]["content"]


def test_purge_does_not_touch_unrelated_assistant_replies() -> None:
    """Only the exact prefix matches. Free-form assistant replies that
    happen to mention 'Understood' or 'now' are preserved."""
    stub = _make_loop_stub_with_history(
        [
            {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "Understood, but here's a different thing."},
            {"role": "assistant", "content": "I am now ready to help."},
            {"role": "assistant", "content": "Understood. I am now gpt-5.4-mini."},  # the only one
        ]
    )
    stub._purge_stale_model_switch_acks()
    msgs = stub.context.messages
    contents = [m["content"] for m in msgs if m["role"] == "assistant"]
    assert "Understood, but here's a different thing." in contents
    assert "I am now ready to help." in contents
    assert "Understood. I am now gpt-5.4-mini." not in contents


def test_purge_on_empty_history_is_noop() -> None:
    """Edge case: switch happens before any messages exist."""
    stub = _make_loop_stub_with_history([])
    stub._purge_stale_model_switch_acks()
    assert stub.context.messages == []


def test_purge_handles_non_string_content() -> None:
    """Anthropic-style multimodal content (list of blocks) must not crash
    the purge. Only string-content acks match."""
    stub = _make_loop_stub_with_history(
        [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Understood. I am now gpt-5.4-mini."}],
            },
            {"role": "assistant", "content": "Understood. I am now gpt-5.4."},  # string match
        ]
    )
    stub._purge_stale_model_switch_acks()
    msgs = stub.context.messages
    # The block-form is preserved (not a string), the plain-string ack is removed.
    assert len(msgs) == 1
    assert isinstance(msgs[0]["content"], list)
