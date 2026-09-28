"""Codex CLI OAuth Token Reader — managed credential reuse for OpenAI.

Reads OAuth tokens from Codex CLI's storage (~/.codex/auth.json)
for use as OpenAI API credentials.

Pattern: OpenClaw ``managedBy: "codex-cli"`` — Codex CLI owns token
lifecycle; GEODE reads without persisting copies.

Token source: ~/.codex/auth.json
  { tokens: { access_token, refresh_token, account_id }, last_refresh }
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from core.auth.credential_cache import (
    CredentialCache,
    read_json_credentials_file,
    refresh_managed_token,
)
from core.auth.jwt_claims import decode_jwt_claims

if TYPE_CHECKING:
    from core.auth.profiles import ProfileStore

log = logging.getLogger(__name__)
_profile_sync_lock = threading.Lock()


def codex_auth_path() -> Path:
    """Resolve the Codex CLI credential under ``$CODEX_HOME`` or ``~/.codex``."""

    configured = os.environ.get("CODEX_HOME", "").strip()
    root = Path(configured).expanduser().resolve() if configured else Path.home() / ".codex"
    return root / "auth.json"


_cache = CredentialCache(codex_auth_path)


class CodexCliCredentials(TypedDict, total=False):
    """Parsed Codex CLI OAuth credentials."""

    access_token: str
    refresh_token: str
    expires_at: float  # seconds
    account_id: str


def invalidate_cache() -> None:
    """Force next read to bypass cache."""
    _cache.invalidate()


def _decode_jwt_expiry(token: str) -> float | None:
    """Decode exp claim from JWT access token (seconds)."""
    exp = decode_jwt_claims(token).get("exp")
    return float(exp) if isinstance(exp, (int, float)) and exp > 0 else None


def _read_from_file() -> dict[str, Any] | None:
    """Read tokens from the resolved Codex CLI credential path."""
    data = read_json_credentials_file(codex_auth_path())
    return data if data is not None and "tokens" in data else None


def _parse_codex_credentials(data: dict[str, Any]) -> CodexCliCredentials | None:
    """Parse and validate Codex CLI auth.json.

    Mirrors OpenClaw readCodexKeychainCredentials() / readCodexCliCredentials().
    """
    tokens = data.get("tokens")
    if not isinstance(tokens, dict):
        return None

    access_token = tokens.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        return None

    refresh_token = tokens.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        return None

    # Expiry: decode from JWT, or fallback to last_refresh + 1h
    expires = _decode_jwt_expiry(access_token)
    if expires is None:
        last_refresh = data.get("last_refresh")
        if isinstance(last_refresh, str):
            try:
                from datetime import datetime

                dt = datetime.fromisoformat(last_refresh.replace("Z", "+00:00"))
                expires = dt.timestamp() + 3600
            except (ValueError, TypeError):
                expires = time.time() + 3600
        else:
            expires = time.time() + 3600

    result: CodexCliCredentials = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires,
    }

    account_id = tokens.get("account_id")
    if isinstance(account_id, str) and account_id:
        result["account_id"] = account_id

    return result


def read_codex_cli_credentials(
    *,
    force_refresh: bool = False,
) -> CodexCliCredentials | None:
    """Read Codex CLI OAuth credentials (cached, TTL 15min).

    Returns None if Codex CLI is not logged in.
    """

    def read() -> CodexCliCredentials | None:
        data = _read_from_file()
        return _parse_codex_credentials(data) if data else None

    parsed: CodexCliCredentials | None = _cache.read(read, force_refresh=force_refresh)

    if parsed:
        is_expired = time.time() > parsed["expires_at"]
        log.info(
            "Codex CLI OAuth: account=%s expired=%s",
            parsed.get("account_id", "unknown"),
            is_expired,
        )
    return parsed


def refresh_codex_cli_token(profile: Any) -> bool:
    """Re-read token from Codex CLI's storage (managed refresh)."""
    return refresh_managed_token("Codex CLI", read_codex_cli_credentials, profile)


def sync_codex_cli_profile(
    store: ProfileStore | None, *, force_refresh: bool = False
) -> CodexCliCredentials | None:
    """Refresh only the external owner's profiles before selecting a request account."""
    from core.auth.profiles import AuthProfile, CredentialType

    with _profile_sync_lock:
        creds = read_codex_cli_credentials(force_refresh=force_refresh)
        if store is None:
            return creds
        imported = [
            profile
            for profile in store.list_by_provider("openai-codex")
            if profile.managed_by == "codex-cli"
        ]
        if not creds:
            for profile in imported:
                if store.get(profile.name) is profile:
                    store.remove(profile.name)
            return None
        if not imported:
            name = "openai-codex:codex-cli"
            # A native profile with this name belongs to a different owner.
            if store.get(name) is not None:
                return creds
            imported = [
                AuthProfile(name, "openai-codex", CredentialType.OAUTH, managed_by="codex-cli")
            ]
        for profile in imported:
            # Replacement preserves references already borrowed by an in-flight call.
            refreshed = replace(
                profile,
                key=creds["access_token"],
                refresh_token=creds.get("refresh_token", ""),
                expires_at=creds.get("expires_at", 0.0),
                metadata={**profile.metadata, "account_id": creds.get("account_id", "")},
            )
            if refreshed != profile:
                store.add(refreshed)
        return creds
