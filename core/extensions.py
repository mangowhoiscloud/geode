"""Shared trust decisions for GEODE's existing extension surfaces."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from core.config.policy_source import PolicySourcePaths, load_policy_source


class ExtensionSurface(StrEnum):
    SKILL = "skill"
    HOOK = "hook"
    MCP = "mcp"
    LLM_ADAPTER = "llm-adapter"


class ExtensionExecution(StrEnum):
    METADATA = "metadata"
    TRUSTED = "trusted"
    BROKERED = "brokered"


class ExtensionState(StrEnum):
    DISABLED = "disabled"
    REJECTED = "rejected"
    GRANTED = "granted"
    DEGRADED = "degraded"


def _names(values: Iterable[str], *, label: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{label} must be a collection of strings")
    snapshot = tuple(values)
    if any(not isinstance(value, str) for value in snapshot):
        raise TypeError(f"{label} entries must be strings")
    return tuple(dict.fromkeys(value.strip() for value in snapshot if value.strip()))


@dataclass(frozen=True, slots=True)
class ExtensionDescriptor:
    """Non-executing metadata projected from one existing surface."""

    name: str
    surface: ExtensionSurface
    origin: str
    execution: ExtensionExecution
    enabled: bool = True
    capabilities: tuple[str, ...] = ()
    resource_keys: tuple[str, ...] = ()
    bundled: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("extension name is empty")
        if not isinstance(self.origin, str) or not self.origin.strip():
            raise ValueError("extension origin is empty")
        if not isinstance(self.enabled, bool) or not isinstance(self.bundled, bool):
            raise TypeError("extension enabled/bundled values must be booleans")
        object.__setattr__(self, "surface", ExtensionSurface(self.surface))
        object.__setattr__(self, "execution", ExtensionExecution(self.execution))
        object.__setattr__(
            self,
            "capabilities",
            _names(self.capabilities, label="extension capabilities"),
        )
        object.__setattr__(
            self,
            "resource_keys",
            _names(self.resource_keys, label="extension resource keys"),
        )

    @property
    def extension_id(self) -> str:
        return f"{self.surface.value}:{self.name}"


@dataclass(frozen=True, slots=True)
class ExtensionGrant:
    """Operator-owned enablement, trust, execution, and capability decision."""

    enabled: bool
    trusted: bool
    execution: ExtensionExecution
    capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution", ExtensionExecution(self.execution))
        object.__setattr__(
            self,
            "capabilities",
            _names(self.capabilities, label="extension grant capabilities"),
        )


@dataclass(frozen=True, slots=True)
class ExtensionPolicy:
    """Immutable operator decisions captured by one runtime generation."""

    grants: Mapping[str, ExtensionGrant]
    content_hash: str

    def __post_init__(self) -> None:
        records = dict(self.grants)
        if any(not isinstance(key, str) or not key.strip() for key in records):
            raise ValueError("extension policy ID is empty")
        object.__setattr__(self, "grants", MappingProxyType(records))

    @classmethod
    def empty(cls) -> ExtensionPolicy:
        return cls(MappingProxyType({}), _policy_hash({}))

    @classmethod
    def from_mapping(cls, raw: Any) -> ExtensionPolicy:
        if not isinstance(raw, Mapping) or raw.get("version") != 1:
            raise ValueError("extension policy must be an object with version=1")
        if unknown := sorted(set(raw) - {"version", "extensions"}):
            raise ValueError(f"unknown extension policy fields: {unknown}")
        records = raw.get("extensions")
        if not isinstance(records, Mapping):
            raise ValueError("extension policy extensions must be an object")
        grants: dict[str, ExtensionGrant] = {}
        for extension_id, value in records.items():
            if not isinstance(extension_id, str) or not isinstance(value, Mapping):
                raise TypeError("extension policy entries must map string IDs to objects")
            if unknown := sorted(set(value) - {"enabled", "trusted", "execution", "capabilities"}):
                raise ValueError(f"unknown fields for extension {extension_id!r}: {unknown}")
            enabled = value.get("enabled", True)
            trusted = value.get("trusted", False)
            capabilities = value.get("capabilities", [])
            if not isinstance(enabled, bool) or not isinstance(trusted, bool):
                raise TypeError("extension enabled/trusted values must be booleans")
            if isinstance(capabilities, (str, bytes)) or not isinstance(capabilities, list):
                raise TypeError("extension capabilities must be a list of strings")
            grants[extension_id] = ExtensionGrant(
                enabled=enabled,
                trusted=trusted,
                execution=ExtensionExecution(value.get("execution", "metadata")),
                capabilities=tuple(capabilities),
            )
        return cls(grants, _policy_hash(raw))


def _policy_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def load_extension_policy(sources: PolicySourcePaths | None) -> ExtensionPolicy:
    """Load the selected operator policy; absence is an empty fail-closed policy."""

    def validate(value: Any, _path: Any) -> None:
        try:
            ExtensionPolicy.from_mapping(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(str(exc)) from exc

    loaded = load_policy_source(
        sources=sources,
        label="extension policy",
        validate_strict=validate,
        validate_graceful=validate,
        coerce=ExtensionPolicy.from_mapping,
    )
    return loaded or ExtensionPolicy.empty()


def load_default_extension_policy() -> ExtensionPolicy:
    """Load the operator-owned global policy or an explicit strict override."""
    from core.paths import GLOBAL_EXTENSION_POLICY_PATH

    return load_extension_policy(
        PolicySourcePaths(
            "GEODE_EXTENSION_POLICY_OVERRIDE",
            operator_local=GLOBAL_EXTENSION_POLICY_PATH,
            override_is_strict=True,
        )
    )


@dataclass(frozen=True, slots=True)
class ExtensionDecision:
    """Observable authorization result produced before executable load."""

    descriptor: ExtensionDescriptor
    state: ExtensionState
    enabled: bool
    trusted: bool
    granted_capabilities: tuple[str, ...] = ()
    reason: str = ""

    @property
    def installed(self) -> bool:
        """A discovered manifest/entry-point/config is installed metadata."""
        return True

    def status(self) -> dict[str, Any]:
        """Return a bounded, secret-free lifecycle projection."""
        return {
            "id": self.descriptor.extension_id,
            "origin": self.descriptor.origin,
            "state": self.state.value,
            "installed": self.installed,
            "manifest_enabled": self.descriptor.enabled,
            "enabled": self.enabled,
            "trusted": self.trusted,
            "capabilities": list(self.granted_capabilities),
            "resource_keys": list(self.descriptor.resource_keys),
            "reason": self.reason,
        }

    @property
    def may_load_in_process(self) -> bool:
        return (
            self.state is ExtensionState.GRANTED
            and self.descriptor.execution is ExtensionExecution.TRUSTED
        )

    @property
    def may_launch_brokered(self) -> bool:
        return (
            self.state is ExtensionState.GRANTED
            and self.descriptor.execution is ExtensionExecution.BROKERED
        )

    def degraded(self, reason: str) -> ExtensionDecision:
        return ExtensionDecision(
            self.descriptor,
            ExtensionState.DEGRADED,
            self.enabled,
            self.trusted,
            self.granted_capabilities,
            reason,
        )


def decide_extension(
    descriptor: ExtensionDescriptor,
    policy: ExtensionPolicy,
) -> ExtensionDecision:
    """Apply an operator policy without importing or instantiating extension code."""
    if not descriptor.enabled:
        return ExtensionDecision(
            descriptor, ExtensionState.DISABLED, False, False, reason="manifest"
        )
    if descriptor.bundled:
        return ExtensionDecision(
            descriptor,
            ExtensionState.GRANTED,
            True,
            True,
            descriptor.capabilities,
            "bundled-first-party",
        )
    grant = policy.grants.get(descriptor.extension_id)
    if grant is None:
        return ExtensionDecision(
            descriptor,
            ExtensionState.REJECTED,
            False,
            False,
            reason="missing operator policy",
        )
    if not grant.enabled:
        return ExtensionDecision(
            descriptor, ExtensionState.DISABLED, False, grant.trusted, reason="policy"
        )
    if grant.execution is not descriptor.execution:
        return ExtensionDecision(
            descriptor,
            ExtensionState.REJECTED,
            True,
            grant.trusted,
            reason=f"execution mismatch: manifest={descriptor.execution} policy={grant.execution}",
        )
    missing = tuple(name for name in descriptor.capabilities if name not in grant.capabilities)
    if missing:
        return ExtensionDecision(
            descriptor,
            ExtensionState.REJECTED,
            True,
            grant.trusted,
            reason=f"missing capability grants: {', '.join(missing)}",
        )
    if descriptor.execution is ExtensionExecution.TRUSTED and not grant.trusted:
        return ExtensionDecision(
            descriptor,
            ExtensionState.REJECTED,
            True,
            False,
            reason="in-process execution requires trust",
        )
    return ExtensionDecision(
        descriptor,
        ExtensionState.GRANTED,
        True,
        grant.trusted,
        descriptor.capabilities,
        "operator policy",
    )


@dataclass(frozen=True, slots=True)
class ExtensionContext:
    """Narrow immutable ports for fully trusted in-process code."""

    extension_id: str
    capabilities: tuple[str, ...]
    ports: Mapping[str, Any]

    def __post_init__(self) -> None:
        ports = dict(self.ports)
        if unknown := sorted(set(ports) - set(self.capabilities)):
            raise ValueError(f"extension ports lack grants: {unknown}")
        object.__setattr__(self, "ports", MappingProxyType(ports))

    def require(self, name: str) -> Any:
        try:
            return self.ports[name]
        except KeyError as exc:
            raise PermissionError(f"extension {self.extension_id!r} lacks port {name!r}") from exc


def extension_context(
    decision: ExtensionDecision,
    ports: Mapping[str, Any] | None = None,
) -> ExtensionContext:
    if not decision.may_load_in_process:
        raise PermissionError(f"extension {decision.descriptor.extension_id!r} is not trusted")
    return ExtensionContext(
        decision.descriptor.extension_id,
        decision.granted_capabilities,
        ports or {},
    )


__all__ = [
    "ExtensionContext",
    "ExtensionDecision",
    "ExtensionDescriptor",
    "ExtensionExecution",
    "ExtensionGrant",
    "ExtensionPolicy",
    "ExtensionState",
    "ExtensionSurface",
    "decide_extension",
    "extension_context",
    "load_default_extension_policy",
    "load_extension_policy",
]
