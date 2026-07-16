"""Google native-app OAuth and split credential-store contracts."""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from core.auth.google_oauth import (
    GOOGLE_SERVICE_BUNDLES,
    GoogleAccount,
    GoogleAccountStore,
    GoogleCredentialStoreError,
    GoogleLoopbackReceiver,
    GoogleOAuthError,
    GoogleSecret,
    KeyringGoogleSecretStore,
    build_google_authorization_url,
    google_scopes_for_services,
    load_google_client_json,
    login_google,
    normalize_google_services,
    revoke_google_account,
)


class MemorySecretStore:
    def __init__(self) -> None:
        self.values: dict[str, GoogleSecret] = {}
        self.available = True

    def ensure_available(self) -> None:
        if not self.available:
            raise RuntimeError("unavailable")

    def get(self, secret_ref: str) -> GoogleSecret | None:
        return self.values.get(secret_ref)

    def set(self, secret_ref: str, secret: GoogleSecret) -> None:
        self.values[secret_ref] = secret

    def delete(self, secret_ref: str) -> None:
        self.values.pop(secret_ref, None)


def _account() -> GoogleAccount:
    return GoogleAccount(
        account_id="acct-1",
        email="user@example.com",
        display_name="User",
        client_id="client.apps.googleusercontent.com",
        project_id="project",
        services=("gmail-send",),
        granted_scopes=(
            "openid",
            GOOGLE_SERVICE_BUNDLES["gmail-send"].scopes[0],
        ),
        secret_ref="account:acct-1",
        status="connected",
        created_at="2026-07-16T00:00:00Z",
        updated_at="2026-07-16T00:00:00Z",
    )


def test_service_bundles_collapse_implied_read_scopes() -> None:
    assert normalize_google_services(
        ["calendar-read", "calendar-write", "tasks-read", "tasks-write"]
    ) == ("calendar-write", "tasks-write")
    scopes = google_scopes_for_services(["gmail-send", "calendar-read"])
    assert "openid" in scopes
    assert GOOGLE_SERVICE_BUNDLES["gmail-send"].scopes[0] in scopes


def test_unknown_service_bundle_is_rejected() -> None:
    with pytest.raises(GoogleOAuthError, match="Unknown Google service"):
        normalize_google_services(["everything"])


def test_client_json_requires_installed_desktop_shape(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "abc.apps.googleusercontent.com",
                    "client_secret": "secret",
                    "project_id": "project",
                }
            }
        ),
        encoding="utf-8",
    )
    client = load_google_client_json(path)
    assert client.client_id == "abc.apps.googleusercontent.com"
    assert client.client_secret == "secret"

    path.write_text(json.dumps({"web": {}}), encoding="utf-8")
    with pytest.raises(GoogleOAuthError, match="Desktop"):
        load_google_client_json(path)


def test_keyring_store_rejects_plaintext_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    class PlaintextBackend:
        priority = 1

    class FakeKeyring:
        @staticmethod
        def get_keyring() -> object:
            return PlaintextBackend()

    monkeypatch.setattr(KeyringGoogleSecretStore, "_keyring", staticmethod(lambda: FakeKeyring))
    with pytest.raises(GoogleCredentialStoreError, match="No secure OS keyring"):
        KeyringGoogleSecretStore().ensure_available()


def test_keyring_store_accepts_secure_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    class MacOSKeyring:
        priority = 5

    class FakeKeyring:
        @staticmethod
        def get_keyring() -> object:
            return MacOSKeyring()

    monkeypatch.setattr(KeyringGoogleSecretStore, "_keyring", staticmethod(lambda: FakeKeyring))
    KeyringGoogleSecretStore().ensure_available()


def test_account_metadata_never_contains_secret_material(tmp_path: Path) -> None:
    secrets = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secrets)
    store.save(_account(), GoogleSecret(client_secret="client-secret", refresh_token="refresh"))

    raw = (tmp_path / "accounts.json").read_text(encoding="utf-8")
    assert "client-secret" not in raw
    assert '"refresh_token"' not in raw
    assert '"client_secret"' not in raw
    assert "user@example.com" not in raw
    assert "access_token" not in raw
    assert store.get_active() == _account()
    assert store.load_secret(_account()).refresh_token == "refresh"
    if os.name != "nt":
        assert (tmp_path / "accounts.json").stat().st_mode & 0o777 == 0o600
        assert tmp_path.stat().st_mode & 0o777 == 0o700

    payload = json.loads(raw)
    assert payload["revision"] == 1
    assert (tmp_path / ".accounts.lock").exists()


def test_refresh_patch_preserves_concurrent_reauthorization_fields(tmp_path: Path) -> None:
    secrets = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secrets)
    original = _account()
    store.save(original, GoogleSecret(client_secret="secret", refresh_token="refresh"))
    stale = store.get(original.account_id)
    assert stale is not None

    reauthorized = replace(
        original,
        client_id="new-client.apps.googleusercontent.com",
        services=("calendar-write", "workspace-files"),
        granted_scopes=("openid", "new-scope"),
        updated_at="2026-07-16T01:00:00Z",
    )
    store.save(
        reauthorized,
        GoogleSecret(client_secret="new-secret", refresh_token="new-refresh"),
    )
    updated = store.update_refresh_metadata(
        replace(
            stale,
            token_expires_at=1234.0,
            last_refresh_at="2026-07-16T02:00:00Z",
            updated_at="2026-07-16T02:00:00Z",
        )
    )

    assert updated is False
    current = store.get(original.account_id)
    assert current is not None
    assert current.client_id == reauthorized.client_id
    assert current.services == reauthorized.services
    assert current.granted_scopes == reauthorized.granted_scopes
    assert current.token_expires_at == 0.0
    assert store.load_secret(current).refresh_token == "new-refresh"

    assert store.update_refresh_metadata(
        replace(
            current,
            token_expires_at=5678.0,
            last_refresh_at="2026-07-16T03:00:00Z",
            updated_at="2026-07-16T03:00:00Z",
        ),
        rotated_secret=GoogleSecret(
            client_secret="stale-client-secret",
            refresh_token="rotated-refresh",
        ),
    )
    refreshed = store.get(original.account_id)
    assert refreshed is not None
    assert refreshed.token_expires_at == 5678.0
    refreshed_secret = store.load_secret(refreshed)
    assert refreshed_secret.client_secret == "new-secret"
    assert refreshed_secret.refresh_token == "rotated-refresh"
    assert refreshed_secret.account_email == reauthorized.email
    payload = json.loads((tmp_path / "accounts.json").read_text(encoding="utf-8"))
    assert payload["revision"] == 3


def test_refresh_patch_rejects_same_metadata_with_a_newer_secret(tmp_path: Path) -> None:
    secrets = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secrets)
    original = _account()
    store.save(original, GoogleSecret(client_secret="secret", refresh_token="old-refresh"))
    stale = store.get(original.account_id)
    assert stale is not None

    reauthorized = replace(original, updated_at="2026-07-16T01:00:00Z")
    store.save(
        reauthorized,
        GoogleSecret(client_secret="secret", refresh_token="new-refresh"),
    )

    updated = store.update_refresh_metadata(
        replace(
            stale,
            token_expires_at=1234.0,
            last_refresh_at="2026-07-16T02:00:00Z",
            updated_at="2026-07-16T02:00:00Z",
        ),
        expected_refresh_token="old-refresh",
        rotated_secret=GoogleSecret(
            client_secret="secret",
            refresh_token="stale-rotated-refresh",
        ),
    )

    assert updated is False
    current = store.get(original.account_id)
    assert current is not None
    assert current.token_expires_at == 0.0
    assert current.updated_at == reauthorized.updated_at
    assert store.load_secret(current).refresh_token == "new-refresh"


def test_corrupt_registry_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "accounts.json"
    path.write_text("{broken", encoding="utf-8")
    store = GoogleAccountStore(path, secret_store=MemorySecretStore())
    with pytest.raises(GoogleOAuthError, match="unreadable"):
        store.list_accounts()


def test_authorization_url_has_pkce_state_and_offline_access() -> None:
    url = build_google_authorization_url(
        "abc.apps.googleusercontent.com",
        "http://127.0.0.1:1234/oauth2/callback",
        ("openid", "email"),
        state="state-value",
        code_challenge="challenge-value",
        login_hint="user@example.com",
    )
    params = parse_qs(urlparse(url).query)
    assert params["state"] == ["state-value"]
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"] == ["challenge-value"]
    assert params["access_type"] == ["offline"]
    assert params["prompt"] == ["consent"]
    assert params["login_hint"] == ["user@example.com"]


def test_loopback_receiver_captures_one_callback() -> None:
    receiver = GoogleLoopbackReceiver()
    receiver.start()
    with urllib.request.urlopen(
        f"{receiver.redirect_uri}?code=code-1&state=state-1",
        timeout=2,
    ) as response:
        assert response.status == 200
    result = receiver.wait(2)
    assert result.code == "code-1"
    assert result.state == "state-1"


def test_login_flow_persists_refresh_token_only_in_secret_store(tmp_path: Path) -> None:
    client_path = tmp_path / "client.json"
    client_path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "abc.apps.googleusercontent.com",
                    "client_secret": "client-secret",
                    "project_id": "project-1",
                }
            }
        ),
        encoding="utf-8",
    )
    secret_store = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secret_store)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            assert form["code_verifier"][0]
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "refresh_token": "refresh-token",
                    "expires_in": 3600,
                    "scope": " ".join(google_scopes_for_services(["gmail-send"])),
                },
            )
        if request.url.path == "/v1/userinfo":
            assert request.headers["Authorization"] == "Bearer access-token"
            return httpx.Response(
                200,
                json={"sub": "google-subject", "email": "user@example.com", "name": "User"},
            )
        raise AssertionError(request.url)

    def browser_open(url: str) -> bool:
        params = parse_qs(urlparse(url).query)
        redirect_uri = params["redirect_uri"][0]
        with urllib.request.urlopen(
            f"{redirect_uri}?code=auth-code&state={params['state'][0]}",
            timeout=2,
        ):
            pass
        return True

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        account = login_google(
            client_json=client_path,
            services=("gmail-send",),
            account_store=store,
            browser_open=browser_open,
            http_client=client,
        )

    assert account.email == "user@example.com"
    assert store.load_secret(account) == GoogleSecret(
        client_secret="client-secret",
        refresh_token="refresh-token",
        account_email="user@example.com",
        display_name="User",
    )
    metadata = (tmp_path / "accounts.json").read_text(encoding="utf-8")
    assert "access-token" not in metadata
    assert "refresh-token" not in metadata
    assert "client-secret" not in metadata
    assert "user@example.com" not in metadata


def test_reauthorization_rejects_a_different_browser_identity(tmp_path: Path) -> None:
    client_path = tmp_path / "client.json"
    client_path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "abc.apps.googleusercontent.com",
                    "client_secret": "client-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    secrets = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secrets)
    import hashlib

    active = replace(
        _account(),
        account_id=hashlib.sha256(b"active-subject").hexdigest()[:24],
        client_id="abc.apps.googleusercontent.com",
    )
    active = replace(active, secret_ref=f"account:{active.account_id}")
    store.save(active, GoogleSecret(client_secret="client-secret", refresh_token="refresh"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token",
                    "refresh_token": "other-refresh",
                    "scope": " ".join(google_scopes_for_services(["gmail-send"])),
                },
            )
        return httpx.Response(
            200,
            json={"sub": "other-subject", "email": "other@example.com"},
        )

    def browser_open(url: str) -> bool:
        params = parse_qs(urlparse(url).query)
        assert params["login_hint"] == ["user@example.com"]
        with urllib.request.urlopen(
            f"{params['redirect_uri'][0]}?code=auth-code&state={params['state'][0]}",
            timeout=2,
        ):
            pass
        return True

    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        pytest.raises(GoogleOAuthError, match="--new-account"),
    ):
        login_google(
            client_json=client_path,
            services=("gmail-send",),
            account_store=store,
            browser_open=browser_open,
            http_client=client,
        )

    assert [account.account_id for account in store.list_accounts()] == [active.account_id]


def test_new_account_reuses_client_without_inheriting_active_scopes(tmp_path: Path) -> None:
    secrets = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secrets)
    active = _account()
    store.save(active, GoogleSecret(client_secret="client-secret", refresh_token="refresh"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            form = parse_qs(request.content.decode())
            assert form["client_id"] == [active.client_id]
            assert form["client_secret"] == ["client-secret"]
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "new-refresh",
                    "scope": " ".join(google_scopes_for_services(["calendar-read"])),
                },
            )
        return httpx.Response(
            200,
            json={"sub": "new-subject", "email": "second@example.com"},
        )

    def browser_open(url: str) -> bool:
        params = parse_qs(urlparse(url).query)
        assert "login_hint" not in params
        requested_scopes = set(params["scope"][0].split())
        assert GOOGLE_SERVICE_BUNDLES["calendar-read"].scopes[0] in requested_scopes
        assert GOOGLE_SERVICE_BUNDLES["gmail-send"].scopes[0] not in requested_scopes
        with urllib.request.urlopen(
            f"{params['redirect_uri'][0]}?code=auth-code&state={params['state'][0]}",
            timeout=2,
        ):
            pass
        return True

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        connected = login_google(
            client_json=None,
            services=("calendar-read",),
            new_account=True,
            account_store=store,
            browser_open=browser_open,
            http_client=client,
        )

    assert connected.email == "second@example.com"
    assert connected.services == ("calendar-read",)
    assert len(store.list_accounts()) == 2


def test_revoke_happens_before_local_removal(tmp_path: Path) -> None:
    secrets = MemorySecretStore()
    store = GoogleAccountStore(tmp_path / "accounts.json", secret_store=secrets)
    account = _account()
    store.save(account, GoogleSecret(client_secret="secret", refresh_token="refresh-token"))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(parse_qs(request.content.decode())["token"][0])
        return httpx.Response(200)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        removed = revoke_google_account(
            account_store=store,
            http_client=client,
        )
    assert removed.email == account.email
    assert seen == ["refresh-token"]
    assert store.list_accounts() == []
    assert secrets.values == {}
