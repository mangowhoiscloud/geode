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

  1. ``_build_model_card(model)`` names the active model + provider in
     a single neutral line (PR-MIC 2026-05-23 weakened the v0.52.8
     strong "non-negotiable" assertion to Option B from the X2
     decision; the strong block is grep-pinned absent by
     ``test_model_card_does_not_carry_assertion_overhead``).

  2. ``AgenticLoop.update_model`` purges prior ``"Understood. I am now
     <prev>."`` assistant acks BEFORE adding the new one — string AND
     Anthropic-style block-form. Each switch leaves exactly one
     active ack.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import core.agent.loop as _loop_mod
import pytest
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
# Contract 1 — model card names the active model + provider (Option B / PR-MIC)
# ---------------------------------------------------------------------------


def test_model_card_names_active_model() -> None:
    """The model card must name the active model — minimal, non-aggressive.

    PR-MIC (2026-05-23) — Option B from the X2 decision: drop the
    v0.52.8 strong "non-negotiable" assertion + stale-ack override
    sentences. Root cause of the original incident is now fully
    covered by ``_purge_stale_model_switch_acks`` (block-form aware
    after PR-MIC). The system prompt stays informative without the
    ~80-token assertion overhead per round.
    """
    card = _build_model_card("gpt-5.5")
    assert "<model_card>" in card
    assert "gpt-5.5" in card
    # Provider context retained.
    assert "openai" in card.lower()


def test_model_card_includes_provider() -> None:
    """Sanity: the model card still names the provider for context."""
    card = _build_model_card("gpt-5.5")
    assert "openai" in card.lower()


def test_model_card_for_anthropic_model() -> None:
    """Same shape for Anthropic models — identity statement is provider-agnostic."""
    card = _build_model_card("claude-opus-4-7")
    assert "<model_card>" in card
    assert "claude-opus-4-7" in card
    assert "anthropic" in card.lower()


def test_model_card_does_not_carry_assertion_overhead() -> None:
    """PR-MIC drift guard — the strong-assertion sentences from v0.52.8
    must not creep back without an explicit revisit of the X2 decision.

    Pin the three load-bearing phrases of the old "non-negotiable"
    block so a future drift surfaces in CI rather than at runtime.
    """
    card = _build_model_card("gpt-5.5")
    assert "non-negotiable" not in card.lower(), (
        "the v0.52.8 strong assertion was dropped in PR-MIC; re-adding "
        "it needs a fresh X2 decision (purge already covers root cause)"
    )
    assert "When asked which model you are" not in card, (
        "explicit-answer assertion dropped — purge now handles ack pollution"
    )
    assert "stale acknowledgements" not in card, (
        "stale-ack override sentence dropped — purge already strips acks"
    )


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


def test_purge_handles_block_form_content() -> None:
    """Anthropic-style multimodal content (list of blocks) must also be
    purged when the first text block carries our self-emitted ack
    prefix. PR-MIC (2026-05-23) — pre-fix the block-form was silently
    preserved, so a model switch could leave a stale identity ack
    behind if any code path stored the ack as blocks."""
    stub = _make_loop_stub_with_history(
        [
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Understood. I am now gpt-5.4-mini."}],
            },
            {"role": "assistant", "content": "Understood. I am now gpt-5.4."},  # string match
            # Non-matching block — should survive (different prefix).
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Here is the answer to your question."}],
            },
        ]
    )
    stub._purge_stale_model_switch_acks()
    msgs = stub.context.messages
    # Both prefix-matching acks gone (block + string). Unrelated block survives.
    assert len(msgs) == 1
    assert isinstance(msgs[0]["content"], list)
    assert msgs[0]["content"][0]["text"].startswith("Here is")


def test_purge_handles_mixed_block_types() -> None:
    """Block-form content with mixed types (text + image) must not crash;
    only text blocks are scanned for the prefix."""
    stub = _make_loop_stub_with_history(
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "image", "source": {"type": "base64", "data": "..."}},
                    {"type": "text", "text": "Understood. I am now claude-opus-4-6."},
                ],
            },
        ]
    )
    stub._purge_stale_model_switch_acks()
    # Any text-block matching the prefix → drop the whole message.
    assert stub.context.messages == []
