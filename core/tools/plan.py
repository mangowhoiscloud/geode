"""Immutable tool metadata and content-addressed plan compilation."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Iterator, Mapping, Set
from dataclasses import dataclass, field, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class _ImmutableMapping(Mapping[str, Any]):
    """Read-only JSON object without a mutable builtin base."""

    __slots__ = ("_values",)
    _values: Mapping[str, Any]

    def __init__(self, values: Mapping[str, Any]) -> None:
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    def __setattr__(self, _name: str, _value: Any) -> None:
        raise AttributeError("tool schemas are immutable")

    def __delattr__(self, _name: str) -> None:
        raise AttributeError("tool schemas are immutable")

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __copy__(self) -> _ImmutableMapping:
        return self

    def __deepcopy__(self, _memo: dict[int, Any]) -> _ImmutableMapping:
        return self


def _freeze_json(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        raise TypeError("tool schema numbers must be finite")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("tool schema object keys must be strings")
        return _ImmutableMapping({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise TypeError(f"tool schema values must be JSON-compatible, got {type(value).__name__}")


def thaw_tool_schema(value: Any) -> Any:
    """Return plain JSON containers for provider SDK boundaries."""
    if isinstance(value, Mapping):
        return {key: thaw_tool_schema(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw_tool_schema(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Provider-neutral model-facing tool descriptor."""

    name: str
    description: str
    input_schema: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("tool name cannot be empty")
        frozen = _freeze_json(self.input_schema)
        if not isinstance(frozen, Mapping):
            raise TypeError("tool input_schema must be a JSON object")
        object.__setattr__(self, "input_schema", frozen)

    def __deepcopy__(self, _memo: dict[int, Any]) -> ToolSpec:
        return self


@dataclass(frozen=True, slots=True)
class ExecutionBinding:
    """Stable identity for one handler or named executor route."""

    name: str
    origin: str
    route: str = "handler"

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("execution binding name cannot be empty")
        if not self.origin.strip():
            raise ValueError("binding origin cannot be empty")
        if self.route not in {"handler", "special"}:
            raise ValueError(f"execution binding {self.name!r} has invalid route {self.route!r}")


@dataclass(frozen=True, slots=True)
class SafetyPolicy:
    """Minimum effect, data, consent, and runtime safety constraints."""

    effect: str = "read"
    data_class: str = "public"
    consent_required: bool = False
    allow_headless: bool = True
    allow_subagents: bool = True
    denied: bool = False

    def __post_init__(self) -> None:
        if not self.effect.strip() or not self.data_class.strip():
            raise ValueError("safety effect and data class cannot be empty")


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    """Provider, service, and authorization requirements for one tool."""

    providers: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    auth: tuple[str, ...] = ()
    available: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "providers", _canonical_requirement(self.providers))
        object.__setattr__(self, "services", _canonical_requirement(self.services))
        object.__setattr__(self, "auth", _canonical_requirement(self.auth))


def _canonical_requirement(values: Iterable[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("capability requirements must be an iterable of strings")
    captured = tuple(values)
    if any(not isinstance(item, str) or not item.strip() for item in captured):
        raise ValueError("capability requirement values cannot be empty")
    return tuple(sorted(set(captured)))


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """Joined tool metadata used to derive every plan projection."""

    spec: ToolSpec
    execution: ExecutionBinding
    safety: SafetyPolicy
    capability: CapabilityRequirement
    deferred: bool = False

    def __post_init__(self) -> None:
        if self.spec.name != self.execution.name:
            raise ValueError(
                f"tool registration name mismatch: {self.spec.name!r} vs {self.execution.name!r}"
            )


class ToolDecision(StrEnum):
    ENABLED = "enabled"
    UNAVAILABLE_CAPABILITY = "unavailable_capability"
    DENIED_POLICY = "denied_policy"


@dataclass(frozen=True, slots=True)
class ToolPlan:
    """One immutable, generation-aware tool catalog snapshot."""

    generation: int
    content_hash: str
    registrations: tuple[ToolRegistration, ...]
    schema_map: Mapping[str, ToolSpec]
    execution_map: Mapping[str, ExecutionBinding]
    outcomes: Mapping[str, ToolDecision]

    def __post_init__(self) -> None:
        registrations = tuple(self.registrations)
        schemas = dict(self.schema_map)
        executions = dict(self.execution_map)
        outcomes = dict(self.outcomes)
        by_name = {item.spec.name: item for item in registrations}
        if self.generation < 1:
            raise ValueError("tool plan generation must be positive")
        if len(by_name) != len(registrations):
            raise ValueError("tool plan contains duplicate registrations")
        if set(outcomes) != set(by_name):
            raise ValueError("tool plan outcomes must cover every registration")
        if any(outcomes[name] is not _decision(item) for name, item in by_name.items()):
            raise ValueError("tool plan outcomes do not match registration metadata")
        enabled = tuple(name for name in by_name if outcomes[name] is ToolDecision.ENABLED)
        if tuple(schemas) != enabled or tuple(executions) != enabled:
            raise ValueError("tool plan schema/execution maps must match enabled registrations")
        if any(
            schemas[name] != by_name[name].spec or executions[name] != by_name[name].execution
            for name in enabled
        ):
            raise ValueError("tool plan projection does not match its registrations")
        if self.content_hash != _content_hash(registrations):
            raise ValueError("tool plan content hash does not match its registrations")
        object.__setattr__(self, "registrations", registrations)
        object.__setattr__(self, "schema_map", MappingProxyType(schemas))
        object.__setattr__(self, "execution_map", MappingProxyType(executions))
        object.__setattr__(self, "outcomes", MappingProxyType(outcomes))

    @property
    def eager_tool_names(self) -> tuple[str, ...]:
        """Enabled tools loaded eagerly, in provider-visible order."""
        return tuple(
            item.spec.name
            for item in self.registrations
            if item.spec.name in self.schema_map and not item.deferred
        )

    @property
    def deferred_tool_names(self) -> tuple[str, ...]:
        """Enabled tools eligible for provider-side deferred loading."""
        return tuple(
            item.spec.name
            for item in self.registrations
            if item.spec.name in self.schema_map and item.deferred
        )


@dataclass(frozen=True, slots=True)
class BoundToolPlan:
    """One plan bound to its exact ordinary execution handlers."""

    plan: ToolPlan
    handlers: Mapping[str, Any]
    tool_names: tuple[str, ...]
    _generation: int | None = None
    _content_hash: str = ""
    _base: BoundToolPlan | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        names = tuple(self.tool_names)
        if len(set(names)) != len(names):
            raise ValueError("bound tool plan contains duplicate tool names")
        unknown = set(names) - self.plan.schema_map.keys()
        if unknown:
            names_list = ", ".join(sorted(unknown))
            raise ValueError(f"bound tool plan references unknown tools: {names_list}")
        expected_order = tuple(name for name in self.plan.schema_map if name in set(names))
        if names != expected_order:
            raise ValueError("bound tool names must preserve plan order")

        handlers = dict(self.handlers)
        ordinary = {name for name in names if self.plan.execution_map[name].route == "handler"}
        if missing := sorted(ordinary - handlers.keys()):
            raise ValueError(f"missing ordinary handlers: {', '.join(missing)}")
        if extra := sorted(handlers.keys() - ordinary):
            raise ValueError(f"unexpected ordinary handlers: {', '.join(extra)}")
        if invalid := sorted(name for name, handler in handlers.items() if not callable(handler)):
            raise TypeError(f"tool handlers must be callable: {', '.join(invalid)}")

        generation = self.plan.generation if self._generation is None else self._generation
        if generation < 1:
            raise ValueError("bound tool plan generation must be positive")
        content_hash = _bound_content_hash(self.plan.content_hash, names)
        if self._content_hash and self._content_hash != content_hash:
            raise ValueError("bound tool plan content hash does not match its projection")

        object.__setattr__(self, "handlers", MappingProxyType(handlers))
        object.__setattr__(self, "tool_names", names)
        object.__setattr__(self, "_generation", generation)
        object.__setattr__(self, "_content_hash", content_hash)

    @property
    def generation(self) -> int:
        assert self._generation is not None
        return self._generation

    @property
    def content_hash(self) -> str:
        return self._content_hash

    @property
    def base(self) -> BoundToolPlan:
        """Return the unprojected catalog retained across provider switches."""
        return self if self._base is None else self._base

    @property
    def schema_map(self) -> Mapping[str, ToolSpec]:
        return MappingProxyType({name: self.plan.schema_map[name] for name in self.tool_names})

    @property
    def execution_map(self) -> Mapping[str, ExecutionBinding]:
        return MappingProxyType({name: self.plan.execution_map[name] for name in self.tool_names})

    @property
    def ordered_specs(self) -> tuple[ToolSpec, ...]:
        return tuple(self.plan.schema_map[name] for name in self.tool_names)

    @property
    def eager_tool_names(self) -> tuple[str, ...]:
        eager = set(self.plan.eager_tool_names)
        return tuple(name for name in self.tool_names if name in eager)

    @property
    def deferred_tool_names(self) -> tuple[str, ...]:
        deferred = set(self.plan.deferred_tool_names)
        return tuple(name for name in self.tool_names if name in deferred)

    def filtered(
        self,
        *,
        allowed_tool_names: Set[str] | None = None,
        denied_tool_names: Set[str] = frozenset(),
    ) -> BoundToolPlan:
        """Return an immutable session projection without changing the parent."""
        selected = tuple(
            name
            for name in self.tool_names
            if (allowed_tool_names is None or name in allowed_tool_names)
            and name not in denied_tool_names
        )
        if selected == self.tool_names:
            return self
        selected_set = set(selected)
        return BoundToolPlan(
            self.plan,
            {name: handler for name, handler in self.handlers.items() if name in selected_set},
            selected,
            self.generation + 1,
            _base=self.base,
        )

    def projected(
        self,
        specs: Iterable[ToolSpec],
        *,
        unavailable_tool_names: Set[str] = frozenset(),
    ) -> BoundToolPlan:
        """Bind an ordered policy projection without mutating this snapshot."""
        projected_specs = tuple(specs)
        names = tuple(spec.name for spec in projected_specs)
        if len(set(names)) != len(names):
            raise ValueError("bound tool projection contains duplicate tool names")
        if unknown := sorted(set(names) - set(self.tool_names)):
            names_list = ", ".join(unknown)
            raise ValueError(f"bound tool projection references unknown tools: {names_list}")
        unavailable = set(unavailable_tool_names)
        if unknown := sorted(unavailable - set(self.tool_names)):
            names_list = ", ".join(unknown)
            raise ValueError(f"unavailable projection references unknown tools: {names_list}")
        if overlap := sorted(unavailable & set(names)):
            names_list = ", ".join(overlap)
            raise ValueError(f"unavailable projection includes visible tools: {names_list}")
        if projected_specs == self.ordered_specs and not unavailable:
            return self

        registrations = {item.spec.name: item for item in self.plan.registrations}
        selected = set(names)
        remaining = tuple(
            item for item in self.plan.registrations if item.spec.name not in selected
        )
        all_specs = tuple(
            (spec, registrations[spec.name].execution.origin) for spec in projected_specs
        ) + tuple((item.spec, item.execution.origin) for item in remaining)
        all_names = (*names, *(item.spec.name for item in remaining))
        projected_plan = compile_tool_plan(
            all_specs,
            (registrations[name].execution for name in all_names),
            safety={
                name: (
                    replace(registrations[name].safety, denied=True)
                    if name not in selected
                    and name not in unavailable
                    and name in self.plan.schema_map
                    else registrations[name].safety
                )
                for name in all_names
            },
            capabilities={
                name: (
                    replace(registrations[name].capability, available=False)
                    if name in unavailable
                    else registrations[name].capability
                )
                for name in all_names
            },
            deferred_tools=frozenset(name for name in all_names if registrations[name].deferred),
            previous=self.plan,
        )
        return BoundToolPlan(
            projected_plan,
            {name: self.handlers[name] for name in names if name in self.handlers},
            names,
            self.generation + 1,
            _base=self.base,
        )

    def at_generation(self, generation: int) -> BoundToolPlan:
        """Return this content at a later session generation."""
        if generation == self.generation:
            return self
        if generation < self.generation:
            raise ValueError("bound tool plan generation cannot decrease")
        return BoundToolPlan(
            self.plan,
            self.handlers,
            self.tool_names,
            generation,
            _base=self.base,
        )


def bind_tool_plan(plan: ToolPlan, handlers: Mapping[str, Any]) -> BoundToolPlan:
    """Bind every enabled ordinary route to one callable before side effects."""
    return BoundToolPlan(plan, handlers, tuple(plan.schema_map))


def _bound_content_hash(plan_hash: str, tool_names: tuple[str, ...]) -> str:
    canonical = json.dumps(
        {"plan_hash": plan_hash, "tool_names": tool_names},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _collect_specs(
    entries: Iterable[tuple[ToolSpec, str]],
) -> dict[str, tuple[ToolSpec, str]]:
    collected: dict[str, tuple[ToolSpec, str]] = {}
    for spec, origin in entries:
        previous = collected.get(spec.name)
        if previous is not None:
            raise ValueError(f"duplicate tool spec {spec.name!r}: {previous[1]} vs {origin}")
        collected[spec.name] = (spec, origin)
    return collected


def _collect_bindings(entries: Iterable[ExecutionBinding]) -> dict[str, ExecutionBinding]:
    collected: dict[str, ExecutionBinding] = {}
    for binding in entries:
        previous = collected.get(binding.name)
        if previous is not None:
            raise ValueError(
                f"duplicate execution binding {binding.name!r}: "
                f"{previous.origin} vs {binding.origin}"
            )
        collected[binding.name] = binding
    return collected


def _decision(registration: ToolRegistration) -> ToolDecision:
    if registration.safety.denied:
        return ToolDecision.DENIED_POLICY
    if not registration.capability.available:
        return ToolDecision.UNAVAILABLE_CAPABILITY
    return ToolDecision.ENABLED


def _content_hash(registrations: tuple[ToolRegistration, ...]) -> str:
    payload = [
        {
            "name": item.spec.name,
            "description": item.spec.description,
            "input_schema": thaw_tool_schema(item.spec.input_schema),
            "execution": {
                "origin": item.execution.origin,
                "route": item.execution.route,
            },
            "safety": {
                "effect": item.safety.effect,
                "data_class": item.safety.data_class,
                "consent_required": item.safety.consent_required,
                "allow_headless": item.safety.allow_headless,
                "allow_subagents": item.safety.allow_subagents,
                "denied": item.safety.denied,
            },
            "capability": {
                "providers": item.capability.providers,
                "services": item.capability.services,
                "auth": item.capability.auth,
                "available": item.capability.available,
            },
            "deferred": item.deferred,
            "outcome": _decision(item).value,
        }
        for item in registrations
    ]
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compile_tool_plan(
    specs: Iterable[tuple[ToolSpec, str]],
    bindings: Iterable[ExecutionBinding],
    *,
    safety: Mapping[str, SafetyPolicy] | None = None,
    capabilities: Mapping[str, CapabilityRequirement] | None = None,
    deferred_tools: Set[str] = frozenset(),
    previous: ToolPlan | None = None,
) -> ToolPlan:
    """Validate and compile separate schema/execution inputs into one snapshot."""
    specs_by_name = _collect_specs(specs)
    bindings_by_name = _collect_bindings(bindings)
    spec_names = set(specs_by_name)
    binding_names = set(bindings_by_name)
    if missing := sorted(spec_names - binding_names):
        raise ValueError(f"missing execution bindings: {', '.join(missing)}")
    if missing := sorted(binding_names - spec_names):
        raise ValueError(f"missing tool specs: {', '.join(missing)}")

    safety = safety or {}
    capabilities = capabilities or {}
    if type(deferred_tools) in {str, bytes}:
        raise TypeError("deferred_tools must be a set of tool names")
    deferred_names = set(deferred_tools)
    if any(not isinstance(name, str) or not name.strip() for name in deferred_names):
        raise ValueError("deferred tool names cannot be empty")
    if unknown := sorted((set(safety) | set(capabilities)) - spec_names):
        raise ValueError(f"metadata references unknown tools: {', '.join(unknown)}")
    if unknown := sorted(deferred_names - spec_names):
        raise ValueError(f"deferred metadata references unknown tools: {', '.join(unknown)}")

    registrations = tuple(
        ToolRegistration(
            spec=specs_by_name[name][0],
            execution=bindings_by_name[name],
            safety=safety.get(name, SafetyPolicy()),
            capability=capabilities.get(name, CapabilityRequirement()),
            deferred=name in deferred_names,
        )
        for name in specs_by_name
    )
    content_hash = _content_hash(registrations)
    if previous is not None and previous.content_hash == content_hash:
        return previous

    outcomes = {item.spec.name: _decision(item) for item in registrations}
    enabled = tuple(
        item for item in registrations if outcomes[item.spec.name] is ToolDecision.ENABLED
    )
    schema_map = MappingProxyType({item.spec.name: item.spec for item in enabled})
    execution_map = MappingProxyType({item.spec.name: item.execution for item in enabled})
    return ToolPlan(
        generation=1 if previous is None else previous.generation + 1,
        content_hash=content_hash,
        registrations=registrations,
        schema_map=schema_map,
        execution_map=execution_map,
        outcomes=MappingProxyType(outcomes),
    )


__all__ = [
    "BoundToolPlan",
    "CapabilityRequirement",
    "ExecutionBinding",
    "SafetyPolicy",
    "ToolDecision",
    "ToolPlan",
    "ToolRegistration",
    "ToolSpec",
    "bind_tool_plan",
    "compile_tool_plan",
    "thaw_tool_schema",
]
