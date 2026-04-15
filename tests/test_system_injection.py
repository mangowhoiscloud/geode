"""Tests for core.agent.system_injection — sandwich-style context reinforcement.

Covers:
  1. build_system_reminder: content assembly, budget enforcement
  2. prepend_system_reminder: injection, idempotency, empty-case
  3. _is_system_reminder: tag detection
"""

from __future__ import annotations

from unittest.mock import patch

from core.agent.system_injection import (
    _MAX_REMINDER_CHARS,
    _REMINDER_TAG,
    _is_system_reminder,
    build_system_reminder,
    prepend_system_reminder,
)

# ---------------------------------------------------------------------------
# build_system_reminder
# ---------------------------------------------------------------------------


class TestBuildSystemReminder:
    """Tests for build_system_reminder()."""

    def test_includes_date(self) -> None:
        """Reminder always includes current date."""
        result = build_system_reminder()
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
        result = build_system_reminder(extra_context={"task": "analyze Berserk"})
        assert "task: analyze Berserk" in result

    def test_budget_enforcement(self) -> None:
        """Reminder truncated when exceeding budget."""
        huge_ctx = {"data": "x" * (_MAX_REMINDER_CHARS + 500)}
        result = build_system_reminder(extra_context=huge_ctx)
        assert len(result) <= _MAX_REMINDER_CHARS + 10  # +10 for "..." and tag
        assert result.endswith("...")

    @patch("core.agent.system_injection._get_active_rules_summary", return_value="rule_a, rule_b")
    def test_active_rules_included(self, _mock: object) -> None:
        """Active rules summary injected when available."""
        result = build_system_reminder()
        assert "Active rules: rule_a, rule_b" in result

    @patch("core.agent.system_injection._get_active_rules_summary", return_value="")
    def test_no_rules_graceful(self, _mock: object) -> None:
        """No crash when no active rules."""
        result = build_system_reminder()
        assert "Active rules" not in result


# ---------------------------------------------------------------------------
# prepend_system_reminder
# ---------------------------------------------------------------------------


class TestPrependSystemReminder:
    """Tests for prepend_system_reminder()."""

    def test_prepends_to_empty_messages(self) -> None:
        """Injection into empty messages list."""
        messages: list[dict] = []
        result = prepend_system_reminder(messages)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert f"[{_REMINDER_TAG}]" in result[0]["content"]

    def test_prepends_before_user_message(self) -> None:
        """Reminder appears before the first user message."""
        messages = [{"role": "user", "content": "Hello"}]
        result = prepend_system_reminder(messages)
        assert len(result) == 2
        assert _is_system_reminder(result[0])
        assert result[1]["content"] == "Hello"

    def test_idempotent_no_stacking(self) -> None:
        """Calling twice replaces rather than stacking reminders."""
        messages = [{"role": "user", "content": "Hello"}]
        prepend_system_reminder(messages, round_idx=0)
        assert len(messages) == 2

        prepend_system_reminder(messages, round_idx=1)
        assert len(messages) == 2  # replaced, not stacked
        assert "Current round: 2" in messages[0]["content"]

    def test_modifies_in_place(self) -> None:
        """Messages list modified in-place (returns same reference)."""
        messages = [{"role": "user", "content": "test"}]
        result = prepend_system_reminder(messages)
        assert result is messages

    def test_preserves_existing_messages(self) -> None:
        """Original messages preserved after injection."""
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ]
        prepend_system_reminder(messages)
        assert len(messages) == 4
        assert messages[1]["content"] == "first"
        assert messages[2]["content"] == "reply"
        assert messages[3]["content"] == "second"


# ---------------------------------------------------------------------------
# _is_system_reminder
# ---------------------------------------------------------------------------


class TestIsSystemReminder:
    """Tests for _is_system_reminder()."""

    def test_detects_reminder(self) -> None:
        msg = {"role": "user", "content": f"[{_REMINDER_TAG}]\nsome context\n[/{_REMINDER_TAG}]"}
        assert _is_system_reminder(msg) is True

    def test_rejects_assistant(self) -> None:
        msg = {"role": "assistant", "content": f"[{_REMINDER_TAG}]\nfoo"}
        assert _is_system_reminder(msg) is False

    def test_rejects_normal_user(self) -> None:
        msg = {"role": "user", "content": "Hello, please analyze Berserk"}
        assert _is_system_reminder(msg) is False

    def test_rejects_list_content(self) -> None:
        """Tool result messages (list content) are not reminders."""
        msg = {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}
        assert _is_system_reminder(msg) is False


# ---------------------------------------------------------------------------
# Integration: AgenticLoop wiring (mock-based)
# ---------------------------------------------------------------------------


class TestAgenticLoopIntegration:
    """Verify that system injection is wired into the agentic loop."""

    def test_import_succeeds(self) -> None:
        """Module imports cleanly from the agentic loop's call site."""
        from core.agent.system_injection import prepend_system_reminder

        assert callable(prepend_system_reminder)

    def test_injection_in_call_path(self) -> None:
        """Verify _call_llm source references system_injection."""
        import inspect

        from core.agent.agentic_loop import AgenticLoop

        source = inspect.getsource(AgenticLoop._call_llm)
        assert "prepend_system_reminder" in source
