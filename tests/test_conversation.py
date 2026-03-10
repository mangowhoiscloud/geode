"""Tests for ConversationContext — multi-turn message history."""

from __future__ import annotations

from core.cli.conversation import ConversationContext


class TestConversationContext:
    """Unit tests for ConversationContext."""

    def test_add_user_message(self) -> None:
        ctx = ConversationContext()
        ctx.add_user_message("hello")
        assert len(ctx.messages) == 1
        assert ctx.messages[0] == {"role": "user", "content": "hello"}

    def test_add_assistant_message(self) -> None:
        ctx = ConversationContext()
        ctx.add_user_message("hi")
        ctx.add_assistant_message("hello back")
        assert len(ctx.messages) == 2
        assert ctx.messages[1]["role"] == "assistant"

    def test_add_tool_result(self) -> None:
        ctx = ConversationContext()
        ctx.add_user_message("test")
        tool_results = [{"type": "tool_result", "tool_use_id": "123", "content": "ok"}]
        ctx.add_tool_result(tool_results)
        assert len(ctx.messages) == 2
        assert ctx.messages[1]["role"] == "user"
        assert ctx.messages[1]["content"] == tool_results

    def test_get_messages_returns_deep_copy(self) -> None:
        ctx = ConversationContext()
        ctx.add_user_message("hello")
        msgs = ctx.get_messages()
        # Modify the copy
        msgs[0]["content"] = "modified"
        # Original should be unchanged
        assert ctx.messages[0]["content"] == "hello"

    def test_clear(self) -> None:
        ctx = ConversationContext()
        ctx.add_user_message("a")
        ctx.add_assistant_message("b")
        ctx.clear()
        assert ctx.is_empty
        assert len(ctx.messages) == 0

    def test_turn_count(self) -> None:
        ctx = ConversationContext()
        assert ctx.turn_count == 0
        ctx.add_user_message("q1")
        ctx.add_assistant_message("a1")
        ctx.add_user_message("q2")
        assert ctx.turn_count == 2

    def test_is_empty(self) -> None:
        ctx = ConversationContext()
        assert ctx.is_empty
        ctx.add_user_message("test")
        assert not ctx.is_empty

    def test_trim_keeps_max_messages(self) -> None:
        ctx = ConversationContext(max_turns=3)
        # Add 5 turns (10 messages) — should trim to 6 (3 turns)
        for i in range(5):
            ctx.add_user_message(f"q{i}")
            ctx.add_assistant_message(f"a{i}")
        assert len(ctx.messages) <= 6

    def test_trim_ensures_user_first(self) -> None:
        ctx = ConversationContext(max_turns=2)
        # Add 4 turns to trigger trimming
        for i in range(4):
            ctx.add_user_message(f"q{i}")
            ctx.add_assistant_message(f"a{i}")
        # First message should always be user
        assert ctx.messages[0]["role"] == "user"

    def test_max_turns_one_keeps_two_messages(self) -> None:
        ctx = ConversationContext(max_turns=1)
        # Add 3 turns (6 messages) — should trim to 2 (1 turn)
        for i in range(3):
            ctx.add_user_message(f"q{i}")
            ctx.add_assistant_message(f"a{i}")
        assert len(ctx.messages) <= 2
