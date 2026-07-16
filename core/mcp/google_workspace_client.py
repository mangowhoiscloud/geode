"""Async Google Workspace REST client backed by GEODE's Google OAuth store."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlparse

import httpx

from core.auth.google_oauth import (
    GOOGLE_TOKEN_URL,
    GoogleAccount,
    GoogleAccountStore,
    GoogleOAuthError,
    GoogleSecret,
    google_utc_iso,
)

log = logging.getLogger(__name__)

_ALLOWED_GOOGLE_API_HOSTS = frozenset(
    {
        "www.googleapis.com",
        "gmail.googleapis.com",
        "people.googleapis.com",
        "tasks.googleapis.com",
        "docs.googleapis.com",
        "sheets.googleapis.com",
    }
)


class GoogleWorkspaceError(RuntimeError):
    """Base error returned by the Google Workspace client."""


class GoogleWorkspaceAuthError(GoogleWorkspaceError):
    """No account, missing scope, or refresh failure."""


class GoogleWorkspaceAPIError(GoogleWorkspaceError):
    """A Google API returned a non-success response."""

    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(message)


@dataclass(slots=True)
class _AccessToken:
    value: str
    expires_at: float


_TOKEN_CACHE: dict[str, _AccessToken] = {}
_CACHE_LOCK = threading.RLock()


def clear_google_token_cache(account_id: str | None = None) -> None:
    """Drop cached access tokens after logout or tests."""
    with _CACHE_LOCK:
        if account_id is None:
            _TOKEN_CACHE.clear()
        else:
            _TOKEN_CACHE.pop(account_id, None)


class GoogleWorkspaceClient:
    """Refreshes access tokens and sends bounded requests to Google APIs."""

    def __init__(
        self,
        *,
        account_store: GoogleAccountStore | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.account_store = account_store or GoogleAccountStore()
        self._http_client = http_client

    def active_account(self) -> GoogleAccount:
        account = self.account_store.get_active()
        if account is None:
            raise GoogleWorkspaceAuthError(
                "No Google account is connected. Run /login google first."
            )
        return account

    def has_active_account(self) -> bool:
        try:
            return self.active_account().status == "connected"
        except GoogleWorkspaceAuthError:
            return False

    def has_scopes(self, required_scopes: Sequence[str]) -> bool:
        try:
            granted = set(self.active_account().granted_scopes)
        except GoogleWorkspaceAuthError:
            return False
        return set(required_scopes).issubset(granted)

    def has_any_scope(self, required_scopes: Sequence[str]) -> bool:
        try:
            granted = set(self.active_account().granted_scopes)
        except GoogleWorkspaceAuthError:
            return False
        return bool(granted.intersection(required_scopes))

    def _require_scopes(
        self,
        account: GoogleAccount,
        required_scopes: Sequence[str],
        *,
        any_scope: bool,
    ) -> None:
        if not required_scopes:
            return
        granted = set(account.granted_scopes)
        required = set(required_scopes)
        allowed = bool(granted.intersection(required)) if any_scope else required.issubset(granted)
        if allowed:
            return
        missing = sorted(required - granted)
        qualifier = "one of " if any_scope else ""
        raise GoogleWorkspaceAuthError(
            f"Google account {account.email} is missing {qualifier}the required scope(s): "
            f"{', '.join(missing)}. Reauthorize with /login google --services <bundle>."
        )

    async def _access_token(self, account: GoogleAccount, *, force: bool = False) -> str:
        with _CACHE_LOCK:
            cached = _TOKEN_CACHE.get(account.account_id)
            if not force and cached is not None and cached.expires_at > time.time() + 60:
                return cached.value

        try:
            secret = await asyncio.to_thread(self.account_store.load_secret, account)
        except GoogleOAuthError as exc:
            raise GoogleWorkspaceAuthError(str(exc)) from exc

        form = {
            "client_id": account.client_id,
            "refresh_token": secret.refresh_token,
            "grant_type": "refresh_token",
        }
        if secret.client_secret:
            form["client_secret"] = secret.client_secret
        client = self._http_client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http_client is None
        try:
            try:
                response = await client.post(GOOGLE_TOKEN_URL, data=form)
            except httpx.HTTPError as exc:
                raise GoogleWorkspaceAuthError(
                    "Could not reach Google to refresh the access token"
                ) from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.status_code != 200:
            raise GoogleWorkspaceAuthError(
                f"Google token refresh failed ({response.status_code}). "
                "Run /login google to reconnect."
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleWorkspaceAuthError("Google token refresh returned invalid JSON") from exc
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise GoogleWorkspaceAuthError("Google token refresh returned no access token")
        try:
            expires_at = time.time() + max(0.0, float(payload.get("expires_in", 3600)))
        except (TypeError, ValueError) as exc:
            raise GoogleWorkspaceAuthError(
                "Google token refresh returned an invalid expiry"
            ) from exc
        token = str(payload["access_token"])
        with _CACHE_LOCK:
            _TOKEN_CACHE[account.account_id] = _AccessToken(token, expires_at)

        refresh_token = str(payload.get("refresh_token", "")) or secret.refresh_token
        refreshed_at = google_utc_iso()
        updated = replace(
            account,
            token_expires_at=expires_at,
            last_refresh_at=refreshed_at,
            updated_at=refreshed_at,
        )
        try:
            rotated_secret = (
                GoogleSecret(
                    client_secret=secret.client_secret,
                    refresh_token=refresh_token,
                )
                if refresh_token != secret.refresh_token
                else None
            )
            metadata_updated = await asyncio.to_thread(
                self.account_store.update_refresh_metadata,
                updated,
                expected_refresh_token=secret.refresh_token,
                rotated_secret=rotated_secret,
            )
            if not metadata_updated:
                clear_google_token_cache(account.account_id)
        except Exception:
            log.warning(
                "Google token refreshed but account metadata update failed: account_id=%s",
                account.account_id,
                exc_info=True,
            )
        return token

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_GOOGLE_API_HOSTS:
            raise GoogleWorkspaceError(f"Refusing non-Google Workspace API URL: {url}")

    async def request(
        self,
        method: str,
        url: str,
        *,
        required_scopes: Sequence[str] = (),
        any_scope: bool = False,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        content: bytes | str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Send one authorized request, refreshing once after a 401."""
        self._validate_url(url)
        account = self.active_account()
        self._require_scopes(account, required_scopes, any_scope=any_scope)
        token = await self._access_token(account)
        merged_headers = dict(headers or {})
        merged_headers["Authorization"] = f"Bearer {token}"

        client = self._http_client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._http_client is None
        try:
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    content=content,
                    headers=merged_headers,
                )
                if response.status_code == 401:
                    token = await self._access_token(account, force=True)
                    merged_headers["Authorization"] = f"Bearer {token}"
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        content=content,
                        headers=merged_headers,
                    )
            except httpx.HTTPError as exc:
                raise GoogleWorkspaceError("Google Workspace API request failed") from exc
        finally:
            if owns_client:
                await client.aclose()
        if response.is_error:
            raise GoogleWorkspaceAPIError(
                response.status_code,
                _google_error_message(response),
            )
        return response

    async def request_json(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = await self.request(method, url, **kwargs)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as exc:
            raise GoogleWorkspaceAPIError(
                response.status_code,
                "Google API returned a non-JSON response",
            ) from exc
        if not isinstance(payload, dict):
            raise GoogleWorkspaceAPIError(
                response.status_code,
                "Google API returned an unexpected payload",
            )
        return payload


def _google_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Google API error {response.status_code}: {response.text[:500]}"
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message", "")).strip()
            if message:
                return f"Google API error {response.status_code}: {message[:500]}"
        if isinstance(error, str):
            return f"Google API error {response.status_code}: {error[:500]}"
    return f"Google API error {response.status_code}"


_default_client: GoogleWorkspaceClient | None = None


def get_google_workspace_client() -> GoogleWorkspaceClient:
    global _default_client
    if _default_client is None:
        _default_client = GoogleWorkspaceClient()
    return _default_client


def reset_google_workspace_client() -> None:
    global _default_client
    _default_client = None
    clear_google_token_cache()
