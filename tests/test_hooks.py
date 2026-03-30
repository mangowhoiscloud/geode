"""Tests for L4 HookSystem."""

from core.hooks import HookEvent, HookResult, HookSystem


class TestHookEvent:
    def test_all_events_exist(self):
        assert len(HookEvent) == 41

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
