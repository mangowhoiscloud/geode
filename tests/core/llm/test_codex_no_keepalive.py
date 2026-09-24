"""Actual SDK clients preserve Codex's keep-alive override and shared timeouts."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from core.config import CODEX_BASE_URL, settings
from core.llm.adapters._openai_common import (
    build_async_codex_client,
    build_async_openai_client,
)


@pytest.mark.parametrize("codex", [False, True], ids=["openai", "codex"])
def test_client_transport_policy(monkeypatch: pytest.MonkeyPatch, codex: bool) -> None:
    async def check() -> None:
        configured = {
            "llm_connect_timeout": 11.0,
            "llm_read_timeout": 29.0,
            "llm_write_timeout": 13.0,
            "llm_pool_timeout": 7.0,
            "llm_max_connections": 19,
            "llm_max_keepalive_connections": 3,
            "llm_keepalive_expiry": 17.0,
        }
        for name, value in configured.items():
            monkeypatch.setattr(settings, name, value)
        builder = build_async_codex_client if codex else build_async_openai_client
        async with builder("test-token") as client:
            transport = client._client
            assert isinstance(transport, httpx.AsyncClient)
            assert transport.timeout == httpx.Timeout(connect=11, read=29, write=13, pool=7)
            assert client.timeout == transport.timeout
            assert client.max_retries == 0
            # HTTPX exposes limits only through the pool; inspect the constructed
            # pool instead of requiring a particular builder implementation.
            pool = transport._transport._pool
            assert pool._max_connections == 19
            assert pool._max_keepalive_connections == (0 if codex else 3)
            assert pool._keepalive_expiry == 17
            if codex:
                assert str(client.base_url).rstrip("/") == CODEX_BASE_URL.rstrip("/")
                assert client.default_headers["originator"] == "codex_cli_rs"
            else:
                assert str(client.base_url) == "https://api.openai.com/v1/"
                assert "originator" not in client.default_headers
        assert transport.is_closed

    asyncio.run(check())
