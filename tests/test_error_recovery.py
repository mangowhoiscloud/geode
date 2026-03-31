"""Tests for adaptive error recovery system.

Covers:
- ErrorRecoveryStrategy: retry, alternative, fallback, escalate
- AgenticLoop integration: recovery chain replaces auto-skip
- Safety: DANGEROUS/WRITE tools excluded from recovery
- Hook events: TOOL_RECOVERY_ATTEMPTED/SUCCEEDED/FAILED
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.agent.agentic_loop import AgenticLoop
from core.agent.conversation import ConversationContext
from core.agent.error_recovery import (
    _EXCLUDED_TOOLS,
    ErrorRecoveryStrategy,
    RecoveryResult,
    RecoveryStrategy,
)
from core.agent.tool_executor import ToolExecutor
from core.hooks import HookEvent, HookSystem

# ---------------------------------------------------------------------------
# ErrorRecoveryStrategy unit tests
# ---------------------------------------------------------------------------


class TestErrorRecoveryStrategy:
    """Unit tests for ErrorRecoveryStrategy."""

    @pytest.fixture()
    def executor(self) -> ToolExecutor:
        """Executor with multiple handlers for testing alternatives."""
        handlers: dict[str, Any] = {
            "list_ips": MagicMock(return_value={"status": "ok", "ips": []}),
            "search_ips": MagicMock(return_value={"status": "ok", "results": []}),
            "analyze_ip": MagicMock(return_value={"status": "ok", "tier": "S"}),
            "show_help": MagicMock(return_value={"status": "ok"}),
        }
        return ToolExecutor(action_handlers=handlers, auto_approve=True)

    @pytest.fixture()
    def strategy(self, executor: ToolExecutor) -> ErrorRecoveryStrategy:
        """Strategy with zero retry delay for fast tests."""
        return ErrorRecoveryStrategy(executor, retry_base_delay=0.0)

    def test_retry_success(self, strategy: ErrorRecoveryStrategy) -> None:
        """1st failure → retry succeeds → recovery OK."""
        result = strategy.recover("list_ips", {}, failure_count=1)
        assert result.recovered is True
        assert result.strategy_used == RecoveryStrategy.RETRY
        assert len(result.attempts) == 1
        assert result.attempts[0].success is True

    def test_retry_failure_then_alternative(self, executor: ToolExecutor) -> None:
        """retry fails → alternative tool (same category) succeeds."""
        # list_ips and search_ips are both 'discovery' category
        call_count = 0

        def failing_list(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"error": "Connection timeout"}

        executor._handlers["list_ips"] = failing_list
        strategy = ErrorRecoveryStrategy(executor, retry_base_delay=0.0)

        result = strategy.recover("list_ips", {}, failure_count=2)
        # retry fails (list_ips still broken), then alternative (search_ips) succeeds
        assert result.recovered is True
        assert result.strategy_used == RecoveryStrategy.ALTERNATIVE
        assert len(result.attempts) >= 2

    def test_no_alternative_then_fallback(self, executor: ToolExecutor) -> None:
        """No alternative in same category → try cheaper fallback."""
        # analyze_ip is 'analysis' category, 'expensive' tier
        # Make analyze_ip fail
        executor._handlers["analyze_ip"] = MagicMock(return_value={"error": "API timeout"})
        # compare_ips would be alternative but not registered
        # search_ips is 'discovery'/'free' — different category but cheaper
        strategy = ErrorRecoveryStrategy(executor, retry_base_delay=0.0)

        result = strategy.recover("analyze_ip", {"ip_name": "Berserk"}, failure_count=2)
        # Should try: retry (fail) → alternative (might find one or fail) → fallback/escalate
        assert len(result.attempts) >= 2

    def test_all_strategies_exhausted_returns_failure(self, executor: ToolExecutor) -> None:
        """All strategies fail → recovery exhausted."""
        # Make all tools fail
        for name in executor._handlers:
            executor._handlers[name] = MagicMock(return_value={"error": "Everything is broken"})
        strategy = ErrorRecoveryStrategy(executor, retry_base_delay=0.0)

        result = strategy.recover("list_ips", {}, failure_count=2)
        assert result.recovered is False
        assert "recovery_exhausted" in result.final_result or "escalated" in result.final_result

    def test_max_recovery_attempts_limit(self, executor: ToolExecutor) -> None:
        """Recovery stops after max_recovery_attempts."""
        for name in executor._handlers:
            executor._handlers[name] = MagicMock(return_value={"error": "Broken"})
        strategy = ErrorRecoveryStrategy(executor, max_recovery_attempts=2, retry_base_delay=0.0)

        result = strategy.recover("list_ips", {}, failure_count=2)
        assert result.recovered is False
        assert len(result.attempts) <= 2

    def test_dangerous_tools_excluded(self, strategy: ErrorRecoveryStrategy) -> None:
        """DANGEROUS tools (run_bash) are not eligible for recovery."""
        assert not strategy.is_recoverable("run_bash")
        result = strategy.recover("run_bash", {"command": "echo hi"}, failure_count=2)
        assert result.recovered is False
        assert "recovery_skipped" in result.final_result

    def test_write_tools_excluded(self, strategy: ErrorRecoveryStrategy) -> None:
        """WRITE tools (memory_save, note_save, etc.) are not eligible."""
        for tool in ("memory_save", "note_save", "set_api_key", "manage_auth"):
            assert not strategy.is_recoverable(tool)
            result = strategy.recover(tool, {}, failure_count=2)
            assert result.recovered is False
            assert "recovery_skipped" in result.final_result

    def test_excluded_tools_constant(self) -> None:
        """Verify the excluded tools set matches expectations."""
        assert "run_bash" in _EXCLUDED_TOOLS
        assert "memory_save" in _EXCLUDED_TOOLS
        assert "note_save" in _EXCLUDED_TOOLS
        assert "set_api_key" in _EXCLUDED_TOOLS
        assert "manage_auth" in _EXCLUDED_TOOLS
        # Safe tools should NOT be excluded
        assert "list_ips" not in _EXCLUDED_TOOLS

    def test_first_failure_only_retries(self, strategy: ErrorRecoveryStrategy) -> None:
        """On first failure, only retry is attempted (no alternative/fallback)."""
        strategies = strategy._select_strategies("list_ips", failure_count=1)
        assert strategies == [RecoveryStrategy.RETRY]

    def test_second_failure_enables_full_chain(self, strategy: ErrorRecoveryStrategy) -> None:
        """On 2+ failures, the full chain is enabled."""
        strategies = strategy._select_strategies("list_ips", failure_count=2)
        assert RecoveryStrategy.RETRY in strategies
        assert RecoveryStrategy.ESCALATE in strategies

    def test_recovery_result_summary(self) -> None:
        """RecoveryResult.to_summary() produces readable text."""
        result = RecoveryResult(
            recovered=True,
            final_result={"status": "ok"},
            strategy_used=RecoveryStrategy.ALTERNATIVE,
            attempts=[MagicMock()],
        )
        summary = result.to_summary()
        assert "alternative" in summary.lower()
        assert "succeeded" in summary.lower()

    def test_recovery_failure_summary(self) -> None:
        """Failed recovery summary lists tried strategies."""
        attempt = MagicMock()
        attempt.strategy = RecoveryStrategy.RETRY
        result = RecoveryResult(
            recovered=False,
            final_result={"error": "all failed"},
            attempts=[attempt],
        )
        summary = result.to_summary()
        assert "failed" in summary.lower()
        assert "retry" in summary.lower()

    def test_escalate_always_fails(self, strategy: ErrorRecoveryStrategy) -> None:
        """Escalate strategy always returns failure (signals HITL needed)."""
        import time

        attempt = strategy._try_escalate("list_ips", {}, time.monotonic())
        assert attempt.success is False
        assert attempt.result.get("escalated") is True

    def test_alternative_finds_same_category_tool(self, strategy: ErrorRecoveryStrategy) -> None:
        """Alternative lookup finds tools in the same category."""
        # list_ips and search_ips are both 'discovery' category
        alt = strategy._find_alternative("list_ips")
        assert alt == "search_ips"

    def test_alternative_skips_excluded_tools(self, executor: ToolExecutor) -> None:
        """Alternative lookup skips DANGEROUS/WRITE tools."""
        executor._handlers["memory_save"] = MagicMock(return_value={"status": "ok"})
        strategy = ErrorRecoveryStrategy(executor, retry_base_delay=0.0)
        # memory_save is 'memory' category, same as memory_search
        # But memory_save is excluded
        alt = strategy._find_alternative("memory_save")
        assert alt is None  # memory_save itself is excluded from recovery

    def test_fallback_finds_cheaper_tier(self, strategy: ErrorRecoveryStrategy) -> None:
        """Fallback finds a cheaper tool (lower cost_tier)."""
        # analyze_ip is 'expensive', list_ips is 'free'
        fallback = strategy._find_fallback("analyze_ip")
        assert fallback is not None
        # The fallback should be a registered tool with lower cost tier
        tool_def = strategy._tool_lookup.get(fallback, {})
        assert tool_def.get("cost_tier") in ("free", "cheap")

    def test_fallback_returns_none_for_free_tools(self, strategy: ErrorRecoveryStrategy) -> None:
        """No fallback exists for tools already at 'free' tier."""
        # list_ips is already 'free' — can't go cheaper
        fallback = strategy._find_fallback("list_ips")
        assert fallback is None


# ---------------------------------------------------------------------------
# AgenticLoop integration tests
# ---------------------------------------------------------------------------


class TestAgenticLoopRecovery:
    """Integration tests for error recovery in AgenticLoop."""

    @pytest.fixture()
    def context(self) -> ConversationContext:
        return ConversationContext(max_turns=10)

    @pytest.fixture()
    def hooks(self) -> HookSystem:
        return HookSystem()

    def _make_tool_response(self, tool_name: str, tool_input: dict[str, Any]) -> MagicMock:
        """Create a mock LLM response with a tool_use block."""
        tool_block = MagicMock()
        tool_block.type = "tool_use"
        tool_block.name = tool_name
        tool_block.input = tool_input
        tool_block.id = f"toolu_{tool_name}_123"

        response = MagicMock()
        response.content = [tool_block]
        return response

    def test_recovery_replaces_auto_skip(
        self, context: ConversationContext, hooks: HookSystem
    ) -> None:
        """After 2 consecutive failures, recovery chain is attempted."""
        call_count = 0

        def sometimes_fails(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"error": "timeout"}
            return {"status": "ok", "ips": []}

        executor = ToolExecutor(action_handlers={"list_ips": sometimes_fails}, auto_approve=True)
        loop = AgenticLoop(context, executor, hooks=hooks)
        loop._tool_processor._consecutive_failures = {"list_ips": 2}  # simulate 2 prior failures

        response = self._make_tool_response("list_ips", {})
        results = asyncio.run(loop._tool_processor.process(response))

        assert len(results) == 1
        content = results[0]["content"]
        # Should contain recovery attempt info, not just "skipped"
        assert "recovery" in content.lower() or "status" in content.lower()

    def test_recovery_success_resets_failure_counter(self, context: ConversationContext) -> None:
        """Successful recovery resets the consecutive failure counter."""
        executor = ToolExecutor(
            action_handlers={
                "list_ips": MagicMock(return_value={"status": "ok"}),
                "search_ips": MagicMock(return_value={"status": "ok"}),
            },
            auto_approve=True,
        )
        loop = AgenticLoop(context, executor)
        loop._tool_processor._consecutive_failures = {"list_ips": 2}

        response = self._make_tool_response("list_ips", {})
        asyncio.run(loop._tool_processor.process(response))

        # After successful recovery, counter should be reset
        assert loop._tool_processor._consecutive_failures.get("list_ips", 0) == 0

    def test_hook_events_emitted_on_recovery(
        self, context: ConversationContext, hooks: HookSystem
    ) -> None:
        """Recovery attempts emit TOOL_RECOVERY_ATTEMPTED and SUCCEEDED/FAILED."""
        events_received: list[HookEvent] = []

        def capture_event(event: HookEvent, data: dict[str, Any]) -> None:
            events_received.append(event)

        hooks.register(HookEvent.TOOL_RECOVERY_ATTEMPTED, capture_event)
        hooks.register(HookEvent.TOOL_RECOVERY_SUCCEEDED, capture_event)
        hooks.register(HookEvent.TOOL_RECOVERY_FAILED, capture_event)

        executor = ToolExecutor(
            action_handlers={
                "list_ips": MagicMock(return_value={"status": "ok"}),
            },
            auto_approve=True,
        )
        loop = AgenticLoop(context, executor, hooks=hooks)
        loop._tool_processor._consecutive_failures = {"list_ips": 2}

        response = self._make_tool_response("list_ips", {})
        asyncio.run(loop._tool_processor.process(response))

        assert HookEvent.TOOL_RECOVERY_ATTEMPTED in events_received
        # Either succeeded or failed should be emitted
        assert (
            HookEvent.TOOL_RECOVERY_SUCCEEDED in events_received
            or HookEvent.TOOL_RECOVERY_FAILED in events_received
        )

    def test_dangerous_tool_skips_recovery(self, context: ConversationContext) -> None:
        """DANGEROUS tools bypass recovery and return error directly."""
        executor = ToolExecutor(auto_approve=True)
        loop = AgenticLoop(context, executor)
        loop._tool_processor._consecutive_failures = {"run_bash": 2}

        response = self._make_tool_response("run_bash", {"command": "echo hi", "reason": "test"})

        with patch.object(executor, "_request_approval", return_value=False):
            results = asyncio.run(loop._tool_processor.process(response))

        assert len(results) == 1
        content = results[0]["content"]
        assert "recovery_skipped" in content or "denied" in content

    def test_below_threshold_no_recovery(self, context: ConversationContext) -> None:
        """Below _MAX_CONSECUTIVE_FAILURES, no recovery is triggered."""
        executor = ToolExecutor(
            action_handlers={
                "list_ips": MagicMock(return_value={"error": "timeout"}),
            },
            auto_approve=True,
        )
        loop = AgenticLoop(context, executor)
        loop._tool_processor._consecutive_failures = {"list_ips": 0}  # first failure

        response = self._make_tool_response("list_ips", {})
        results = asyncio.run(loop._tool_processor.process(response))

        content = results[0]["content"]
        # Should be normal error, not recovery
        assert "recovery" not in content.lower()

    def test_recovery_backward_compatible_with_old_skip(self, context: ConversationContext) -> None:
        """Recovery still produces a usable tool_result for the LLM."""
        executor = ToolExecutor(
            action_handlers={
                "list_ips": MagicMock(return_value={"error": "broken"}),
                "search_ips": MagicMock(return_value={"error": "also broken"}),
            },
            auto_approve=True,
        )
        loop = AgenticLoop(context, executor)
        loop._tool_processor._consecutive_failures = {"list_ips": 3}

        response = self._make_tool_response("list_ips", {})
        results = asyncio.run(loop._tool_processor.process(response))

        # Must produce exactly 1 tool_result
        assert len(results) == 1
        assert results[0]["type"] == "tool_result"
        assert results[0]["tool_use_id"] == "toolu_list_ips_123"
        # Content must be valid JSON string
        import json

        parsed = json.loads(results[0]["content"])
        assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# Hook event definition tests
# ---------------------------------------------------------------------------


class TestRecoveryHookEvents:
    """Verify new HookEvents exist and work correctly."""

    def test_hook_events_defined(self) -> None:
        """All three recovery hook events are defined."""
        assert hasattr(HookEvent, "TOOL_RECOVERY_ATTEMPTED")
        assert hasattr(HookEvent, "TOOL_RECOVERY_SUCCEEDED")
        assert hasattr(HookEvent, "TOOL_RECOVERY_FAILED")

    def test_hook_event_values(self) -> None:
        """Hook event string values follow convention."""
        assert HookEvent.TOOL_RECOVERY_ATTEMPTED.value == "tool_recovery_attempted"
        assert HookEvent.TOOL_RECOVERY_SUCCEEDED.value == "tool_recovery_succeeded"
        assert HookEvent.TOOL_RECOVERY_FAILED.value == "tool_recovery_failed"

    def test_hook_system_triggers_recovery_events(self) -> None:
        """HookSystem can register and trigger recovery events."""
        hooks = HookSystem()
        received: list[dict[str, Any]] = []

        def on_recovery(event: HookEvent, data: dict[str, Any]) -> None:
            received.append({"event": event, **data})

        hooks.register(HookEvent.TOOL_RECOVERY_ATTEMPTED, on_recovery)
        hooks.trigger(
            HookEvent.TOOL_RECOVERY_ATTEMPTED,
            {"tool_name": "list_ips", "fail_count": 2},
        )

        assert len(received) == 1
        assert received[0]["tool_name"] == "list_ips"

    def test_total_hook_event_count(self) -> None:
        """Verify total hook event count after H6 orphan pruning."""
        assert len(HookEvent) == 46


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestRecoveryEdgeCases:
    """Edge cases for the error recovery system."""

    def test_unregistered_tool_recovery(self) -> None:
        """Recovery for a tool with no handler returns failure."""
        executor = ToolExecutor(auto_approve=True)
        strategy = ErrorRecoveryStrategy(executor, retry_base_delay=0.0)
        result = strategy.recover("nonexistent_tool", {}, failure_count=2)
        # retry will fail (no handler), and eventually exhausts
        assert result.recovered is False

    def test_recovery_with_zero_max_attempts(self) -> None:
        """max_recovery_attempts=0 means no recovery attempted."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"list_ips": handler}, auto_approve=True)
        strategy = ErrorRecoveryStrategy(executor, max_recovery_attempts=0, retry_base_delay=0.0)
        result = strategy.recover("list_ips", {}, failure_count=2)
        assert result.recovered is False
        assert len(result.attempts) == 0

    def test_recovery_passes_original_input(self) -> None:
        """Recovery retry uses the original tool_input."""
        captured_kwargs: dict[str, Any] = {}

        def capture_handler(**kwargs: Any) -> dict[str, Any]:
            captured_kwargs.update(kwargs)
            return {"status": "ok"}

        executor = ToolExecutor(action_handlers={"analyze_ip": capture_handler}, auto_approve=True)
        strategy = ErrorRecoveryStrategy(executor, retry_base_delay=0.0)
        strategy.recover("analyze_ip", {"ip_name": "Berserk", "dry_run": True}, failure_count=1)
        assert captured_kwargs.get("ip_name") == "Berserk"
        assert captured_kwargs.get("dry_run") is True

    def test_is_recoverable_for_safe_tools(self) -> None:
        """Safe tools are recoverable."""
        executor = ToolExecutor(auto_approve=True)
        strategy = ErrorRecoveryStrategy(executor)
        assert strategy.is_recoverable("list_ips") is True
        assert strategy.is_recoverable("analyze_ip") is True
        assert strategy.is_recoverable("search_ips") is True

    def test_recovery_attempt_records_duration(self) -> None:
        """Each recovery attempt records duration_ms."""
        handler = MagicMock(return_value={"status": "ok"})
        executor = ToolExecutor(action_handlers={"list_ips": handler}, auto_approve=True)
        strategy = ErrorRecoveryStrategy(executor, retry_base_delay=0.0)
        result = strategy.recover("list_ips", {}, failure_count=1)
        assert result.attempts[0].duration_ms >= 0
