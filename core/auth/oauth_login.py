"""OAuth login flows — `/login oauth openai` device code flow.

Grounded from Hermes Agent hermes_cli/auth.py:3054-3196.

v0.50.2: Stores credentials in ``~/.geode/auth.toml`` (the v0.50.0 SOT)
as an ``OAUTH_BORROWED`` Plan + Profile pair. The legacy
``~/.geode/auth.json`` file is auto-absorbed on first read and renamed
to ``auth.json.migrated.bak`` so we don't keep two stores in sync.
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

# Legacy auth store path — kept only for one-shot migration into auth.toml.
LEGACY_AUTH_STORE_PATH = Path.home() / ".geode" / "auth.json"
# Backwards-compat alias — some external callers imported this name.
AUTH_STORE_PATH = LEGACY_AUTH_STORE_PATH

# Plan ID we use for any OAuth token GEODE itself issued (vs. external
# managed CLIs like ~/.codex/auth.json which keep their own SOT).
_GEODE_OPENAI_PLAN_ID = "openai-codex-geode"


def _migrate_legacy_auth_json_if_present() -> dict[str, Any]:
    """One-shot migration of pre-v0.50.2 ``~/.geode/auth.json``.

    Returns the parsed legacy payload (so callers can immediately seed the
    Plan registry with it) and renames the file to ``.migrated.bak`` so
    subsequent boots skip the work. Empty dict on no-op.
    """
    if not LEGACY_AUTH_STORE_PATH.exists():
        return {}
    try:
        raw = json.loads(LEGACY_AUTH_STORE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
    except (json.JSONDecodeError, OSError):
        log.warning("Legacy auth.json unreadable; skipping migration")
        return {}

    bak_path = LEGACY_AUTH_STORE_PATH.with_suffix(".json.migrated.bak")
    try:
        LEGACY_AUTH_STORE_PATH.rename(bak_path)
        log.info("Migrated legacy auth.json → %s (one-shot)", bak_path)
    except OSError:
        log.warning("Could not rename %s; leaving in place", LEGACY_AUTH_STORE_PATH)
    return raw


def _persist_oauth_to_authtoml(creds: dict[str, Any]) -> None:
    """Write Codex device-code creds into ``~/.geode/auth.toml`` SOT."""
    try:
        from core.auth.auth_toml import save_auth_toml
        from core.auth.plan_registry import get_plan_registry
        from core.auth.plans import Plan, PlanKind
        from core.auth.profiles import AuthProfile, CredentialType
        from core.lifecycle.container import ensure_profile_store
    except Exception:  # pragma: no cover — import-time defensive
        log.debug("auth.toml persistence skipped — Plan modules unavailable")
        return

    registry = get_plan_registry()
    plan = registry.get(_GEODE_OPENAI_PLAN_ID) or Plan(
        id=_GEODE_OPENAI_PLAN_ID,
        provider="openai-codex",
        kind=PlanKind.OAUTH_BORROWED,
        display_name="OpenAI Codex (GEODE OAuth)",
        base_url="https://chatgpt.com/backend-api/codex",
        auth_type="oauth_external",
        subscription_tier=str(creds.get("plan_type") or "") or None,
    )
    registry.add(plan)

    store = ensure_profile_store()
    profile_name = f"{plan.id}:user"
    expires_at = float(creds.get("expires_at", 0.0) or 0.0)
    existing = store.get(profile_name)
    if existing is not None:
        existing.key = str(creds.get("access_token", ""))
        existing.refresh_token = str(creds.get("refresh_token", ""))
        existing.expires_at = expires_at
        existing.plan_id = plan.id
        existing.error_count = 0
        existing.cooldown_until = 0.0
        existing.metadata.update(
            {
                "account_id": creds.get("account_id", ""),
                "email": creds.get("email", ""),
                "plan_type": creds.get("plan_type", ""),
                "source": "geode-device-code",
            }
        )
    else:
        store.add(
            AuthProfile(
                name=profile_name,
                provider=plan.provider,
                credential_type=CredentialType.OAUTH,
                key=str(creds.get("access_token", "")),
                refresh_token=str(creds.get("refresh_token", "")),
                expires_at=expires_at,
                plan_id=plan.id,
                metadata={
                    "account_id": creds.get("account_id", ""),
                    "email": creds.get("email", ""),
                    "plan_type": creds.get("plan_type", ""),
                    "source": "geode-device-code",
                },
            )
        )
    save_auth_toml()


def _load_auth_store() -> dict[str, Any]:
    """Read OAuth credentials, preferring auth.toml but falling back to legacy.

    On first call after upgrade we still see ``~/.geode/auth.json``: parse
    it once, write its `providers.openai` entry into auth.toml, and rename
    the legacy file so the next read goes through the new SOT only.
    """
    legacy = _migrate_legacy_auth_json_if_present()
    if legacy:
        openai_creds = legacy.get("providers", {}).get("openai")
        if isinstance(openai_creds, dict) and openai_creds.get("access_token"):
            try:
                _persist_oauth_to_authtoml(openai_creds)
            except Exception:
                log.warning("Failed to persist legacy OAuth creds to auth.toml", exc_info=True)
        return legacy if isinstance(legacy, dict) else {"version": 1, "providers": {}}

    # Re-build a json-shaped view from the auth.toml SOT for legacy callers
    # like get_auth_status().
    try:
        from core.auth.plan_registry import get_plan_registry
        from core.lifecycle.container import ensure_profile_store
    except Exception:  # pragma: no cover
        return {"version": 1, "providers": {}}

    registry = get_plan_registry()
    plan = registry.get(_GEODE_OPENAI_PLAN_ID)
    store = ensure_profile_store()
    profile = store.get(f"{_GEODE_OPENAI_PLAN_ID}:user") if plan else None
    if profile is None:
        return {"version": 1, "providers": {}}
    md = profile.metadata or {}
    return {
        "version": 1,
        "providers": {
            "openai": {
                "access_token": profile.key,
                "refresh_token": profile.refresh_token,
                "expires_at": profile.expires_at,
                "account_id": md.get("account_id", ""),
                "email": md.get("email", ""),
                "plan_type": md.get("plan_type", ""),
                "source": md.get("source", "geode-device-code"),
            }
        },
    }


def _save_auth_store(data: dict[str, Any]) -> None:
    """Persist Codex OAuth creds via ``~/.geode/auth.toml`` (v0.50.2 SOT).

    Kept for backwards-compatible call sites — extracts the openai entry
    and routes it through the Plan registry.
    """
    creds = (data or {}).get("providers", {}).get("openai") or {}
    if creds.get("access_token"):
        _persist_oauth_to_authtoml(creds)


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

    # Step 2: Surface the code to the user via IPC events (v0.51.1).
    # The thin-client renderer translates these into an in-place rich prompt.
    from core.ui.agentic_ui import (
        emit_oauth_login_failed,
        emit_oauth_login_pending,
        emit_oauth_login_started,
    )

    _PROVIDER_LABEL = "OpenAI Codex"
    emit_oauth_login_started(
        provider=_PROVIDER_LABEL,
        verification_uri=_DEVICE_PAGE,
        user_code=user_code,
    )

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
                    emit_oauth_login_pending(_PROVIDER_LABEL, elapsed)
                    continue
                raise RuntimeError(f"Polling returned status {poll_resp.status_code}")
    except KeyboardInterrupt:
        emit_oauth_login_failed(_PROVIDER_LABEL, "cancelled by user")
        return {}

    if code_resp is None:
        emit_oauth_login_failed(_PROVIDER_LABEL, "timed out after 15 minutes")
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

    # Save to ~/.geode/auth.toml (v0.50.2 SOT — _save_auth_store internally
    # routes via auth_toml.save_auth_toml + plan registry).
    store = _load_auth_store()
    store.setdefault("providers", {})
    store["providers"]["openai"] = creds
    _save_auth_store(store)

    from core.ui.agentic_ui import emit_oauth_login_success

    emit_oauth_login_success(
        provider=_PROVIDER_LABEL,
        account_id=account_id,
        email=email,
        plan_type=plan_type or "unknown",
        stored_at=str(AUTH_STORE_PATH),
    )

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
        from core.auth.codex_cli_oauth import read_codex_cli_credentials

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
