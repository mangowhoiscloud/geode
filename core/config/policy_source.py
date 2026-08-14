"""Neutral source selection for file-backed runtime policies.

The kernel owns only the deterministic selection mechanism. Product code
supplies the candidate paths explicitly through :class:`PolicySourcePaths`;
schema validation and coercion remain with each policy reader.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

_OVERRIDE_SUFFIX = "_OVERRIDE"
_STRICT_SUFFIX = "_STRICT"

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PolicySourcePaths:
    """Immutable candidates for one file-backed policy source."""

    override_env: str
    operator_local: Path | None = None
    packaged_default: Path | None = None
    override_is_strict: bool = False
    explicit_override: Path | None = None
    explicit_override_strict: bool = False


type PolicySourceBundle = Mapping[str, PolicySourcePaths]
EMPTY_POLICY_SOURCES: PolicySourceBundle = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class PolicySourceSelection:
    """Selected policy path plus its strict-loading mode."""

    path: Path
    strict: bool


def select_policy_source(
    sources: PolicySourcePaths,
    *,
    environ: Mapping[str, str] | None = None,
) -> PolicySourceSelection | None:
    """Select ``override -> operator-local -> packaged-default``.

    An explicit environment override is authoritative even when its target
    does not exist. Only the matching ``<prefix>_STRICT=1`` flag enables
    strict loading; filesystem fallbacks are always graceful.
    """
    if sources.explicit_override is not None:
        return PolicySourceSelection(
            sources.explicit_override,
            strict=sources.explicit_override_strict,
        )
    active_environ = os.environ if environ is None else environ
    override_path = active_environ.get(sources.override_env)
    if override_path:
        strict_env = sources.override_env.removesuffix(_OVERRIDE_SUFFIX) + _STRICT_SUFFIX
        return PolicySourceSelection(
            Path(override_path),
            strict=sources.override_is_strict or active_environ.get(strict_env) == "1",
        )
    if sources.operator_local is not None and sources.operator_local.is_file():
        return PolicySourceSelection(sources.operator_local, strict=False)
    if sources.packaged_default is not None and sources.packaged_default.is_file():
        return PolicySourceSelection(sources.packaged_default, strict=False)
    return None


def load_policy_source[PolicyT](
    *,
    sources: PolicySourcePaths | None,
    label: str,
    validate_strict: Callable[[Any, Path], None],
    validate_graceful: Callable[[Any, Path], None],
    coerce: Callable[[Any], PolicyT],
) -> PolicyT | None:
    """Resolve and load one JSON policy with strict/graceful parity."""
    if sources is None:
        return None
    selection = select_policy_source(sources)
    if selection is None:
        return None
    path = selection.path
    if selection.strict:
        if not path.is_file():
            raise RuntimeError(f"{sources.override_env}={path} file not found")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"{sources.override_env}={path} load failed: {exc}") from exc
        validate_strict(data, path)
        return coerce(data)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("%s SoT at %s is unreadable; ignoring", label, path)
        return None
    try:
        validate_graceful(data, path)
    except RuntimeError as exc:
        log.warning("%s SoT at %s schema invalid: %s; ignoring", label, path, exc)
        return None
    return coerce(data)


type EncodedPolicySourceBundle = dict[str, dict[str, str | bool]]


def encode_policy_sources(
    sources: PolicySourceBundle,
    *,
    environ: Mapping[str, str] | None = None,
) -> EncodedPolicySourceBundle:
    """Serialize candidates plus the parent's active override for a worker."""
    active_environ = os.environ if environ is None else environ
    encoded: EncodedPolicySourceBundle = {}
    for name, spec in sources.items():
        override = spec.explicit_override
        override_strict = spec.explicit_override_strict
        if override is None:
            raw_override = active_environ.get(spec.override_env, "")
            override = Path(raw_override) if raw_override else None
            strict_env = spec.override_env.removesuffix(_OVERRIDE_SUFFIX) + _STRICT_SUFFIX
            override_strict = spec.override_is_strict or active_environ.get(strict_env) == "1"
        encoded[name] = {
            "override_env": spec.override_env,
            "operator_local": str(spec.operator_local) if spec.operator_local else "",
            "packaged_default": str(spec.packaged_default) if spec.packaged_default else "",
            "override_is_strict": spec.override_is_strict,
            "explicit_override": str(override) if override else "",
            "explicit_override_strict": override_strict,
        }
    return encoded


def decode_policy_sources(
    encoded: Mapping[str, Mapping[str, str | bool]],
) -> PolicySourceBundle:
    """Restore an immutable worker-local policy-source bundle."""
    decoded: dict[str, PolicySourcePaths] = {}
    for name, raw in encoded.items():
        override_env = raw.get("override_env", "")
        if not isinstance(override_env, str) or not override_env:
            continue

        operator_local = raw.get("operator_local", "")
        packaged_default = raw.get("packaged_default", "")
        explicit_override = raw.get("explicit_override", "")

        decoded[name] = PolicySourcePaths(
            override_env=override_env,
            operator_local=(
                Path(operator_local) if isinstance(operator_local, str) and operator_local else None
            ),
            packaged_default=(
                Path(packaged_default)
                if isinstance(packaged_default, str) and packaged_default
                else None
            ),
            override_is_strict=raw.get("override_is_strict") is True,
            explicit_override=(
                Path(explicit_override)
                if isinstance(explicit_override, str) and explicit_override
                else None
            ),
            explicit_override_strict=raw.get("explicit_override_strict") is True,
        )
    return MappingProxyType(decoded)


__all__ = [
    "EMPTY_POLICY_SOURCES",
    "EncodedPolicySourceBundle",
    "PolicySourceBundle",
    "PolicySourcePaths",
    "PolicySourceSelection",
    "decode_policy_sources",
    "encode_policy_sources",
    "load_policy_source",
    "select_policy_source",
]
