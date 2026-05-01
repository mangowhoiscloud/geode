"""Tests for ``apply_messages_cache_control`` — Hermes system_and_3 strategy.

Verifies rolling message-level cache_control breakpoints, non-mutation,
edge cases (empty/short message lists), and content-shape handling
(str vs list[block]).
"""

from __future__ import annotations

from typing import Any

import pytest
from core.llm.providers.anthropic import (
    MAX_MESSAGE_CACHE_BREAKPOINTS,
    apply_messages_cache_control,
)


class TestApplyMessagesCacheControl:
    def test_empty_messages_returns_empty(self):
        assert apply_messages_cache_control([]) == []

    def test_zero_breakpoints_returns_copy_without_marks(self):
        original = [{"role": "user", "content": "hi"}]
        out = apply_messages_cache_control(original, n_breakpoints=0)
        assert out == original
        assert out is not original  # copied, not aliased

    def test_does_not_mutate_input(self):
        original: list[dict[str, Any]] = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "second"},
        ]
        snapshot = [dict(m) for m in original]
        apply_messages_cache_control(original)
        assert original == snapshot, "input must be unchanged"

    def test_single_user_message_string_content(self):
        out = apply_messages_cache_control([{"role": "user", "content": "hello"}])
        assert len(out) == 1
        content = out[0]["content"]
        assert isinstance(content, list)
        assert len(content) == 1
        assert content[0] == {
            "type": "text",
            "text": "hello",
            "cache_control": {"type": "ephemeral"},
        }

    def test_marks_last_three_messages_only(self):
        msgs = [
            {"role": "user", "content": "m1"},
            {"role": "assistant", "content": "m2"},
            {"role": "user", "content": "m3"},
            {"role": "assistant", "content": "m4"},
            {"role": "user", "content": "m5"},
        ]
        out = apply_messages_cache_control(msgs)
        # First two messages: untouched (still string)
        assert out[0]["content"] == "m1"
        assert out[1]["content"] == "m2"
        # Last three: marked
        for i in (2, 3, 4):
            content = out[i]["content"]
            assert isinstance(content, list)
            assert content[0].get("cache_control") == {"type": "ephemeral"}

    def test_list_content_marks_last_block_only(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "abc", "content": "ok"},
                    {"type": "text", "text": "follow-up"},
                ],
            }
        ]
        out = apply_messages_cache_control(msgs)
        blocks = out[0]["content"]
        assert "cache_control" not in blocks[0]
        assert blocks[1]["cache_control"] == {"type": "ephemeral"}

    def test_skips_system_role(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "u1"},
        ]
        out = apply_messages_cache_control(msgs)
        # System untouched
        assert out[0]["content"] == "sys"
        # User marked (still within last-3 window)
        assert isinstance(out[1]["content"], list)
        assert out[1]["content"][0].get("cache_control") == {"type": "ephemeral"}

    def test_skips_empty_content(self):
        msgs = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": []},
        ]
        out = apply_messages_cache_control(msgs)
        # Empty string falls through string path: gets converted to one block
        assert isinstance(out[0]["content"], list)
        # Empty list content: skipped silently (still empty list)
        assert out[1]["content"] == []

    def test_max_breakpoints_constant(self):
        # Anthropic 4-cap minus 1 for system → 3 for messages
        assert MAX_MESSAGE_CACHE_BREAKPOINTS == 3

    def test_fewer_messages_than_breakpoints(self):
        msgs = [{"role": "user", "content": "only"}]
        out = apply_messages_cache_control(msgs, n_breakpoints=3)
        assert isinstance(out[0]["content"], list)
        assert out[0]["content"][0].get("cache_control") == {"type": "ephemeral"}

    def test_custom_breakpoints(self):
        msgs = [{"role": "user", "content": f"m{i}"} for i in range(5)]
        out = apply_messages_cache_control(msgs, n_breakpoints=1)
        # Only the last one should be marked
        for i in range(4):
            assert out[i]["content"] == f"m{i}"
        last = out[4]["content"]
        assert isinstance(last, list)
        assert last[0].get("cache_control") == {"type": "ephemeral"}


class TestNonMutation:
    """Defensive: re-applying does not double up."""

    def test_idempotent_on_already_cached(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "hi", "cache_control": {"type": "ephemeral"}},
                ],
            }
        ]
        out = apply_messages_cache_control(msgs)
        block = out[0]["content"][0]
        # Marker stays exactly one
        assert block["cache_control"] == {"type": "ephemeral"}

    def test_repeated_calls_independent(self):
        msgs = [{"role": "user", "content": "m"}]
        first = apply_messages_cache_control(msgs)
        second = apply_messages_cache_control(msgs)
        # Both produce equivalent result, neither mutates the input
        assert first == second
        assert msgs == [{"role": "user", "content": "m"}]


@pytest.mark.parametrize(
    "n",
    [0, 1, 2, 3, 5, 10],
)
def test_n_breakpoints_bound(n: int):
    msgs = [{"role": "user", "content": f"m{i}"} for i in range(20)]
    out = apply_messages_cache_control(msgs, n_breakpoints=n)
    marked = sum(
        1
        for m in out
        if isinstance(m["content"], list) and m["content"] and m["content"][-1].get("cache_control")
    )
    assert marked == min(n, 20)
