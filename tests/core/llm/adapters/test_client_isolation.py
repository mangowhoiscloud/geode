"""Adapter client isolation invariants.

Pins Codex MCP review 2026-05-23 BLOCKER fix: each API adapter must own its
own AsyncAnthropic / AsyncOpenAI client instead of sharing a module singleton.

The invariants (updated for PR-LOOP-POLLUTION-FIX, 2026-06-12):
1. Each adapter holds a per-instance ``_clients`` LoopAffineClientCache
   (empty until first call) — clients are additionally partitioned per
   owning event loop, see core/llm/loop_affinity.py.
2. ``_get_client()`` inside one event loop returns a stable client.
3. Separate adapter instances never share clients.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import openai
import pytest
from core.auth.auth_toml import load_auth_toml, save_auth_toml
from core.auth.profiles import AuthProfile, CredentialType, ProfileStore
from core.auth.rotation import ProfileRotator
from core.cli.commands.login import cmd_login
from core.config import settings
from core.llm.adapters import registry as adapters
from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
from core.llm.adapters.openai_payg import OpenAIPaygAdapter
from core.llm.loop_affinity import drain_current_loop_clients
from core.llm.strategies import plan_registry
from core.llm.strategies.plans import default_plan_for_payg
from core.wiring import container


def test_anthropic_payg_holds_own_client_cache() -> None:
    """The adapter dataclass exposes a per-instance loop-affine cache."""
    from core.llm.loop_affinity import LoopAffineClientCache

    a = AnthropicPaygAdapter()
    assert isinstance(a._clients, LoopAffineClientCache)
    b = AnthropicPaygAdapter()
    # Two instances → two independent caches.
    assert a._clients is not b._clients


def test_payg_client_cached_per_instance_within_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Within ONE event loop the same instance reuses its client; a fresh
    instance builds its own (no cross-instance sharing)."""
    import core.llm.adapters.anthropic_payg as payg_mod

    built: list[object] = []

    def _fake_build(api_key: str) -> object:
        marker = object()
        built.append(marker)
        return marker

    monkeypatch.setattr(payg_mod, "build_async_anthropic_client", _fake_build)
    monkeypatch.setattr("core.config.settings.anthropic_api_key", "test-key")

    async def _exercise() -> None:
        a = AnthropicPaygAdapter()
        first = a._get_client()
        second = a._get_client()
        assert first is second, "same instance + same loop must reuse the client"
        b = AnthropicPaygAdapter()
        assert b._get_client() is not first, "fresh instance must not share"

    asyncio.run(_exercise())
    assert len(built) == 2


def test_openai_payg_holds_own_client_cache() -> None:
    from core.llm.loop_affinity import LoopAffineClientCache

    a = OpenAIPaygAdapter()
    assert isinstance(a._clients, LoopAffineClientCache)


def test_payg_raises_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an api_key, PAYG raises a clear RuntimeError instead of silently
    falling back to OAuth (which would happen with the legacy singleton path).
    """
    monkeypatch.setattr("core.config.settings.anthropic_api_key", "")
    a = AnthropicPaygAdapter()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not set"):
        a._get_client()


_PAYG_CASES = [
    ("openai", "openai_api_key"),
    ("anthropic", "anthropic_api_key"),
    ("glm", "zai_api_key"),
    ("openrouter", "openrouter_api_key"),
]


def _write_auth(path: Path, provider: str, key: str) -> None:
    registry, store = plan_registry.PlanRegistry(), ProfileStore()
    plan = default_plan_for_payg(provider, key)
    registry.add(plan)
    store.add(
        AuthProfile(f"{plan.id}:env", provider, CredentialType.API_KEY, key=key, plan_id=plan.id)
    )
    save_auth_toml(registry=registry, store=store, path=path)


def _setup_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, provider: str, field: str
) -> tuple[Path, ProfileStore]:
    path = tmp_path / "auth.toml"
    monkeypatch.setenv("GEODE_AUTH_TOML", str(path))
    monkeypatch.setattr(settings, field, "synthetic-old")
    registry, store = plan_registry.PlanRegistry(), ProfileStore()
    monkeypatch.setattr(plan_registry, "_plan_registry", registry)
    monkeypatch.setattr(container, "_profile_store", store)
    monkeypatch.setattr(container, "_profile_rotator", ProfileRotator(store))
    _write_auth(path, provider, "synthetic-old")
    assert load_auth_toml()
    return path, store


def _sdk_transport(
    monkeypatch: pytest.MonkeyPatch, provider: str, observed: list[tuple[str, str | None]]
) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        header = (
            request.headers.get("x-api-key")
            if provider == "anthropic"
            else request.headers.get("authorization")
        )
        observed.append((str(request.url), header))
        return httpx.Response(200, json={"data": [], "has_more": False, "object": "list"})

    def build(key, **kwargs):
        # Real SDK auth serialization; only HTTP transport is synthetic.
        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        if provider == "anthropic":
            return anthropic.AsyncAnthropic(api_key=key, http_client=http, max_retries=0)
        return openai.AsyncOpenAI(api_key=key, http_client=http, max_retries=0, **kwargs)

    factory = (
        "build_async_anthropic_client" if provider == "anthropic" else "build_async_openai_client"
    )
    monkeypatch.setattr(f"core.llm.adapters.{provider}_payg.{factory}", build)


@pytest.mark.parametrize("provider,field", _PAYG_CASES)
def test_refresh_captured_payg_sdk_header_after_registry_reload(
    provider, field, tmp_path, monkeypatch
):
    path, store = _setup_state(monkeypatch, tmp_path, provider, field)
    observed: list[tuple[str, str | None]] = []
    _sdk_transport(monkeypatch, provider, observed)
    captured = adapters.registry_snapshot().get_adapter(f"{provider}-payg")
    assert captured.source == "payg"

    async def scenario() -> None:
        before = captured._get_client()
        try:
            await before.models.list()  # Header oracle only, not backend model-catalog acceptance.
            adapters.reload_adapters()
            _write_auth(path, provider, "synthetic-new")
            cmd_login("refresh")
            assert ProfileRotator(store).resolve(provider).key == "synthetic-new"
            after = captured._get_client()
            await after.models.list()
            expected = "synthetic-new" if provider == "anthropic" else "Bearer synthetic-new"
            assert observed[-1][1] == expected
            assert captured.source == "payg"
            assert captured._get_client() is after
            assert captured.test_environment().ok
            assert observed[-1][0].startswith(default_plan_for_payg(provider, "").base_url)
            if provider != "openrouter":
                assert captured.detect_credential().source_path.startswith("auth profile:")
            assert (
                getattr(settings, field) == "synthetic-old"
            )  # External environment owner untouched.
            monkeypatch.setattr(settings, field, "")
            assert captured.test_environment().ok
            assert captured._get_client() is after
            assert after is not before
            assert not before.is_closed()  # In-flight holder remains alive until loop drain.
        finally:
            await drain_current_loop_clients()
        assert before.is_closed() and after.is_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider,field", _PAYG_CASES)
def test_invalid_auth_candidate_keeps_sdk_selection(provider, field, tmp_path, monkeypatch):
    path, store = _setup_state(monkeypatch, tmp_path, provider, field)
    observed: list[tuple[str, str | None]] = []
    _sdk_transport(monkeypatch, provider, observed)
    adapter = adapters.get_adapter(f"{provider}-payg")

    async def scenario() -> None:
        before = adapter._get_client()
        profile = ProfileRotator(store).resolve(provider)
        try:
            path.write_text(
                '[[profiles]]\nname="bad"\nprovider="openai"\ncredential_type="not-valid"\n'
            )
            cmd_login("refresh")
            after = adapter._get_client()
            assert ProfileRotator(store).resolve(provider) is profile
            assert after is before
            await after.models.list()
            expected = "synthetic-old" if provider == "anthropic" else "Bearer synthetic-old"
            assert observed[-1][1] == expected
        finally:
            await drain_current_loop_clients()
        assert before.is_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize("provider,field", _PAYG_CASES)
def test_payg_profile_removal_returns_to_environment_without_borrowing_subscription(
    provider, field, tmp_path, monkeypatch
):
    path, store = _setup_state(monkeypatch, tmp_path, provider, field)
    observed: list[tuple[str, str | None]] = []
    _sdk_transport(monkeypatch, provider, observed)
    monkeypatch.setattr(settings, field, "synthetic-environment")
    adapter = adapters.get_adapter(f"{provider}-payg")

    async def scenario() -> None:
        first = adapter._get_client()
        try:
            # A valid empty file removes its own profile; an external OAuth
            # profile remains live but must never become the PAYG credential.
            profile = ProfileRotator(store).resolve(provider)
            store.add(
                replace(
                    profile,
                    name=f"{provider}:external",
                    credential_type=CredentialType.OAUTH,
                    key="synthetic-subscription",
                    managed_by="external-cli",
                )
            )
            path.write_text("")
            cmd_login("refresh")
            after = adapter._get_client()
            await after.models.list()
            expected = (
                "synthetic-environment"
                if provider == "anthropic"
                else "Bearer synthetic-environment"
            )
            assert observed[-1][1] == expected
            assert adapter.source == "payg"
            assert store.get(f"{provider}:external") is not None
            assert not first.is_closed()
        finally:
            await drain_current_loop_clients()
        assert first.is_closed() and after.is_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "provider,field,endpoint_env",
    [
        ("openai", "openai_api_key", "OPENAI_BASE_URL"),
        ("anthropic", "anthropic_api_key", "ANTHROPIC_BASE_URL"),
    ],
)
def test_sdk_endpoint_override_does_not_receive_default_endpoint_profile_key(
    provider, field, endpoint_env, tmp_path, monkeypatch
):
    _path, store = _setup_state(monkeypatch, tmp_path, provider, field)
    monkeypatch.setattr(settings, field, "synthetic-endpoint-key")
    monkeypatch.setenv(endpoint_env, "https://other.invalid/v1")
    observed: list[tuple[str, str | None]] = []
    _sdk_transport(monkeypatch, provider, observed)
    adapter = adapters.get_adapter(f"{provider}-payg")

    async def scenario() -> None:
        try:
            await adapter._get_client().models.list()
            assert observed[-1][0].startswith("https://other.invalid/v1/")
            assert observed[-1][1].endswith("synthetic-endpoint-key")
            assert adapter.detect_credential().source_path == f"settings.{field}"
            # Explicit matching endpoint ownership can then adopt that profile.
            profile = ProfileRotator(store).resolve(provider)
            profile.base_url_override = "https://other.invalid/v1/"
            await adapter._get_client().models.list()
            assert observed[-1][1].endswith("synthetic-old")
        finally:
            await drain_current_loop_clients()

    asyncio.run(scenario())


def test_payg_auth_refresh_does_not_replace_captured_codex_subscription_client(
    tmp_path, monkeypatch
):
    path, _store = _setup_state(monkeypatch, tmp_path, "openai", "openai_api_key")
    observed: list[tuple[str, str | None]] = []

    def build(token):
        def respond(request: httpx.Request) -> httpx.Response:
            observed.append((str(request.url), request.headers["authorization"]))
            return httpx.Response(200, json={"data": [], "object": "list"})

        return openai.AsyncOpenAI(
            api_key=token,
            base_url="https://chatgpt.com/backend-api/codex",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )

    monkeypatch.setattr(
        "core.llm.providers.codex._resolve_codex_token_info",
        lambda **_: SimpleNamespace(token="synthetic-subscription", fingerprint="unchanged"),
    )
    monkeypatch.setattr("core.llm.adapters.codex_oauth.build_async_codex_client", build)
    captured = adapters.get_adapter("codex-oauth")

    async def scenario() -> None:
        before = captured._get_client()
        try:
            adapters.reload_adapters()
            _write_auth(path, "openai", "synthetic-new-payg")
            cmd_login("refresh")
            assert captured._get_client() is before
            assert captured.source == "subscription"
            await before.models.list()
            assert observed == [
                (
                    "https://chatgpt.com/backend-api/codex/models",
                    "Bearer synthetic-subscription",
                )
            ]
        finally:
            await drain_current_loop_clients()
        assert before.is_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize("producer", ["key", "login-add", "login-set-key", "anthropic-login"])
def test_explicit_api_key_selection_replaces_prior_pin_in_sdk_and_fresh_store(
    producer, tmp_path, monkeypatch
):
    from core.cli.commands.key import cmd_key

    path, store = _setup_state(monkeypatch, tmp_path, "anthropic", "anthropic_api_key")
    old_profile = ProfileRotator(store).resolve("anthropic")
    store.set_active(old_profile.name)
    # Distinct existing identity ensures /key must replace the pin too, not
    # merely update the object that happened to be active.
    prior = replace(old_profile, name="anthropic:prior", key="sk-ant-synthetic-prior")
    store.add(prior)
    store.set_auth_order("anthropic", [prior.name, old_profile.name])
    observed: list[tuple[str, str | None]] = []
    _sdk_transport(monkeypatch, "anthropic", observed)
    adapter = AnthropicPaygAdapter()
    new_key = "sk-ant-synthetic-selected"

    async def scenario() -> None:
        first = adapter._get_client()
        try:
            await first.models.list()
            assert observed[-1][1] == prior.key
            with (
                patch("core.cli.commands._upsert_env"),
                patch("core.cli.commands.login._persist_credential_source"),
                patch("core.cli.commands.console") as console,
                patch("getpass.getpass", return_value=new_key),
                patch("sys.stdin.isatty", return_value=True),
                patch("core.cli.commands.login.TerminalMenu") as menu,
            ):
                menu.side_effect = [
                    MagicMock(show=MagicMock(return_value=1)),
                    MagicMock(show=MagicMock(return_value=0)),
                ]
                console.input.return_value = new_key
                if producer == "key":
                    assert cmd_key(new_key)
                elif producer == "login-add":
                    cmd_login("add")
                elif producer == "login-set-key":
                    cmd_login(f"set-key {old_profile.plan_id} {new_key}")
                else:
                    cmd_login("anthropic")
            after = adapter._get_client()
            await after.models.list()
            assert observed[-1][1] == new_key
            assert store.get_pinned_active("anthropic").key == new_key
            assert not first.is_closed()
            fresh_registry, fresh = plan_registry.PlanRegistry(), ProfileStore()
            assert load_auth_toml(registry=fresh_registry, store=fresh, path=path)
            assert fresh.get_pinned_active("anthropic").key == new_key
            monkeypatch.setattr(plan_registry, "_plan_registry", fresh_registry)
            monkeypatch.setattr(container, "_profile_store", fresh)
            assert adapter._get_client() is after
            await after.models.list()
            assert observed[-1][1] == new_key
        finally:
            await drain_current_loop_clients()

    asyncio.run(scenario())
