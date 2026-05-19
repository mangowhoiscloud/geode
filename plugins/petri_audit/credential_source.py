"""Per-provider credential source enumeration + resolution + suppression.

Centralises the "which credential should I use for *this* provider right
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
2. ``settings.{provider}_credential_source`` if it carries an explicit
   non-auto value (e.g. ``ANTHROPIC_CREDENTIAL_SOURCE=api_key``).
3. Manifest ``[petri.source.<provider>].default`` if not auto.
4. Manifest ``[petri.source.<provider>].allowed`` order — first non-auto,
   non-suppressed, *available* source wins. Manifest ordering is the
   intent — keep OAuth first so the autoresearch self-improving loop hits
   subscription quota by default; API-key fallback still resolves when
   the user has only ``ANTHROPIC_API_KEY`` set.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from plugins.petri_audit.adapters import (
    get_adapter_metadata,
    is_adapter_available,
)
from plugins.petri_audit.manifest import AUTO_SOURCE, load_manifest

log = logging.getLogger(__name__)

__all__ = [
    "PAYG_SOURCE",
    "CredentialResolutionError",
    "clear_suppressions",
    "is_suppressed",
    "list_credential_sources",
    "resolve_credential_source",
    "self_improving_loop_fallback_policy",
    "suppress_credential_source",
]


_lock = threading.Lock()
_suppressed: set[tuple[str, str]] = set()


PAYG_SOURCE = "api_key"
"""The conventional name for any pay-as-you-go credential source.

Every provider in the Petri manifest has ``api_key`` as its PAYG entry
(``anthropic.api_key``, ``openai.api_key``, ``zhipuai.api_key``).
``resolve_credential_source(fallback_to_payg=False)`` filters this
source out so a subscription run never silently bills the user's API
key after OAuth quota exhaustion. See
``docs/plans/2026-05-19-self-improving-loop-config-consolidation.md`` Phase β.
"""


class CredentialResolutionError(RuntimeError):
    """Raised when no credential source resolves for a provider.

    Carries ``provider``, the ``allowed`` set, and an optional
    ``subscription_only`` flag so callers (e.g. the /petri picker, the
    FE banner) can render an actionable error instead of a bare
    traceback. The default message is Stripe-style (cause + remedy +
    docs) and mentions ``[self_improving_loop] fallback_to_payg = true`` as the
    explicit opt-in.
    """

    def __init__(
        self,
        provider: str,
        allowed: list[str],
        *,
        subscription_only: bool = False,
    ):
        self.provider = provider
        self.allowed = allowed
        self.subscription_only = subscription_only
        if subscription_only:
            super().__init__(
                f"provider={provider}: no subscription credential source available "
                f"(allowed={allowed}, PAYG fallback blocked by [self_improving_loop] "
                f"fallback_to_payg=false).\n"
                f"\n"
                f"To continue NOW, do one of:\n"
                f"  1. Wait until the subscription quota resets.\n"
                f"  2. Enable PAYG fallback (will incur cost):\n"
                f"     ~/.geode/config.toml:\n"
                f"       [self_improving_loop]\n"
                f"       fallback_to_payg = true\n"
                f"  3. Pin a different source in [self_improving_loop.petri.<role>] "
                f'with source = "api_key".\n'
            )
        else:
            super().__init__(
                f"provider={provider}: no credential source available "
                f"(allowed={allowed}); set an env var from the picker or "
                f"adjust settings.{provider}_credential_source"
            )


def list_credential_sources(provider: str) -> list[dict[str, Any]]:
    """Enumerate credential sources for a provider with current status.

    One entry per allowed source. Shape::

        {
            provider: str,
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
    spec = manifest.get_source(provider)
    out: list[dict[str, Any]] = []
    for source in spec.allowed:
        entry: dict[str, Any] = {
            "provider": provider,
            "source": source,
            "is_default": source == spec.default,
            "is_suppressed": is_suppressed(provider, source),
        }
        if source == AUTO_SOURCE:
            entry["available"] = True
            entry["adapter"] = None
            entry["inspect_prefix"] = None
            entry["auth_env_vars"] = []
            entry["metadata"] = None
        else:
            adapter = manifest.get_adapter(provider, source)
            entry["available"] = is_adapter_available(provider, source) and not is_suppressed(
                provider, source
            )
            entry["adapter"] = adapter.module
            entry["inspect_prefix"] = adapter.inspect_prefix
            entry["auth_env_vars"] = list(adapter.auth_env_vars)
            entry["metadata"] = get_adapter_metadata(provider, source)
        out.append(entry)
    return out


def self_improving_loop_fallback_policy() -> bool:
    """Read the ``[self_improving_loop] fallback_to_payg`` flag from config.toml.

    Default ``True`` preserves pre-2026-05-19 behaviour. Production
    Petri call sites (``registry.get_binding`` / ``models.to_inspect_model``)
    invoke this helper to thread the flag into
    :func:`resolve_credential_source` without each call site needing
    to import ``core.config.self_improving_loop`` directly.

    Lazy import so this module stays usable in test contexts that
    stub ``core.config``.
    """
    try:
        from core.config.self_improving_loop import load_self_improving_loop_config
    except ImportError:
        return True
    try:
        return load_self_improving_loop_config().fallback_to_payg
    except Exception:
        log.warning(
            "self-improving-loop config load failed; defaulting to fallback_to_payg=True",
            exc_info=True,
        )
        return True


def resolve_credential_source(
    provider: str,
    *,
    override: str | None = None,
    fallback_to_payg: bool = True,
) -> str:
    """Resolve the effective concrete source for ``provider``.

    Never returns the ``auto`` sentinel — the caller always gets back a
    concrete adapter key it can pass to
    :func:`plugins.petri_audit.adapters.load_adapter_module`. Raises
    :class:`CredentialResolutionError` when no concrete source resolves.

    Args:
        provider: provider name (anthropic / openai / zhipuai).
        override: explicit source request; bypasses both auto resolution
            and the ``fallback_to_payg`` filter (the caller is taking
            responsibility for the choice).
        fallback_to_payg: when ``False``, the ``api_key`` source is
            filtered out of auto expansion so subscription-only runs
            cannot silently fall through to PAYG. The first OAuth-like
            source's availability is now load-bearing; if it fails, a
            ``CredentialResolutionError(subscription_only=True)`` is
            raised with an actionable message. Default ``True`` keeps
            the pre-2026-05-19 behaviour for back-compat callers.

    See module docstring for the full priority order.
    """
    manifest = load_manifest()
    spec = manifest.get_source(provider)

    candidate = override or _settings_source(provider) or spec.default

    if candidate != AUTO_SOURCE:
        if candidate not in spec.allowed:
            raise CredentialResolutionError(provider, spec.allowed)
        # Strict mode also blocks a PAYG-default manifest entry (e.g.
        # zhipuai whose manifest default is ``api_key``). Explicit
        # ``override`` is unaffected — caller takes responsibility.
        if not fallback_to_payg and override is None and candidate == PAYG_SOURCE:
            raise CredentialResolutionError(
                provider,
                spec.allowed,
                subscription_only=True,
            )
        if not is_suppressed(provider, candidate):
            return candidate
        # Suppressed concrete request → fall through to auto expansion.

    # 'auto' expansion — iterate allowed in manifest order, skip auto +
    # suppressed, return the first that is available.
    for source in spec.allowed:
        if source == AUTO_SOURCE:
            continue
        if not fallback_to_payg and source == PAYG_SOURCE:
            continue
        if is_suppressed(provider, source):
            continue
        if is_adapter_available(provider, source):
            return source
    raise CredentialResolutionError(
        provider,
        spec.allowed,
        subscription_only=not fallback_to_payg,
    )


def _settings_source(provider: str) -> str | None:
    """Read ``settings.{provider}_credential_source`` lazily.

    Returns ``None`` when the setting is absent, empty, or 'auto'.
    Defensive against ``core.config`` import failure (e.g. test
    environments with a stubbed settings module) so this module never
    crashes the picker on a recoverable problem.

    Legacy alias: settings historically used the value ``"oauth"`` to
    mean "use the provider's OAuth path". The manifest spells the OAuth
    source as ``claude-cli`` / ``openai-codex`` per provider. We map
    here so existing .env / config.toml files keep working without
    rewrites.
    """
    try:
        from core.config import settings
    except Exception:
        return None
    field = f"{provider}_credential_source"
    value = getattr(settings, field, None)
    if not isinstance(value, str) or not value or value == AUTO_SOURCE:
        return None
    if value == "oauth":
        return _LEGACY_OAUTH_ALIAS.get(provider, value)
    return value


_LEGACY_OAUTH_ALIAS = {
    "anthropic": "claude-cli",
    "openai": "openai-codex",
}


def suppress_credential_source(provider: str, source: str) -> None:
    """Disable a (provider, source) pair for the rest of this process.

    Idempotent. Used when an OAuth token's first call fails (expired,
    revoked) so the run can fall through to the API-key path without
    a process restart. Cleared by :func:`clear_suppressions` (tests
    only — production never clears).
    """
    with _lock:
        _suppressed.add((provider, source))


def is_suppressed(provider: str, source: str) -> bool:
    return (provider, source) in _suppressed


def clear_suppressions() -> None:
    """Drop all suppressions — used by tests."""
    with _lock:
        _suppressed.clear()
