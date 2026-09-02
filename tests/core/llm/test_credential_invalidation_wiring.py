"""Credential changes must drop the clients that actually serve traffic.

2026-07-29 incident class: ``/key`` and ``/login`` reset the ``providers/``
SYNC singletons, a surface the live path stopped using long before they were
deleted — so a rotated key kept flowing through a stale ADAPTER client until
restart.

The caches are loop-affine: ``LoopAffineClientCache.get()`` only stores an
entry when a loop is running (``core/llm/loop_affinity.py``). A first draft of
these tests seeded them from sync code, cached nothing, and passed vacuously
(Codex review) — every state assertion below therefore runs inside
``asyncio.run`` and checks ``bound_loop_count()``.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from core.llm.adapters.registry import (
    _REGISTRY,
    bootstrap_builtins,
    invalidate_provider_clients,
    normalize_registry_provider,
)

_REPO = Path(__file__).resolve().parents[3]


def _cached_adapters() -> list[Any]:
    bootstrap_builtins()
    return [a for a in _REGISTRY.values() if getattr(a, "_clients", None) is not None]


@pytest.fixture(autouse=True)
def _isolate_caches() -> Any:
    """Leave no bound loops behind for the next test."""
    yield
    for adapter in _cached_adapters():
        adapter._clients.invalidate()


def _seed(adapters: list[Any]) -> None:
    for adapter in adapters:
        adapter._clients.get(object)


def test_invalidate_empties_bound_caches() -> None:
    adapters = _cached_adapters()
    assert adapters, "no adapter exposes a client cache — wiring assumption broken"

    async def _scenario() -> tuple[list[int], list[int]]:
        _seed(adapters)
        before = [a._clients.bound_loop_count() for a in adapters]
        invalidate_provider_clients()
        return before, [a._clients.bound_loop_count() for a in adapters]

    before, after = asyncio.run(_scenario())
    assert all(n == 1 for n in before), f"seeding failed — caches never bound: {before}"
    assert all(n == 0 for n in after), f"invalidation left bound clients: {after}"


def test_invalidate_is_scoped_to_one_provider() -> None:
    adapters = _cached_adapters()
    target = normalize_registry_provider("anthropic")
    assert any(a.provider == target for a in adapters)
    assert any(a.provider != target for a in adapters), "need a non-target adapter"

    async def _scenario() -> tuple[list[int], list[int]]:
        _seed(adapters)
        invalidate_provider_clients("anthropic")
        return (
            [a._clients.bound_loop_count() for a in adapters if a.provider == target],
            [a._clients.bound_loop_count() for a in adapters if a.provider != target],
        )

    hit, untouched = asyncio.run(_scenario())
    assert all(n == 0 for n in hit), f"target provider not invalidated: {hit}"
    assert all(n == 1 for n in untouched), f"unrelated providers were dropped: {untouched}"


def test_login_refresh_calls_adapter_invalidation() -> None:
    """``/login refresh`` must drop adapter clients, not just provider caches."""
    from core.cli.commands import login as login_mod

    with (
        patch("core.llm.adapters.registry.invalidate_provider_clients") as mock_inv,
        patch("core.auth.auth_toml.load_auth_toml", return_value=True),
        patch("core.auth.codex_cli_oauth.invalidate_cache"),
        patch("core.mcp.google_workspace_client.reset_google_workspace_client"),
        # The CLI surface may bail on environment; the invalidation call is
        # what this pins.
        contextlib.suppress(Exception),
    ):
        login_mod.cmd_login("refresh")

    assert mock_inv.called, "/login refresh did not invalidate adapter clients"
    assert mock_inv.call_args.args[0] == "openai"


def test_codex_oauth_refresh_in_fallback_invalidates() -> None:
    """The codex-cli token refresh re-calls with a new token — the adapter's
    cached client must go (it reads the token at build time)."""
    import core.llm.fallback as fallback_mod

    profile = type("P", (), {"managed_by": "codex-cli", "name": "codex"})()
    rotator = type("R", (), {"resolve": staticmethod(lambda _p: profile)})()

    with (
        patch("core.llm.adapters.registry.invalidate_provider_clients") as mock_inv,
        patch("core.auth.codex_cli_oauth.refresh_codex_cli_token", return_value=True),
        patch("core.wiring.container.get_profile_rotator", return_value=rotator),
    ):
        assert fallback_mod._try_oauth_refresh("openai") is True

    mock_inv.assert_called_once_with("openai")


@pytest.mark.parametrize(
    "rel_path",
    ["core/cli/commands/key.py", "core/cli/commands/login.py", "core/llm/fallback.py"],
)
def test_credential_modules_reference_the_live_entry_point(rel_path: str) -> None:
    """Cheap breadth check over every credential-changing module — the
    behavioural pins above cover two of them in depth."""
    src = (_REPO / rel_path).read_text(encoding="utf-8")
    assert "invalidate_provider_clients" in src, (
        f"{rel_path} changes credentials without dropping adapter clients"
    )


def test_key_command_invalidates_for_every_provider_branch() -> None:
    """``/key`` invalidates every built-in API-key provider."""
    src = (_REPO / "core/cli/commands/key.py").read_text(encoding="utf-8")
    invalidated = {
        node.args[0].value
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_invalidate"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }
    assert {"anthropic", "openai", "openrouter", "glm"} <= invalidated, (
        f"/key branches missing adapter invalidation: {invalidated}"
    )
