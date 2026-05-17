"""Per-family credential source enumeration + resolution + suppression.

Centralises the "which credential should I use for *this* family right
now" decision so the rest of the Petri plugin (`/petri` picker,
`to_inspect_model` router, OAuth retry paths) stops re-implementing the
``settings → keychain → API key`` fallback chain in three different
places.

Frontier reference: Hermes ``agent/credential_sources.py`` — per-source
``suppress_credential_source(provider, source_id)`` so a token that
turns out to be expired mid-run is dropped from the pool without
restarting the process.

Layers:

- :func:`list_credential_sources` — enumerate (used by /petri picker).
- :func:`resolve_credential_source` — pick the effective concrete source.
- :func:`suppress_credential_source` — disable a source until process exit
  (used when an OAuth token fails the first call mid-run).
- :func:`is_suppressed` / :func:`clear_suppressions` — read / reset.

Priority for the ``auto`` sentinel:

1. ``override`` argument (callable wins over settings).
2. ``settings.{family}_credential_source`` if it carries an explicit
   non-auto value (e.g. ``ANTHROPIC_CREDENTIAL_SOURCE=api_key``).
3. Manifest ``[petri.source.<family>].default`` if not auto.
4. Manifest ``[petri.source.<family>].allowed`` order — first non-auto,
   non-suppressed, *available* source wins. Manifest ordering is the
   intent — keep OAuth first so the autoresearch outer loop hits
   subscription quota by default; API-key fallback still resolves when
   the user has only ``ANTHROPIC_API_KEY`` set.
"""

from __future__ import annotations

import threading
from typing import Any

from plugins.petri_audit.adapters import (
    get_adapter_metadata,
    is_adapter_available,
)
from plugins.petri_audit.manifest import AUTO_SOURCE, load_manifest

__all__ = [
    "CredentialResolutionError",
    "clear_suppressions",
    "is_suppressed",
    "list_credential_sources",
    "resolve_credential_source",
    "suppress_credential_source",
]


_lock = threading.Lock()
_suppressed: set[tuple[str, str]] = set()


class CredentialResolutionError(RuntimeError):
    """Raised when no credential source resolves for a family.

    Carries ``family`` and the ``allowed`` set so callers (e.g. the
    /petri picker) can render an actionable error instead of a bare
    traceback.
    """

    def __init__(self, family: str, allowed: list[str]):
        self.family = family
        self.allowed = allowed
        super().__init__(
            f"family={family}: no credential source available "
            f"(allowed={allowed}); set an env var from the picker or "
            f"adjust settings.{family}_credential_source"
        )


def list_credential_sources(family: str) -> list[dict[str, Any]]:
    """Enumerate credential sources for a family with current status.

    One entry per allowed source. Shape::

        {
            family: str,
            source: str,
            is_default: bool,
            is_suppressed: bool,
            available: bool,
            adapter: str | None,          # dotted module path; None for 'auto'
            inspect_prefix: str | None,
            auth_env_vars: list[str],
            metadata: dict | None,        # OAuth-only
        }

    The /petri picker consumes this directly.
    """
    manifest = load_manifest()
    spec = manifest.get_source(family)
    out: list[dict[str, Any]] = []
    for source in spec.allowed:
        entry: dict[str, Any] = {
            "family": family,
            "source": source,
            "is_default": source == spec.default,
            "is_suppressed": is_suppressed(family, source),
        }
        if source == AUTO_SOURCE:
            entry["available"] = True
            entry["adapter"] = None
            entry["inspect_prefix"] = None
            entry["auth_env_vars"] = []
            entry["metadata"] = None
        else:
            adapter = manifest.get_adapter(family, source)
            entry["available"] = is_adapter_available(family, source) and not is_suppressed(
                family, source
            )
            entry["adapter"] = adapter.module
            entry["inspect_prefix"] = adapter.inspect_prefix
            entry["auth_env_vars"] = list(adapter.auth_env_vars)
            entry["metadata"] = get_adapter_metadata(family, source)
        out.append(entry)
    return out


def resolve_credential_source(
    family: str,
    *,
    override: str | None = None,
) -> str:
    """Resolve the effective concrete source for ``family``.

    Never returns the ``auto`` sentinel — the caller always gets back a
    concrete adapter key it can pass to
    :func:`plugins.petri_audit.adapters.load_adapter_module`. Raises
    :class:`CredentialResolutionError` when no concrete source resolves.

    See module docstring for the full priority order.
    """
    manifest = load_manifest()
    spec = manifest.get_source(family)

    candidate = override or _settings_source(family) or spec.default

    if candidate != AUTO_SOURCE:
        if candidate not in spec.allowed:
            raise CredentialResolutionError(family, spec.allowed)
        if not is_suppressed(family, candidate):
            return candidate
        # Suppressed concrete request → fall through to auto expansion.

    # 'auto' expansion — iterate allowed in manifest order, skip auto +
    # suppressed, return the first that is available.
    for source in spec.allowed:
        if source == AUTO_SOURCE:
            continue
        if is_suppressed(family, source):
            continue
        if is_adapter_available(family, source):
            return source
    raise CredentialResolutionError(family, spec.allowed)


def _settings_source(family: str) -> str | None:
    """Read ``settings.{family}_credential_source`` lazily.

    Returns ``None`` when the setting is absent, empty, or 'auto'.
    Defensive against ``core.config`` import failure (e.g. test
    environments with a stubbed settings module) so this module never
    crashes the picker on a recoverable problem.
    """
    try:
        from core.config import settings
    except Exception:
        return None
    field = f"{family}_credential_source"
    value = getattr(settings, field, None)
    if isinstance(value, str) and value and value != AUTO_SOURCE:
        return value
    return None


def suppress_credential_source(family: str, source: str) -> None:
    """Disable a (family, source) pair for the rest of this process.

    Idempotent. Used when an OAuth token's first call fails (expired,
    revoked) so the run can fall through to the API-key path without
    a process restart. Cleared by :func:`clear_suppressions` (tests
    only — production never clears).
    """
    with _lock:
        _suppressed.add((family, source))


def is_suppressed(family: str, source: str) -> bool:
    return (family, source) in _suppressed


def clear_suppressions() -> None:
    """Drop all suppressions — used by tests."""
    with _lock:
        _suppressed.clear()
