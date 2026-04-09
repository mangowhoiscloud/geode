"""Tests for L4 HookSystem."""

import time

from core.hooks import HookEvent, HookResult, HookSystem, InterceptResult


class TestHookEvent:
    def test_all_events_exist(self):
        assert len(HookEvent) == 55

    def test_event_values(self):
        assert HookEvent.PIPELINE_START.value == "pipeline_start"
        assert HookEvent.PIPELINE_END.value == "pipeline_end"
        assert HookEvent.PIPELINE_ERROR.value == "pipeline_error"
        assert HookEvent.NODE_ENTER.value == "node_enter"
        assert HookEvent.NODE_EXIT.value == "node_exit"
        assert HookEvent.NODE_ERROR.value == "node_error"
        assert HookEvent.ANALYST_COMPLETE.value == "analyst_complete"
        assert HookEvent.EVALUATOR_COMPLETE.value == "evaluator_complete"
        assert HookEvent.SCORING_COMPLETE.value == "scoring_complete"
        assert HookEvent.VERIFICATION_PASS.value == "verification_pass"
        assert HookEvent.VERIFICATION_FAIL.value == "verification_fail"

    def test_new_audit_events(self):
        """v0.42.0 audit: 4 new lifecycle events."""
        assert HookEvent.SHUTDOWN_STARTED.value == "shutdown_started"
        assert HookEvent.CONFIG_RELOADED.value == "config_reloaded"
        assert HookEvent.MCP_SERVER_CONNECTED.value == "mcp_server_connected"
        assert HookEvent.MCP_SERVER_FAILED.value == "mcp_server_failed"

    def test_production_p0_events(self):
        """P0 production hooks: interceptor + cost enforcement + audit."""
        assert HookEvent.USER_INPUT_RECEIVED.value == "user_input_received"
        assert HookEvent.TOOL_EXEC_START.value == "tool_exec_start"
        assert HookEvent.TOOL_EXEC_END.value == "tool_exec_end"
        assert HookEvent.COST_WARNING.value == "cost_warning"
        assert HookEvent.COST_LIMIT_EXCEEDED.value == "cost_limit_exceeded"
        assert HookEvent.EXECUTION_CANCELLED.value == "execution_cancelled"


class TestAuditLoggers:
    """Verify table-driven audit loggers register correctly."""

    def test_audit_loggers_registered(self):
        """build_hooks() registers audit logger handlers."""
        from unittest.mock import patch

        with (
            patch("core.runtime_wiring.bootstrap.RunLog"),
            patch("core.runtime_wiring.bootstrap.StuckDetector"),
        ):
            from core.runtime_wiring.bootstrap import build_hooks

            hooks, _, _, _ = build_hooks(
                session_key="test",
                run_id="test-run",
                log_dir=None,
                stuck_timeout_s=60,
            )

        # Check a representative sample of audit loggers
        all_hooks = hooks.list_hooks()
        assert "ctx_critical" in all_hooks.get("context_critical", [])
        assert "llm_start" in all_hooks.get("llm_call_start", [])
        assert "shutdown" in all_hooks.get("shutdown_started", [])
        assert "mcp_fail" in all_hooks.get("mcp_server_failed", [])

    def test_p0_audit_loggers_registered(self):
        """P0 production audit loggers are registered."""
        from unittest.mock import patch

        with (
            patch("core.runtime_wiring.bootstrap.RunLog"),
            patch("core.runtime_wiring.bootstrap.StuckDetector"),
        ):
            from core.runtime_wiring.bootstrap import build_hooks

            hooks, _, _, _ = build_hooks(
                session_key="test",
                run_id="test-run",
                log_dir=None,
                stuck_timeout_s=60,
            )

        all_hooks = hooks.list_hooks()
        assert "user_input" in all_hooks.get("user_input_received", [])
        assert "tool_start" in all_hooks.get("tool_exec_start", [])
        assert "tool_end" in all_hooks.get("tool_exec_end", [])
        assert "cost_warn" in all_hooks.get("cost_warning", [])
        assert "cost_exceeded" in all_hooks.get("cost_limit_exceeded", [])
        assert "exec_cancel" in all_hooks.get("execution_cancelled", [])


class TestMemoryToolHooks:
    """S4 fix: memory tools fire hook events symmetrically with CLI."""

    def test_rule_create_fires_hook(self):
        """RuleCreateTool.execute() fires RULE_CREATED hook."""
        from unittest.mock import MagicMock, patch

        from core.tools.memory_tools import RuleCreateTool, set_memory_hooks

        mock_hooks = MagicMock()
        set_memory_hooks(mock_hooks)

        mock_proj = MagicMock()
        mock_proj.create_rule.return_value = True

        with patch("core.tools.memory_tools._project_memory_ctx") as ctx:
            ctx.get.return_value = mock_proj
            tool = RuleCreateTool()
            tool.execute(name="test-rule", paths=["*.py"], content="rule body")

        mock_hooks.trigger.assert_called_once()
        call_args = mock_hooks.trigger.call_args
        assert call_args[0][0].value == "rule_created"
        assert call_args[0][1]["name"] == "test-rule"

        set_memory_hooks(None)  # cleanup


class TestHookResult:
    def test_success_result(self):
        r = HookResult(success=True, event=HookEvent.PIPELINE_START, handler_name="my_hook")
        assert r.success is True
        assert r.error is None

    def test_failure_result(self):
        r = HookResult(
            success=False,
            event=HookEvent.NODE_ERROR,
            handler_name="bad_hook",
            error="something broke",
        )
        assert r.success is False
        assert r.error == "something broke"


class TestInterceptResult:
    def test_default_not_blocked(self):
        r = InterceptResult()
        assert r.blocked is False
        assert r.reason == ""
        assert r.data == {}

    def test_blocked_with_reason(self):
        r = InterceptResult(blocked=True, reason="input rejected")
        assert r.blocked is True
        assert r.reason == "input rejected"


class TestHookSystem:
    def test_register_and_trigger(self):
        hooks = HookSystem()
        calls: list[dict] = []

        def on_start(event, data):
            calls.append({"event": event, "data": data})

        hooks.register(HookEvent.PIPELINE_START, on_start)
        results = hooks.trigger(HookEvent.PIPELINE_START, {"ip": "Berserk"})

        assert len(results) == 1
        assert results[0].success is True
        assert len(calls) == 1
        assert calls[0]["data"]["ip"] == "Berserk"

    def test_priority_ordering(self):
        hooks = HookSystem()
        order: list[str] = []

        def low_priority(event, data):
            order.append("low")

        def high_priority(event, data):
            order.append("high")

        hooks.register(HookEvent.NODE_ENTER, low_priority, priority=200)
        hooks.register(HookEvent.NODE_ENTER, high_priority, priority=10)

        hooks.trigger(HookEvent.NODE_ENTER)
        assert order == ["high", "low"]

    def test_multiple_handlers_same_event(self):
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(HookEvent.PIPELINE_END, lambda e, d: calls.append("a"), name="a")
        hooks.register(HookEvent.PIPELINE_END, lambda e, d: calls.append("b"), name="b")

        results = hooks.trigger(HookEvent.PIPELINE_END)
        assert len(results) == 2
        assert len(calls) == 2

    def test_handler_error_doesnt_stop_chain(self):
        hooks = HookSystem()
        calls: list[str] = []

        def bad_hook(event, data):
            raise ValueError("boom")

        def good_hook(event, data):
            calls.append("ok")

        hooks.register(HookEvent.NODE_EXIT, bad_hook, name="bad", priority=1)
        hooks.register(HookEvent.NODE_EXIT, good_hook, name="good", priority=2)

        results = hooks.trigger(HookEvent.NODE_EXIT)
        assert len(results) == 2
        assert results[0].success is False
        assert results[0].error == "boom"
        assert results[1].success is True
        assert calls == ["ok"]

    def test_trigger_no_handlers(self):
        hooks = HookSystem()
        results = hooks.trigger(HookEvent.SCORING_COMPLETE)
        assert results == []

    def test_unregister(self):
        hooks = HookSystem()
        hooks.register(HookEvent.PIPELINE_START, lambda e, d: None, name="tmp")
        assert hooks.unregister(HookEvent.PIPELINE_START, "tmp") is True
        assert hooks.trigger(HookEvent.PIPELINE_START) == []

    def test_unregister_nonexistent(self):
        hooks = HookSystem()
        assert hooks.unregister(HookEvent.PIPELINE_START, "nope") is False

    def test_list_hooks(self):
        hooks = HookSystem()
        hooks.register(HookEvent.NODE_ENTER, lambda e, d: None, name="h1")
        hooks.register(HookEvent.NODE_EXIT, lambda e, d: None, name="h2")

        all_hooks = hooks.list_hooks()
        assert "node_enter" in all_hooks
        assert "h1" in all_hooks["node_enter"]

        filtered = hooks.list_hooks(HookEvent.NODE_EXIT)
        assert "node_exit" in filtered
        assert "h2" in filtered["node_exit"]

    def test_clear_specific_event(self):
        hooks = HookSystem()
        hooks.register(HookEvent.NODE_ENTER, lambda e, d: None, name="a")
        hooks.register(HookEvent.NODE_EXIT, lambda e, d: None, name="b")

        hooks.clear(HookEvent.NODE_ENTER)
        assert hooks.list_hooks(HookEvent.NODE_ENTER) == {"node_enter": []}
        assert "b" in hooks.list_hooks(HookEvent.NODE_EXIT)["node_exit"]

    def test_clear_all(self):
        hooks = HookSystem()
        hooks.register(HookEvent.NODE_ENTER, lambda e, d: None, name="a")
        hooks.register(HookEvent.NODE_EXIT, lambda e, d: None, name="b")

        hooks.clear()
        assert hooks.list_hooks() == {}

    def test_default_name_from_function(self):
        hooks = HookSystem()

        def my_handler(event, data):
            pass

        hooks.register(HookEvent.PIPELINE_START, my_handler)
        all_hooks = hooks.list_hooks()
        assert "my_handler" in all_hooks["pipeline_start"]

    def test_trigger_with_none_data(self):
        hooks = HookSystem()
        received: list[dict] = []

        def handler(event, data):
            received.append(data)

        hooks.register(HookEvent.PIPELINE_START, handler)
        hooks.trigger(HookEvent.PIPELINE_START)  # No data arg
        assert received == [{}]


class TestInterceptor:
    """Tests for trigger_interceptor() — block/modify semantics."""

    def test_interceptor_pass_through(self):
        """Handler returns None → not blocked."""
        hooks = HookSystem()
        hooks.register(HookEvent.USER_INPUT_RECEIVED, lambda e, d: None, name="noop")

        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {"user_input": "hello"})
        assert result.blocked is False
        assert result.data["user_input"] == "hello"

    def test_interceptor_block(self):
        """Handler returns {"block": True} → blocked with reason."""
        hooks = HookSystem()

        def blocker(_event, _data):
            return {"block": True, "reason": "profanity detected"}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, blocker, name="filter")

        result = hooks.trigger_interceptor(
            HookEvent.USER_INPUT_RECEIVED, {"user_input": "bad words"}
        )
        assert result.blocked is True
        assert result.reason == "profanity detected"

    def test_interceptor_block_stops_chain(self):
        """Once a handler blocks, subsequent handlers do not run."""
        hooks = HookSystem()
        calls: list[str] = []

        def blocker(_event, _data):
            calls.append("blocker")
            return {"block": True, "reason": "blocked"}

        def after_blocker(_event, _data):
            calls.append("after")

        hooks.register(HookEvent.USER_INPUT_RECEIVED, blocker, name="b", priority=10)
        hooks.register(HookEvent.USER_INPUT_RECEIVED, after_blocker, name="a", priority=20)

        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {})
        assert result.blocked is True
        assert calls == ["blocker"]

    def test_interceptor_modify(self):
        """Handler returns {"modify": {...}} → data updated."""
        hooks = HookSystem()

        def modifier(_event, _data):
            return {"modify": {"sanitized": True, "user_input": "cleaned"}}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, modifier, name="sanitizer")

        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {"user_input": "raw"})
        assert result.blocked is False
        assert result.data["sanitized"] is True
        assert result.data["user_input"] == "cleaned"

    def test_interceptor_chained_modifications(self):
        """Multiple handlers can chain modifications."""
        hooks = HookSystem()

        def add_flag(_event, _data):
            return {"modify": {"flag_a": True}}

        def add_another_flag(_event, _data):
            return {"modify": {"flag_b": True}}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, add_flag, name="a", priority=10)
        hooks.register(HookEvent.USER_INPUT_RECEIVED, add_another_flag, name="b", priority=20)

        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {"base": 1})
        assert result.data["base"] == 1
        assert result.data["flag_a"] is True
        assert result.data["flag_b"] is True

    def test_interceptor_error_continues_chain(self):
        """Handler exception is non-blocking — chain continues."""
        hooks = HookSystem()

        def failing(_event, _data):
            raise ValueError("oops")

        def good(_event, _data):
            return {"modify": {"ok": True}}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, failing, name="bad", priority=10)
        hooks.register(HookEvent.USER_INPUT_RECEIVED, good, name="good", priority=20)

        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {})
        assert result.blocked is False
        assert result.data["ok"] is True

    def test_interceptor_no_handlers(self):
        """No handlers registered → pass through."""
        hooks = HookSystem()
        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {"x": 1})
        assert result.blocked is False
        assert result.data == {"x": 1}

    def test_interceptor_defensive_copy(self):
        """Input data dict is not mutated."""
        hooks = HookSystem()

        def modifier(_event, _data):
            return {"modify": {"added": True}}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, modifier, name="m")

        original = {"key": "val"}
        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, original)
        assert "added" in result.data
        assert "added" not in original  # original unchanged


class TestHookTimeout:
    """Tests for per-hook timeout via _call_handler."""

    def test_timeout_skips_slow_handler(self):
        """Slow handler is skipped when timeout_s is set."""
        hooks = HookSystem()

        def slow_handler(_event, _data):
            time.sleep(5)
            return {"modify": {"slow": True}}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, slow_handler, name="slow")

        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {"x": 1}, timeout_s=0.1)
        assert result.blocked is False
        assert "slow" not in result.data  # handler was skipped

    def test_no_timeout_runs_normally(self):
        """Without timeout, handler runs to completion."""
        hooks = HookSystem()

        def fast_handler(_event, _data):
            return {"modify": {"fast": True}}

        hooks.register(HookEvent.USER_INPUT_RECEIVED, fast_handler, name="fast")

        result = hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {})
        assert result.data["fast"] is True
