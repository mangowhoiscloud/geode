"""Tests for HookSystem integration with graph.py."""

from __future__ import annotations

from geode.graph import _make_hooked_node, build_graph
from geode.orchestration.hooks import HookEvent, HookSystem
from geode.state import GeodeState


class TestMakeHookedNode:
    def test_triggers_enter_and_exit(self):
        triggered_events = []

        def recorder(event, data):
            triggered_events.append(event)

        hooks = HookSystem()
        hooks.register(HookEvent.NODE_ENTER, recorder)
        hooks.register(HookEvent.NODE_EXIT, recorder)

        def dummy_node(state: GeodeState) -> dict:
            return {"pipeline_mode": "test"}

        hooked = _make_hooked_node(dummy_node, "test_node", hooks)
        result = hooked({"ip_name": "test"})

        assert result == {"pipeline_mode": "test"}
        assert HookEvent.NODE_ENTER in triggered_events
        assert HookEvent.NODE_EXIT in triggered_events

    def test_triggers_error_on_exception(self):
        triggered_events = []

        def recorder(event, data):
            triggered_events.append(event)

        hooks = HookSystem()
        hooks.register(HookEvent.NODE_ERROR, recorder)
        hooks.register(HookEvent.PIPELINE_ERROR, recorder)

        def failing_node(state: GeodeState) -> dict:
            raise ValueError("boom")

        import contextlib

        hooked = _make_hooked_node(failing_node, "bad_node", hooks)
        with contextlib.suppress(ValueError):
            hooked({"ip_name": "test"})

        assert HookEvent.NODE_ERROR in triggered_events
        assert HookEvent.PIPELINE_ERROR in triggered_events

    def test_router_triggers_pipeline_start(self):
        triggered_events = []

        def recorder(event, data):
            triggered_events.append(event)

        hooks = HookSystem()
        hooks.register(HookEvent.PIPELINE_START, recorder)

        def router_fn(state: GeodeState) -> dict:
            return {"pipeline_mode": "full_pipeline"}

        hooked = _make_hooked_node(router_fn, "router", hooks)
        hooked({"ip_name": "test"})

        assert HookEvent.PIPELINE_START in triggered_events

    def test_synthesizer_triggers_pipeline_end(self):
        triggered_events = []

        def recorder(event, data):
            triggered_events.append(event)

        hooks = HookSystem()
        hooks.register(HookEvent.PIPELINE_END, recorder)

        def synth_fn(state: GeodeState) -> dict:
            return {"synthesis": {}}

        hooked = _make_hooked_node(synth_fn, "synthesizer", hooks)
        hooked({"ip_name": "test"})

        assert HookEvent.PIPELINE_END in triggered_events

    def test_hook_data_contains_duration(self):
        captured_data = {}

        def recorder(event, data):
            if event == HookEvent.NODE_EXIT:
                captured_data.update(data)

        hooks = HookSystem()
        hooks.register(HookEvent.NODE_EXIT, recorder)

        def slow_node(state: GeodeState) -> dict:
            return {"result": "done"}

        hooked = _make_hooked_node(slow_node, "test", hooks)
        hooked({"ip_name": "Berserk"})

        assert "duration_ms" in captured_data
        assert captured_data["duration_ms"] >= 0
        assert captured_data["node"] == "test"
        assert captured_data["ip_name"] == "Berserk"

    def test_scoring_triggers_completion_event(self):
        triggered_events = []

        def recorder(event, data):
            triggered_events.append(event)

        hooks = HookSystem()
        hooks.register(HookEvent.SCORING_COMPLETE, recorder)

        def scoring_fn(state: GeodeState) -> dict:
            return {"final_score": 82.0}

        hooked = _make_hooked_node(scoring_fn, "scoring", hooks)
        hooked({"ip_name": "test"})

        assert HookEvent.SCORING_COMPLETE in triggered_events


class TestBuildGraphWithHooks:
    def test_build_graph_without_hooks(self):
        graph = build_graph()
        assert graph is not None

    def test_build_graph_with_hooks(self):
        hooks = HookSystem()
        graph = build_graph(hooks=hooks)
        assert graph is not None

    def test_compile_graph_with_hooks(self):
        from geode.graph import compile_graph

        hooks = HookSystem()
        compiled = compile_graph(hooks=hooks)
        assert compiled is not None
