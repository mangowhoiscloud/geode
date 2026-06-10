"""geode-mcp HTTP transport guards (v0.99.171).

Pins:
1. Default transport stays stdio — ``--http`` is opt-in.
2. Non-loopback bind without GEODE_MCP_TOKEN is refused (exit 2) — fail-loud,
   not an open remote-execution surface.
3. SDK contract: when a token is configured, ``auth=AuthSettings`` is passed
   alongside ``token_verifier`` — the installed mcp SDK silently SKIPS the
   auth middleware if ``auth`` is None (streamable_http_app gates
   BearerAuthBackend on ``settings.auth``).
4. ``_StaticTokenVerifier`` accepts the exact token, rejects others
   (constant-time compare).
5. Live HTTP round-trip on a loopback port: wrong/no token rejected (401),
   correct token completes initialize + tools/list.
"""

from __future__ import annotations

import asyncio
import socket
import threading

import pytest

pytest.importorskip("mcp")

from core.mcp_server import _is_loopback, _StaticTokenVerifier, create_mcp_server


def test_default_transport_is_stdio_and_http_is_optin() -> None:
    import inspect

    import core.mcp_server as mod

    source = inspect.getsource(mod.main)
    assert 'parser.add_argument(\n        "--http"' in source or '"--http"' in source
    assert 'server.run(transport="streamable-http")' in source
    # stdio default: the no-http branch calls run() with no transport arg
    assert "server.run()" in source


def test_nonloopback_bind_without_token_refused(monkeypatch, capsys) -> None:
    import sys

    import core.mcp_server as mod

    monkeypatch.delenv("GEODE_MCP_TOKEN", raising=False)
    monkeypatch.setattr("core.config.env_io.load_env_files", lambda **_kw: None)
    monkeypatch.setattr(
        sys,
        "argv",
        ["geode-mcp", "--http", "--host", "0.0.0.0"],  # noqa: S104 — guard-under-test
    )
    with pytest.raises(SystemExit) as excinfo:
        mod.main()
    assert excinfo.value.code == 2
    assert "GEODE_MCP_TOKEN" in capsys.readouterr().err


def test_loopback_detection() -> None:
    assert _is_loopback("127.0.0.1")
    assert _is_loopback("localhost")
    assert _is_loopback("::1")
    assert not _is_loopback("0.0.0.0")  # noqa: S104 — the value being classified
    assert not _is_loopback("192.168.0.10")


def test_token_configured_server_carries_auth_settings() -> None:
    server = create_mcp_server(host="127.0.0.1", port=39999, auth_token="sekrit")
    assert server.settings.auth is not None
    assert server._token_verifier is not None


def test_tokenless_server_has_no_auth_settings() -> None:
    server = create_mcp_server(host="127.0.0.1", port=39998)
    assert server.settings.auth is None


def test_static_verifier_accepts_exact_rejects_other() -> None:
    verifier = _StaticTokenVerifier("sekrit")
    ok = asyncio.run(verifier.verify_token("sekrit"))
    bad = asyncio.run(verifier.verify_token("not-it"))
    assert ok is not None and ok.client_id == "geode-mcp-static"
    assert bad is None


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def http_server_with_token():
    """Run the streamable-http app with a token on a loopback port."""
    import uvicorn

    port = _free_port()
    server = create_mcp_server(host="127.0.0.1", port=port, auth_token="sekrit")
    app = server.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    uv_server = uvicorn.Server(config)
    thread = threading.Thread(target=uv_server.run, daemon=True)
    thread.start()
    deadline = 50
    while not uv_server.started and deadline:
        deadline -= 1
        import time

        time.sleep(0.1)
    assert uv_server.started, "uvicorn did not start"
    yield f"http://127.0.0.1:{port}/mcp"
    uv_server.should_exit = True
    thread.join(timeout=5)


def test_http_roundtrip_auth(http_server_with_token) -> None:
    url = http_server_with_token

    async def _with_token() -> list[str]:
        from mcp.client.streamable_http import streamablehttp_client

        from mcp import ClientSession

        async with (
            streamablehttp_client(url, headers={"Authorization": "Bearer sekrit"}) as (
                read,
                write,
                _get_sid,
            ),
            ClientSession(read, write) as session,
        ):
            await asyncio.wait_for(session.initialize(), timeout=15)
            tools = await asyncio.wait_for(session.list_tools(), timeout=10)
            return [tool.name for tool in tools.tools]

    names = asyncio.run(_with_token())
    assert "run_agent" in names and "get_health" in names

    async def _wrong_token_rejected() -> bool:
        from mcp.client.streamable_http import streamablehttp_client

        try:
            async with streamablehttp_client(url, headers={"Authorization": "Bearer wrong"}) as (
                read,
                write,
                _get_sid,
            ):
                from mcp import ClientSession

                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=10)
            return False
        except BaseException:
            return True

    assert asyncio.run(_wrong_token_rejected())

    async def _no_token_rejected() -> bool:
        from mcp.client.streamable_http import streamablehttp_client

        try:
            async with streamablehttp_client(url) as (read, write, _get_sid):
                from mcp import ClientSession

                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(session.initialize(), timeout=10)
            return False
        except BaseException:
            return True

    assert asyncio.run(_no_token_rejected())


def test_http_mode_loads_env_files_for_token(monkeypatch) -> None:
    """The token is a secret → lives in .env; main() must run the shared
    loader before reading GEODE_MCP_TOKEN."""
    import inspect

    import core.mcp_server as mod

    source = inspect.getsource(mod.main)
    assert "load_env_files()" in source
    token_read = 'os.environ.get("GEODE_MCP_TOKEN")'
    assert token_read in source
    assert source.index("load_env_files()") < source.index(token_read)
