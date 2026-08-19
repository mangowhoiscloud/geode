"""Claude CLI OAuth credential and subscription metadata resolution."""

from __future__ import annotations

import json
import logging
import platform
import subprocess
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "get_claude_oauth_metadata",
    "is_claude_oauth_available",
    "resolve_claude_oauth_token",
]


def _resolve_keychain_service() -> str:
    """Resolve the macOS keychain entry name for Anthropic OAuth.

    Priority — env var ``GEODE_ANTHROPIC_KEYCHAIN_SERVICE`` (per-process
    override) → ``[credentials.keychain] anthropic`` in
    ``core/config/routing.toml`` → legacy default ``"Claude Code-credentials"``.

    P2-C (2026-05-17): migrated from a hardcoded module-level constant
    so users can rebind the entry name (e.g. when running multiple
    Claude accounts side-by-side) by editing ``~/.geode/routing.toml``.
    """
    import os

    env = os.environ.get("GEODE_ANTHROPIC_KEYCHAIN_SERVICE")
    if env:
        return env
    try:
        from core.config.routing_manifest import load_routing_manifest

        manifest = load_routing_manifest()
    except Exception:
        return "Claude Code-credentials"
    return manifest.credential_keychain.services.get("anthropic", "Claude Code-credentials")


KEYCHAIN_SERVICE = _resolve_keychain_service()
"""macOS keychain entry written by ``claude /login``. Contains the
JSON ``{"claudeAiOauth": {"accessToken": ..., "refreshToken": ...,
"expiresAt": ..., "scopes": [...], "subscriptionType": ..., ...}}``
blob — the same row the CLI itself reads on startup. The
``subscriptionType`` field carries whichever plan the user is logged
into (e.g. ``pro``, ``max``); the picker UI surfaces that verbatim so
this module does not need to know the enumeration ahead of time.

P2-C: now resolved at import time via :func:`_resolve_keychain_service`
so the env override / manifest entry / legacy default cascade applies."""


def _read_keychain_blob() -> dict[str, Any] | None:
    """Return the parsed ``claudeAiOauth`` dict from the macOS keychain.

    Returns ``None`` when the platform is not macOS, the ``security``
    binary is missing, the keychain entry does not exist, or the
    stored JSON is malformed. No exception is raised — callers
    fall back to ``ANTHROPIC_API_KEY`` or trigger ``inspect_ai``'s
    standard "missing credential" error.
    """
    # ``platform.system()`` is preferred over ``sys.platform`` here because
    # mypy narrows ``sys.platform`` based on its ``--platform`` setting and
    # marks the subsequent subprocess block as unreachable on the CI runner.
    if platform.system() != "Darwin":
        log.debug("claude CLI credentials: macOS-only keychain path; got %s", platform.system())
        return None
    try:
        proc = subprocess.run(  # noqa: S603  # nosec — argv built from module constants
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        log.debug("claude CLI credentials: `security` invocation failed", exc_info=True)
        return None
    if proc.returncode != 0:
        log.debug(
            "claude CLI credentials: keychain entry '%s' missing (rc=%d)",
            KEYCHAIN_SERVICE,
            proc.returncode,
        )
        return None
    try:
        blob = json.loads(proc.stdout.strip())
        inner = blob["claudeAiOauth"]
    except (json.JSONDecodeError, KeyError, TypeError):
        log.debug("claude CLI credentials: keychain blob malformed", exc_info=True)
        return None
    if not isinstance(inner, dict):
        return None
    return inner


def _read_authtoml_anthropic_creds() -> dict[str, Any] | None:
    """Lazy import of :mod:`core.auth.oauth_login` so the audit plugin
    stays loadable when the optional [audit] extra is absent.

    Returns the GEODE-owned Anthropic OAuth credentials when the
    ``/login anthropic`` PKCE flow (PR C3) has been completed and the
    resulting token is still inside its expiry window. ``None`` for
    every miss path (no credentials, expired, or import failure).
    """
    try:
        from core.auth.oauth_login import read_geode_anthropic_credentials
    except ImportError:
        return None
    try:
        return read_geode_anthropic_credentials()
    except Exception:
        log.debug("claude CLI credentials: auth.toml read failed", exc_info=True)
        return None


def resolve_claude_oauth_token() -> str | None:
    """Return the OAuth access token, preferring the GEODE-owned source.

    Resolution order:

    1. ``~/.geode/auth.toml`` ``providers.anthropic`` (PR C3 PKCE flow).
       Cross-platform, GEODE-owned SOT.
    2. macOS keychain ``Claude Code-credentials`` (PR #1202 fallback).
       Backwards-compat for users who still have the keychain entry
       written by the legacy ``claude /login`` subprocess.

    Returns ``None`` when neither source resolves a valid ``sk-ant-``
    prefixed token.
    """
    authtoml_creds = _read_authtoml_anthropic_creds()
    if authtoml_creds:
        token = authtoml_creds.get("access_token")
        if isinstance(token, str) and token.startswith("sk-ant-"):
            return token

    # Fall back to the macOS keychain (legacy PR #1202 path).
    blob = _read_keychain_blob()
    if blob is None:
        return None
    token = blob.get("accessToken")
    if not isinstance(token, str) or not token.startswith("sk-ant-"):
        log.debug("claude CLI credentials: token shape unexpected")
        return None
    return token


def get_claude_oauth_metadata() -> dict[str, Any] | None:
    """Return subscription metadata for the picker UI.

    Same resolution order as :func:`resolve_claude_oauth_token` — auth.
    toml first (PR C3, owned), keychain fallback (PR #1202, borrowed).
    The shape stays uniform so the picker can render either source
    transparently:

    - ``subscription_type``: plan name from the credential blob
      (auth.toml's PKCE flow does not return one; falls back to a
      "(via PKCE)" placeholder so the picker still has a non-empty
      label).
    - ``rate_limit_tier``: only present in the keychain blob.
    - ``scopes``: token scopes (both sources surface this).
    - ``expires_at``: unix epoch (seconds for auth.toml, millis for
      keychain — normalised to seconds at the call site).
    """
    # Prefer GEODE-owned auth.toml when present.
    authtoml_creds = _read_authtoml_anthropic_creds()
    if authtoml_creds:
        return {
            "subscription_type": None,  # PKCE flow does not return plan
            "rate_limit_tier": None,
            "scopes": list(authtoml_creds.get("scopes") or []),
            "expires_at": authtoml_creds.get("expires_at"),
            "source": "auth.toml",
        }

    blob = _read_keychain_blob()
    if blob is None or not isinstance(blob.get("accessToken"), str):
        return None
    return {
        "subscription_type": blob.get("subscriptionType"),
        "rate_limit_tier": blob.get("rateLimitTier"),
        "scopes": list(blob.get("scopes", [])),
        "expires_at": blob.get("expiresAt"),
        "source": "keychain",
    }


def is_claude_oauth_available() -> bool:
    """Read-only check — does not pin or cache the token. Used by the
    ``/auth`` picker (PR B) and ``geode_product.petri_audit.models.
    to_inspect_model`` to auto-select the OAuth path when available."""
    return resolve_claude_oauth_token() is not None
