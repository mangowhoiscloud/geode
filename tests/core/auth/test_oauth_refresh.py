"""Native refresh uses the selected account and commits only unchanged ownership."""

from __future__ import annotations

import asyncio
import base64
import fcntl
import json
import time
from pathlib import Path

import httpx
import pytest
from core.auth import oauth_refresh as refresh
from core.auth.auth_toml import auth_file_transaction, auth_toml_path
from core.auth.oauth_login import _persist_oauth_to_authtoml
from core.llm.strategies.plan_registry import get_plan_registry
from core.wiring.container import ensure_profile_store


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


def token(expiry: float, account: str = "account-a") -> str:
    body = json.dumps(
        {
            "exp": expiry,
            "https://api.openai.com/auth": {
                "chatgpt_account_id": account,
            },
        }
    ).encode()
    return "header." + base64.urlsafe_b64encode(body).decode().rstrip("=") + ".signature"


@pytest.fixture()
def native(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("core.auth.codex_cli_oauth.sync_codex_cli_profile", lambda *a, **kw: None)
    _persist_oauth_to_authtoml(
        {
            "access_token": token(time.time() - 100),
            "refresh_token": "old-refresh",
            "expires_at": time.time() - 100,
            "account_id": "account-a",
        }
    )
    return auth_toml_path()


def transport(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    client = httpx.AsyncClient
    monkeypatch.setattr(
        refresh.httpx,
        "AsyncClient",
        lambda **kw: client(**kw, transport=httpx.MockTransport(handler)),
    )


@pytest.mark.parametrize("state", ["native", "borrowed", "disabled", "cooldown"])
def test_login_health_matches_refreshable_route(native: Path, state: str) -> None:
    from core.cli.commands.login import build_login_snapshot
    from core.llm.routing import model_available

    profile = ensure_profile_store().get("openai-codex-geode:user")
    assert profile is not None
    if state == "borrowed":
        profile.managed_by = "codex-cli"
    elif state == "disabled":
        profile.disabled = True
    elif state == "cooldown":
        profile.cooldown_until = time.time() + 3600
    before = native.read_bytes()
    row = next(row for row in build_login_snapshot()["profiles"] if row["name"] == profile.name)
    assert row["eligible"] is (state == "native")
    assert model_available("gpt-6.1-sol", source="subscription") is (state == "native")
    if state == "native":
        assert row["reason"] == "refresh_required"
    assert native.read_bytes() == before


@pytest.mark.anyio
async def test_concurrent_requests_rotate_once_and_publish_before_return(
    native: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    new_token = token(time.time() + 3600)

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"access_token": new_token, "refresh_token": "rotated"})

    transport(monkeypatch, handler)
    await asyncio.gather(refresh.refresh_native_oauth(""), refresh.refresh_native_oauth(""))
    assert len(calls) == 1
    assert calls[0]["grant_type"] == "refresh_token"
    assert calls[0]["refresh_token"] == "old-refresh"
    profile = ensure_profile_store().get("openai-codex-geode:user")
    assert profile is not None and profile.key == new_token and profile.refresh_token == "rotated"
    assert "rotated" in native.read_text()
    assert native.stat().st_mode & 0o777 == 0o600


@pytest.mark.anyio
@pytest.mark.parametrize("case", ["other-account", "expired", "rejected", "malformed"])
async def test_failed_refresh_never_replaces_old_credentials(
    native: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    before = native.read_bytes()
    responses = {
        "other-account": httpx.Response(200, json={"access_token": token(time.time() + 3600, "b")}),
        "expired": httpx.Response(200, json={"access_token": token(time.time() - 1)}),
        "rejected": httpx.Response(401, text="secret-response-must-not-escape"),
        "malformed": httpx.Response(200, json=["secret-response-must-not-escape"]),
    }
    transport(monkeypatch, lambda request: responses[case])
    with pytest.raises(refresh.OAuthRefreshError) as error:
        await refresh.refresh_native_oauth("")
    assert "secret-response" not in str(error.value)
    assert native.read_bytes() == before


@pytest.mark.anyio
async def test_account_removed_during_grant_is_not_resurrected(
    native: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        with auth_file_transaction() as (_, store):
            store.remove("openai-codex-geode:user")
        return httpx.Response(200, json={"access_token": token(time.time() + 3600)})

    transport(monkeypatch, handler)
    with pytest.raises(refresh.OAuthRefreshError, match="publication failed"):
        await refresh.refresh_native_oauth("")
    assert ensure_profile_store().get("openai-codex-geode:user") is None


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["disabled", "cooldown", "imported"])
async def test_ineligible_or_borrowed_profiles_do_not_refresh(
    native: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    profile = ensure_profile_store().get("openai-codex-geode:user")
    assert profile is not None
    if state == "disabled":
        profile.disabled = True
    elif state == "cooldown":
        profile.cooldown_until = time.time() + 100
    else:
        profile.managed_by = "codex-cli"

    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("credential owner must not be bypassed")

    transport(monkeypatch, forbidden)
    await refresh.refresh_native_oauth("")


def test_explicit_model_plan_admits_refresh_without_exposing_expired_token(native: Path) -> None:
    from core.llm.adapters.codex_oauth import CodexOAuthAdapter
    from core.llm.providers.codex import _resolve_codex_token_info
    from core.llm.routing import model_available

    get_plan_registry().set_routing("gpt-6.1-sol", ["openai-codex-geode"])
    detection = CodexOAuthAdapter().detect_model_credential("gpt-6.1-sol")
    assert detection is not None and "refresh required" in detection.source_path
    assert model_available("gpt-6.1-sol", source="subscription")
    with pytest.raises(RuntimeError, match="no available account"):
        _resolve_codex_token_info(model="gpt-6.1-sol")


@pytest.mark.anyio
async def test_account_replaced_while_waiting_never_sends_new_account_grant(
    native: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("a waiting request cannot refresh a replacement account")

    transport(monkeypatch, forbidden)
    with native.with_name(f".{native.name}.refresh.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        task = asyncio.create_task(refresh.refresh_native_oauth(""))
        await asyncio.sleep(0.02)
        _persist_oauth_to_authtoml(
            {
                "access_token": token(time.time() - 10, "account-b"),
                "refresh_token": "account-b",
                "expires_at": time.time() - 10,
                "account_id": "account-b",
            }
        )
        fcntl.flock(lock, fcntl.LOCK_UN)
        with pytest.raises(refresh.OAuthRefreshError, match="account or route changed"):
            await task


@pytest.mark.anyio
async def test_route_changed_during_grant_is_not_overwritten(
    native: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.auth.profiles import CredentialType

    def handler(request: httpx.Request) -> httpx.Response:
        with auth_file_transaction() as (_, store):
            profile = store.get("openai-codex-geode:user")
            assert profile is not None
            profile.credential_type = CredentialType.API_KEY
        return httpx.Response(200, json={"access_token": token(time.time() + 3600)})

    transport(monkeypatch, handler)
    with pytest.raises(refresh.OAuthRefreshError, match="publication failed"):
        await refresh.refresh_native_oauth("")
    profile = ensure_profile_store().get("openai-codex-geode:user")
    assert profile is not None and profile.credential_type is CredentialType.API_KEY
    assert profile.is_expired
