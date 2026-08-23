"""Generation-bound LLM adapter discovery and lookup.

Built-ins and the ``geode.llm_adapters`` package entry-point group are
discovered into an immutable :class:`AdapterRegistrySnapshot`. New sessions
capture the current generation; a live session binds its captured snapshot so
reloads cannot change routing mid-turn.

The historical register/get/list functions remain compatibility views over
the current or session-bound snapshot. Mutations publish a new generation
instead of changing a shared dictionary in place.

See ``docs/plans/2026-05-23-llm-adapter-abstraction.md`` Layer 4 for the
``resolve_for(provider, source)`` contract — it raises on ``source="auto"``
because the picker is responsible for collapsing ``auto`` to a concrete value
before the adapter is selected.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from core.llm.adapters.base import (
    CONCRETE_SOURCES,
    SOURCE_AUTO,
    EnvironmentDiagnosticCapable,
    EnvironmentReport,
    LLMAdapter,
)

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.config.policy_source import PolicySourceBundle


ADAPTER_ENTRY_POINT_GROUP = "geode.llm_adapters"


class AdapterAlreadyRegisteredError(RuntimeError):
    """Raised by :func:`register_adapter` when a name collides without ``replace=True``."""


class AdapterNotFoundError(KeyError):
    """Raised by :func:`get_adapter` and :func:`resolve_for` on lookup miss."""


@dataclass(frozen=True, slots=True)
class AdapterOverride:
    """Explicit duplicate-ID winner with auditable precedence and trust."""

    origin: str
    priority: int
    trust_decision: str

    def __post_init__(self) -> None:
        if not self.origin.strip():
            raise ValueError("adapter override origin is empty")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("adapter override priority must be an integer")
        if not self.trust_decision.strip():
            raise ValueError("adapter override trust_decision is empty")


@dataclass(frozen=True, slots=True)
class AdapterRegistration:
    """One immutable registry record; the adapter owns its runtime clients."""

    adapter: LLMAdapter
    origin: str
    priority: int
    trust_decision: str

    def __post_init__(self) -> None:
        if not self.origin.strip():
            raise ValueError("adapter registration origin is empty")
        if isinstance(self.priority, bool) or not isinstance(self.priority, int):
            raise TypeError("adapter registration priority must be an integer")
        if not self.trust_decision.strip():
            raise ValueError("adapter registration trust_decision is empty")


@dataclass(frozen=True, slots=True)
class AdapterValidationReport:
    """Bounded discovery evidence attached to one registry generation."""

    generation: int
    loaded: tuple[str, ...]
    origins: tuple[tuple[str, str], ...]
    overrides: tuple[tuple[str, str, int, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AdapterRegistrySnapshot:
    """Immutable adapter catalog captured by one session."""

    generation: int
    registrations: Mapping[str, AdapterRegistration]
    report: AdapterValidationReport

    def __post_init__(self) -> None:
        records = dict(self.registrations)
        names = tuple(records)
        if names != tuple(record.adapter.name for record in records.values()):
            raise ValueError("adapter registry keys must match canonical adapter names")
        if self.report.generation != self.generation:
            raise ValueError("adapter validation report generation mismatch")
        origins = tuple((name, record.origin) for name, record in records.items())
        if self.report.loaded != names or self.report.origins != origins:
            raise ValueError("adapter validation report does not match registry contents")
        object.__setattr__(self, "registrations", MappingProxyType(records))

    def get_adapter(self, name: str) -> LLMAdapter:
        """Return one adapter by canonical ID."""
        if name == "codex-cli":
            raise AdapterNotFoundError(
                "adapter 'codex-cli' was retired; use 'codex-oauth' for ChatGPT subscription access"
            )
        try:
            return self.registrations[name].adapter
        except KeyError as exc:
            raise AdapterNotFoundError(
                f"adapter {name!r} not registered. Known: {sorted(self.registrations)}"
            ) from exc

    def list_adapters(self) -> tuple[LLMAdapter, ...]:
        """Adapters in deterministic discovery order."""
        return tuple(record.adapter for record in self.registrations.values())

    def resolve_for(self, provider: str, source: str) -> LLMAdapter:
        """Resolve the unique adapter matching a concrete route."""
        provider = normalize_registry_provider(provider)
        if source == SOURCE_AUTO:
            raise ValueError(
                "resolve_for: source='auto' is a picker sentinel — collapse it to a "
                "concrete value (payg / subscription / adapter) before resolving."
            )
        if source not in CONCRETE_SOURCES:
            raise ValueError(
                f"resolve_for: source={source!r} is not a concrete value "
                f"(must be one of {sorted(CONCRETE_SOURCES)})"
            )
        candidates = [
            adapter
            for adapter in self.list_adapters()
            if adapter.provider == provider and adapter.source == source
        ]
        if not candidates:
            known = [(adapter.provider, adapter.source) for adapter in self.list_adapters()]
            raise AdapterNotFoundError(
                f"no adapter for provider={provider!r} source={source!r}. Known pairs: {known}"
            )
        if len(candidates) > 1:
            raise RuntimeError(
                f"resolve_for: multiple adapters match provider={provider!r} source={source!r}: "
                f"{[adapter.name for adapter in candidates]} — registry invariant violated"
            )
        return candidates[0]


_EMPTY_REPORT = AdapterValidationReport(0, (), ())
_CURRENT = AdapterRegistrySnapshot(0, {}, _EMPTY_REPORT)
_ACTIVE_SNAPSHOT: ContextVar[AdapterRegistrySnapshot | None] = ContextVar(
    "active_adapter_registry_snapshot", default=None
)
_BOOTSTRAPPED = False
_REGISTRY_LOCK = RLock()


class _RegistryView(Mapping[str, LLMAdapter]):
    """Read-only compatibility view for legacy tests and diagnostics."""

    def __getitem__(self, name: str) -> LLMAdapter:
        return active_registry_snapshot().get_adapter(name)

    def __iter__(self) -> Iterator[str]:
        return iter(active_registry_snapshot().registrations)

    def __len__(self) -> int:
        return len(active_registry_snapshot().registrations)


_REGISTRY: Mapping[str, LLMAdapter] = _RegistryView()


def registry_snapshot() -> AdapterRegistrySnapshot:
    """Return the process-current generation for a newly created session."""
    return _CURRENT


def active_registry_snapshot() -> AdapterRegistrySnapshot:
    """Return the session-bound generation, or the process current generation."""
    return _ACTIVE_SNAPSHOT.get() or _CURRENT


@contextmanager
def use_registry_snapshot(snapshot: AdapterRegistrySnapshot) -> Iterator[None]:
    """Bind one captured generation for a complete async session operation."""
    token = _ACTIVE_SNAPSHOT.set(snapshot)
    try:
        yield
    finally:
        _ACTIVE_SNAPSHOT.reset(token)


def _validate_adapter(adapter: LLMAdapter, *, prefix: str) -> None:
    name = adapter.name
    if not name:
        raise ValueError(f"{prefix}: adapter.name is empty")
    if adapter.source not in CONCRETE_SOURCES:
        raise ValueError(
            f"{prefix}: adapter.source={adapter.source!r} is not a concrete value "
            f"(must be one of {sorted(CONCRETE_SOURCES)})"
        )


def _publish(
    registrations: Mapping[str, AdapterRegistration],
    *,
    overrides: tuple[tuple[str, str, int, str], ...] = (),
) -> AdapterRegistrySnapshot:
    global _CURRENT
    generation = _CURRENT.generation + 1
    records = dict(registrations)
    route_owners: dict[tuple[str, str], str] = {}
    for canonical_id, registration in records.items():
        adapter = registration.adapter
        route = (adapter.provider, adapter.source)
        if existing := route_owners.get(route):
            raise ValueError(f"adapters {existing!r} and {canonical_id!r} both own route {route!r}")
        route_owners[route] = canonical_id
    report = AdapterValidationReport(
        generation=generation,
        loaded=tuple(records),
        origins=tuple((name, record.origin) for name, record in records.items()),
        overrides=overrides,
    )
    _CURRENT = AdapterRegistrySnapshot(generation, records, report)
    return _CURRENT


def register_adapter(
    adapter: LLMAdapter,
    *,
    replace: bool = False,
    origin: str | None = None,
    priority: int = 0,
    trust_decision: str = "",
) -> None:
    """Publish a compatibility registration as a new registry generation.

    Supported third-party packages should use the ``geode.llm_adapters``
    entry-point group. ``replace=True`` is an explicit trust boundary and must
    record the override decision instead of silently changing ownership.
    """
    _validate_adapter(adapter, prefix="register_adapter")
    name = adapter.name
    with _REGISTRY_LOCK:
        records = dict(_CURRENT.registrations)
        if name in records and not replace:
            raise AdapterAlreadyRegisteredError(
                f"adapter {name!r} already registered; pass replace=True to override"
            )
        resolved_origin = origin or (
            f"runtime:{type(adapter).__module__}:{type(adapter).__qualname__}"
        )
        overrides: tuple[tuple[str, str, int, str], ...] = ()
        if replace:
            if not trust_decision.strip():
                raise ValueError("register_adapter: replace=True requires trust_decision")
            overrides = ((name, resolved_origin, priority, trust_decision),)
        records[name] = AdapterRegistration(
            adapter=adapter,
            origin=resolved_origin,
            priority=priority,
            trust_decision=trust_decision or "runtime-registration",
        )
        _publish(records, overrides=overrides)
    log.debug(
        "adapter registered: %s (provider=%s source=%s origin=%s)",
        name,
        adapter.provider,
        adapter.source,
        resolved_origin,
    )


def unregister_adapter(name: str) -> None:
    """Publish a generation without ``name``. No-op when absent."""
    with _REGISTRY_LOCK:
        if name not in _CURRENT.registrations:
            return
        records = dict(_CURRENT.registrations)
        records.pop(name)
        _publish(records)


def get_adapter(name: str) -> LLMAdapter:
    """Look up a registered adapter by its canonical ``name``.

    Raises :class:`AdapterNotFoundError` when missing.
    """
    return active_registry_snapshot().get_adapter(name)


def list_adapters() -> list[LLMAdapter]:
    """Session-bound adapters in deterministic discovery order."""
    return list(active_registry_snapshot().list_adapters())


def adapter_health(name: str) -> EnvironmentReport:
    """Probe optional environment diagnostics by registry name.

    Step I.c (2026-05-23) — thin one-call accessor over the optional
    :class:`EnvironmentDiagnosticCapable` probe so picker UIs / readiness
    audits / external consumers (petri_audit's ``credential_source``
    cascade, the ``/auth`` slash, the routing-recovery loop) don't have
    to ``get_adapter(name).test_environment()`` themselves and don't
    need to know which exception ``get_adapter`` raises on a typo.

    Raises :class:`KeyError` when no adapter is registered under
    ``name`` (delegates to :func:`get_adapter`). Unsupported diagnostics
    and credential failures return an
    :class:`EnvironmentReport` with ``ok=False`` and operator-facing hints.
    """
    adapter = get_adapter(name)
    if not isinstance(adapter, EnvironmentDiagnosticCapable):
        return EnvironmentReport(
            ok=False,
            hints=(f"adapter {name!r} does not support environment diagnostics",),
        )
    return adapter.test_environment()


# PR-DRIFT-ANCHORS (2026-06-10) — single SoT for the legacy→registry
# provider-key translation. ``core.config._resolve_provider`` returns the
# broader vocabulary (``openai-codex`` for gpt-5.x, ``zhipuai`` for GLM);
# this registry keys adapters on the narrower ``openai`` / ``glm`` (the
# Codex distinction rides the ``source`` axis as ``subscription``).
# Previously FOUR independent copies of this map existed
# (agent_loop.__init__, _model_switching._resolve_path_b_adapter,
# runner._normalize_provider_for_registry,
# _reflection._normalize_provider_for_registry — the last two only
# carried the openai half), with a comment admitting they were not
# sync'd. Add new aliases HERE only.
PROVIDER_REGISTRY_NORMALIZATION: dict[str, str] = {
    "openai-codex": "openai",
    "glm-coding": "glm",
    "zhipuai": "glm",
}


def normalize_registry_provider(provider: str) -> str:
    """Translate a legacy ``_resolve_provider`` key to this registry's
    provider vocabulary (identity for already-narrow keys)."""
    return PROVIDER_REGISTRY_NORMALIZATION.get(provider, provider)


def resolve_for(provider: str, source: str) -> LLMAdapter:
    """Find the unique adapter matching ``(provider, source)``.

    ``provider`` accepts BOTH vocabularies — the registry's family names
    (``openai`` / ``glm``) and the routing layer's variant ids
    (``openai-codex`` / ``glm-coding`` / ``zhipuai``) — normalized here at
    the boundary. Callers used to be responsible for calling
    :func:`normalize_registry_provider` themselves; the fast-chat incident
    (2026-07-06 — ``loop._provider='openai-codex'`` passed through
    unnormalized, every codex-subscription fast-chat turn failed with
    AdapterUnavailableError) showed convention-enforced translation does
    not survive new callers. Normalizing at the lookup entry kills the
    bug class.

    ``source`` MUST be a concrete value (one of
    ``core.llm.adapters.base.CONCRETE_SOURCES``). The picker collapses
    ``"auto"`` → concrete before calling. Passing ``"auto"`` here raises
    :class:`ValueError` — failing loudly is the same anti-leak posture
    paperclip's registry takes on duplicate type registration.

    Raises :class:`AdapterNotFoundError` when no adapter matches.
    """
    return active_registry_snapshot().resolve_for(provider, source)


def invalidate_provider_clients(provider: str | None = None) -> int:
    """Drop cached SDK clients so a credential change takes effect at once.

    2026-07-29: ``/key`` and ``/login`` previously reset the ``providers/``
    SYNC client singletons — which the live path stopped using long ago, so a
    rotated key kept flowing through a stale ADAPTER client until restart.
    Adapters are registry singletons holding ``LoopAffineClientCache``; this
    invalidates them (all, or one provider's).

    Returns the number of adapters whose cache was dropped.
    """
    dropped = 0
    for adapter in _REGISTRY.values():
        if provider is not None and adapter.provider != normalize_registry_provider(provider):
            continue
        cache = getattr(adapter, "_clients", None)
        if cache is not None and hasattr(cache, "invalidate"):
            cache.invalidate()
            dropped += 1
    return dropped


def _builtin_registrations(
    policy_sources: PolicySourceBundle | None,
) -> list[AdapterRegistration]:
    """Instantiate the explicit first-party factory set."""
    from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.llm.adapters.glm_coding_plan import GlmCodingPlanAdapter
    from core.llm.adapters.glm_payg import GlmPaygAdapter
    from core.llm.adapters.openai_payg import OpenAIPaygAdapter

    factories: tuple[Callable[[], LLMAdapter], ...] = (
        AnthropicPaygAdapter,
        OpenAIPaygAdapter,
        CodexOAuthAdapter,
        GlmPaygAdapter,
        GlmCodingPlanAdapter,
    )
    records: list[AdapterRegistration] = []
    for factory in factories:
        instance = factory()
        if isinstance(instance, GlmCodingPlanAdapter):
            instance.routing_sources = (policy_sources or {}).get("provider_routing")
        _validate_adapter(instance, prefix="builtin adapter")
        records.append(
            AdapterRegistration(
                adapter=instance,
                origin=f"builtin:{instance.name}",
                priority=100,
                trust_decision="bundled-first-party",
            )
        )
    return records


def _entry_point_origin(entry_point: Any) -> str:
    distribution = getattr(entry_point, "dist", None)
    metadata = getattr(distribution, "metadata", None)
    distribution_name = "unknown-distribution"
    if metadata is not None:
        distribution_name = str(metadata.get("Name") or distribution_name)
    return f"entrypoint:{distribution_name}:{entry_point.name}"


def _entry_point_registrations() -> list[AdapterRegistration]:
    """Load no-argument adapter factories from installed package metadata."""
    from importlib.metadata import entry_points

    records: list[AdapterRegistration] = []
    discovered = sorted(
        entry_points(group=ADAPTER_ENTRY_POINT_GROUP),
        key=lambda item: (item.name, item.value),
    )
    for entry_point in discovered:
        origin = _entry_point_origin(entry_point)
        factory = entry_point.load()
        if not callable(factory):
            raise TypeError(f"{origin} must resolve to a no-argument adapter factory")
        try:
            adapter = factory()
        except Exception as exc:
            raise RuntimeError(f"{origin} adapter factory failed") from exc
        if not isinstance(adapter, LLMAdapter):
            raise TypeError(f"{origin} factory did not return an LLMAdapter")
        _validate_adapter(adapter, prefix=origin)
        if adapter.name != entry_point.name:
            raise ValueError(
                f"{origin} declares canonical ID {entry_point.name!r} "
                f"but returned adapter {adapter.name!r}"
            )
        records.append(
            AdapterRegistration(
                adapter=adapter,
                origin=origin,
                priority=0,
                trust_decision="installed-package-entry-point",
            )
        )
    return records


def _resolve_discovery_collisions(
    candidates: list[AdapterRegistration],
    overrides: Mapping[str, AdapterOverride],
) -> tuple[dict[str, AdapterRegistration], tuple[tuple[str, str, int, str], ...]]:
    grouped: dict[str, list[AdapterRegistration]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.adapter.name, []).append(candidate)

    selected: dict[str, AdapterRegistration] = {}
    applied: list[tuple[str, str, int, str]] = []
    for canonical_id, group in grouped.items():
        if len(group) == 1:
            selected[canonical_id] = group[0]
            continue
        decision = overrides.get(canonical_id)
        origins = [candidate.origin for candidate in group]
        if decision is None:
            raise AdapterAlreadyRegisteredError(
                f"adapter {canonical_id!r} discovered from multiple origins: {origins}; "
                "an explicit AdapterOverride is required"
            )
        try:
            winner = next(candidate for candidate in group if candidate.origin == decision.origin)
        except StopIteration as exc:
            raise ValueError(
                f"adapter override for {canonical_id!r} selects unknown origin "
                f"{decision.origin!r}; candidates: {origins}"
            ) from exc
        selected[canonical_id] = AdapterRegistration(
            adapter=winner.adapter,
            origin=winner.origin,
            priority=decision.priority,
            trust_decision=decision.trust_decision,
        )
        applied.append((canonical_id, decision.origin, decision.priority, decision.trust_decision))

    if unused := sorted(set(overrides) - {item[0] for item in applied}):
        raise ValueError(f"adapter overrides did not resolve a collision: {unused}")
    return selected, tuple(applied)


def reload_adapters(
    *,
    policy_sources: PolicySourceBundle | None = None,
    overrides: Mapping[str, AdapterOverride] | None = None,
) -> AdapterRegistrySnapshot:
    """Discover adapters and publish a new generation for future sessions."""
    global _BOOTSTRAPPED
    with _REGISTRY_LOCK:
        candidates = [*_builtin_registrations(policy_sources), *_entry_point_registrations()]
        selected, applied = _resolve_discovery_collisions(candidates, overrides or {})
        snapshot = _publish(selected, overrides=applied)
        _BOOTSTRAPPED = True
        return snapshot


def bootstrap_builtins(
    *,
    policy_sources: PolicySourceBundle | None = None,
    overrides: Mapping[str, AdapterOverride] | None = None,
) -> AdapterRegistrySnapshot:
    """Idempotently discover built-ins and supported package entry points."""
    with _REGISTRY_LOCK:
        if _BOOTSTRAPPED:
            if overrides:
                raise RuntimeError("adapter registry is already bootstrapped; call reload_adapters")
            return _CURRENT
        return reload_adapters(policy_sources=policy_sources, overrides=overrides)


def _reset_for_test() -> None:
    """Reset all registry generations. Test-only."""
    global _BOOTSTRAPPED, _CURRENT
    with _REGISTRY_LOCK:
        _CURRENT = AdapterRegistrySnapshot(0, {}, _EMPTY_REPORT)
        _BOOTSTRAPPED = False
        _ACTIVE_SNAPSHOT.set(None)


__all__ = [
    "ADAPTER_ENTRY_POINT_GROUP",
    "AdapterAlreadyRegisteredError",
    "AdapterNotFoundError",
    "AdapterOverride",
    "AdapterRegistration",
    "AdapterRegistrySnapshot",
    "AdapterValidationReport",
    "active_registry_snapshot",
    "adapter_health",
    "bootstrap_builtins",
    "get_adapter",
    "invalidate_provider_clients",
    "list_adapters",
    "register_adapter",
    "registry_snapshot",
    "reload_adapters",
    "resolve_for",
    "unregister_adapter",
    "use_registry_snapshot",
]
