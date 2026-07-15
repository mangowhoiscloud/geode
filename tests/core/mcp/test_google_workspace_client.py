"""Google Workspace REST client refresh, scope, and host-boundary tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest
from core.auth.google_oauth import GoogleAccount, GoogleAccountStore, GoogleSecret
from core.mcp.google_workspace_client import (
    GoogleWorkspaceAuthError,
    GoogleWorkspaceClient,
    GoogleWorkspaceError,
    clear_google_token_cache,
)

SCOPE = "https://www.googleapis.com/auth/drive.file"


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, GoogleSecret] = {}

    def ensure_available(self) -> None:
        return

    def get(self, secret_ref: str) -> GoogleSecret | None:
        return self.values.get(secret_ref)

    def set(self, secret_ref: str, secret: GoogleSecret) -> None:
        self.values[secret_ref] = secret

    def delete(self, secret_ref: str) -> None:
        self.values.pop(secret_ref, None)


def _store(tmp_path: Path, scopes: tuple[str, ...] = (SCOPE,)) -> GoogleAccountStore:
    secrets = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secrets)
    account = GoogleAccount(
        account_id="account-1",
        email="user@example.com",
        display_name="User",
        client_id="client.apps.googleusercontent.com",
        project_id="project",
        services=("workspace-files",),
        granted_scopes=scopes,
        secret_ref="account:account-1",
        status="connected",
        created_at="2026-07-16T00:00:00Z",
        updated_at="2026-07-16T00:00:00Z",
    )
    store.save(account, GoogleSecret(client_secret="secret", refresh_token="refresh"))
    return store


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    clear_google_token_cache()


def test_refreshes_then_sends_bearer_token(tmp_path: Path) -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(
                200,
                json={"access_token": "access-1", "expires_in": 3600},
            )
        assert request.headers["Authorization"] == "Bearer access-1"
        return httpx.Response(200, json={"files": [{"id": "f1"}]})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GoogleWorkspaceClient(account_store=_store(tmp_path), http_client=http)
            return await client.request_json(
                "GET",
                "https://www.googleapis.com/drive/v3/files",
                required_scopes=(SCOPE,),
            )

    payload = asyncio.run(run())
    assert payload["files"][0]["id"] == "f1"
    assert requests == [("POST", "/token"), ("GET", "/drive/v3/files")]


def test_missing_scope_fails_before_network(tmp_path: Path) -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GoogleWorkspaceClient(account_store=_store(tmp_path, ()), http_client=http)
            with pytest.raises(GoogleWorkspaceAuthError, match="missing"):
                await client.request_json(
                    "GET",
                    "https://www.googleapis.com/drive/v3/files",
                    required_scopes=(SCOPE,),
                )

    asyncio.run(run())
    assert called is False


def test_token_is_never_sent_to_unapproved_host(tmp_path: Path) -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200))
        ) as http:
            client = GoogleWorkspaceClient(account_store=_store(tmp_path), http_client=http)
            with pytest.raises(GoogleWorkspaceError, match="Refusing"):
                await client.request_json(
                    "GET",
                    "https://example.com/collect",
                    required_scopes=(SCOPE,),
                )

    asyncio.run(run())


def test_401_forces_one_refresh_and_retry(tmp_path: Path) -> None:
    token_count = 0
    api_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal token_count, api_count
        if request.url.host == "oauth2.googleapis.com":
            token_count += 1
            return httpx.Response(
                200,
                json={"access_token": f"access-{token_count}", "expires_in": 3600},
            )
        api_count += 1
        if api_count == 1:
            assert request.headers["Authorization"] == "Bearer access-1"
            return httpx.Response(401, json={"error": {"message": "expired"}})
        assert request.headers["Authorization"] == "Bearer access-2"
        return httpx.Response(200, json={"ok": True})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = GoogleWorkspaceClient(account_store=_store(tmp_path), http_client=http)
            return await client.request_json(
                "GET",
                "https://www.googleapis.com/drive/v3/files",
                required_scopes=(SCOPE,),
            )

    payload = asyncio.run(run())
    assert payload == {"ok": True}
    assert token_count == 2
    assert api_count == 2
