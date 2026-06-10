"""Tests for L4 HookSystem."""

import asyncio
import time

from core.agent.context_manager import ContextWindowManager
from core.hooks import HookEvent, HookResult, HookSystem, InterceptResult


class TestHookEvent:
    def test_all_events_exist(self):
        # Canonical total-count assertion for the HookEvent enum.
        # PR-HOOKEVENT-RESERVE (2026-05-26) consolidated this — the 3
        # sibling files (test_error_recovery.py, test_mcp_lifecycle.py,
        # test_llm_lifecycle_hooks.py) used to duplicate this assertion,
        # so every new HookEvent broke 4 tests in lockstep. They now
        # assert only their topic-specific event existence; total count
        # lives here.
        # Tally: +6 PR-2 cognitive + 5 OL-A1.5 auto-trigger
        # + 3 PR-CL-BUDGET handoff + 5 PR-HOOKEVENT-RESERVE (mutation /
        # baseline lifecycle) + 1 PR-MAX-GEN
        # (SELF_IMPROVING_AUTO_TRIGGER_MAX_GENERATION_REACHED) +
        # 1 PR-NO-FALLBACK (ADAPTER_DISPATCH_ATTEMPT).
        assert len(HookEvent) == 64

    def test_event_values(self):
        assert HookEvent.SESSION_STARTED.value == "session_start"
        assert HookEvent.SESSION_ENDED.value == "session_end"
        assert HookEvent.SUBAGENT_STARTED.value == "subagent_started"
        assert HookEvent.SUBAGENT_COMPLETED.value == "subagent_completed"
        assert HookEvent.SUBAGENT_FAILED.value == "subagent_failed"
        assert HookEvent.TURN_COMPLETED.value == "turn_complete"
        assert HookEvent.TRIGGER_FIRED.value == "trigger_fired"

    def test_new_audit_events(self):
        """v0.42.0 audit: 4 new lifecycle events."""
        assert HookEvent.SHUTDOWN_STARTED.value == "shutdown_started"
        assert HookEvent.CONFIG_RELOADED.value == "config_reloaded"
        assert HookEvent.MCP_SERVER_CONNECTED.value == "mcp_server_connected"
        assert HookEvent.MCP_SERVER_FAILED.value == "mcp_server_failed"

    def test_production_p0_events(self):
        """P0 production hooks: interceptor + cost enforcement + audit."""
        assert HookEvent.USER_INPUT_RECEIVED.value == "user_input_received"
        assert HookEvent.TOOL_EXEC_STARTED.value == "tool_exec_start"
        assert HookEvent.TOOL_EXEC_ENDED.value == "tool_exec_end"
        assert HookEvent.TOOL_EXEC_FAILED.value == "tool_exec_failed"
        assert HookEvent.TOOL_RESULT_TRANSFORM.value == "tool_result_transform"
        assert HookEvent.COST_WARNING.value == "cost_warning"
        assert HookEvent.COST_LIMIT_EXCEEDED.value == "cost_limit_exceeded"
        assert HookEvent.EXECUTION_CANCELLED.value == "execution_cancelled"


class TestAuditLoggers:
    """Verify table-driven audit loggers register correctly."""

    def test_audit_loggers_registered(self):
        """build_hooks() registers audit logger handlers."""
        from unittest.mock import patch

        with (
            patch("core.wiring.bootstrap.RunLog"),
        ):
            from core.wiring.bootstrap import build_hooks

            hooks, _, _ = build_hooks(
                session_key="test",
                run_id="test-run",
                log_dir=None,
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
            patch("core.wiring.bootstrap.RunLog"),
        ):
            from core.wiring.bootstrap import build_hooks

            hooks, _, _ = build_hooks(
                session_key="test",
                run_id="test-run",
                log_dir=None,
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
            asyncio.run(tool.aexecute(name="test-rule", paths=["*.py"], content="rule body"))

        mock_hooks.trigger.assert_called_once()
        call_args = mock_hooks.trigger.call_args
        assert call_args[0][0].value == "rule_created"
        assert call_args[0][1]["name"] == "test-rule"

        set_memory_hooks(None)  # cleanup


class TestHookResult:
    def test_success_result(self):
        r = HookResult(success=True, event=HookEvent.SESSION_STARTED, handler_name="my_hook")
        assert r.success is True
        assert r.error is None

    def test_failure_result(self):
        r = HookResult(
            success=False,
            event=HookEvent.TOOL_EXEC_FAILED,
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

        hooks.register(HookEvent.SESSION_STARTED, on_start)
        results = hooks.trigger(HookEvent.SESSION_STARTED, {"subject": "Project Atlas"})

        assert len(results) == 1
        assert results[0].success is True
        assert len(calls) == 1
        assert calls[0]["data"]["subject"] == "Project Atlas"

    def test_priority_ordering(self):
        hooks = HookSystem()
        order: list[str] = []

        def low_priority(event, data):
            order.append("low")

        def high_priority(event, data):
            order.append("high")

        hooks.register(HookEvent.TOOL_EXEC_STARTED, low_priority, priority=200)
        hooks.register(HookEvent.TOOL_EXEC_STARTED, high_priority, priority=10)

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED)
        assert order == ["high", "low"]

    def test_multiple_handlers_same_event(self):
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(HookEvent.SESSION_ENDED, lambda e, d: calls.append("a"), name="a")
        hooks.register(HookEvent.SESSION_ENDED, lambda e, d: calls.append("b"), name="b")

        results = hooks.trigger(HookEvent.SESSION_ENDED)
        assert len(results) == 2
        assert len(calls) == 2

    def test_handler_error_doesnt_stop_chain(self):
        hooks = HookSystem()
        calls: list[str] = []

        def bad_hook(event, data):
            raise ValueError("boom")

        def good_hook(event, data):
            calls.append("ok")

        hooks.register(HookEvent.TOOL_EXEC_ENDED, bad_hook, name="bad", priority=1)
        hooks.register(HookEvent.TOOL_EXEC_ENDED, good_hook, name="good", priority=2)

        results = hooks.trigger(HookEvent.TOOL_EXEC_ENDED)
        assert len(results) == 2
        assert results[0].success is False
        assert results[0].error == "boom"
        assert results[1].success is True
        assert calls == ["ok"]

    def test_trigger_no_handlers(self):
        hooks = HookSystem()
        results = hooks.trigger(HookEvent.TURN_COMPLETED)
        assert results == []

    def test_unregister(self):
        hooks = HookSystem()
        hooks.register(HookEvent.SESSION_STARTED, lambda e, d: None, name="tmp")
        assert hooks.unregister(HookEvent.SESSION_STARTED, "tmp") is True
        assert hooks.trigger(HookEvent.SESSION_STARTED) == []

    def test_unregister_nonexistent(self):
        hooks = HookSystem()
        assert hooks.unregister(HookEvent.SESSION_STARTED, "nope") is False

    def test_list_hooks(self):
        hooks = HookSystem()
        hooks.register(HookEvent.TOOL_EXEC_STARTED, lambda e, d: None, name="h1")
        hooks.register(HookEvent.TOOL_EXEC_ENDED, lambda e, d: None, name="h2")

        all_hooks = hooks.list_hooks()
        assert "tool_exec_start" in all_hooks
        assert "h1" in all_hooks["tool_exec_start"]

        filtered = hooks.list_hooks(HookEvent.TOOL_EXEC_ENDED)
        assert "tool_exec_end" in filtered
        assert "h2" in filtered["tool_exec_end"]

    def test_clear_specific_event(self):
        hooks = HookSystem()
        hooks.register(HookEvent.TOOL_EXEC_STARTED, lambda e, d: None, name="a")
        hooks.register(HookEvent.TOOL_EXEC_ENDED, lambda e, d: None, name="b")

        hooks.clear(HookEvent.TOOL_EXEC_STARTED)
        assert hooks.list_hooks(HookEvent.TOOL_EXEC_STARTED) == {"tool_exec_start": []}
        assert "b" in hooks.list_hooks(HookEvent.TOOL_EXEC_ENDED)["tool_exec_end"]

    def test_clear_all(self):
        hooks = HookSystem()
        hooks.register(HookEvent.TOOL_EXEC_STARTED, lambda e, d: None, name="a")
        hooks.register(HookEvent.TOOL_EXEC_ENDED, lambda e, d: None, name="b")

        hooks.clear()
        assert hooks.list_hooks() == {}

    def test_default_name_from_function(self):
        hooks = HookSystem()

        def my_handler(event, data):
            pass

        hooks.register(HookEvent.SESSION_STARTED, my_handler)
        all_hooks = hooks.list_hooks()
        assert "my_handler" in all_hooks["session_start"]

    def test_trigger_with_none_data(self):
        hooks = HookSystem()
        received: list[dict] = []

        def handler(event, data):
            received.append(data)

        hooks.register(HookEvent.SESSION_STARTED, handler)
        hooks.trigger(HookEvent.SESSION_STARTED)  # No data arg
        assert received == [{}]


class TestRegisterPrefix:
    """PR-COMM-2 (2026-05-24) — wildcard prefix subscriptions.

    Replaces the bootstrap pattern ``for event in HookEvent:
    hooks.register(event, handler, ...)`` with a single
    ``register_prefix("*", handler, ...)`` call. Future HookEvent
    additions automatically extend subscriber coverage instead of
    silently bypassing every wildcard handler.
    """

    def test_star_subscribes_to_every_event(self):
        hooks = HookSystem()
        seen: list[HookEvent] = []

        def universal(event, _data):
            seen.append(event)

        hooks.register_prefix("*", universal)

        for event in (
            HookEvent.SESSION_STARTED,
            HookEvent.TOOL_EXEC_STARTED,
            HookEvent.SUBAGENT_FAILED,
            HookEvent.LLM_CALL_ENDED,
        ):
            hooks.trigger(event)

        assert seen == [
            HookEvent.SESSION_STARTED,
            HookEvent.TOOL_EXEC_STARTED,
            HookEvent.SUBAGENT_FAILED,
            HookEvent.LLM_CALL_ENDED,
        ]

    def test_prefix_match_segment_boundary(self):
        """``"SESSION"`` matches ``SESSION_STARTED`` but not ``SESSIONLESS_*``
        (none such today — the test guards against a future regression
        where someone replaces the ``+ "_"`` boundary with a bare
        ``startswith``)."""
        hooks = HookSystem()
        seen: list[HookEvent] = []

        def node_handler(event, _data):
            seen.append(event)

        hooks.register_prefix("TOOL_EXEC", node_handler)

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED)
        hooks.trigger(HookEvent.TOOL_EXEC_ENDED)
        hooks.trigger(HookEvent.SESSION_STARTED)  # must NOT fire

        assert seen == [HookEvent.TOOL_EXEC_STARTED, HookEvent.TOOL_EXEC_ENDED]

    def test_exact_event_name_matches_prefix(self):
        """``prefix == event.name`` matches the exact event (not just
        ``<prefix>_<suffix>`` shapes). Allows a handler to subscribe to
        a single event via the prefix API for consistency with
        :meth:`register`."""
        hooks = HookSystem()
        seen: list[HookEvent] = []

        def handler(event, _data):
            seen.append(event)

        hooks.register_prefix("TURN_COMPLETED", handler)

        hooks.trigger(HookEvent.TURN_COMPLETED)
        hooks.trigger(HookEvent.SESSION_STARTED)  # different event

        assert seen == [HookEvent.TURN_COMPLETED]

    def test_dedup_across_exact_and_prefix(self):
        """When the same handler name is registered as both exact and
        wildcard, only ONE invocation fires per trigger (the exact-match
        entry wins — see ``_resolve_hooks_for`` dedup contract)."""
        hooks = HookSystem()
        call_count = [0]

        def shared_handler(_event, _data):
            call_count[0] += 1

        hooks.register(HookEvent.SESSION_STARTED, shared_handler, name="dup_handler")
        hooks.register_prefix("SESSION", shared_handler, name="dup_handler")

        hooks.trigger(HookEvent.SESSION_STARTED)

        assert call_count[0] == 1

    def test_priority_merged_across_exact_and_prefix(self):
        """Exact-registered and prefix-registered handlers compose in a
        single priority-sorted execution order, NOT exact-first then
        wildcards. Ensures wildcards aren't relegated to "always last"."""
        hooks = HookSystem()
        order: list[str] = []

        def low_exact(_event, _data):
            order.append("low_exact")

        def high_prefix(_event, _data):
            order.append("high_prefix")

        hooks.register(HookEvent.SESSION_STARTED, low_exact, priority=200)
        hooks.register_prefix("SESSION", high_prefix, priority=10)

        hooks.trigger(HookEvent.SESSION_STARTED)

        assert order == ["high_prefix", "low_exact"]

    def test_unregister_prefix_removes_subscriber(self):
        hooks = HookSystem()
        fired = [0]

        def handler(_e, _d):
            fired[0] += 1

        hooks.register_prefix("*", handler, name="watchall")
        hooks.trigger(HookEvent.SESSION_STARTED)
        assert fired[0] == 1

        removed = hooks.unregister_prefix("*", "watchall")
        assert removed is True

        hooks.trigger(HookEvent.SESSION_STARTED)
        assert fired[0] == 1  # no change after unregister

    def test_unregister_prefix_returns_false_when_missing(self):
        hooks = HookSystem()
        assert hooks.unregister_prefix("SESSION", "ghost") is False

    def test_dedup_within_same_prefix_replaces_handler(self):
        """Re-registering with the same name under the same prefix
        replaces (matches :meth:`register`'s per-event dedup)."""
        hooks = HookSystem()
        seen: list[str] = []

        def v1(_e, _d):
            seen.append("v1")

        def v2(_e, _d):
            seen.append("v2")

        hooks.register_prefix("SESSION", v1, name="versioned")
        hooks.register_prefix("SESSION", v2, name="versioned")

        hooks.trigger(HookEvent.SESSION_STARTED)

        assert seen == ["v2"]

    def test_prefix_handler_fires_on_async_trigger(self):
        """The async trigger path must consult the same wildcard table
        as the sync trigger path — otherwise async-using callers would
        see different coverage."""
        import asyncio

        hooks = HookSystem()
        seen: list[HookEvent] = []

        def handler(event, _data):
            seen.append(event)

        hooks.register_prefix("*", handler)
        asyncio.run(hooks.trigger_async(HookEvent.SESSION_ENDED))
        assert seen == [HookEvent.SESSION_ENDED]

    def test_prefix_handler_fires_on_interceptor_trigger(self):
        """Same coverage invariant for the interceptor channel."""
        hooks = HookSystem()
        seen: list[HookEvent] = []

        def handler(event, _data):
            seen.append(event)

        hooks.register_prefix("*", handler)
        hooks.trigger_interceptor(HookEvent.USER_INPUT_RECEIVED, {"user_input": "hi"})
        assert seen == [HookEvent.USER_INPUT_RECEIVED]

    def test_list_hooks_includes_wildcard_subscribers(self):
        """``list_hooks()`` introspection must surface wildcard handlers
        — pre-fix they were invisible (registered in ``_prefix_hooks``
        which ``list_hooks`` didn't consult). The wildcard channel is
        keyed as ``"*<prefix>"`` so callers can distinguish it from the
        exact-match channels."""
        hooks = HookSystem()

        def watcher(_e, _d):
            pass

        hooks.register_prefix("*", watcher, name="run_log_handler")

        all_hooks = hooks.list_hooks()
        assert "**" in all_hooks
        assert "run_log_handler" in all_hooks["**"]

    def test_list_hooks_event_specific_includes_matching_wildcards(self):
        """When ``list_hooks(event)`` is called, the result lists every
        handler that would fire on a trigger of that event — including
        wildcard subscribers whose prefix matches."""
        hooks = HookSystem()

        def exact(_e, _d):
            pass

        def wild(_e, _d):
            pass

        hooks.register(HookEvent.TOOL_EXEC_STARTED, exact, name="exact_h")
        hooks.register_prefix("TOOL_EXEC", wild, name="wild_h")

        listing = hooks.list_hooks(HookEvent.TOOL_EXEC_STARTED)
        names = listing[HookEvent.TOOL_EXEC_STARTED.value]
        assert "exact_h" in names
        assert "wild_h" in names

    def test_clear_all_drops_wildcards_too(self):
        """``clear()`` with no event must drop wildcard subscriptions
        alongside exact registrations — otherwise wildcards survive
        ``clear()`` and pollute the next test / serve restart."""
        hooks = HookSystem()
        fired = [0]

        def watcher(_e, _d):
            fired[0] += 1

        hooks.register_prefix("*", watcher)
        hooks.clear()

        hooks.trigger(HookEvent.SESSION_STARTED)
        assert fired[0] == 0

    def test_clear_specific_event_keeps_wildcards(self):
        """Per-event ``clear(EVENT)`` only drops handlers registered
        directly against that event; wildcards remain bound and
        continue firing on subsequent triggers of that event."""
        hooks = HookSystem()
        fired = [0]

        def watcher(_e, _d):
            fired[0] += 1

        hooks.register_prefix("*", watcher)
        hooks.register(HookEvent.SESSION_STARTED, lambda *_: None, name="exact_only")
        hooks.clear(HookEvent.SESSION_STARTED)

        hooks.trigger(HookEvent.SESSION_STARTED)
        assert fired[0] == 1  # wildcard survived

    def test_replaces_bootstrap_for_event_loop(self):
        """Regression pin for the bootstrap migration:
        ``hooks.register_prefix("*", handler)`` must produce the same
        observable behaviour as the pre-fix ``for event in HookEvent:
        hooks.register(event, handler, ...)`` loop. Triggering EVERY
        event must invoke the handler EVERY time."""
        hooks = HookSystem()
        call_count = [0]

        def handler(_event, _data):
            call_count[0] += 1

        hooks.register_prefix("*", handler, name="run_log_handler")

        for event in HookEvent:
            hooks.trigger(event)

        assert call_count[0] == len(HookEvent)


class TestAsyncHookSystem:
    def test_trigger_async_awaits_async_handler(self):
        hooks = HookSystem()
        calls: list[str] = []

        async def async_handler(_event, data):
            await asyncio.sleep(0)
            calls.append(data["subject"])

        hooks.register(HookEvent.SESSION_STARTED, async_handler, name="async_handler")

        results = asyncio.run(hooks.trigger_async(HookEvent.SESSION_STARTED, {"subject": "GEODE"}))

        assert [r.success for r in results] == [True]
        assert calls == ["GEODE"]

    def test_trigger_with_result_async_captures_return(self):
        hooks = HookSystem()

        async def async_modifier(_event, _data):
            await asyncio.sleep(0)
            return {"updated_result": {"data": "async"}}

        hooks.register(HookEvent.TOOL_EXEC_ENDED, async_modifier, name="async_modifier")

        results = asyncio.run(
            hooks.trigger_with_result_async(
                HookEvent.TOOL_EXEC_ENDED,
                {"tool_name": "fetch", "tool_input": {}, "result": {"data": "raw"}},
            )
        )

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].data == {"updated_result": {"data": "async"}}

    def test_trigger_interceptor_async_applies_modifications(self):
        hooks = HookSystem()

        async def async_interceptor(_event, _data):
            await asyncio.sleep(0)
            return {"modify": {"tool_input": {"limit": 3}}}

        hooks.register(HookEvent.TOOL_EXEC_STARTED, async_interceptor, name="async_interceptor")

        result = asyncio.run(
            hooks.trigger_interceptor_async(
                HookEvent.TOOL_EXEC_STARTED,
                {"tool_name": "list_subjects", "tool_input": {"limit": 1}},
            )
        )

        assert result.blocked is False
        assert result.data["tool_input"] == {"limit": 3}


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


class TestToolExecInterceptor:
    """Tests for TOOL_EXEC_START interceptor and TOOL_EXEC_END feedback patterns."""

    def test_tool_exec_start_block(self):
        """TOOL_EXEC_START interceptor can block tool execution."""
        hooks = HookSystem()

        def blocker(_event, data):
            if data.get("tool_name") == "dangerous_tool":
                return {"block": True, "reason": "tool blocked by policy"}
            return None

        hooks.register(HookEvent.TOOL_EXEC_STARTED, blocker, name="policy_gate")

        result = hooks.trigger_interceptor(
            HookEvent.TOOL_EXEC_STARTED,
            {"tool_name": "dangerous_tool", "tool_input": {"cmd": "rm -rf /"}},
        )
        assert result.blocked is True
        assert result.reason == "tool blocked by policy"

    def test_tool_exec_start_modify_input(self):
        """TOOL_EXEC_START interceptor can modify tool_input."""
        hooks = HookSystem()

        def sanitizer(_event, data):
            return {"modify": {"tool_input": {"sanitized": True}}}

        hooks.register(HookEvent.TOOL_EXEC_STARTED, sanitizer, name="input_sanitizer")

        result = hooks.trigger_interceptor(
            HookEvent.TOOL_EXEC_STARTED,
            {"tool_name": "search", "tool_input": {"query": "raw"}},
        )
        assert result.blocked is False
        assert result.data["tool_input"] == {"sanitized": True}

    def test_tool_exec_start_passthrough(self):
        """TOOL_EXEC_START with no-op handler passes through."""
        hooks = HookSystem()
        hooks.register(HookEvent.TOOL_EXEC_STARTED, lambda e, d: None, name="observer")

        result = hooks.trigger_interceptor(
            HookEvent.TOOL_EXEC_STARTED,
            {"tool_name": "safe_tool", "tool_input": {}},
        )
        assert result.blocked is False
        assert result.data["tool_name"] == "safe_tool"

    def test_tool_exec_end_modify_result(self):
        """TOOL_EXEC_END trigger_with_result can return updated_result."""
        hooks = HookSystem()

        def result_modifier(_event, data):
            if data.get("tool_name") == "fetch":
                return {"updated_result": {"data": "transformed"}}
            return None

        hooks.register(HookEvent.TOOL_EXEC_ENDED, result_modifier, name="transformer")

        results = hooks.trigger_with_result(
            HookEvent.TOOL_EXEC_ENDED,
            {
                "tool_name": "fetch",
                "tool_input": {},
                "duration_ms": 100,
                "has_error": False,
                "result": {"data": "raw"},
            },
        )
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].data["updated_result"] == {"data": "transformed"}

    def test_tool_exec_end_additional_context(self):
        """TOOL_EXEC_END handler can inject additional_context."""
        hooks = HookSystem()

        def ctx_injector(_event, _data):
            return {"additional_context": "Extra info from hook"}

        hooks.register(HookEvent.TOOL_EXEC_ENDED, ctx_injector, name="ctx_inject")

        results = hooks.trigger_with_result(
            HookEvent.TOOL_EXEC_ENDED,
            {"tool_name": "search", "tool_input": {}, "duration_ms": 50, "has_error": False},
        )
        assert results[0].data["additional_context"] == "Extra info from hook"

    def test_tool_exec_end_no_modification(self):
        """TOOL_EXEC_END observe-only handler returns empty data."""
        hooks = HookSystem()
        hooks.register(HookEvent.TOOL_EXEC_ENDED, lambda e, d: None, name="observer")

        results = hooks.trigger_with_result(
            HookEvent.TOOL_EXEC_ENDED,
            {"tool_name": "t", "tool_input": {}, "duration_ms": 1, "has_error": False},
        )
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].data == {}


class TestAggressiveRecoveryHook:
    """aggressive_context_recovery delegates to CONTEXT_OVERFLOW_ACTION hook."""

    def test_aggressive_recovery_uses_hook(self):
        """aggressive_context_recovery fires CONTEXT_OVERFLOW_ACTION via _resolve_overflow_strategy."""
        from unittest.mock import MagicMock, patch

        from core.orchestration.context_monitor import ContextMetrics

        hook_calls: list[dict] = []

        hooks = HookSystem()

        def strategy_handler(_event, data):
            hook_calls.append(data)
            return {"strategy": "prune", "keep_recent": 5}

        hooks.register(HookEvent.CONTEXT_OVERFLOW_ACTION, strategy_handler, name="test_handler")

        mgr = ContextWindowManager(hooks=hooks, quiet=True)

        critical = ContextMetrics(
            estimated_tokens=180_000,
            context_window=200_000,
            usage_pct=98.0,
            remaining_tokens=20_000,
            is_warning=True,
            is_critical=True,
        )
        resolved = ContextMetrics(
            estimated_tokens=60_000,
            context_window=200_000,
            usage_pct=30.0,
            remaining_tokens=140_000,
            is_warning=False,
            is_critical=False,
        )

        mock_settings = MagicMock()
        mock_settings.compact_keep_recent = 10

        with (
            patch(
                "core.orchestration.context_monitor.check_context",
                side_effect=[critical, critical, resolved],
            ),
            patch(
                "core.orchestration.context_monitor.summarize_tool_results",
                return_value=(0, 0, 0),
            ),
            patch("core.config.settings", mock_settings),
            patch(
                "core.orchestration.context_monitor.prune_oldest_messages",
                side_effect=lambda m, **kw: m[:3],
            ),
        ):
            import asyncio

            asyncio.run(
                mgr.aggressive_context_recovery(
                    "system", [{"role": "user", "content": "hi"}] * 20, "gpt-4o", "openai"
                )
            )

        # Verify hook was called
        assert len(hook_calls) == 1
        assert hook_calls[0]["provider"] == "openai"
        assert hook_calls[0]["model"] == "gpt-4o"


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


class TestMatcher:
    """Tests for matcher-based tool_name filtering on TOOL_EXEC_* events."""

    def test_matcher_filters_tool_name(self):
        """Handler with matcher only fires for matching tool_name."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            lambda e, d: calls.append("bash"),
            name="bash_only",
            matcher="run_bash",
        )

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "run_bash"})
        assert calls == ["bash"]

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "web_search"})
        assert calls == ["bash"]  # not fired again

    def test_matcher_regex_pattern(self):
        """Matcher supports regex patterns (pipe alternation)."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            lambda e, d: calls.append(d["tool_name"]),
            name="dangerous",
            matcher="run_bash|terminal|computer_use",
        )

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "run_bash"})
        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "terminal"})
        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "web_search"})
        assert calls == ["run_bash", "terminal"]

    def test_empty_matcher_matches_all(self):
        """Empty matcher (default) fires for all tools."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            lambda e, d: calls.append(d["tool_name"]),
            name="all_tools",
        )

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "any_tool"})
        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "other_tool"})
        assert calls == ["any_tool", "other_tool"]

    def test_matcher_ignored_for_non_tool_events(self):
        """Matcher is ignored for non-tool events (e.g., SESSION_STARTED)."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.SESSION_STARTED,
            lambda e, d: calls.append("fired"),
            name="with_matcher",
            matcher="run_bash",
        )

        hooks.trigger(HookEvent.SESSION_STARTED, {"tool_name": "something_else"})
        assert calls == ["fired"]  # matcher not applied

    def test_matcher_on_interceptor(self):
        """Matcher works with trigger_interceptor()."""
        hooks = HookSystem()

        def bash_blocker(_event, _data):
            return {"block": True, "reason": "bash blocked"}

        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            bash_blocker,
            name="bash_gate",
            matcher="run_bash",
        )

        result_bash = hooks.trigger_interceptor(
            HookEvent.TOOL_EXEC_STARTED, {"tool_name": "run_bash"}
        )
        assert result_bash.blocked is True

        result_safe = hooks.trigger_interceptor(
            HookEvent.TOOL_EXEC_STARTED, {"tool_name": "web_search"}
        )
        assert result_safe.blocked is False

    def test_matcher_on_trigger_with_result(self):
        """Matcher works with trigger_with_result()."""
        hooks = HookSystem()

        hooks.register(
            HookEvent.TOOL_EXEC_ENDED,
            lambda e, d: {"updated_result": {"enriched": True}},
            name="enrich_search",
            matcher="web_search",
        )

        results_match = hooks.trigger_with_result(
            HookEvent.TOOL_EXEC_ENDED, {"tool_name": "web_search", "result": {}}
        )
        assert len(results_match) == 1
        assert results_match[0].data["updated_result"] == {"enriched": True}

        results_no_match = hooks.trigger_with_result(
            HookEvent.TOOL_EXEC_ENDED, {"tool_name": "read_file", "result": {}}
        )
        assert len(results_no_match) == 0

    def test_matcher_on_tool_result_transform(self):
        """Matcher works on TOOL_RESULT_TRANSFORM event."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.TOOL_RESULT_TRANSFORM,
            lambda e, d: calls.append(d["tool_name"]),
            name="json_transform",
            matcher="export_json",
        )

        hooks.trigger(HookEvent.TOOL_RESULT_TRANSFORM, {"tool_name": "export_json"})
        hooks.trigger(HookEvent.TOOL_RESULT_TRANSFORM, {"tool_name": "other"})
        assert calls == ["export_json"]

    def test_matcher_on_tool_exec_failed(self):
        """Matcher works on TOOL_EXEC_FAILED event."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.TOOL_EXEC_FAILED,
            lambda e, d: calls.append(d["tool_name"]),
            name="bash_fail_watcher",
            matcher="run_bash",
        )

        hooks.trigger(HookEvent.TOOL_EXEC_FAILED, {"tool_name": "run_bash", "error": "timeout"})
        hooks.trigger(HookEvent.TOOL_EXEC_FAILED, {"tool_name": "web_search", "error": "404"})
        assert calls == ["run_bash"]

    def test_invalid_regex_fails_open(self):
        """Invalid regex matcher fails open (matches all)."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            lambda e, d: calls.append("fired"),
            name="bad_regex",
            matcher="[invalid",
        )

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "any_tool"})
        assert calls == ["fired"]

    def test_mixed_matcher_and_no_matcher(self):
        """Handlers with and without matchers coexist correctly."""
        hooks = HookSystem()
        calls: list[str] = []

        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            lambda e, d: calls.append("all"),
            name="global",
            priority=10,
        )
        hooks.register(
            HookEvent.TOOL_EXEC_STARTED,
            lambda e, d: calls.append("bash"),
            name="bash_only",
            priority=20,
            matcher="run_bash",
        )

        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "run_bash"})
        assert calls == ["all", "bash"]

        calls.clear()
        hooks.trigger(HookEvent.TOOL_EXEC_STARTED, {"tool_name": "web_search"})
        assert calls == ["all"]


class TestToolExecFailedEvent:
    """Tests for new TOOL_EXEC_FAILED event."""

    def test_tool_exec_failed_event_value(self):
        assert HookEvent.TOOL_EXEC_FAILED.value == "tool_exec_failed"

    def test_tool_exec_failed_fires_on_error(self):
        hooks = HookSystem()
        calls: list[dict] = []

        hooks.register(
            HookEvent.TOOL_EXEC_FAILED,
            lambda e, d: calls.append(d),
            name="fail_watcher",
        )

        hooks.trigger(
            HookEvent.TOOL_EXEC_FAILED,
            {
                "tool_name": "run_bash",
                "error": "command not found",
                "error_type": "execution_error",
                "recoverable": True,
            },
        )
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "run_bash"
        assert calls[0]["error_type"] == "execution_error"


class TestToolResultTransformEvent:
    """Tests for new TOOL_RESULT_TRANSFORM event."""

    def test_tool_result_transform_event_value(self):
        assert HookEvent.TOOL_RESULT_TRANSFORM.value == "tool_result_transform"

    def test_transform_returns_transformed_result(self):
        hooks = HookSystem()

        def transformer(_event, data):
            result = data.get("result", {})
            if isinstance(result, dict):
                return {"transformed_result": {**result, "transformed": True}}
            return None

        hooks.register(HookEvent.TOOL_RESULT_TRANSFORM, transformer, name="add_flag")

        results = hooks.trigger_with_result(
            HookEvent.TOOL_RESULT_TRANSFORM,
            {"tool_name": "fetch", "result": {"data": "raw"}, "has_error": False},
        )
        assert len(results) == 1
        assert results[0].data["transformed_result"]["transformed"] is True
        assert results[0].data["transformed_result"]["data"] == "raw"

    def test_transform_skips_on_none_return(self):
        hooks = HookSystem()
        hooks.register(
            HookEvent.TOOL_RESULT_TRANSFORM,
            lambda e, d: None,
            name="noop",
        )

        results = hooks.trigger_with_result(
            HookEvent.TOOL_RESULT_TRANSFORM,
            {"tool_name": "fetch", "result": {"data": "raw"}},
        )
        assert len(results) == 1
        assert results[0].data == {}


class TestNewAuditLoggers:
    """Verify new events have audit loggers registered."""

    def test_tool_failed_and_transform_audit_loggers(self):
        from unittest.mock import patch

        with (
            patch("core.wiring.bootstrap.RunLog"),
        ):
            from core.wiring.bootstrap import build_hooks

            hooks, _, _ = build_hooks(
                session_key="test",
                run_id="test-run",
                log_dir=None,
            )

        all_hooks = hooks.list_hooks()
        assert "tool_failed" in all_hooks.get("tool_exec_failed", [])
        assert "tool_transform" in all_hooks.get("tool_result_transform", [])
