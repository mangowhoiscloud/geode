from core.orchestration.bootstrap import BootstrapContext, BootstrapManager

from core.hooks import HookEvent, HookSystem


def test_bootstrap_context_defaults_to_generic_subject() -> None:
    ctx = BootstrapContext(node_name="router", subject_id="subject-1")

    assert ctx.node_name == "router"
    assert ctx.subject_id == "subject-1"
    assert ctx.prompt_overrides == {}
    assert ctx.extra_instructions == []
    assert ctx.parameters == {}
    assert ctx.skip is False


def test_prepare_node_triggers_hooks_with_subject_id() -> None:
    hooks = HookSystem()
    manager = BootstrapManager(hooks)
    captured: list[dict[str, object]] = []

    def handler(event: HookEvent, data: dict[str, object]) -> None:
        captured.append(data)
        ctx = data["bootstrap_context"]
        assert isinstance(ctx, BootstrapContext)
        ctx.extra_instructions.append("Prefer concise reasoning")
        ctx.parameters["temperature"] = 0.1

    hooks.register(HookEvent.NODE_BOOTSTRAP, handler)

    ctx = manager.prepare_node("analysis", "subject-1", {"dry_run": True})

    assert captured[0]["node"] == "analysis"
    assert captured[0]["subject_id"] == "subject-1"
    assert ctx.extra_instructions == ["Prefer concise reasoning"]
    assert ctx.parameters == {"temperature": 0.1}


def test_register_override_only_applies_to_matching_node() -> None:
    hooks = HookSystem()
    manager = BootstrapManager(hooks)

    manager.register_override(
        "analysis",
        lambda ctx: ctx.prompt_overrides.update({"system": "custom"}),
    )

    matched = manager.prepare_node("analysis", "subject-1", {})
    unmatched = manager.prepare_node("synthesis", "subject-1", {})

    assert matched.prompt_overrides == {"system": "custom"}
    assert unmatched.prompt_overrides == {}


def test_apply_context_merges_overrides_without_mutating_input() -> None:
    state = {"subject_id": "subject-1", "existing": True}
    ctx = BootstrapContext(
        node_name="analysis",
        subject_id="subject-1",
        prompt_overrides={"system": "custom"},
        extra_instructions=["Focus on evidence"],
        parameters={"max_items": 3},
    )

    merged = BootstrapManager.apply_context(state, ctx)

    assert merged == {
        "subject_id": "subject-1",
        "existing": True,
        "_prompt_overrides": {"system": "custom"},
        "_extra_instructions": ["Focus on evidence"],
        "_bootstrap_parameters": {"max_items": 3},
    }
    assert state == {"subject_id": "subject-1", "existing": True}
