"""Refresh only GEODE-owned OpenAI OAuth, before a subscription request.

Imported CLI tokens stay read-only. A separate refresh lock serializes grant
rotation; the auth-file commit lock is never held across the network request.
"""

from __future__ import annotations

import asyncio
import fcntl
import math
import os
import time
from typing import TYPE_CHECKING

import httpx

from core.auth.auth_toml import auth_file_transaction, auth_toml_path, load_auth_toml
from core.auth.jwt_claims import decode_jwt_claims
from core.auth.oauth_login import _CLIENT_ID, _TOKEN_URL
from core.auth.profiles import AuthProfile, CredentialType
from core.llm.strategies.plan_registry import PlanRegistry, get_plan_registry

if TYPE_CHECKING:
    from core.auth.profiles import ProfileStore
    from core.config.policy_source import PolicySourcePaths


class OAuthRefreshError(RuntimeError):
    """A refresh failed; callers must preserve the subscription billing route."""


def can_refresh_native_oauth(profile: AuthProfile, store: ProfileStore) -> bool:
    """Inspect the native refresh owner without refreshing or borrowing authority."""
    from core.config import CODEX_BASE_URL

    plan = get_plan_registry().get(profile.plan_id)
    endpoint = profile.base_url_override or (plan.base_url if plan else CODEX_BASE_URL)
    return (
        profile.provider == "openai-codex"
        and profile.credential_type is CredentialType.OAUTH
        and not profile.managed_by
        and bool(profile.key.strip())
        and bool(profile.refresh_token.strip())
        and not profile.disabled
        and not profile.is_cooling_down
        and endpoint.rstrip("/") == CODEX_BASE_URL.rstrip("/")
        and store.file_profiles(str(auth_toml_path().absolute())).get(profile.name) is profile
    )


def _identity(profile: AuthProfile) -> tuple[str, str, str]:
    auth = decode_jwt_claims(profile.key).get("https://api.openai.com/auth", {})
    account = auth.get("chatgpt_account_id", "") if isinstance(auth, dict) else ""
    return profile.key, profile.refresh_token, str(account)


def _route(profile: AuthProfile, registry: PlanRegistry) -> tuple[object, ...]:
    plan = registry.get(profile.plan_id)
    return (
        profile.name,
        profile.provider,
        profile.credential_type,
        profile.managed_by,
        profile.plan_id,
        profile.base_url_override,
        (plan.provider, plan.kind, plan.auth_type, plan.base_url) if plan else None,
    )


async def refresh_native_oauth(model: str, *, sources: PolicySourcePaths | None = None) -> None:
    from core.auth.codex_cli_oauth import sync_codex_cli_profile
    from core.config import CODEX_BASE_URL
    from core.llm.routing import resolve_routing
    from core.wiring.container import ensure_profile_store

    store = ensure_profile_store()
    sync_codex_cli_profile(store, force_refresh=True)

    def candidate() -> AuthProfile | None:
        target = resolve_routing(
            model,
            provider="openai",
            source="subscription",
            sources=sources,
            allow_refreshable=True,
        )
        if target is None:
            return None
        profile = target.profile
        if (
            profile.managed_by
            or profile.credential_type is not CredentialType.OAUTH
            or not profile.refresh_token
            or not profile.expires_at
            or profile.expires_at > time.time() + 60
        ):
            return None
        if target.base_url.rstrip("/") != CODEX_BASE_URL.rstrip("/"):
            raise OAuthRefreshError("Native OAuth refresh requires the subscription endpoint")
        return profile

    selected = candidate()
    if selected is None:
        return
    path = auth_toml_path()
    # No imported or environment credential may be written into auth.toml.
    if store.file_profiles(str(path.absolute())).get(selected.name) is not selected:
        raise OAuthRefreshError("OAuth refresh requires a file-owned profile; run /login openai")
    initial_name = selected.name
    initial_identity = _identity(selected)
    initial_route = _route(selected, get_plan_registry())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(
        path.with_name(f".{path.name}.refresh.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        deadline = time.monotonic() + 45
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise OAuthRefreshError("OAuth refresh is busy; retry shortly") from None
                await asyncio.sleep(0.05)
        if not load_auth_toml(store=store, path=path, clear_missing=True):
            raise OAuthRefreshError("Cannot refresh an invalid auth file")
        reloaded = store.get(initial_name)
        if reloaded is None:
            return
        identity = _identity(reloaded)
        if (
            _route(reloaded, get_plan_registry()) != initial_route
            or identity[2] != initial_identity[2]
            or (not identity[2] and identity != initial_identity)
        ):
            raise OAuthRefreshError("OAuth account or route changed while waiting; retry")
        selected = candidate()
        if selected is None:
            return  # Another request refreshed or removed the selected account.
        if selected.name != initial_name:
            raise OAuthRefreshError("Selected OAuth account changed while waiting; retry")
        if store.file_profiles(str(path.absolute())).get(selected.name) is not selected:
            raise OAuthRefreshError("OAuth profile ownership changed; retry after /login refresh")
        expected = _identity(selected)
        profile_name = selected.name
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    _TOKEN_URL,
                    json={
                        "client_id": _CLIENT_ID,
                        "grant_type": "refresh_token",
                        "refresh_token": selected.refresh_token,
                    },
                )
        except httpx.HTTPError:
            raise OAuthRefreshError("OAuth refresh transport failed; retry shortly") from None
        if response.status_code != 200:
            action = (
                "run /login openai" if response.status_code in (400, 401, 403) else "retry shortly"
            )
            raise OAuthRefreshError(
                f"OAuth refresh rejected (HTTP {response.status_code}); {action}"
            )
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError
            token = payload.get("access_token", selected.key)
            refresh = payload.get("refresh_token", selected.refresh_token)
            if (
                not isinstance(token, str)
                or not token
                or not isinstance(refresh, str)
                or not refresh
            ):
                raise ValueError
            claims = decode_jwt_claims(token)
            expiry = float(claims.get("exp", 0))
            account = claims.get("https://api.openai.com/auth", {})
            account_id = account.get("chatgpt_account_id", "") if isinstance(account, dict) else ""
            if not math.isfinite(expiry) or expiry <= time.time():
                raise ValueError
            if expected[2] and account_id != expected[2]:
                raise ValueError
        except (ValueError, TypeError):
            raise OAuthRefreshError(
                "OAuth refresh returned invalid account credentials; run /login openai"
            ) from None

        def publish() -> None:
            with auth_file_transaction(store=store, path=path) as (registry, pending):
                current = pending.get(profile_name)
                live = store.get(profile_name)
                if (
                    current is None
                    or _identity(current) != expected
                    or _route(current, registry) != initial_route
                    or live is None
                    or live.disabled
                    or live.is_cooling_down
                    or current.disabled
                    or current.is_cooling_down
                ):
                    raise ValueError("account changed")
                current.key, current.refresh_token, current.expires_at = token, refresh, expiry

        # A rotated grant must reach a terminal local write even if the caller
        # cancels. Offload the bounded file-lock/write, retaining its ownership.
        publication = asyncio.create_task(asyncio.to_thread(publish))
        cancellation: asyncio.CancelledError | None = None
        while not publication.done():
            try:
                await asyncio.shield(publication)
            except asyncio.CancelledError as exc:
                cancellation = cancellation or exc
            except (OSError, ValueError):
                break
        try:
            publication.result()
        except (OSError, ValueError):
            # The remote grant may already have rotated: never claim rollback.
            raise OAuthRefreshError(
                "OAuth grant refreshed but local publication failed or account changed; "
                "run /login refresh, then /login openai if authentication remains unavailable"
            ) from None
        if cancellation is not None:
            raise cancellation
    finally:
        os.close(fd)
