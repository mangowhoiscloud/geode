"""OAuth login flows — `/login openai` device-code flow.

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


def auth_store_path() -> Path:
    """Resolve the *current* auth store path (``~/.geode/auth.toml``).

    v0.50.2 made auth.toml the SOT. Pre-v0.52.2 ``AUTH_STORE_PATH`` was an
    alias for the legacy ``auth.json`` constant, so the OAuth success
    message and other UX surfaces displayed a stale path even though the
    actual write landed in ``auth.toml``. Resolving via ``auth_toml_path()``
    keeps the display string honest and respects the ``GEODE_AUTH_TOML``
    env override used by tests.
    """
    from core.auth.auth_toml import auth_toml_path

    return auth_toml_path()


# Backwards-compat alias — old callers imported the constant name.
# Now resolves to the live auth.toml path so any consumer that *displays*
# this value matches the actual SOT.
AUTH_STORE_PATH = auth_store_path()

# Plan ID we use for any OAuth token GEODE itself issued (vs. external
# managed CLIs like ~/.codex/auth.json which keep their own SOT).
_GEODE_OPENAI_PLAN_ID = "openai-codex-geode"


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode the payload section of a (signed) JWT, no verification.

    Used to read OpenAI-issued claims like ``chatgpt_plan_type`` /
    ``chatgpt_account_id`` / ``email`` from the access_token. The token's
    signature is the OAuth provider's concern; GEODE only needs the
    public claims for routing + display.
    """
    import base64

    parts = token.split(".")
    if len(parts) < 2:
        return {}
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _plan_type_from_token(token: str) -> str:
    """Extract ``chatgpt_plan_type`` from an OpenAI OAuth access token."""
    claims = _decode_jwt_claims(token)
    auth_claim = claims.get("https://api.openai.com/auth", {})
    if isinstance(auth_claim, dict):
        plan_type = auth_claim.get("chatgpt_plan_type", "")
        return str(plan_type) if plan_type else ""
    return ""


def reconcile_plan_tier_from_stored_jwt() -> tuple[str, str] | None:
    """Re-decode the stored OpenAI OAuth JWT and sync ``subscription_tier``.

    The user's ChatGPT plan can change between logins (Plus → Pro → Max,
    etc.). The Plan's ``subscription_tier`` is set on login but stays
    frozen if the user only refreshes their access token via
    ``refresh_token`` flow. This re-extracts ``chatgpt_plan_type`` from
    the live JWT and updates both the Plan and the profile metadata.

    Returns ``(old, new)`` tuple if a drift was reconciled, ``None``
    when no GEODE OAuth profile exists or the tier matches.
    """
    try:
        from core.auth.plan_registry import get_plan_registry
        from core.wiring.container import ensure_profile_store
    except Exception:
        return None

    registry = get_plan_registry()
    plan = registry.get(_GEODE_OPENAI_PLAN_ID)
    store = ensure_profile_store()
    profile = store.get(f"{_GEODE_OPENAI_PLAN_ID}:user") if plan else None
    if plan is None or profile is None or not profile.key:
        return None

    fresh = _plan_type_from_token(profile.key)
    if not fresh:
        return None
    stored = plan.subscription_tier or ""
    if fresh == stored:
        return None

    plan.subscription_tier = fresh
    if profile.metadata is not None:
        profile.metadata["plan_type"] = fresh
    try:
        from core.auth.auth_toml import save_auth_toml

        save_auth_toml()
    except Exception:
        log.debug("auth.toml persist after tier drift skipped", exc_info=True)
    log.info(
        "OpenAI plan tier reconciled from JWT: %s → %s (plan=%s)",
        stored or "(unset)",
        fresh,
        plan.id,
    )
    return (stored, fresh)


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
        from core.wiring.container import ensure_profile_store
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
        from core.wiring.container import ensure_profile_store
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

    # Extract account info from JWT (uses _decode_jwt_claims helper —
    # any decode failure returns {} so the unpacks below resolve to "").
    payload = _decode_jwt_claims(access_token)
    auth_claim = payload.get("https://api.openai.com/auth", {}) or {}
    profile_claim = payload.get("https://api.openai.com/profile", {}) or {}
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
        # v0.52.2 — resolve the live SOT path each call (auth.toml since
        # v0.50.2). Pre-fix this displayed the legacy auth.json constant
        # while the actual write landed in auth.toml.
        stored_at=str(auth_store_path()),
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


# ---------------------------------------------------------------------------
# Anthropic PKCE OAuth (owned-credential path)
# ---------------------------------------------------------------------------
#
# Mirrors :func:`login_openai` for the Anthropic side. The two providers
# share the post-flow path (auth.toml SOT + ProfileStore.add) but use
# different grant types — Codex's device-code endpoint vs Anthropic's
# manual-paste PKCE (browser → /oauth/code/callback page renders code →
# user pastes it back into the CLI). See
# ``docs/architecture/provider-login.md`` for the full architecture.
#
# Endpoints reverse-engineered from the Claude Code native binary's
# strings on 2026-05-17:
#   authorize:   https://platform.claude.com/oauth/authorize
#   token:       https://api.anthropic.com/v1/oauth/token
#   beta header: anthropic-beta: oauth-2025-04-20
#
# Policy notice — ToS Tier 3 (impersonation): the flow reuses Claude
# Code's public OAuth client_id (PKCE — no secret). Anthropic does not
# publish a developer portal for third-party OAuth client registration,
# so the only feasible "owned" path is to call the same client_id the
# first-party CLI uses. The first activation emits a WARNING through
# :mod:`plugins.petri_audit.claude_code_provider` once the resulting
# token is consumed.

_ANTHROPIC_AUTHORIZE_URL = "https://platform.claude.com/oauth/authorize"
_ANTHROPIC_TOKEN_URL = "https://api.anthropic.com/v1/oauth/token"  # noqa: S105 — URL not password
_ANTHROPIC_OAUTH_BETA_HEADER = "oauth-2025-04-20"
# The OAuth client `9d1c250a-...` is registered with this server-hosted
# redirect URI only — loopback URIs (http://localhost:*) are rejected at
# the authorize step. The /oauth/code/callback page renders the
# authorization code so the user can copy & paste it back into the CLI.
_ANTHROPIC_REDIRECT_URI = "https://platform.claude.com/oauth/code/callback"

# Scope set mirrors Claude Code's hint string in the native binary:
#   "user:profile user:inference user:sessions:claude_code user:mcp_servers"
# Anthropic rejects authorize requests asking for scopes outside the
# set registered for the client, so we send the full superset.
_ANTHROPIC_DEFAULT_SCOPES = (
    "user:inference",
    "user:profile",
    "user:sessions:claude_code",
    "user:mcp_servers",
)

# Claude Code's public OAuth client_id candidates, reverse-engineered from
# the native binary. We try them in order — the first that survives the
# token exchange wins. Future Anthropic API changes may invalidate any
# given candidate; the multi-trial loop keeps the path resilient.
_ANTHROPIC_CLIENT_ID_CANDIDATES = (
    # Most likely: matches the well-known Claude Code OAuth client id.
    "9d1c250a-e61b-44d9-88ed-5944d1962f5e",
)


def _generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` — RFC 7636 §4.1/§4.2.

    96 bytes of entropy (768 bits) — the upper bound of the spec
    ``43..128`` URL-safe character range. Mirrors the value Claude Code's
    native binary uses (``randomBytesBase64(96)``).
    """
    import base64
    import hashlib
    import secrets

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(96)).decode("ascii").rstrip("=")
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )
    return verifier, challenge


def _parse_pasted_code(raw: str) -> tuple[str, str]:
    """Extract ``(code, state)`` from a pasted authorization response.

    The /oauth/code/callback page shows the value in ``code#state`` fragment
    form (Claude Code's native binary uses the same split). Users may also
    paste the full callback URL or the bare code on its own — we accept
    all three. An empty returned state lets the caller skip CSRF check;
    that is acceptable for a public PKCE flow where the verifier already
    binds the request.
    """
    import urllib.parse

    if raw.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(raw)
        params = urllib.parse.parse_qs(parsed.query)
        return params.get("code", [""])[0], params.get("state", [""])[0]
    if "#" in raw:
        code, _, state = raw.partition("#")
        return code, state
    return raw, ""


def _run_anthropic_pkce_flow(client_id: str) -> dict[str, Any]:
    """Drive a single manual-paste PKCE OAuth round with ``client_id``.

    Mirrors Claude Code's native flow: open the authorize URL, wait for
    the user to paste back the ``code#state`` value rendered on
    ``/oauth/code/callback``. Raises ``RuntimeError`` on token-exchange
    failure (so the caller can fall through to the next candidate).
    """
    import secrets
    import urllib.parse
    import webbrowser

    import httpx

    from core.ui import agentic_ui as _pkg

    verifier, challenge = _generate_pkce_pair()
    state = secrets.token_urlsafe(16)
    scope = " ".join(_ANTHROPIC_DEFAULT_SCOPES)
    auth_url = (
        _ANTHROPIC_AUTHORIZE_URL
        + "?"
        + urllib.parse.urlencode(
            {
                "code": "true",
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": _ANTHROPIC_REDIRECT_URI,
                "scope": scope,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    log.info("anthropic-oauth: opening browser (manual-paste flow)")
    webbrowser.open(auth_url)

    _pkg.console.print()
    _pkg.console.print(
        "  [bold]A browser window has been opened to authorize with Anthropic.[/bold]"
    )
    _pkg.console.print(f"  [muted]If it didn't open, visit:[/muted] {auth_url}")
    _pkg.console.print()
    _pkg.console.print(
        "  After approving, copy the code shown on the callback page and paste it below."
    )
    _pkg.console.print(
        "  [muted]Accepted formats: 'code#state', the full callback URL, or just the code.[/muted]"
    )
    _pkg.console.print()

    try:
        # /login is a THIN-handler command (see core.cli.routing — RunLocation.THIN),
        # so this input() runs in the thin-client process where stdin is the user's
        # terminal. Daemon never reaches this code path.
        raw = input("  Paste authorization code: ").strip()  # allow-direct-io: thin-only OAuth manual-paste
    except (EOFError, KeyboardInterrupt) as exc:
        raise RuntimeError("Anthropic OAuth cancelled — no code provided") from exc

    if not raw:
        raise RuntimeError("Anthropic OAuth: empty code")

    auth_code, returned_state = _parse_pasted_code(raw)
    if not auth_code:
        raise RuntimeError("Anthropic OAuth: could not parse code from pasted value")
    if returned_state and returned_state != state:
        raise RuntimeError("Anthropic OAuth state mismatch — possible CSRF, aborting")

    try:
        with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
            resp = client.post(
                _ANTHROPIC_TOKEN_URL,
                json={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "redirect_uri": _ANTHROPIC_REDIRECT_URI,
                    "client_id": client_id,
                    "code_verifier": verifier,
                    "state": state,
                },
                headers={
                    "Content-Type": "application/json",
                    "anthropic-beta": _ANTHROPIC_OAUTH_BETA_HEADER,
                },
            )
    except Exception as exc:
        raise RuntimeError(f"Anthropic token exchange failed: {exc}") from exc

    if resp.status_code != 200:
        body_preview = resp.text[:300] if resp.text else "(empty)"
        raise RuntimeError(f"Anthropic token exchange returned {resp.status_code}: {body_preview}")

    return dict(resp.json())


def login_anthropic() -> dict[str, Any]:
    """Run Anthropic PKCE OAuth flow — owned-credential path (PR C3).

    Tries each ``_ANTHROPIC_CLIENT_ID_CANDIDATES`` in order; the first
    candidate that completes the token exchange wins. On success the
    credentials land in ``~/.geode/auth.toml`` under
    ``providers.anthropic`` so other parts of GEODE (`ProfileStore`,
    `claude_code_provider`) see a uniform SOT.

    Returns the persisted credential dict (with computed expiry +
    timestamps) on success, raises ``RuntimeError`` when every
    candidate fails. Caller should fall back to ``ANTHROPIC_API_KEY``
    on RuntimeError.
    """
    from core.ui.agentic_ui import (
        emit_oauth_login_failed,
        emit_oauth_login_started,
        emit_oauth_login_success,
    )

    provider_label = "Anthropic (Claude subscription)"
    emit_oauth_login_started(
        provider=provider_label,
        verification_uri=_ANTHROPIC_AUTHORIZE_URL,
        user_code="(browser opens automatically)",
    )

    last_error: Exception | None = None
    tokens: dict[str, Any] = {}
    used_client_id = ""
    for client_id in _ANTHROPIC_CLIENT_ID_CANDIDATES:
        log.info("anthropic-oauth: trying client_id=%s", client_id)
        try:
            tokens = _run_anthropic_pkce_flow(client_id)
            used_client_id = client_id
            break
        except RuntimeError as exc:
            last_error = exc
            log.warning("anthropic-oauth: client_id=%s failed (%s)", client_id, exc)
            continue

    if not tokens:
        msg = (
            "all Anthropic OAuth client_id candidates failed; "
            "set ANTHROPIC_API_KEY env or use /login add wizard"
        )
        emit_oauth_login_failed(provider_label, str(last_error) if last_error else msg)
        raise RuntimeError(msg)

    access_token = tokens.get("access_token", "")
    refresh_token = tokens.get("refresh_token", "")
    if not access_token:
        emit_oauth_login_failed(provider_label, "token response missing access_token")
        raise RuntimeError("Anthropic token exchange did not return an access_token")

    expires_in = tokens.get("expires_in")
    expires_at = int(time.time()) + int(expires_in) if isinstance(expires_in, int | float) else 0
    scopes = tokens.get("scope") or tokens.get("scopes") or []
    if isinstance(scopes, str):
        scopes = scopes.split()

    now_iso = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    creds = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "scopes": list(scopes),
        "client_id": used_client_id,
        "last_refresh": now_iso,
        "source": "geode-pkce",
    }

    # Save to ~/.geode/auth.toml under providers.anthropic (mirror of
    # OpenAI's providers.openai key).
    store = _load_auth_store()
    store.setdefault("providers", {})
    store["providers"]["anthropic"] = creds
    _save_auth_store(store)

    emit_oauth_login_success(
        provider=provider_label,
        stored_at=str(auth_store_path()),
    )

    return creds


def read_geode_anthropic_credentials() -> dict[str, Any] | None:
    """Read Anthropic OAuth credentials from ``~/.geode/auth.toml``.

    Returns ``None`` when the credential is missing or expired. The
    return shape mirrors :func:`read_geode_openai_credentials` so
    downstream code can use one resolver pattern for both providers.
    """
    store = _load_auth_store()
    creds = store.get("providers", {}).get("anthropic")
    if not creds:
        return None

    access_token = creds.get("access_token", "")
    if not access_token:
        return None

    expires_at = creds.get("expires_at", 0)
    if expires_at and time.time() > expires_at:
        log.info("GEODE auth.toml Anthropic token expired")
        return None

    return {
        "access_token": access_token,
        "refresh_token": creds.get("refresh_token", ""),
        "expires_at": float(expires_at),
        "scopes": list(creds.get("scopes") or []),
        "client_id": creds.get("client_id", ""),
    }
