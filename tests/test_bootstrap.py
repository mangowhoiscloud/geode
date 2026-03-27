"""Tests for Bootstrap Hook system (NODE_BOOTSTRAP event)."""

from __future__ import annotations

from typing import Any

from core.hooks import HookEvent, HookSystem
from core.orchestration.bootstrap import BootstrapContext, BootstrapManager


class TestBootstrapContext:
    def test_defaults(self) -> None:
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")
        assert ctx.node_name == "router"
        assert ctx.ip_name == "Berserk"
        assert ctx.prompt_overrides == {}
        assert ctx.extra_instructions == []
        assert ctx.parameters == {}
        assert ctx.skip is False

    def test_extra_instructions(self) -> None:
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")
        ctx.extra_instructions.append("Focus on RPG genre")
        ctx.extra_instructions.append("Prioritize franchise potential")
        assert len(ctx.extra_instructions) == 2
        assert "Focus on RPG genre" in ctx.extra_instructions

    def test_prompt_overrides(self) -> None:
        ctx = BootstrapContext(node_name="analyst", ip_name="Naruto")
        ctx.prompt_overrides["system"] = "You are an expert anime analyst."
        ctx.prompt_overrides["user"] = "Analyze {ip_name} for hidden value."
        assert ctx.prompt_overrides["system"] == "You are an expert anime analyst."
        assert len(ctx.prompt_overrides) == 2

    def test_parameter_overrides(self) -> None:
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")
        ctx.parameters["temperature"] = 0.3
        ctx.parameters["max_tokens"] = 2048
        assert ctx.parameters["temperature"] == 0.3
        assert ctx.parameters["max_tokens"] == 2048


class TestBootstrapManager:
    def test_prepare_node_fires_node_bootstrap(self) -> None:
        """NODE_BOOTSTRAP event fires when prepare_node is called."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)
        fired: list[HookEvent] = []

        def on_bootstrap(event: HookEvent, data: dict[str, Any]) -> None:
            fired.append(event)

        hooks.register(HookEvent.NODE_BOOTSTRAP, on_bootstrap)
        mgr.prepare_node("router", "Berserk", {"ip_name": "Berserk"})

        assert fired == [HookEvent.NODE_BOOTSTRAP]

    def test_node_bootstrap_fires_before_node_enter(self) -> None:
        """NODE_BOOTSTRAP fires BEFORE NODE_ENTER in the hook sequence."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)
        event_order: list[str] = []

        def on_bootstrap(event: HookEvent, data: dict[str, Any]) -> None:
            event_order.append("bootstrap")

        def on_enter(event: HookEvent, data: dict[str, Any]) -> None:
            event_order.append("enter")

        hooks.register(HookEvent.NODE_BOOTSTRAP, on_bootstrap)
        hooks.register(HookEvent.NODE_ENTER, on_enter)

        # Simulate the sequence: bootstrap fires first, then enter
        mgr.prepare_node("router", "Berserk", {})
        hooks.trigger(HookEvent.NODE_ENTER, {"node": "router"})

        assert event_order == ["bootstrap", "enter"]

    def test_bootstrap_data_contains_node_and_ip(self) -> None:
        """NODE_BOOTSTRAP data dict contains node_name and ip_name."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)
        captured_data: list[dict[str, Any]] = []

        def on_bootstrap(event: HookEvent, data: dict[str, Any]) -> None:
            captured_data.append(dict(data))

        hooks.register(HookEvent.NODE_BOOTSTRAP, on_bootstrap)
        mgr.prepare_node("scoring", "Ghost in the Shell", {"ip_name": "Ghost in the Shell"})

        assert len(captured_data) == 1
        assert captured_data[0]["node"] == "scoring"
        assert captured_data[0]["ip_name"] == "Ghost in the Shell"
        assert "bootstrap_context" in captured_data[0]

    def test_hook_modifies_extra_instructions(self) -> None:
        """Hooks can add extra_instructions via bootstrap_context."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)

        def add_instructions(event: HookEvent, data: dict[str, Any]) -> None:
            ctx = data["bootstrap_context"]
            ctx.extra_instructions.append("Focus on dark fantasy IPs")

        hooks.register(HookEvent.NODE_BOOTSTRAP, add_instructions)
        ctx = mgr.prepare_node("router", "Berserk", {})

        assert "Focus on dark fantasy IPs" in ctx.extra_instructions

    def test_hook_modifies_prompt_overrides(self) -> None:
        """Hooks can set prompt_overrides via bootstrap_context."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)

        def override_prompts(event: HookEvent, data: dict[str, Any]) -> None:
            ctx = data["bootstrap_context"]
            ctx.prompt_overrides["system"] = "Custom system prompt for RPG"

        hooks.register(HookEvent.NODE_BOOTSTRAP, override_prompts)
        ctx = mgr.prepare_node("analyst", "Berserk", {})

        assert ctx.prompt_overrides["system"] == "Custom system prompt for RPG"

    def test_hook_modifies_parameters(self) -> None:
        """Hooks can set parameter overrides via bootstrap_context."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)

        def set_params(event: HookEvent, data: dict[str, Any]) -> None:
            ctx = data["bootstrap_context"]
            ctx.parameters["temperature"] = 0.1
            ctx.parameters["max_tokens"] = 4096

        hooks.register(HookEvent.NODE_BOOTSTRAP, set_params)
        ctx = mgr.prepare_node("router", "Berserk", {})

        assert ctx.parameters["temperature"] == 0.1
        assert ctx.parameters["max_tokens"] == 4096

    def test_skip_true_prevents_execution(self) -> None:
        """When skip=True is set, node execution should be skipped."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)

        def skip_node(event: HookEvent, data: dict[str, Any]) -> None:
            ctx = data["bootstrap_context"]
            ctx.skip = True

        hooks.register(HookEvent.NODE_BOOTSTRAP, skip_node)
        ctx = mgr.prepare_node("router", "Berserk", {})

        assert ctx.skip is True

    def test_register_override_convenience(self) -> None:
        """register_override convenience method registers a node-specific hook."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)

        def router_override(ctx: BootstrapContext) -> None:
            ctx.extra_instructions.append("Router-specific instruction")

        mgr.register_override("router", router_override)

        # Fires for router
        ctx_router = mgr.prepare_node("router", "Berserk", {})
        assert "Router-specific instruction" in ctx_router.extra_instructions

        # Does NOT fire for analyst (different node)
        ctx_analyst = mgr.prepare_node("analyst", "Berserk", {})
        assert ctx_analyst.extra_instructions == []

    def test_register_override_with_name(self) -> None:
        """register_override accepts a custom name parameter."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)

        mgr.register_override(
            "router",
            lambda ctx: ctx.extra_instructions.append("test"),
            name="my_router_override",
        )

        all_hooks = hooks.list_hooks(HookEvent.NODE_BOOTSTRAP)
        assert "my_router_override" in all_hooks["node_bootstrap"]

    def test_multiple_bootstrap_hooks_fire_in_priority_order(self) -> None:
        """Multiple NODE_BOOTSTRAP hooks fire in priority order (lower = first)."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)
        order: list[str] = []

        def high_priority(event: HookEvent, data: dict[str, Any]) -> None:
            order.append("first")
            data["bootstrap_context"].extra_instructions.append("high-pri")

        def low_priority(event: HookEvent, data: dict[str, Any]) -> None:
            order.append("second")
            data["bootstrap_context"].extra_instructions.append("low-pri")

        hooks.register(HookEvent.NODE_BOOTSTRAP, low_priority, name="low", priority=200)
        hooks.register(HookEvent.NODE_BOOTSTRAP, high_priority, name="high", priority=10)

        ctx = mgr.prepare_node("router", "Berserk", {})

        assert order == ["first", "second"]
        assert ctx.extra_instructions == ["high-pri", "low-pri"]

    def test_manager_without_hooks_passthrough(self) -> None:
        """BootstrapManager with no registered hooks returns default context."""
        hooks = HookSystem()
        mgr = BootstrapManager(hooks)

        ctx = mgr.prepare_node("router", "Berserk", {"ip_name": "Berserk"})

        assert ctx.node_name == "router"
        assert ctx.ip_name == "Berserk"
        assert ctx.skip is False
        assert ctx.prompt_overrides == {}
        assert ctx.extra_instructions == []
        assert ctx.parameters == {}


class TestApplyContext:
    def test_apply_empty_context(self) -> None:
        """Empty context returns state without bootstrap keys."""
        state: dict[str, Any] = {"ip_name": "Berserk", "dry_run": True}
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")

        result = BootstrapManager.apply_context(state, ctx)

        assert result["ip_name"] == "Berserk"
        assert result["dry_run"] is True
        assert "_prompt_overrides" not in result
        assert "_extra_instructions" not in result
        assert "_bootstrap_parameters" not in result

    def test_apply_prompt_overrides(self) -> None:
        """apply_context merges prompt_overrides into state."""
        state: dict[str, Any] = {"ip_name": "Berserk"}
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")
        ctx.prompt_overrides["system"] = "Custom prompt"

        result = BootstrapManager.apply_context(state, ctx)

        assert result["_prompt_overrides"] == {"system": "Custom prompt"}

    def test_apply_extra_instructions(self) -> None:
        """apply_context merges extra_instructions into state."""
        state: dict[str, Any] = {"ip_name": "Naruto"}
        ctx = BootstrapContext(node_name="analyst", ip_name="Naruto")
        ctx.extra_instructions.append("Focus on shonen genre")
        ctx.extra_instructions.append("Consider franchise longevity")

        result = BootstrapManager.apply_context(state, ctx)

        assert result["_extra_instructions"] == [
            "Focus on shonen genre",
            "Consider franchise longevity",
        ]

    def test_apply_parameters(self) -> None:
        """apply_context merges parameters into state."""
        state: dict[str, Any] = {"ip_name": "Berserk"}
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")
        ctx.parameters["temperature"] = 0.2

        result = BootstrapManager.apply_context(state, ctx)

        assert result["_bootstrap_parameters"] == {"temperature": 0.2}

    def test_apply_does_not_mutate_original_state(self) -> None:
        """apply_context returns a new dict, does not mutate original."""
        state: dict[str, Any] = {"ip_name": "Berserk"}
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")
        ctx.prompt_overrides["system"] = "Custom"

        result = BootstrapManager.apply_context(state, ctx)

        assert "_prompt_overrides" in result
        assert "_prompt_overrides" not in state

    def test_apply_all_overrides_together(self) -> None:
        """apply_context merges all override types simultaneously."""
        state: dict[str, Any] = {"ip_name": "Berserk", "dry_run": True}
        ctx = BootstrapContext(node_name="router", ip_name="Berserk")
        ctx.prompt_overrides["system"] = "Custom system"
        ctx.extra_instructions.append("Extra 1")
        ctx.parameters["temperature"] = 0.5

        result = BootstrapManager.apply_context(state, ctx)

        assert result["_prompt_overrides"] == {"system": "Custom system"}
        assert result["_extra_instructions"] == ["Extra 1"]
        assert result["_bootstrap_parameters"] == {"temperature": 0.5}
        assert result["ip_name"] == "Berserk"
        assert result["dry_run"] is True


class TestHookEventCount:
    def test_events_exist(self) -> None:
        """HookEvent has 45 events (+TURN_COMPLETE +SESSION_START/END +CONTEXT_OVERFLOW_ACTION +LLM_CALL_START/END)."""
        assert len(HookEvent) == 46

    def test_node_bootstrap_event_value(self) -> None:
        assert HookEvent.NODE_BOOTSTRAP.value == "node_bootstrap"


class TestMakeHookedNodeWithBootstrap:
    """Integration tests: _make_hooked_node with BootstrapManager."""

    def test_skip_returns_empty_dict(self) -> None:
        """When bootstrap sets skip=True, node returns {} without executing."""
        from core.graph import _make_hooked_node

        hooks = HookSystem()
        mgr = BootstrapManager(hooks)
        executed = []

        def skip_all(event: HookEvent, data: dict[str, Any]) -> None:
            data["bootstrap_context"].skip = True

        hooks.register(HookEvent.NODE_BOOTSTRAP, skip_all)

        def fake_node(state: dict[str, Any]) -> dict[str, Any]:
            executed.append(True)
            return {"result": "should not appear"}

        wrapped = _make_hooked_node(fake_node, "router", hooks, mgr)  # type: ignore[arg-type]
        result = wrapped({"ip_name": "Berserk"})  # type: ignore[arg-type]

        assert result == {}
        assert executed == []  # Node was NOT executed

    def test_bootstrap_context_applied_to_state(self) -> None:
        """BootstrapManager applies context before node execution."""
        from core.graph import _make_hooked_node

        hooks = HookSystem()
        mgr = BootstrapManager(hooks)
        captured_states: list[dict[str, Any]] = []

        def add_instruction(event: HookEvent, data: dict[str, Any]) -> None:
            data["bootstrap_context"].extra_instructions.append("RPG focus")

        hooks.register(HookEvent.NODE_BOOTSTRAP, add_instruction)

        def fake_node(state: dict[str, Any]) -> dict[str, Any]:
            captured_states.append(dict(state))
            return {"done": True}

        wrapped = _make_hooked_node(fake_node, "router", hooks, mgr)  # type: ignore[arg-type]
        wrapped({"ip_name": "Berserk"})  # type: ignore[arg-type]

        assert len(captured_states) == 1
        assert captured_states[0]["_extra_instructions"] == ["RPG focus"]

    def test_no_bootstrap_mgr_preserves_original_behavior(self) -> None:
        """Without bootstrap_mgr, behavior is identical to before."""
        from core.graph import _make_hooked_node

        hooks = HookSystem()
        events_fired: list[HookEvent] = []

        def track_events(event: HookEvent, data: dict[str, Any]) -> None:
            events_fired.append(event)

        hooks.register(HookEvent.NODE_ENTER, track_events)
        hooks.register(HookEvent.NODE_EXIT, track_events)

        def fake_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"value": 42}

        # No bootstrap_mgr (default None)
        wrapped = _make_hooked_node(fake_node, "router", hooks)  # type: ignore[arg-type]
        result = wrapped({"ip_name": "Berserk"})  # type: ignore[arg-type]

        assert result == {"value": 42}
        assert HookEvent.NODE_ENTER in events_fired
        assert HookEvent.NODE_EXIT in events_fired
        # NODE_BOOTSTRAP should NOT fire
        assert HookEvent.NODE_BOOTSTRAP not in events_fired

    def test_bootstrap_fires_before_enter_in_hooked_node(self) -> None:
        """In _make_hooked_node, NODE_BOOTSTRAP fires before NODE_ENTER."""
        from core.graph import _make_hooked_node

        hooks = HookSystem()
        mgr = BootstrapManager(hooks)
        event_order: list[str] = []

        def on_bootstrap(event: HookEvent, data: dict[str, Any]) -> None:
            event_order.append("bootstrap")

        def on_enter(event: HookEvent, data: dict[str, Any]) -> None:
            event_order.append("enter")

        def on_exit(event: HookEvent, data: dict[str, Any]) -> None:
            event_order.append("exit")

        hooks.register(HookEvent.NODE_BOOTSTRAP, on_bootstrap)
        hooks.register(HookEvent.NODE_ENTER, on_enter)
        hooks.register(HookEvent.NODE_EXIT, on_exit)

        def fake_node(state: dict[str, Any]) -> dict[str, Any]:
            return {"done": True}

        wrapped = _make_hooked_node(fake_node, "router", hooks, mgr)  # type: ignore[arg-type]
        wrapped({"ip_name": "Berserk"})  # type: ignore[arg-type]

        assert event_order == ["bootstrap", "enter", "exit"]
