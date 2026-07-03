"""browser_scan / browser_execute_js — CDP-attach to a real Chrome.

The live CDP round-trip is unverified (needs a Chrome launched with
--remote-debugging-port); these tests pin the tool contract by mocking the
two transport helpers (``_list_pages`` / ``_evaluate``): tab selection,
compaction reuse, empty-script validation, JS-exception surfacing, and the
connection-refused hint that tells the operator how to launch Chrome.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from core.tools import browser_tools as bt
from core.tools.browser_tools import BrowserExecuteJsTool, BrowserScanTool, _pick_page

_PAGES = [
    {
        "type": "page",
        "url": "chrome://newtab/",
        "title": "New Tab",
        "webSocketDebuggerUrl": "ws://x/1",
    },
    {
        "type": "page",
        "url": "https://example.com/list",
        "title": "Example",
        "webSocketDebuggerUrl": "ws://x/2",
    },
]


def _run(coro: Any) -> dict[str, Any]:
    return asyncio.run(coro)


def test_pick_page_prefers_real_http_tab_over_chrome_internal() -> None:
    assert _pick_page(_PAGES, None)["url"] == "https://example.com/list"


def test_pick_page_honors_url_contains() -> None:
    assert _pick_page(_PAGES, "example")["url"] == "https://example.com/list"
    assert _pick_page(_PAGES, "nomatch") is None


def test_scan_returns_compacted_content(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<html><body><h1>Title</h1><p>Body text here</p></body></html>"

    async def _pages(_endpoint: str, **_kw: Any) -> list[dict[str, Any]]:
        return _PAGES

    async def _eval(_ws: str, _expr: str, **_kw: Any) -> str:
        return html

    monkeypatch.setattr(bt, "_list_pages", _pages)
    monkeypatch.setattr(bt, "_evaluate", _eval)
    out = _run(BrowserScanTool().aexecute())["result"]
    assert out["url"] == "https://example.com/list"
    assert "Title" in out["content"]
    assert len(out["tabs"]) == 2


def test_scan_tabs_only_skips_page_readout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _pages(_endpoint: str, **_kw: Any) -> list[dict[str, Any]]:
        return _PAGES

    def _boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("_evaluate must not be called for tabs_only")

    monkeypatch.setattr(bt, "_list_pages", _pages)
    monkeypatch.setattr(bt, "_evaluate", _boom)
    out = _run(BrowserScanTool().aexecute(tabs_only=True))["result"]
    assert "content" not in out
    assert len(out["tabs"]) == 2


def test_execute_js_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _pages(_endpoint: str, **_kw: Any) -> list[dict[str, Any]]:
        return _PAGES

    async def _eval(_ws: str, expr: str, **_kw: Any) -> str:
        assert expr == "document.title"
        return "Example"

    monkeypatch.setattr(bt, "_list_pages", _pages)
    monkeypatch.setattr(bt, "_evaluate", _eval)
    out = _run(BrowserExecuteJsTool().aexecute(script="document.title"))["result"]
    assert out["js_return"] == "Example"


def test_execute_js_empty_script_is_validation_error() -> None:
    out = _run(BrowserExecuteJsTool().aexecute(script="   "))
    assert out["error_type"] == "validation"
    assert "error" in out


def test_execute_js_surfaces_js_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _pages(_endpoint: str, **_kw: Any) -> list[dict[str, Any]]:
        return _PAGES

    async def _eval(_ws: str, _expr: str, **_kw: Any) -> str:
        raise RuntimeError("JS exception: ReferenceError: foo is not defined")

    monkeypatch.setattr(bt, "_list_pages", _pages)
    monkeypatch.setattr(bt, "_evaluate", _eval)
    out = _run(BrowserExecuteJsTool().aexecute(script="foo()"))
    assert out["error_type"] == "validation"
    assert "ReferenceError" in out["error"]


def test_connection_refused_gives_launch_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _refused(_endpoint: str, **_kw: Any) -> list[dict[str, Any]]:
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(bt, "_list_pages", _refused)
    out = _run(BrowserScanTool().aexecute())
    assert out["error_type"] == "connection"
    assert "remote-debugging-port" in out["hint"]
