"""Immutable tool-plan compilation contracts."""

from __future__ import annotations

import copy
import dataclasses
from collections.abc import Mapping
from typing import Any, cast

import pytest
from core.tools.plan import (
    BoundToolPlan,
    CapabilityRequirement,
    ExecutionBinding,
    SafetyPolicy,
    ToolDecision,
    ToolSpec,
    bind_tool_plan,
    compile_tool_plan,
)


def _spec(name: str = "search", *, description: str = "Search") -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
            "required": ["tags"],
        },
    )


def _binding(
    name: str = "search", *, origin: str = "handlers.search", route: str = "handler"
) -> ExecutionBinding:
    return ExecutionBinding(name=name, origin=origin, route=route)


def test_records_reject_missing_identity_before_compilation() -> None:
    with pytest.raises(ValueError, match="tool name cannot be empty"):
        ToolSpec(name="", description="Search", input_schema={})
    with pytest.raises(ValueError, match="binding origin cannot be empty"):
        ExecutionBinding(name="search", origin="")
    with pytest.raises(TypeError, match="input_schema must be a JSON object"):
        ToolSpec(name="search", description="Search", input_schema=cast(Any, []))


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_tool_spec_rejects_non_json_numbers(value: float) -> None:
    with pytest.raises(TypeError, match="numbers must be finite"):
        ToolSpec(name="search", description="Search", input_schema={"default": value})


def test_tool_spec_schema_is_recursively_immutable_and_adapter_compatible() -> None:
    source = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string"}}},
        "required": ["tags"],
    }
    spec = ToolSpec(name="search", description="Search", input_schema=source)
    source["properties"]["tags"]["type"] = "string"

    assert isinstance(spec.input_schema, Mapping)
    assert spec.input_schema["properties"]["tags"]["type"] == "array"
    with pytest.raises(TypeError):
        spec.input_schema["properties"]["tags"]["type"] = "string"
    with pytest.raises(AttributeError):
        spec.input_schema["required"].append("query")
    with pytest.raises(AttributeError):
        cast(Any, spec.input_schema)._values = {}
    with pytest.raises(AttributeError):
        del cast(Any, spec.input_schema)._values
    with pytest.raises(AttributeError):
        spec.__dict__["input_schema"] = {}
    assert copy.deepcopy(spec).input_schema is spec.input_schema
    assert dataclasses.asdict(spec)["input_schema"] == spec.input_schema


def test_compile_rejects_duplicate_names_with_both_origins() -> None:
    with pytest.raises(
        ValueError,
        match=r"duplicate tool spec 'search': definitions\[0\] vs extension\.json",
    ):
        compile_tool_plan(
            ((_spec(), "definitions[0]"), (_spec(), "extension.json")),
            (_binding(),),
        )

    with pytest.raises(
        ValueError,
        match=r"duplicate execution binding 'search': handlers\.search vs extension\.search",
    ):
        compile_tool_plan(
            ((_spec(), "definitions[0]"),),
            (_binding(), _binding(origin="extension.search")),
        )


def test_execution_binding_records_handler_or_named_route_identity() -> None:
    special = ExecutionBinding(
        name="search",
        origin="ToolExecutor.special",
        route="special",
    )

    assert special.route == "special"
    with pytest.raises(ValueError, match="invalid route"):
        ExecutionBinding(name="search", origin="handlers.search", route="")
    with pytest.raises(ValueError, match="invalid route"):
        ExecutionBinding(name="search", origin="handlers.search", route="unknown")


@pytest.mark.parametrize(
    ("specs", "bindings", "message"),
    [
        (((_spec(), "definitions[0]"),), (), "missing execution bindings: search"),
        ((), (_binding(),), "missing tool specs: search"),
    ],
)
def test_compile_requires_exact_schema_execution_parity(
    specs: tuple[tuple[ToolSpec, str], ...],
    bindings: tuple[ExecutionBinding, ...],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        compile_tool_plan(specs, bindings)


def test_compiler_is_content_addressed_and_generation_aware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    binding = _binding()
    plan = compile_tool_plan(((spec, "definitions[0]"),), (binding,))

    monkeypatch.setenv("GEODE_FAKE_SECRET", "must-not-affect-plan")
    same = compile_tool_plan(((spec, "definitions[0]"),), (binding,), previous=plan)
    changed = compile_tool_plan(
        ((_spec(description="Changed"), "definitions[0]"),),
        (_binding(),),
        previous=plan,
    )

    assert same is plan
    assert plan.generation == 1
    assert changed.generation == 2
    assert changed.content_hash != plan.content_hash
    assert plan.schema_map["search"].description == "Search"
    assert set(changed.schema_map) == set(changed.execution_map) == {"search"}


def test_compiler_preserves_provider_visible_definition_order() -> None:
    plan = compile_tool_plan(
        ((_spec("zeta"), "definitions[0]"), (_spec("alpha"), "definitions[1]")),
        (_binding("alpha"), _binding("zeta")),
    )
    reordered = compile_tool_plan(
        ((_spec("alpha"), "definitions[1]"), (_spec("zeta"), "definitions[0]")),
        (_binding("zeta"), _binding("alpha")),
        previous=plan,
    )

    assert list(plan.schema_map) == list(plan.execution_map) == ["zeta", "alpha"]
    assert list(reordered.schema_map) == ["alpha", "zeta"]
    assert reordered.content_hash != plan.content_hash
    assert reordered.generation == plan.generation + 1


def test_deferred_membership_is_hash_bound_and_ordered() -> None:
    specs = ((_spec("zeta"), "definitions[0]"), (_spec("alpha"), "definitions[1]"))
    bindings = (_binding("alpha"), _binding("zeta"))
    eager = compile_tool_plan(specs, bindings)
    deferred = compile_tool_plan(
        specs,
        bindings,
        deferred_tools=frozenset({"zeta"}),
        previous=eager,
    )

    assert eager.eager_tool_names == ("zeta", "alpha")
    assert eager.deferred_tool_names == ()
    assert deferred.eager_tool_names == ("alpha",)
    assert deferred.deferred_tool_names == ("zeta",)
    assert deferred.generation == eager.generation + 1
    assert deferred.content_hash != eager.content_hash
    assert eager.registrations[0].deferred is False
    assert deferred.registrations[0].deferred is True

    with pytest.raises(ValueError, match="deferred metadata references unknown tools: missing"):
        compile_tool_plan(specs, bindings, deferred_tools=frozenset({"missing"}))


def test_bound_plan_validates_routes_and_filters_without_mutating_parent() -> None:
    plan = compile_tool_plan(
        ((_spec("ordinary"), "definitions[0]"), (_spec("special"), "definitions[1]")),
        (_binding("ordinary"), _binding("special", route="special")),
        deferred_tools=frozenset({"ordinary"}),
    )

    def handler(**_kwargs: Any) -> dict[str, bool]:
        return {"ok": True}

    bound = bind_tool_plan(plan, {"ordinary": handler})

    assert isinstance(bound, BoundToolPlan)
    assert bound.tool_names == ("ordinary", "special")
    assert tuple(spec.name for spec in bound.ordered_specs) == bound.tool_names
    assert bound.handlers["ordinary"] is handler
    assert bound.eager_tool_names == ("special",)
    assert bound.deferred_tool_names == ("ordinary",)
    assert bound.filtered() is bound

    narrowed = bound.filtered(denied_tool_names=frozenset({"ordinary"}))
    assert narrowed is not bound
    assert narrowed.plan is plan
    assert narrowed.tool_names == ("special",)
    assert narrowed.handlers == {}
    assert narrowed.eager_tool_names == ("special",)
    assert narrowed.deferred_tool_names == ()
    assert narrowed.content_hash != bound.content_hash
    assert narrowed.generation == bound.generation + 1
    assert bound.tool_names == ("ordinary", "special")
    assert tuple(bound.handlers) == ("ordinary",)
    with pytest.raises(TypeError):
        bound.handlers["other"] = handler


def test_bound_plan_projects_order_and_description_as_new_identity() -> None:
    plan = compile_tool_plan(
        ((_spec("alpha"), "definitions[0]"), (_spec("beta"), "definitions[1]")),
        (_binding("alpha"), _binding("beta")),
        deferred_tools=frozenset({"beta"}),
    )

    def alpha() -> str:
        return "alpha"

    def beta() -> str:
        return "beta"

    bound = bind_tool_plan(plan, {"alpha": alpha, "beta": beta})

    projected = bound.projected((_spec("beta", description="Policy override"), _spec("alpha")))

    assert projected is not bound
    assert projected.tool_names == ("beta", "alpha")
    assert projected.ordered_specs[0].description == "Policy override"
    assert tuple(projected.handlers) == ("beta", "alpha")
    assert projected.handlers["alpha"] is alpha
    assert projected.handlers["beta"] is beta
    assert projected.deferred_tool_names == ("beta",)
    assert projected.content_hash != bound.content_hash
    assert projected.generation == bound.generation + 1
    assert bound.tool_names == ("alpha", "beta")
    assert bound.ordered_specs[1].description == "Search"
    assert bound.projected(bound.ordered_specs) is bound

    with pytest.raises(ValueError, match="duplicate tool names"):
        bound.projected((_spec("alpha"), _spec("alpha")))
    with pytest.raises(ValueError, match="unknown tools: missing"):
        bound.projected((_spec("missing"),))


@pytest.mark.parametrize(
    ("handlers", "message"),
    [
        ({}, "missing ordinary handlers: search"),
        ({"search": None}, "tool handlers must be callable: search"),
        (
            {"search": lambda: None, "extra": lambda: None},
            "unexpected ordinary handlers: extra",
        ),
    ],
)
def test_bound_plan_rejects_missing_noncallable_and_extra_handlers(
    handlers: dict[str, Any],
    message: str,
) -> None:
    plan = compile_tool_plan(((_spec(), "definitions[0]"),), (_binding(),))

    with pytest.raises((TypeError, ValueError), match=message):
        bind_tool_plan(plan, handlers)


def test_compiler_distinguishes_capability_unavailable_from_policy_denied() -> None:
    unavailable = compile_tool_plan(
        ((_spec(), "definitions[0]"),),
        (_binding(),),
        capabilities={"search": CapabilityRequirement(available=False)},
    )
    denied = compile_tool_plan(
        ((_spec(), "definitions[0]"),),
        (_binding(),),
        safety={"search": SafetyPolicy(denied=True)},
    )

    assert unavailable.outcomes["search"] is ToolDecision.UNAVAILABLE_CAPABILITY
    assert denied.outcomes["search"] is ToolDecision.DENIED_POLICY
    assert unavailable.schema_map == unavailable.execution_map == {}
    assert denied.schema_map == denied.execution_map == {}


def test_plan_mappings_and_registration_metadata_are_immutable() -> None:
    plan = compile_tool_plan(
        ((_spec(), "definitions[0]"),),
        (_binding(),),
        safety={"search": SafetyPolicy(effect="external", data_class="personal")},
        capabilities={
            "search": CapabilityRequirement(
                providers=("openai",), services=("search",), auth=("oauth",)
            )
        },
    )

    assert isinstance(plan.schema_map, Mapping)
    with pytest.raises(TypeError):
        plan.schema_map["other"] = _spec("other")
    registration = plan.registrations[0]
    assert registration.safety.effect == "external"
    assert registration.safety.data_class == "personal"
    assert registration.capability.providers == ("openai",)


def test_capability_requirements_have_canonical_set_identity() -> None:
    first = CapabilityRequirement(
        providers=("openai", "anthropic", "openai"),
        services=("search", "files"),
        auth=("oauth", "oauth"),
    )
    second = CapabilityRequirement(
        providers=("anthropic", "openai"),
        services=("files", "search"),
        auth=("oauth",),
    )

    assert first == second
    generated = CapabilityRequirement(providers=(item for item in ("openai", "openai")))
    assert generated.providers == ("openai",)
    with pytest.raises(TypeError, match="iterable of strings"):
        CapabilityRequirement(providers=cast(Any, "openai"))


def test_direct_tool_plan_construction_copies_mutable_containers() -> None:
    original = compile_tool_plan(
        ((_spec(), "definitions[0]"),),
        (_binding(),),
    )
    registrations = list(original.registrations)
    schemas = dict(original.schema_map)
    executions = dict(original.execution_map)
    outcomes = dict(original.outcomes)
    copied = type(original)(
        1,
        original.content_hash,
        cast(Any, registrations),
        schemas,
        executions,
        outcomes,
    )

    registrations.clear()
    schemas.clear()
    executions.clear()
    outcomes.clear()
    assert len(copied.registrations) == len(copied.schema_map) == len(copied.execution_map) == 1
    assert len(copied.outcomes) == 1


def test_direct_tool_plan_construction_rejects_projection_reordering() -> None:
    original = compile_tool_plan(
        ((_spec("zeta"), "definitions[0]"), (_spec("alpha"), "definitions[1]")),
        (_binding("zeta"), _binding("alpha")),
    )

    with pytest.raises(ValueError, match="maps must match enabled registrations"):
        type(original)(
            original.generation,
            original.content_hash,
            original.registrations,
            dict(reversed(original.schema_map.items())),
            dict(reversed(original.execution_map.items())),
            original.outcomes,
        )
