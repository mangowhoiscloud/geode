"""Native OAuth persistence, failure and concurrent login boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.auth.oauth_login import _persist_oauth_to_authtoml


def _isolate(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(path))
    return path


def _stored_token() -> str:
    from core.wiring.container import ensure_profile_store

    return ensure_profile_store().get("openai-codex-geode:user").key


def test_persisted_native_login_is_active_and_private(tmp_path, monkeypatch):
    from core.wiring.container import ensure_profile_store

    path = _isolate(tmp_path, monkeypatch)
    legacy = tmp_path / "auth.json"
    legacy.write_text('{"providers":{"openai":{"access_token":"legacy"}}}')
    previous = legacy.read_bytes()
    _persist_oauth_to_authtoml({"access_token": "native", "refresh_token": "refresh"})
    assert _stored_token() == "native"
    assert ensure_profile_store().get_pinned_active("openai-codex").key == "native"
    assert oct(path.stat().st_mode)[-3:] == "600"
    assert legacy.read_bytes() == previous


class TestCmdLogin:
    def test_login_no_args(self):
        from core.cli.commands import cmd_login

        # Should not raise, just print help
        cmd_login("")

    def test_login_status(self, tmp_path: Path, monkeypatch):
        from core.cli.commands import cmd_login

        _isolate(tmp_path, monkeypatch)
        cmd_login("status")  # Should not raise

    def test_login_unknown_provider(self):
        from core.cli.commands import cmd_login

        cmd_login("unknown_provider")  # Should print error, not raise

    def test_login_in_command_map(self):
        from core.cli.commands import COMMAND_MAP

        assert "/login" in COMMAND_MAP
        assert COMMAND_MAP["/login"] == "login"


def _build_fake_jwt(claims: dict) -> str:
    """Construct a JWT-shaped string with ``claims`` as the payload.

    Signature is bogus — ``decode_jwt_claims`` does no verification.
    """
    import base64
    import json

    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    body = (
        base64.urlsafe_b64encode(json.dumps(claims, separators=(",", ":")).encode())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{body}.signature"


class TestJWTDecode:
    """`decode_jwt_claims` + `_plan_type_from_token` — regression for the
    v0.95.x plan tier reconciliation path."""

    def test_decode_valid_jwt(self):
        from core.auth.jwt_claims import decode_jwt_claims

        token = _build_fake_jwt(
            {
                "https://api.openai.com/auth": {"chatgpt_plan_type": "pro"},
                "https://api.openai.com/profile": {"email": "u@example.com"},
                "exp": 9999999999,
            }
        )
        claims = decode_jwt_claims(token)
        assert claims["exp"] == 9999999999
        assert claims["https://api.openai.com/auth"]["chatgpt_plan_type"] == "pro"

    def test_decode_malformed_returns_empty(self):
        from core.auth.jwt_claims import decode_jwt_claims

        # Fewer than 2 dot-separated parts → early return.
        assert decode_jwt_claims("not-a-jwt") == {}
        assert decode_jwt_claims("") == {}
        # 2+ parts but the payload section is not valid base64+JSON.
        assert decode_jwt_claims("garbage.payload.sig") == {}
        assert decode_jwt_claims("only.one") == {}

    def test_plan_type_extraction(self):
        from core.auth.oauth_login import _plan_type_from_token

        token = _build_fake_jwt({"https://api.openai.com/auth": {"chatgpt_plan_type": "max"}})
        assert _plan_type_from_token(token) == "max"

    def test_plan_type_missing_claim(self):
        from core.auth.oauth_login import _plan_type_from_token

        token = _build_fake_jwt({"some_other_claim": "x"})
        assert _plan_type_from_token(token) == ""


def test_persisting_new_tokens_records_their_plan_tier(tmp_path: Path, monkeypatch) -> None:
    from core.auth.oauth_login import _GEODE_OPENAI_PLAN_ID, _persist_oauth_to_authtoml
    from core.llm.strategies.plan_registry import get_plan_registry, reset_plan_registry

    _isolate(tmp_path, monkeypatch)
    _persist_oauth_to_authtoml({"access_token": "first-token", "plan_type": "plus"})
    _persist_oauth_to_authtoml({"access_token": "second-token", "plan_type": "pro"})
    assert get_plan_registry().get(_GEODE_OPENAI_PLAN_ID).subscription_tier == "pro"

    reset_plan_registry()
    from core.auth.auth_toml import load_auth_toml

    assert load_auth_toml()
    assert get_plan_registry().get(_GEODE_OPENAI_PLAN_ID).subscription_tier == "pro"


def _mock_login_transport(monkeypatch, handler):
    import httpx
    from core.auth import oauth_login

    client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handler))
    )
    monkeypatch.setattr(oauth_login.time, "sleep", lambda seconds: None)
    events = []
    for event in ("started", "pending", "success", "failed"):
        monkeypatch.setattr(
            f"core.ui.agentic_ui.emit_oauth_login_{event}",
            lambda *args, _event=event, **kwargs: events.append((_event, args, kwargs)),
        )
    return events


def test_native_login_rejects_overlap_and_releases_after_cancel(tmp_path, monkeypatch) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import httpx
    import pytest
    from core.auth import oauth_login

    _isolate(tmp_path, monkeypatch)
    oauth_login._persist_oauth_to_authtoml({"access_token": "previous"})
    started, finish = Event(), Event()

    def transport(request):
        started.set()
        assert finish.wait(5)
        raise KeyboardInterrupt

    client = httpx.Client
    events = _mock_login_transport(monkeypatch, transport)
    with ThreadPoolExecutor(max_workers=1) as pool:
        attempt = pool.submit(oauth_login.login_openai)
        assert started.wait(5)
        with pytest.raises(ValueError, match="already in progress"):
            oauth_login.login_openai()
        finish.set()
        assert attempt.result(5) == {}
    assert [event[0] for event in events] == ["failed"]
    assert _stored_token() == "previous"

    token = _build_fake_jwt(
        {"exp": 9999999999, "https://api.openai.com/auth": {"chatgpt_plan_type": "prolite"}}
    )

    def success(request):
        if request.url == oauth_login._DEVICE_CODE_URL:
            return httpx.Response(200, json={"user_code": "code", "device_auth_id": "device"})
        if request.url == oauth_login._DEVICE_TOKEN_URL:
            return httpx.Response(200, json={"authorization_code": "code", "code_verifier": "v"})
        return httpx.Response(200, json={"access_token": token, "refresh_token": "refresh"})

    monkeypatch.setattr(httpx, "Client", client)
    success_events = _mock_login_transport(monkeypatch, success)
    assert oauth_login.login_openai()["access_token"] == token
    assert [event[0] for event in success_events] == ["started", "success"]
    assert success_events[-1][2]["stored_at"] == str(tmp_path / "auth.toml")
    assert success_events[-1][2]["plan_type"] == "ChatGPT Pro Lite"
    assert _stored_token() == token


def test_native_login_failure_after_start_has_one_terminal_event(tmp_path, monkeypatch) -> None:
    import httpx
    import pytest
    from core.auth import oauth_login

    _isolate(tmp_path, monkeypatch)
    oauth_login._persist_oauth_to_authtoml({"access_token": "previous"})

    def failure(request):
        if request.url == oauth_login._DEVICE_CODE_URL:
            return httpx.Response(200, json={"user_code": "code", "device_auth_id": "device"})
        if request.url == oauth_login._DEVICE_TOKEN_URL:
            return httpx.Response(200, json={"authorization_code": "code", "code_verifier": "v"})
        return httpx.Response(500)

    events = _mock_login_transport(monkeypatch, failure)
    with pytest.raises(RuntimeError, match="Token exchange returned status 500"):
        oauth_login.login_openai()
    assert [event[0] for event in events] == ["started", "failed"]
    assert _stored_token() == "previous"


@pytest.mark.parametrize("stage", ["device", "poll", "exchange", "persist"])
@pytest.mark.parametrize("cancel", [False, True])
def test_login_failure_or_cancel_does_not_publish(stage, cancel, tmp_path, monkeypatch):
    import httpx
    from core.auth import oauth_login

    path = _isolate(tmp_path, monkeypatch)
    oauth_login._persist_oauth_to_authtoml({"access_token": "previous"})
    before = path.read_bytes()

    def fail():
        if cancel:
            raise KeyboardInterrupt
        raise OSError("controlled failure")

    def transport(request):
        route = {
            oauth_login._DEVICE_CODE_URL: "device",
            oauth_login._DEVICE_TOKEN_URL: "poll",
            oauth_login._TOKEN_URL: "exchange",
        }[str(request.url)]
        if stage == route:
            fail()
        if route == "device":
            return httpx.Response(200, json={"user_code": "code", "device_auth_id": "device"})
        if route == "poll":
            return httpx.Response(200, json={"authorization_code": "code", "code_verifier": "v"})
        return httpx.Response(200, json={"access_token": "candidate", "refresh_token": "r"})

    events = _mock_login_transport(monkeypatch, transport)
    if stage == "persist":
        monkeypatch.setattr(oauth_login, "_persist_oauth_to_authtoml", lambda creds: fail())
    if cancel:
        assert oauth_login.login_openai() == {}
    else:
        with pytest.raises((OSError, RuntimeError)):
            oauth_login.login_openai()
    assert path.read_bytes() == before
    assert _stored_token() == "previous"
    assert [event[0] for event in events].count("failed") == 1
    assert not any(event[0] == "success" for event in events)


@pytest.mark.parametrize(
    "conflict",
    ["provider", "kind", "auth_type", "endpoint", "profile-endpoint", "live-profile", "live-plan"],
)
def test_native_login_rejects_owner_or_route_collision_before_write(
    conflict, tmp_path, monkeypatch
):
    from dataclasses import replace

    import httpx
    from core.auth import oauth_login
    from core.auth.auth_toml import save_auth_toml
    from core.llm.strategies.plan_registry import get_plan_registry
    from core.llm.strategies.plans import PlanKind
    from core.wiring.container import ensure_profile_store

    path = _isolate(tmp_path, monkeypatch)
    _persist_oauth_to_authtoml({"access_token": "previous"})
    registry, store = get_plan_registry(), ensure_profile_store()
    plan = registry.get("openai-codex-geode")
    profile = store.get("openai-codex-geode:user")
    if conflict == "live-profile":
        store.add(replace(profile, key="foreign", managed_by="another-owner"))
    elif conflict == "live-plan":
        registry.add(replace(plan, display_name="foreign"))
    elif conflict == "profile-endpoint":
        store.add(replace(profile, base_url_override="https://other.invalid/v1"))
        save_auth_toml(registry=registry, store=store)
    else:
        changes = {
            "provider": {"provider": "openai"},
            "kind": {"kind": PlanKind.PAYG},
            "auth_type": {"auth_type": "bearer"},
            "endpoint": {"base_url": "https://other.invalid/v1"},
        }[conflict]
        registry.add(replace(plan, **changes))
        if conflict == "provider":
            store.remove(profile.name)
            store.add(replace(profile, provider="openai"), activate=True)
        save_auth_toml(registry=registry, store=store)
    before = path.read_bytes()
    retained = store.get(profile.name)

    def transport(request):
        if request.url == oauth_login._DEVICE_CODE_URL:
            return httpx.Response(200, json={"user_code": "code", "device_auth_id": "device"})
        if request.url == oauth_login._DEVICE_TOKEN_URL:
            return httpx.Response(200, json={"authorization_code": "code", "code_verifier": "v"})
        return httpx.Response(200, json={"access_token": "candidate", "refresh_token": "r"})

    events = _mock_login_transport(monkeypatch, transport)
    with pytest.raises(ValueError, match=r"owner|conflicts"):
        oauth_login.login_openai()
    assert path.read_bytes() == before
    assert store.get(profile.name) is retained
    assert [event[0] for event in events] == ["started", "failed"]


@pytest.mark.parametrize("trailing_slash", [False, True])
def test_native_login_accepts_canonical_profile_endpoint(tmp_path, monkeypatch, trailing_slash):
    from core.auth.auth_toml import save_auth_toml
    from core.config import CODEX_BASE_URL
    from core.llm.providers.codex import _resolve_codex_token_info
    from core.wiring.container import ensure_profile_store

    _isolate(tmp_path, monkeypatch)
    _persist_oauth_to_authtoml({"access_token": "previous"})
    profile = ensure_profile_store().get("openai-codex-geode:user")
    profile.base_url_override = CODEX_BASE_URL + ("/" if trailing_slash else "")
    save_auth_toml()
    _persist_oauth_to_authtoml({"access_token": "new"})
    assert _resolve_codex_token_info(force_refresh=True).token == "new"
