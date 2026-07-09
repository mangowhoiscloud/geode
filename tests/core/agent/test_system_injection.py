"""Tests for core.agent.system_injection — XML context reinforcement.

Covers:
  1. build_system_reminder: content assembly, budget enforcement
  2. append_system_reminder: end-adjacent injection, input immutability,
     legacy-prefix strip
  3. TestCacheContract: prompt-cache prefix stability guard
     (PR-CACHE-REMINDER, 2026-06-10)
  4. _is_system_reminder: tag detection
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from core.agent.system_injection import (
    _MAX_REMINDER_CHARS,
    _REMINDER_TAG,
    _is_system_reminder,
    append_system_reminder,
    build_system_reminder,
)

# ---------------------------------------------------------------------------
# build_system_reminder
# ---------------------------------------------------------------------------


class TestBuildSystemReminder:
    """Tests for build_system_reminder()."""

    def test_includes_date(self) -> None:
        """Reminder includes current date by default."""
        result = build_system_reminder()
        assert "Current date:" in result

    @patch("core.agent.system_prompt.get_active_rule_names", return_value=[])
    def test_omits_date_for_openai_model(self, _mock: object) -> None:
        """OpenAI GPT-family reminders inherit the no-current-date policy."""
        result = build_system_reminder(model="gpt-5.5")
        assert result == ""

    def test_keeps_date_for_anthropic_model(self) -> None:
        """Non-OpenAI reminders keep the recency guard."""
        result = build_system_reminder(model="claude-opus-4-8")
        assert "Current date:" in result

    def test_includes_round_when_nonzero(self) -> None:
        """Round index included when > 0."""
        result = build_system_reminder(round_idx=3)
        assert "Current round: 4" in result

    def test_excludes_round_when_zero(self) -> None:
        """Round index excluded at round 0."""
        result = build_system_reminder(round_idx=0)
        assert "Current round" not in result

    def test_extra_context_included(self) -> None:
        """Extra context key-value pairs are included."""
        result = build_system_reminder(extra_context={"task": "analyze Project Atlas"})
        assert "task: analyze Project Atlas" in result

    def test_budget_enforcement(self) -> None:
        """Reminder truncated when exceeding budget."""
        huge_ctx = {"data": "x" * (_MAX_REMINDER_CHARS + 500)}
        result = build_system_reminder(extra_context=huge_ctx)
        assert len(result) <= _MAX_REMINDER_CHARS + 10  # +10 for "..." and tag
        assert result.endswith("...")

    @patch("core.agent.system_prompt.get_active_rule_names", return_value=["rule_a", "rule_b"])
    def test_active_rules_included(self, _mock: object) -> None:
        """Active rules summary injected when available."""
        result = build_system_reminder()
        assert "Active rules: rule_a, rule_b" in result

    @patch("core.agent.system_prompt.get_active_rule_names", return_value=[])
    def test_no_rules_graceful(self, _mock: object) -> None:
        """No crash when no active rules."""
        result = build_system_reminder()
        assert "Active rules" not in result


# ---------------------------------------------------------------------------
# append_system_reminder
# ---------------------------------------------------------------------------


class TestAppendSystemReminder:
    """Tests for append_system_reminder()."""

    def test_appends_to_empty_messages(self) -> None:
        """Injection into empty messages list."""
        messages: list[dict[str, Any]] = []
        result = append_system_reminder(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert f"<{_REMINDER_TAG}>" in result[0]["content"]
        assert f"</{_REMINDER_TAG}>" in result[0]["content"]

    @patch("core.agent.system_prompt.get_active_rule_names", return_value=[])
    def test_openai_without_other_context_appends_nothing(self, _mock: object) -> None:
        """No empty reminder is appended after OpenAI date elision."""
        messages = [{"role": "user", "content": "Hello"}]
        result = append_system_reminder(messages, model="gpt-5.5")
        assert result == messages

    def test_appends_after_latest_user_message(self) -> None:
        """Reminder is the LAST message, after all history."""
        messages = [{"role": "user", "content": "Hello"}]
        result = append_system_reminder(messages)
        assert len(result) == 2
        assert result[0]["content"] == "Hello"
        assert _is_system_reminder(result[1])

    def test_preserves_existing_messages(self) -> None:
        """Full history preserved in order, reminder appended last."""
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        result = append_system_reminder(messages)
        assert len(result) == 4
        assert [m["content"] for m in result[:3]] == ["first", "reply", "second"]
        assert _is_system_reminder(result[3])

    def test_strips_legacy_position0_reminder(self) -> None:
        """A reminder persisted at [0] by the old prepend design is dropped."""
        legacy = f"<{_REMINDER_TAG}>\nCurrent date: stale\n</{_REMINDER_TAG}>"
        messages = [
            {"role": "user", "content": legacy},
            {"role": "user", "content": "Hello"},
        ]
        result = append_system_reminder(messages)
        assert len(result) == 2
        assert result[0]["content"] == "Hello"
        assert _is_system_reminder(result[1])
        assert "stale" not in result[1]["content"]


# ---------------------------------------------------------------------------
# Cache contract — prefix stability (PR-CACHE-REMINDER, 2026-06-10)
# ---------------------------------------------------------------------------


class TestCacheContract:
    """Prompt-cache guards: history prefix must stay byte-stable across rounds.

    The pre-2026-06-10 design inserted the reminder at messages[0] and
    rewrote it per round, invalidating the entire message-prefix cache on
    every agentic round. These tests pin the append-only contract.
    """

    def test_input_list_not_mutated(self) -> None:
        """The caller's history list is never modified."""
        messages = [{"role": "user", "content": "Hello"}]
        snapshot = [dict(m) for m in messages]
        result = append_system_reminder(messages, round_idx=2)
        assert messages == snapshot
        assert result is not messages

    def test_history_prefix_stable_across_rounds(self) -> None:
        """Round-varying reminder bytes land ONLY in the final message.

        result[:-1] must be identical across rounds — that is the cacheable
        prefix. Only the appended reminder may differ.
        """
        history = [
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "working"},
        ]
        round1 = append_system_reminder(history, round_idx=1)
        round2 = append_system_reminder(history, round_idx=2)
        assert round1[:-1] == round2[:-1] == history
        assert round1[-1] != round2[-1]  # round counter differs, as intended

    def test_reminder_never_first_message(self) -> None:
        """With non-empty history the reminder must not occupy messages[0]."""
        messages = [{"role": "user", "content": "Hello"}]
        result = append_system_reminder(messages, round_idx=1)
        assert not _is_system_reminder(result[0])
        assert _is_system_reminder(result[-1])


# ---------------------------------------------------------------------------
# _is_system_reminder
# ---------------------------------------------------------------------------


class TestIsSystemReminder:
    """Tests for _is_system_reminder()."""

    def test_detects_reminder(self) -> None:
        msg = {"role": "user", "content": f"<{_REMINDER_TAG}>\nsome context\n</{_REMINDER_TAG}>"}
        assert _is_system_reminder(msg) is True

    def test_rejects_assistant(self) -> None:
        msg = {"role": "assistant", "content": f"<{_REMINDER_TAG}>\nfoo"}
        assert _is_system_reminder(msg) is False

    def test_rejects_normal_user(self) -> None:
        msg = {"role": "user", "content": "Hello, please analyze Project Atlas"}
        assert _is_system_reminder(msg) is False

    def test_rejects_list_content(self) -> None:
        """Tool result messages (list content) are not reminders."""
        msg = {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}
        assert _is_system_reminder(msg) is False


# ---------------------------------------------------------------------------
# Integration: AgenticLoop wiring (source-based)
# ---------------------------------------------------------------------------


class TestAgenticLoopIntegration:
    """Verify that system injection is wired into the agentic loop."""

    def test_import_succeeds(self) -> None:
        """Module imports cleanly from the agentic loop's call site."""
        from core.agent.system_injection import append_system_reminder

        assert callable(append_system_reminder)

    def test_injection_in_call_path(self) -> None:
        """_call_llm appends the reminder and does so AFTER the overflow check.

        Order is load-bearing: the overflow check must see (and prune) the
        shared history list; the per-request reminder copy is made afterwards.
        """
        import inspect

        from core.agent.loop import AgenticLoop

        source = inspect.getsource(AgenticLoop._call_llm)
        assert "append_system_reminder" in source
        assert "prepend_system_reminder" not in source
        assert source.index("_check_context_overflow") < source.index(
            "append_system_reminder(messages"
        )
