"""Codex OAuth runtime cache refresh regressions."""

from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from unittest.mock import patch


class _FakeOpenAI:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def test_legacy_codex_client_rebuilds_when_cli_token_changes(monkeypatch) -> None:
    from core.llm.providers import codex

    current_token = {"value": "access-old"}
    force_refresh_calls: list[bool] = []

    def fake_read_codex_cli_credentials(*, force_refresh: bool = False) -> dict[str, object]:
        force_refresh_calls.append(force_refresh)
        return {
            "access_token": current_token["value"],
            "refresh_token": "refresh-token",
            "expires_at": time.time() + 3600,
        }

    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI, AsyncOpenAI=_FakeOpenAI)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setattr("core.wiring.container.get_profile_store", lambda: None)
    monkeypatch.setattr(
        "core.auth.codex_cli_oauth.read_codex_cli_credentials",
        fake_read_codex_cli_credentials,
    )

    codex.reset_codex_client()
    try:
        first = codex._get_codex_client()
        current_token["value"] = "access-new"
        second = codex._get_codex_client()
    finally:
        codex.reset_codex_client()

    assert first is not None
    assert second is not None
    assert first is not second
    assert first.kwargs["api_key"] == "access-old"
    assert second.kwargs["api_key"] == "access-new"
    assert force_refresh_calls == [True, True]


def test_codex_oauth_adapter_invalidates_loop_cache_when_token_changes(monkeypatch) -> None:
    from core.llm.adapters import codex_oauth
    from core.llm.providers.codex import _ResolvedCodexToken

    current_token = {"value": "access-old"}

    class FakeCache:
        def __init__(self) -> None:
            self.client: dict[str, str] | None = None
            self.invalidations = 0

        def get(self, builder):
            if self.client is None:
                self.client = builder()
            return self.client

        def invalidate(self) -> None:
            self.invalidations += 1
            self.client = None

    def fake_resolve(*, force_refresh: bool = False) -> _ResolvedCodexToken:
        assert force_refresh is True
        return _ResolvedCodexToken(
            token=current_token["value"],
            source="codex-cli:~/.codex/auth.json",
            expires_at=time.time() + 3600,
        )

    fake_cache = FakeCache()
    adapter = codex_oauth.CodexOAuthAdapter()
    adapter._clients = fake_cache
    monkeypatch.setattr("core.llm.providers.codex._resolve_codex_token_info", fake_resolve)
    monkeypatch.setattr(
        codex_oauth,
        "build_async_codex_client",
        lambda token: {"api_key": token},
    )

    first = adapter._get_client()
    again = adapter._get_client()
    current_token["value"] = "access-new"
    second = adapter._get_client()

    assert first is again
    assert second is not first
    assert first["api_key"] == "access-old"
    assert second["api_key"] == "access-new"
    assert fake_cache.invalidations == 2


def test_login_refresh_invalidates_codex_runtime_caches(
    capsys,
    monkeypatch,
) -> None:
    from core.cli.commands.login import cmd_login

    plan_store = SimpleNamespace(
        list_all=lambda: [SimpleNamespace(id="existing-plan")],
    )
    profile_store = SimpleNamespace(
        list_all=lambda: [SimpleNamespace(name="existing:env")],
    )
    invalidate_calls: list[str] = []
    reset_calls: list[str] = []

    monkeypatch.setattr("core.llm.strategies.plan_registry.get_plan_registry", lambda: plan_store)
    monkeypatch.setattr("core.wiring.container.ensure_profile_store", lambda: profile_store)
    monkeypatch.setattr("core.auth.auth_toml.load_auth_toml", lambda: True)
    monkeypatch.setattr("core.auth.auth_toml.auth_toml_path", lambda: "/tmp/auth.toml")  # noqa: S108
    with (
        patch(
            "core.auth.codex_cli_oauth.invalidate_cache",
            side_effect=lambda: invalidate_calls.append("codex-cli"),
        ),
        patch(
            "core.llm.providers.codex.reset_codex_client",
            side_effect=lambda: reset_calls.append("codex"),
        ),
    ):
        cmd_login("refresh")

    assert "auth.toml reloaded" in capsys.readouterr().out
    assert invalidate_calls == ["codex-cli"]
    assert reset_calls == ["codex"]
