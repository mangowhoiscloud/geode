"""Codex CLI OAuth Token Reader — managed credential reuse for OpenAI.

Reads OAuth tokens from Codex CLI's storage (~/.codex/auth.json)
for use as OpenAI API credentials.

Pattern: OpenClaw ``managedBy: "codex-cli"`` — Codex CLI owns token
lifecycle; GEODE reads without persisting copies.

Token source: ~/.codex/auth.json
  { tokens: { access_token, refresh_token, account_id }, last_refresh }
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, TypedDict

from core.auth.credential_cache import CredentialCache, refresh_managed_token

log = logging.getLogger(__name__)

_CODEX_AUTH_PATH = ".codex/auth.json"

_cache = CredentialCache(_CODEX_AUTH_PATH)


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
    import base64

    parts = token.split(".")
    if len(parts) < 2:
        return None
    try:
        # Add padding for base64url
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = payload.get("exp")
        if isinstance(exp, (int, float)) and exp > 0:
            return float(exp)
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        pass
    return None


def _read_from_file() -> dict[str, Any] | None:
    """Read tokens from ~/.codex/auth.json."""
    auth_path = Path.home() / _CODEX_AUTH_PATH
    try:
        raw = auth_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict) and "tokens" in data:
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return None


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
    hit, cached = _cache.get_if_valid(force_refresh=force_refresh)
    if hit:
        result_cached: CodexCliCredentials | None = cached
        return result_cached

    # Read outside lock (file I/O)
    data = _read_from_file()
    mtime = _cache.get_file_mtime()
    parsed = _parse_codex_credentials(data) if data else None
    _cache.update(parsed, mtime)

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
