"""Browser Tools — drive the operator's *real* Chrome over CDP.

Unlike :class:`core.tools.web_tools.WebFetchTool` (a headless ``httpx`` GET
with no JS execution) and the pixel-based ``computer_use`` harness, these
tools attach to a normally-launched Chrome via the Chrome DevTools Protocol
debug endpoint. Because it is the operator's own browser process — real
profile, cookies, login sessions, GPU/WebGL fingerprint — pages that block
headless automation (login walls, SPAs, CAPTCHA risk scoring) behave as they
do for a human. Attaching CDP to an already-running Chrome does *not* set
``navigator.webdriver`` (that flag comes from the ``--enable-automation`` flag
Selenium/Playwright add when they *launch* a browser), so the session stays
indistinguishable from manual use.

Approach note (why CDP, not a Chrome extension): GenericAgent's TMWebdriver
gets the same real-session realness via a bundled extension + local WebSocket
server. CDP-attach reaches the identical outcome (real profile preserved) with
no artifact to build, install, or maintain — the ``websockets`` client is
already an installed dependency. The one manual step is symmetric: launch
Chrome with ``--remote-debugging-port=9222`` instead of dragging an extension
into ``chrome://extensions``.

live-status: unverified — live test required. The CDP round-trip is exercised
only against a mocked transport in tests; end-to-end CAPTCHA/login survival
needs a live Chrome launched with the debug port (see ``hint`` on connection
errors).

Two tools:
- ``browser_scan``     — list tabs + return a compacted text view of a page.
- ``browser_execute_js`` — run arbitrary JS in a tab for full control.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "http://127.0.0.1:9222"
_CONNECT_HINT = (
    "No Chrome DevTools endpoint at {endpoint}. Launch Chrome with remote "
    "debugging first, e.g.\n"
    "  macOS:  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
    "--remote-debugging-port=9222\n"
    "  Linux:  google-chrome --remote-debugging-port=9222\n"
    "Use your normal profile so login sessions are preserved. Override the "
    "endpoint with the GEODE_CDP_ENDPOINT env var if you use a different port."
)


def _endpoint() -> str:
    return os.environ.get("GEODE_CDP_ENDPOINT", _DEFAULT_ENDPOINT).rstrip("/")


async def _list_pages(endpoint: str, *, timeout: float = 5.0) -> list[dict[str, Any]]:
    """Return CDP page targets (``/json/list``), most-recent first."""
    import httpx

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{endpoint}/json/list")
        resp.raise_for_status()
        targets = resp.json()
    return [t for t in targets if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]


def _pick_page(pages: list[dict[str, Any]], url_contains: str | None) -> dict[str, Any] | None:
    if not pages:
        return None
    if url_contains:
        return next((p for p in pages if url_contains in (p.get("url") or "")), None)
    # Skip devtools:// / chrome:// chrome-internal tabs when a real page exists.
    real = [p for p in pages if (p.get("url") or "").startswith(("http://", "https://", "file://"))]
    return (real or pages)[0]


async def _evaluate(ws_url: str, expression: str, *, timeout: float = 20.0) -> Any:
    """Runtime.evaluate *expression* on the page at *ws_url*; return its value.

    Wraps the expression so ``await`` works and a plain last-expression value
    is returned by value. Raises RuntimeError on a JS exception so the caller
    surfaces it as a tool_error rather than a silent null.
    """
    import websockets

    # Wrap so top-level await is legal and the result is serialisable.
    wrapped = f"(async () => {{ return ({expression}); }})()"
    payload = json.dumps(
        {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": wrapped,
                "returnByValue": True,
                "awaitPromise": True,
                "userGesture": True,
            },
        }
    )
    async with websockets.connect(ws_url, max_size=None, open_timeout=timeout) as ws:
        await ws.send(payload)
        async with asyncio.timeout(timeout):
            while True:
                msg = json.loads(await ws.recv())
                if msg.get("id") != 1:
                    continue  # ignore unsolicited protocol events
                if "error" in msg:
                    raise RuntimeError(f"CDP error: {msg['error'].get('message', msg['error'])}")
                result = msg.get("result", {})
                exc = result.get("exceptionDetails")
                if exc:
                    text = exc.get("exception", {}).get("description") or exc.get(
                        "text", "JS error"
                    )
                    raise RuntimeError(f"JS exception: {text}")
                return result.get("result", {}).get("value")


class _BrowserToolBase:
    async def _resolve_page(self, url_contains: str | None) -> dict[str, Any]:
        endpoint = _endpoint()
        pages = await _list_pages(endpoint)
        page = _pick_page(pages, url_contains)
        if page is None:
            from core.tools.base import tool_error

            detail = (
                f"no tab matching url_contains={url_contains!r}"
                if url_contains
                else "no open browser tab"
            )
            raise _ToolError(
                tool_error(
                    f"browser: {detail}",
                    error_type="connection",
                    recoverable=True,
                    hint="Open the page in Chrome, or omit url_contains for the active tab.",
                    context={"endpoint": endpoint, "open_tabs": len(pages)},
                )
            )
        return page

    def _connect_error(self, exc: Exception) -> dict[str, Any]:
        from core.tools.base import tool_error

        return tool_error(
            f"browser: cannot reach Chrome ({type(exc).__name__})",
            error_type="connection",
            recoverable=True,
            hint=_CONNECT_HINT.format(endpoint=_endpoint()),
            context={"endpoint": _endpoint()},
        )


class _ToolError(Exception):
    """Carries an already-formed tool_error dict up to aexecute."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload


class BrowserScanTool(_BrowserToolBase):
    """List browser tabs and return a compacted text view of a page."""

    @property
    def name(self) -> str:
        return "browser_scan"

    @property
    def description(self) -> str:
        return "Perceive a real Chrome tab (via CDP): list tabs and return compacted page text."

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        import httpx

        from core.config import CONTEXT_BLOCK_MAX_CHARS
        from core.tools.web_tools import WebFetchTool

        url_contains: str | None = kwargs.get("url_contains")
        tabs_only: bool = kwargs.get("tabs_only", False)
        max_chars: int = min(kwargs.get("max_chars", CONTEXT_BLOCK_MAX_CHARS), 35000)
        try:
            endpoint = _endpoint()
            pages = await _list_pages(endpoint)
            tabs = [
                {"url": (p.get("url") or "")[:120], "title": (p.get("title") or "")[:80]}
                for p in pages
            ]
            if tabs_only:
                return {"result": {"tabs": tabs, "active_endpoint": endpoint}}
            page = _pick_page(pages, url_contains)
            if page is None:
                return await self._resolve_page(url_contains)  # raises _ToolError
            html = await _evaluate(
                page["webSocketDebuggerUrl"], "document.documentElement.outerHTML"
            )
            # ponytail: reuse WebFetchTool's HTML→text compaction (tag-strip +
            # markdownify + repeated-list collapse). Upgrade path: inject a
            # visibility-based DOM prune JS (GenericAgent simphtml) before
            # readout to also drop off-screen/overlay chrome — needs a live DOM,
            # which we have here, unlike web_fetch's static HTML.
            text = WebFetchTool._html_to_text(html or "")
            return {
                "result": {
                    "url": page.get("url", ""),
                    "source": page.get("url", ""),
                    "title": page.get("title", ""),
                    "tabs": tabs,
                    "content": text[:max_chars],
                    "truncated": len(text) > max_chars,
                }
            }
        except _ToolError as exc:
            return exc.payload
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as exc:
            return self._connect_error(exc)
        except Exception as exc:
            from core.tools.base import tool_error

            return tool_error(
                f"browser_scan failed: {exc}",
                error_type="connection",
                hint="Check the tab is loaded and reachable via CDP.",
                context={"url_contains": url_contains},
            )

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        from core.async_runtime import run_process_coroutine

        return run_process_coroutine(self.aexecute(**kwargs))


class BrowserExecuteJsTool(_BrowserToolBase):
    """Run arbitrary JavaScript in a real Chrome tab for full control."""

    @property
    def name(self) -> str:
        return "browser_execute_js"

    @property
    def description(self) -> str:
        return (
            "Execute JavaScript in a real Chrome tab (via CDP) and return its value. "
            "Top-level await is supported; return a serialisable value."
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        import httpx

        script: str = kwargs.get("script", "")
        url_contains: str | None = kwargs.get("url_contains")
        if not script.strip():
            from core.tools.base import tool_error

            return tool_error(
                "browser_execute_js: empty script",
                error_type="validation",
                recoverable=False,
                hint="Pass a non-empty 'script' expression.",
            )
        try:
            page = await self._resolve_page(url_contains)
            value = await _evaluate(page["webSocketDebuggerUrl"], script)
            return {
                "result": {
                    "url": page.get("url", ""),
                    "source": page.get("url", ""),
                    "js_return": value,
                }
            }
        except _ToolError as exc:
            return exc.payload
        except (httpx.ConnectError, httpx.ConnectTimeout, OSError) as exc:
            return self._connect_error(exc)
        except RuntimeError as exc:
            from core.tools.base import tool_error

            return tool_error(
                str(exc),
                error_type="validation",
                recoverable=True,
                hint="Fix the JS (check the tab's console) and retry.",
                context={"url_contains": url_contains},
            )
        except Exception as exc:
            from core.tools.base import tool_error

            return tool_error(
                f"browser_execute_js failed: {exc}",
                error_type="connection",
                hint="Check the tab is loaded and reachable via CDP.",
                context={"url_contains": url_contains},
            )

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        from core.async_runtime import run_process_coroutine

        return run_process_coroutine(self.aexecute(**kwargs))
