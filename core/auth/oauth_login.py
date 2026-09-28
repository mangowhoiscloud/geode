"""Native OpenAI device-code login, persisted through the auth.toml owner.

External Codex CLI credentials have a separate read-only owner in codex_cli_oauth.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.auth.jwt_claims import decode_jwt_claims

# OpenAI Codex OAuth constants (from Hermes Agent)
_ISSUER = "https://auth.openai.com"
_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
_TOKEN_URL = f"{_ISSUER}/oauth/token"
_DEVICE_CODE_URL = f"{_ISSUER}/api/accounts/deviceauth/usercode"
_DEVICE_TOKEN_URL = f"{_ISSUER}/api/accounts/deviceauth/token"
_DEVICE_CALLBACK = f"{_ISSUER}/deviceauth/callback"
_DEVICE_PAGE = f"{_ISSUER}/codex/device"
_MAX_WAIT_S = 15 * 60  # 15 minutes


def auth_store_path() -> Path:
    """Resolve the *current* auth store path (``~/.geode/auth.toml``).

    Resolving via ``auth_toml_path()`` keeps display strings aligned with the
    actual store and respects the ``GEODE_AUTH_TOML`` test override.
    """
    from core.auth.auth_toml import auth_toml_path

    return auth_toml_path()


# Plan ID we use for any OAuth token GEODE itself issued (vs. external
# managed CLIs like ~/.codex/auth.json which keep their own SOT).
_GEODE_OPENAI_PLAN_ID = "openai-codex-geode"


def _plan_type_from_token(token: str) -> str:
    """Extract ``chatgpt_plan_type`` from an OpenAI OAuth access token."""
    claims = decode_jwt_claims(token)
    auth_claim = claims.get("https://api.openai.com/auth", {})
    if isinstance(auth_claim, dict):
        plan_type = auth_claim.get("chatgpt_plan_type", "")
        return str(plan_type) if plan_type else ""
    return ""


# PR-FIX-CHATGPT-PLAN-HALLUCINATION (2026-05-26) — display-label map for
# the documented ``chatgpt_plan_type`` JWT claim values. Pre-fix the
# GEODE codebase had "ChatGPT Plus" hard-coded in ~28 places regardless
# of the operator's actual tier (verified incident: operator on
# ``plan_type='prolite'`` saw "ChatGPT Plus" surfaced in CLI / hub
# chip / docs / audit reports). The mapping below resolves the slug
# the JWT issuer publishes into the human-readable plan name that
# OpenAI uses in its own product UI. Unknown slugs round-trip as
# ``"ChatGPT {Slug}"`` so a newly-launched tier still displays
# something — instead of perpetuating the "Plus" hallucination.
_CHATGPT_PLAN_LABELS: dict[str, str] = {
    "free": "ChatGPT Free",
    "plus": "ChatGPT Plus",
    "pro": "ChatGPT Pro",
    "prolite": "ChatGPT Pro Lite",
    "team": "ChatGPT Team",
    "business": "ChatGPT Business",
    "enterprise": "ChatGPT Enterprise",
    "edu": "ChatGPT Edu",
}


def chatgpt_plan_label(plan_type: str | None) -> str:
    """Resolve a ``chatgpt_plan_type`` JWT claim slug to its display label.

    Examples
    --------
    >>> chatgpt_plan_label("plus")
    'ChatGPT Plus'
    >>> chatgpt_plan_label("prolite")
    'ChatGPT Pro Lite'
    >>> chatgpt_plan_label("")
    'ChatGPT subscription'
    >>> chatgpt_plan_label("future-tier-2030")
    'ChatGPT Future-Tier-2030'

    Empty / None slugs surface a generic "ChatGPT subscription" label
    (e.g. when no OAuth profile is signed-in yet, or build-time site
    rendering without operator JWT). Unknown slugs title-case the slug
    so a newly-launched tier still gets a reasonable display string
    rather than dropping to "Plus".
    """
    normalised = (plan_type or "").strip().lower()
    if not normalised:
        return "ChatGPT subscription"
    canonical = _CHATGPT_PLAN_LABELS.get(normalised)
    if canonical:
        return canonical
    # Fallback: title-case the slug. Keep punctuation as-is so future
    # tiers with hyphens / numbers (e.g. "plus-2030") survive.
    return f"ChatGPT {normalised.title()}"


def _persist_oauth_to_authtoml(creds: dict[str, Any]) -> None:
    """Write Codex device-code creds into ``~/.geode/auth.toml`` SOT.

    The plan tier follows the token being written, so a changed subscription
    is recorded with the credential rather than when the file is read.
    """
    from core.auth.auth_toml import auth_file_transaction, auth_toml_path
    from core.auth.profiles import AuthProfile, CredentialType
    from core.config import CODEX_BASE_URL
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.llm.strategies.plans import Plan, PlanKind
    from core.wiring.container import ensure_profile_store

    access_token = creds.get("access_token")
    refresh_token = creds.get("refresh_token", "")
    if not isinstance(access_token, str) or not access_token.strip():
        raise ValueError("OAuth access token must be a nonempty string")
    if not isinstance(refresh_token, str):
        raise ValueError("OAuth refresh token must be a string")
    tier = str(creds.get("plan_type") or "") or None
    metadata = {
        "account_id": creds.get("account_id", ""),
        "email": creds.get("email", ""),
        "plan_type": creds.get("plan_type", ""),
        "source": "geode-device-code",
    }
    live = ensure_profile_store()
    live_registry = get_plan_registry()
    with auth_file_transaction(registry=live_registry, store=live) as (registry, store):
        source = str(auth_toml_path().resolve())
        profile_name = f"{_GEODE_OPENAI_PLAN_ID}:user"
        live_profile = live.get(profile_name)
        if live_profile is not None and (
            live_profile.managed_by
            or live.file_profiles(source).get(profile_name) is not live_profile
        ):
            raise ValueError("OAuth credential name belongs to another owner")
        live_plan = live_registry.get(_GEODE_OPENAI_PLAN_ID)
        if live_plan is not None and (
            live_registry.file_plans(source).get(_GEODE_OPENAI_PLAN_ID) is not live_plan
        ):
            raise ValueError("OAuth plan name belongs to another owner")
        current = registry.get(_GEODE_OPENAI_PLAN_ID)
        if current is not None and (
            current.provider != "openai-codex"
            or current.kind is not PlanKind.OAUTH_BORROWED
            or current.auth_type != "oauth_external"
            or current.base_url.rstrip("/") != CODEX_BASE_URL.rstrip("/")
        ):
            raise ValueError("Existing OAuth plan conflicts with the Codex login route")
        plan = (
            Plan(
                id=_GEODE_OPENAI_PLAN_ID,
                provider="openai-codex",
                kind=PlanKind.OAUTH_BORROWED,
                display_name="OpenAI (ChatGPT subscription, GEODE OAuth)",
                base_url="https://chatgpt.com/backend-api/codex",
                auth_type="oauth_external",
                subscription_tier=tier,
            )
            if current is None
            else replace(current, subscription_tier=tier or current.subscription_tier)
        )
        registry.add(plan)
        expires_at = float(creds.get("expires_at", 0.0) or 0.0)
        existing = store.get(profile_name)
        if existing is not None and (
            existing.provider != "openai-codex"
            or existing.credential_type is not CredentialType.OAUTH
            or existing.managed_by
            or (
                existing.base_url_override is not None
                and existing.base_url_override.rstrip("/") != CODEX_BASE_URL.rstrip("/")
            )
        ):
            raise ValueError("Existing profile conflicts with the Codex login route")
        if existing is not None:
            existing.key = access_token
            existing.refresh_token = refresh_token
            existing.expires_at = expires_at
            existing.plan_id = plan.id
            existing.error_count = 0
            existing.cooldown_until = 0.0
            existing.metadata.update(metadata)
        else:
            store.add(
                AuthProfile(
                    name=profile_name,
                    provider=plan.provider,
                    credential_type=CredentialType.OAUTH,
                    key=access_token,
                    refresh_token=refresh_token,
                    expires_at=expires_at,
                    plan_id=plan.id,
                    metadata=metadata,
                )
            )
        store.set_active(profile_name)


def login_openai() -> dict[str, Any]:
    """Run one device login per auth store; reject an overlapping attempt."""
    import fcntl

    from core.ui.agentic_ui import emit_oauth_login_failed

    path = auth_store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(f".{path.name}.login.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("An OpenAI login is already in progress for this auth store") from exc
        try:
            return _login_openai()
        except KeyboardInterrupt:
            emit_oauth_login_failed("OpenAI ChatGPT", "cancelled by user")
            return {}
        except Exception as exc:
            emit_oauth_login_failed("OpenAI ChatGPT", f"login failed ({type(exc).__name__})")
            raise
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _login_openai() -> dict[str, Any]:
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
        emit_oauth_login_pending,
        emit_oauth_login_started,
    )

    _PROVIDER_LABEL = "OpenAI ChatGPT"
    emit_oauth_login_started(
        provider=_PROVIDER_LABEL,
        verification_uri=_DEVICE_PAGE,
        user_code=user_code,
    )

    # Step 3: Poll for authorization
    start = time.monotonic()
    code_resp = None

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

    if not isinstance(access_token, str) or not access_token.strip():
        raise RuntimeError("Token exchange did not return an access_token")

    # Extract account info from JWT (uses decode_jwt_claims helper —
    # any decode failure returns {} so the unpacks below resolve to "").
    payload = decode_jwt_claims(access_token)
    auth_claim = payload.get("https://api.openai.com/auth", {})
    profile_claim = payload.get("https://api.openai.com/profile", {})
    auth_claim = auth_claim if isinstance(auth_claim, dict) else {}
    profile_claim = profile_claim if isinstance(profile_claim, dict) else {}
    account_id = str(auth_claim.get("chatgpt_account_id", "") or "")
    plan_type = str(auth_claim.get("chatgpt_plan_type", "") or "")
    email = str(profile_claim.get("email", "") or "")
    exp = payload.get("exp", 0) or 0

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

    # Publish through the auth file transaction before reporting success.
    _persist_oauth_to_authtoml(creds)

    from core.ui.agentic_ui import emit_oauth_login_success

    emit_oauth_login_success(
        provider=_PROVIDER_LABEL,
        account_id=account_id,
        email=email,
        plan_type=chatgpt_plan_label(plan_type),
        # v0.52.2 — resolve the live SOT path each call (auth.toml since
        # v0.50.2). Pre-fix this displayed the legacy auth.json constant
        # while the actual write landed in auth.toml.
        stored_at=str(auth_store_path()),
    )

    return creds
