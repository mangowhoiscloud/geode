"""Petri audit adapter registry — manifest-driven lazy dispatch.

Each ``(family, source)`` pair in :mod:`plugins.petri_audit.manifest`
maps to a concrete adapter module. The registry imports those modules
lazily so the default ``uv sync`` (no ``[audit]`` extra) keeps cold-start
clean, and exposes a uniform interface:

- :func:`load_adapter_module` — import the module declared by manifest.
- :func:`register_adapter` — call the module's ``register()`` (if any),
  which wires its inspect_ai ``ModelAPI`` into the global registry.
- :func:`is_adapter_available` — call the module's ``is_available()``
  (if any) to probe credentials without side effects.

Adapter module contract (loose — registry checks ``hasattr`` per call):

- ``register() -> None`` — idempotent inspect_ai registration. Stock
  providers (e.g. plain ``anthropic/``, ``openai/``) need no extra
  registration; the function may be absent or a no-op.
- ``is_available() -> bool`` — readiness probe. Stock providers fall
  back to env-var presence; OAuth-backed adapters check the keychain
  / authoritative token file.
- ``metadata() -> dict | None`` (optional) — picker-friendly metadata
  (subscription plan, scopes, expiry). Only OAuth adapters populate.

Used by the upcoming P1-E registry layer (role × source binding) and
the /petri picker (P1-F) to keep adapter selection logic out of the
hardcoded if/elif chain in :mod:`plugins.petri_audit.models`.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Any

from plugins.petri_audit.manifest import AdapterSpec, load_manifest

__all__ = [
    "get_adapter_metadata",
    "get_adapter_spec",
    "is_adapter_available",
    "load_adapter_module",
    "register_adapter",
]


def get_adapter_spec(family: str, source: str) -> AdapterSpec:
    """Return the :class:`AdapterSpec` declared by the active manifest.

    Thin wrapper kept here so callers don't need to import
    :func:`plugins.petri_audit.manifest.load_manifest` directly.
    """
    return load_manifest().get_adapter(family, source)


def load_adapter_module(family: str, source: str) -> ModuleType:
    """Import the adapter module for ``(family, source)`` lazily.

    Raises :class:`ImportError` when the declared module is missing
    (e.g. the ``[audit]`` extra is not installed and the adapter
    depends on it); raises :class:`KeyError` when the manifest has no
    binding for the pair (see :class:`PetriManifest.get_adapter`).
    """
    spec = get_adapter_spec(family, source)
    return importlib.import_module(spec.module)


def register_adapter(family: str, source: str) -> None:
    """Invoke the adapter module's ``register()`` if it exposes one.

    Stock providers (inspect_ai's native ``anthropic`` / ``openai`` /
    ``geode``) need no explicit registration; their modules either omit
    ``register`` or implement a no-op. OAuth-backed adapters (claude-cli
    keychain, codex OAuth) use ``register()`` to wire a ``ModelAPI``
    subclass into inspect_ai's registry. Idempotent — inspect_ai's
    registry overwrites existing entries with the same name.
    """
    module = load_adapter_module(family, source)
    register_fn = getattr(module, "register", None)
    if callable(register_fn):
        register_fn()


def is_adapter_available(family: str, source: str) -> bool:
    """Probe whether the adapter has credentials to run.

    Returns ``True`` when:

    - the module exposes ``is_available() -> bool`` and it returns True; OR
    - the module has no ``is_available`` AND has the env vars listed in
      its :class:`AdapterSpec.auth_env_vars` (fallback for stock
      providers that lean on env-var probes).

    Returns ``False`` otherwise. Never raises — credential probes must
    be side-effect-free, so import failures collapse to "unavailable".
    """
    try:
        module = load_adapter_module(family, source)
    except ImportError:
        return False
    probe = getattr(module, "is_available", None)
    if callable(probe):
        try:
            return bool(probe())
        except Exception:
            return False
    # Fallback — check env vars from the manifest.
    import os

    spec = get_adapter_spec(family, source)
    if not spec.auth_env_vars:
        # No env vars declared and no probe function — assume available
        # (e.g. geode target adapter, which uses GeodeModelAPI internally).
        return True
    return any(os.environ.get(env_var) for env_var in spec.auth_env_vars)


def get_adapter_metadata(family: str, source: str) -> dict[str, Any] | None:
    """Return picker-friendly metadata from the adapter module.

    Only OAuth-backed adapters populate this — stock API-key adapters
    return ``None``. Errors collapse to ``None`` (consumer should treat
    missing metadata as benign and fall back to defaults).
    """
    try:
        module = load_adapter_module(family, source)
    except ImportError:
        return None
    fn = getattr(module, "metadata", None)
    if not callable(fn):
        return None
    try:
        result = fn()
    except Exception:
        return None
    return result if isinstance(result, dict) else None
