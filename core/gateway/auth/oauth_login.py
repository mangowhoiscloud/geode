"""OAuth login flows — `/login openai` device code flow.

Grounded from Hermes Agent hermes_cli/auth.py:3054-3196.
Stores credentials in ~/.geode/auth.json (unified auth store).
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# OpenAI Codex OAuth constants (from Hermes Agent)
_ISSUER = "https://auth.openai.com"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_TOKEN_URL = f"{_ISSUER}/oauth/token"
_DEVICE_CODE_URL = f"{_ISSUER}/api/accounts/deviceauth/usercode"
_DEVICE_TOKEN_URL = f"{_ISSUER}/api/accounts/deviceauth/token"
_DEVICE_CALLBACK = f"{_ISSUER}/deviceauth/callback"
_DEVICE_PAGE = f"{_ISSUER}/codex/device"
_MAX_WAIT_S = 15 * 60  # 15 minutes

# Auth store path
AUTH_STORE_PATH = Path.home() / ".geode" / "auth.json"


def _load_auth_store() -> dict[str, Any]:
    """Load ~/.geode/auth.json. Returns empty dict if not found."""
    if not AUTH_STORE_PATH.exists():
        return {"version": 1, "providers": {}}
    try:
        data = json.loads(AUTH_STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"version": 1, "providers": {}}
        return data
    except (json.JSONDecodeError, OSError):
        return {"version": 1, "providers": {}}


def _save_auth_store(data: dict[str, Any]) -> None:
    """Save ~/.geode/auth.json with 0o600 permissions."""
    AUTH_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    AUTH_STORE_PATH.chmod(0o600)


def login_openai() -> dict[str, Any]:
    """Run OpenAI Codex device code OAuth flow.

    Returns credential dict on success, raises on failure.
    Grounded from Hermes _codex_device_code_login().
    """
    import httpx

    # Step 1: Request device code
    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                _DEVICE_CODE_URL,
                json={"client_id": _CLIENT_ID},
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:
        raise RuntimeError(f"Failed to request device code: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"Device code request returned status {resp.status_code}")

    device_data = resp.json()
    user_code = device_data.get("user_code", "")
    device_auth_id = device_data.get("device_auth_id", "")
    poll_interval = max(3, int(device_data.get("interval", "5")))

    if not user_code or not device_auth_id:
        raise RuntimeError("Device code response missing required fields")

    # Step 2: Show user the code
    print("\n  OpenAI Codex OAuth Login\n")
    print("  1. Open this URL in your browser:")
    print(f"     \033[94m{_DEVICE_PAGE}\033[0m\n")
    print("  2. Enter this code:")
    print(f"     \033[1;93m{user_code}\033[0m\n")
    print("  Waiting for sign-in... (press Ctrl+C to cancel)\n")

    # Step 3: Poll for authorization
    start = time.monotonic()
    code_resp = None

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            while time.monotonic() - start < _MAX_WAIT_S:
                time.sleep(poll_interval)
                poll_resp = client.post(
                    _DEVICE_TOKEN_URL,
                    json={"device_auth_id": device_auth_id, "user_code": user_code},
                    headers={"Content-Type": "application/json"},
                )
                if poll_resp.status_code == 200:
                    code_resp = poll_resp.json()
                    break
                if poll_resp.status_code in (403, 404):
                    elapsed = int(time.monotonic() - start)
                    print(f"\r  Waiting... ({elapsed}s)", end="", flush=True)
                    continue
                raise RuntimeError(f"Polling returned status {poll_resp.status_code}")
    except KeyboardInterrupt:
        print("\n\n  Login cancelled.")
        return {}

    if code_resp is None:
        raise RuntimeError("Login timed out after 15 minutes")

    # Step 4: Exchange authorization code for tokens
    authorization_code = code_resp.get("authorization_code", "")
    code_verifier = code_resp.get("code_verifier", "")

    if not authorization_code or not code_verifier:
        raise RuntimeError("Device auth response missing authorization_code or code_verifier")

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            token_resp = client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": _DEVICE_CALLBACK,
                    "client_id": _CLIENT_ID,
                    "code_verifier": code_verifier,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except Exception as exc:
        raise RuntimeError(f"Token exchange failed: {exc}") from exc

    if token_resp.status_code != 200:
        raise RuntimeError(f"Token exchange returned status {token_resp.status_code}")

    tokens = token_resp.json()
    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")

    if not access_token:
        raise RuntimeError("Token exchange did not return an access_token")

    # Extract account info from JWT
    account_id = ""
    email = ""
    plan_type = ""
    try:
        import base64

        parts = access_token.split(".")
        if len(parts) >= 2:
            padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded))
            auth_claim = payload.get("https://api.openai.com/auth", {})
            profile_claim = payload.get("https://api.openai.com/profile", {})
            account_id = auth_claim.get("chatgpt_account_id", "")
            plan_type = auth_claim.get("chatgpt_plan_type", "")
            email = profile_claim.get("email", "")
            exp = payload.get("exp", 0)
    except Exception:
        exp = 0

    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    creds = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "account_id": account_id,
        "email": email,
        "plan_type": plan_type,
        "expires_at": exp,
        "last_refresh": now_iso,
        "source": "geode-device-code",
    }

    # Save to ~/.geode/auth.json
    store = _load_auth_store()
    store.setdefault("providers", {})
    store["providers"]["openai"] = creds
    _save_auth_store(store)

    print("\n  \033[92mLogin successful!\033[0m")
    print(f"  Account: {email or account_id}")
    print(f"  Plan: {plan_type or 'unknown'}")
    print(f"  Stored: {AUTH_STORE_PATH}\n")

    return creds


def get_auth_status() -> list[dict[str, Any]]:
    """Get status of all stored OAuth credentials."""
    results: list[dict[str, Any]] = []
    store = _load_auth_store()

    for provider, creds in store.get("providers", {}).items():
        expires_at = creds.get("expires_at", 0)
        remaining = expires_at - time.time() if expires_at else 0
        results.append(
            {
                "provider": provider,
                "email": creds.get("email", ""),
                "plan_type": creds.get("plan_type", ""),
                "source": creds.get("source", ""),
                "expires_in": f"{remaining / 3600:.1f}h" if remaining > 0 else "expired",
                "status": "active" if remaining > 0 else "expired",
            }
        )

    # Also check external CLI tokens
    try:
        from core.gateway.auth.codex_cli_oauth import read_codex_cli_credentials

        codex_creds = read_codex_cli_credentials()
        if codex_creds:
            remaining = codex_creds["expires_at"] - time.time()
            results.append(
                {
                    "provider": "openai (codex-cli)",
                    "email": "",
                    "plan_type": "",
                    "source": "~/.codex/auth.json",
                    "expires_in": f"{remaining / 3600:.1f}h" if remaining > 0 else "expired",
                    "status": "active" if remaining > 0 else "expired",
                }
            )
    except Exception:
        log.debug("External CLI token check failed", exc_info=True)

    return results


def read_geode_openai_credentials() -> dict[str, Any] | None:
    """Read OpenAI credentials from ~/.geode/auth.json.

    Returns None if not found or expired.
    """
    store = _load_auth_store()
    creds = store.get("providers", {}).get("openai")
    if not creds:
        return None

    access_token = creds.get("access_token", "")
    if not access_token:
        return None

    expires_at = creds.get("expires_at", 0)
    if expires_at and time.time() > expires_at:
        log.info("GEODE auth.json OpenAI token expired")
        return None

    return {
        "access_token": access_token,
        "refresh_token": creds.get("refresh_token", ""),
        "expires_at": float(expires_at),
        "account_id": creds.get("account_id", ""),
    }
