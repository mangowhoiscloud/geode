"""Tests for ConversationContext — multi-turn message history."""

from __future__ import annotations

import asyncio
from copy import deepcopy

from core.agent.conversation import ConversationContext


class TestConversationContext:
    """Unit tests for ConversationContext."""

    def test_add_user_message(self) -> None:
        ctx = ConversationContext()
        ctx.add_user_message("hello")
        assert len(ctx.messages) == 1
        assert ctx.messages[0] == {"role": "user", "content": "hello"}

    def test_actual_turn_input_marks_provenance_before_synthetic_continuation(self) -> None:
        from core.agent.loop import AgenticLoop, AgenticLoopConfig
        from core.agent.tool_executor import ToolExecutor

        ctx = ConversationContext()
        loop = AgenticLoop(
            ctx,
            ToolExecutor(),
            config=AgenticLoopConfig(source="payg"),
            model="gpt-5.6-sol",
            provider="openai",
            quiet=True,
        )
        asyncio.run(loop._emit_session_start_signals("Keep my correction verbatim"))
        ctx.add_user_message("synthetic continuation")
        ctx.add_system_event("notification", "background result")

        assert ctx.messages[0] == {
            "role": "user",
            "content": "Keep my correction verbatim",
            "metadata": {"origin": "user_input"},
        }
        assert all("metadata" not in message for message in ctx.messages[1:])

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

    def test_trim_preserves_latest_marked_input_and_not_synthetic_replacements(self) -> None:
        ctx = ConversationContext(max_turns=2)
        latest = {"role": "user", "content": "Corrected goal", "metadata": {"origin": "user_input"}}
        ctx.messages.append(latest)
        for i in range(6):
            ctx.add_user_message(f"synthetic continuation {i}")
            ctx.add_assistant_message(f"result {i}")
            ctx.add_system_event("complete", f"notification {i}")
            assert ctx.messages.count(latest) == 1
        assert ctx.messages[-1]["content"] == "[system:complete] notification 5"

    def test_new_input_replaces_old_retention_anchor(self) -> None:
        ctx = ConversationContext(max_turns=2)
        old = {"role": "user", "content": "Old", "metadata": {"origin": "user_input"}}
        latest = {"role": "user", "content": "New", "metadata": {"origin": "user_input"}}
        ctx.messages.extend([old, latest])
        for i in range(6):
            ctx.add_user_message(f"synthetic continuation {i}")
            ctx.add_assistant_message(f"result {i}")
        assert old not in ctx.messages
        assert ctx.messages.count(latest) == 1

    def test_soft_message_cap_does_not_drop_native_compaction_history(self) -> None:
        ctx = ConversationContext()
        native = {
            "role": "assistant",
            "content": "",
            "anthropic_content": [{"type": "compaction", "content": "Native summary"}],
        }
        ctx.messages = [
            native,
            *[
                {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
                for i in range(400)
            ],
        ]
        original = deepcopy(ctx.messages)

        ctx.add_user_message("Continue after native compaction", origin="user_input")

        assert ctx.messages[:-1] == original
        assert ctx.messages[0] is native
        assert ctx.messages[-1]["metadata"] == {"origin": "user_input"}
