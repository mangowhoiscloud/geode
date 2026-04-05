"""Claude Code OAuth Token Reader — managed credential reuse.

Reads OAuth tokens from Claude Code's secure storage (macOS Keychain or
~/.claude/.credentials.json) for use as Anthropic API credentials.

Pattern: OpenClaw ``managedBy: "codex-cli"`` — external CLI owns token
lifecycle; GEODE reads without persisting copies.

Token source priority:
  1. macOS Keychain: service="Claude Code-credentials"
  2. File fallback: ~/.claude/.credentials.json

Claude Code handles its own OAuth refresh. On expiry, GEODE re-reads
from storage to pick up the refreshed token.
"""

from __future__ import annotations

import json
import logging
import subprocess  # nosec B404
import sys
import threading
import time
from pathlib import Path
from typing import Any, TypedDict

log = logging.getLogger(__name__)

# -- Constants (match Claude Code & OpenClaw cli-credentials.ts) --
_KEYCHAIN_SERVICE = "Claude Code-credentials"
_CREDENTIALS_RELATIVE_PATH = ".claude/.credentials.json"
_CACHE_TTL_S = 900  # 15 min (OpenClaw EXTERNAL_CLI_SYNC_TTL_MS)


class ClaudeCodeCredentials(TypedDict, total=False):
    """Parsed Claude Code OAuth credentials."""

    access_token: str
    refresh_token: str
    expires_at: float  # Unix timestamp (ms from Keychain, converted to seconds)
    subscription_type: str  # "max", "pro", etc.
    rate_limit_tier: str


# -- Cache (with mtime fingerprint — OpenClaw sourceFingerprint pattern) --
_cache_lock = threading.Lock()
_cache: dict[str, Any] = {
    "value": None,
    "read_at": 0.0,
    "mtime": 0.0,
}


def _get_file_mtime() -> float:
    """Get mtime of credentials file (0.0 if not found)."""
    try:
        return (Path.home() / _CREDENTIALS_RELATIVE_PATH).stat().st_mtime
    except OSError:
        return 0.0


def _is_cache_valid() -> bool:
    # Called under _cache_lock
    if _cache["value"] is None:
        return False
    if (time.time() - _cache["read_at"]) >= _CACHE_TTL_S:
        return False
    current_mtime = _get_file_mtime()
    return not (current_mtime > 0 and current_mtime != _cache["mtime"])


def invalidate_cache() -> None:
    """Force next read to bypass cache."""
    with _cache_lock:
        _cache["value"] = None
        _cache["read_at"] = 0.0
        _cache["mtime"] = 0.0


# -- Keychain Reader (macOS only) --


def _read_from_keychain() -> dict[str, Any] | None:
    """Read claudeAiOauth from macOS Keychain.

    Equivalent to OpenClaw readClaudeCliKeychainCredentials().
    """
    try:
        result = subprocess.run(  # noqa: S603  # nosec B603,B607
            [  # noqa: S607  # nosec B607
                "security",
                "find-generic-password",
                "-s",
                _KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout.strip())
        return data.get("claudeAiOauth") if isinstance(data, dict) else None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
        log.debug("Keychain read failed: %s", exc)
        return None


# -- File Fallback Reader --


def _read_from_file() -> dict[str, Any] | None:
    """Read claudeAiOauth from ~/.claude/.credentials.json."""
    cred_path = Path.home() / _CREDENTIALS_RELATIVE_PATH
    try:
        raw = cred_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        return data.get("claudeAiOauth") if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


# -- Parser --


def _parse_oauth(raw: dict[str, Any]) -> ClaudeCodeCredentials | None:
    """Parse and validate claudeAiOauth dict.

    Mirrors OpenClaw parseClaudeCliOauthCredential() validation.
    """
    access_token = raw.get("accessToken")
    if not isinstance(access_token, str) or not access_token:
        return None

    expires_at = raw.get("expiresAt")
    if not isinstance(expires_at, (int, float)) or expires_at <= 0:
        return None

    # expiresAt from Keychain is in milliseconds; normalize to seconds
    if expires_at > 1e12:
        expires_at = expires_at / 1000.0

    result: ClaudeCodeCredentials = {
        "access_token": access_token,
        "expires_at": float(expires_at),
    }

    refresh_token = raw.get("refreshToken")
    if isinstance(refresh_token, str) and refresh_token:
        result["refresh_token"] = refresh_token

    sub_type = raw.get("subscriptionType")
    if isinstance(sub_type, str) and sub_type:
        result["subscription_type"] = sub_type

    rl_tier = raw.get("rateLimitTier")
    if isinstance(rl_tier, str) and rl_tier:
        result["rate_limit_tier"] = rl_tier

    return result


# -- Public API --


def read_claude_code_credentials(
    *,
    force_refresh: bool = False,
) -> ClaudeCodeCredentials | None:
    """Read Claude Code OAuth credentials (cached, TTL 15min).

    Priority: macOS Keychain → file fallback.
    Returns None if Claude Code is not logged in.
    """
    with _cache_lock:
        if not force_refresh and _is_cache_valid():
            cached: ClaudeCodeCredentials | None = _cache["value"]
            return cached

    # Read outside lock (I/O — Keychain/file)
    raw: dict[str, Any] | None = None
    if sys.platform == "darwin":
        raw = _read_from_keychain()
        if raw:
            log.debug("Claude Code credentials read from Keychain")

    if raw is None:
        raw = _read_from_file()
        if raw:
            log.debug("Claude Code credentials read from file")

    mtime = _get_file_mtime()
    parsed = _parse_oauth(raw) if raw else None

    with _cache_lock:
        _cache["value"] = parsed
        _cache["read_at"] = time.time()
        _cache["mtime"] = mtime

    if parsed:
        is_expired = time.time() > parsed["expires_at"]
        log.info(
            "Claude Code OAuth: subscription=%s expired=%s",
            parsed.get("subscription_type", "unknown"),
            is_expired,
        )
    return parsed


def refresh_claude_code_token(profile: Any) -> bool:
    """Re-read token from Claude Code's storage (managed refresh).

    Claude Code handles its own token refresh via OAuth. We just re-read
    from Keychain/file to pick up the refreshed token.

    Returns True if the token was updated, False otherwise.
    """
    creds = read_claude_code_credentials(force_refresh=True)
    if not creds:
        log.warning("Claude Code credentials unavailable for refresh")
        return False

    new_token = creds["access_token"]
    if new_token != profile.key:
        profile.key = new_token
        profile.expires_at = creds.get("expires_at", 0.0)
        log.info("Claude Code OAuth token refreshed (managed)")
        return True

    log.debug("Claude Code token unchanged after re-read")
    return False
