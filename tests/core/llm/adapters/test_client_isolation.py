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

import pytest
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
