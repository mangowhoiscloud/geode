"""Adapter client isolation invariants.

Pins Codex MCP review 2026-05-23 BLOCKER fix: each concrete adapter must own
its own AsyncAnthropic / AsyncOpenAI client. Pre-fix the adapters reused the
module-level singletons in ``core.llm.providers.{anthropic,openai}.py`` which
cache the first caller's api_key — so a PAYG adapter constructed first would
permanently shadow the OAuth adapter's credentials (and vice versa).

The invariants (updated for PR-LOOP-POLLUTION-FIX, 2026-06-12):
1. Each adapter holds a per-instance ``_clients`` LoopAffineClientCache
   (empty until first call) — clients are additionally partitioned per
   owning event loop, see core/llm/loop_affinity.py.
2. ``_get_client()`` inside one event loop returns a stable client.
3. The same call on the OAuth adapter returns a DIFFERENT client object than
   the PAYG adapter's (separate instances) — proves no singleton sharing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from core.llm.adapters.anthropic_oauth import (
    CLAUDE_OAUTH_TOKEN_PATH,
    AnthropicOAuthAdapter,
)
from core.llm.adapters.anthropic_payg import AnthropicPaygAdapter
from core.llm.adapters.openai_payg import OpenAIPaygAdapter


def test_anthropic_payg_holds_own_client_cache() -> None:
    """The adapter dataclass exposes a per-instance loop-affine cache."""
    from core.llm.loop_affinity import LoopAffineClientCache

    a = AnthropicPaygAdapter()
    assert isinstance(a._clients, LoopAffineClientCache)
    b = AnthropicPaygAdapter()
    # Two instances → two independent caches.
    assert a._clients is not b._clients


def test_payg_and_oauth_anthropic_get_distinct_clients(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When both PAYG and OAuth adapters are created and their _get_client is
    forced, they must NOT share the same anthropic client object.

    We can't easily mock anthropic SDK construction, so instead we patch the
    shared client builder to record each call and assert it's called twice
    with different api_key values.
    """
    import core.llm.adapters.anthropic_oauth as oauth_mod
    import core.llm.adapters.anthropic_payg as payg_mod
    from core.llm.adapters import _anthropic_common

    # Stub the SDK boundary so we don't hit anthropic.AsyncAnthropic.
    seen_keys: list[str] = []

    def _fake_build(api_key: str) -> object:
        seen_keys.append(api_key)
        return object()  # opaque marker — unique per call

    monkeypatch.setattr(_anthropic_common, "build_async_anthropic_client", _fake_build)
    monkeypatch.setattr(payg_mod, "build_async_anthropic_client", _fake_build)
    monkeypatch.setattr(oauth_mod, "build_async_anthropic_client", _fake_build)

    # Force PAYG to have an api_key and OAuth to have a token file.
    monkeypatch.setattr("core.config.settings.anthropic_api_key", "test-payg-key-123")
    token_file = tmp_path / "oauth-token.json"
    token_file.write_text('{"access_token": "test-oauth-token-456"}', encoding="utf-8")
    monkeypatch.setattr(oauth_mod, "CLAUDE_OAUTH_TOKEN_PATH", token_file)

    payg = AnthropicPaygAdapter()
    oauth = AnthropicOAuthAdapter()

    payg_client = payg._get_client()
    oauth_client = oauth._get_client()

    # Distinct instances + distinct keys passed to the builder.
    assert payg_client is not oauth_client
    assert "test-payg-key-123" in seen_keys
    assert "test-oauth-token-456" in seen_keys


def test_payg_client_cached_per_instance_within_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Within ONE event loop the same instance reuses its client; a fresh
    instance builds its own (no cross-instance sharing)."""
    import asyncio

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


def test_anthropic_oauth_raises_without_token_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Without ~/.claude/oauth-token.json, OAuth raises — does NOT fall through
    to settings.anthropic_api_key.
    """
    import core.llm.adapters.anthropic_oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "CLAUDE_OAUTH_TOKEN_PATH", tmp_path / "missing.json")
    a = AnthropicOAuthAdapter()
    with pytest.raises(RuntimeError, match="Claude OAuth token not found"):
        a._get_client()
    assert CLAUDE_OAUTH_TOKEN_PATH
