"""Web Tools — URL fetch and web search as LLM-callable tools.

Provides:
- WebFetchTool: Fetch and extract text from a URL
- GeneralWebSearchTool: Search the web for current information
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from core.config import CONTEXT_BLOCK_MAX_CHARS

if TYPE_CHECKING:
    import httpx

log = logging.getLogger(__name__)


def http_get_with_tls_fallback(url: str, *, timeout: float = 10.0) -> tuple[httpx.Response, bool]:
    """GET *url*, retrying once with TLS verification disabled on ConnectError.

    SSL cert fallback (Python 3.14 + macOS certifi issue).
    PR-AUDIT-AB (2026-06-10) — ConnectError also covers DNS failure /
    connection-refused, so this retry can silently drop TLS verification
    for reasons that have nothing to do with certificates. Keep the
    fallback (the certifi issue is real) but make it observable: warn +
    return the ``tls_verified`` flag so callers tag their results.

    Shared by :class:`WebFetchTool` and
    :class:`core.tools.llms_txt.LlmsTxtIndexTool` (PR-LLMS-TXT-TOOL,
    2026-06-12) so the downgrade behaviour cannot drift between the two
    fetch paths.

    Returns ``(response, tls_verified)``. Propagates ImportError when
    httpx is not installed; callers surface that as a dependency
    tool_error.
    """
    import httpx

    tls_verified = True
    try:
        resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    except httpx.ConnectError:
        log.warning("fetch_url retrying %s with TLS verification DISABLED", url)
        tls_verified = False
        resp = httpx.get(url, timeout=timeout, follow_redirects=True, verify=False)  # noqa: S501  # nosec B501
    return resp, tls_verified


class WebFetchTool:
    """Fetch and extract text content from a URL."""

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return "Fetch and extract text content from a URL."

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        url: str = kwargs["url"]
        max_chars: int = min(kwargs.get("max_chars", CONTEXT_BLOCK_MAX_CHARS), 10000)

        try:
            import httpx
        except ImportError:
            from core.tools.base import tool_error

            return tool_error(
                "httpx not installed",
                error_type="dependency",
                recoverable=False,
                hint="Install httpx: pip install httpx",
            )

        try:
            resp, tls_verified = http_get_with_tls_fallback(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")

            text = self._html_to_text(resp.text) if "text/html" in content_type else resp.text

            return {
                "result": {
                    "url": url,
                    "source": url,  # explicit source tag for grounding
                    "content": text[:max_chars],
                    "truncated": len(text) > max_chars,
                    "content_type": content_type,
                    "status_code": resp.status_code,
                    "tls_verified": tls_verified,
                }
            }
        except httpx.HTTPStatusError as exc:
            from core.tools.base import tool_error

            status = exc.response.status_code
            return tool_error(
                f"HTTP {status}: {url}",
                error_type="connection",
                recoverable=status in (429, 500, 502, 503, 504),
                hint="Retry later." if status == 429 else "Check URL or try a different source.",
                context={"url": url, "status_code": status},
            )
        except Exception as exc:
            from core.tools.base import tool_error

            return tool_error(
                f"Failed to fetch {url}: {exc}",
                error_type="connection",
                hint="Check URL validity or network connectivity.",
                context={"url": url},
            )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run blocking HTTP fetch off the event loop."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to Markdown, preserving structure.

        Uses markdownify for structure-preserving conversion (links,
        headings, code blocks). Falls back to BeautifulSoup text
        extraction if markdownify unavailable.
        Claude Code pattern: Turndown HTML→MD before context injection.
        """
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            cleaned = str(soup)
        except ImportError:
            cleaned = html

        try:
            from markdownify import markdownify as md

            return md(cleaned, heading_style="ATX", strip=["img"])
        except ImportError:
            # Fallback: plain text extraction
            try:
                return soup.get_text(separator="\n", strip=True)
            except NameError:
                import re

                text = re.sub(r"<[^>]+>", " ", html)
                return re.sub(r"\s+", " ", text).strip()


class GeneralWebSearchTool:
    """Search the web via the adapter registry's WebSearchCapable chain.

    PR-ADAPTER-PATTERN-UNIFICATION (2026-05-28) — replaces the legacy
    "instantiate Anthropic/OpenAI/GLM clients with PAYG keys" trio that
    bypassed the adapter registry and PR-SOURCE-ROUTING's
    :func:`infer_source` flow. The tool now delegates to
    :func:`core.llm.adapters.dispatch.web_search_via_adapters`, which
    enumerates registered adapters with ``supports_web_search=True`` and
    orders them by (provider preference) × (operator's source preference
    via :func:`infer_source`) — so the same ``/login`` choice that switches
    the agent loop's main LLM dispatch now also switches the web_search
    tool. Billing-fatal failures surface as :class:`BillingError` with the
    actionable hint instead of six silent retries.
    """

    @property
    def name(self) -> str:
        return "general_web_search"

    @property
    def description(self) -> str:
        today = date.today()
        return (
            f"Search the web for current information on any topic. "
            f"Today is {today.isoformat()} (year {today.year})."
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        max_results: int = kwargs.get("max_results", 5)
        # PR-TOOL-EXEC-CONTEXT (2026-05-28) — see WebSearchTool.aexecute
        # for the same rationale: prefer the loop's resolved (provider,
        # source) so the same ``/login`` choice that switches the main LLM
        # path also switches the web_search adapter selection.
        ctx = kwargs.get("_tool_context")
        prefer_provider = getattr(ctx, "provider", "") or None
        prefer_source = getattr(ctx, "source", "") or None
        # PR-WEB-SEARCH-MODEL-HINT (2026-06-12) — forward the session's
        # resolved model so a capable session model runs its own search
        # instead of always escalating to the provider primary.
        session_model = getattr(ctx, "model", "") or ""
        from core.llm.adapters.dispatch import (
            AdapterDispatchError,
            AdapterUnavailableError,
            web_search_via_adapters,
        )
        from core.llm.errors import BillingError
        from core.tools.base import tool_error

        try:
            result = await web_search_via_adapters(
                query,
                max_results=max_results,
                prefer_provider=prefer_provider,
                prefer_source=prefer_source,
                model=session_model,
            )
        except BillingError as exc:
            # PR-NO-FALLBACK (2026-05-28) — surface the dispatch error
            # verbatim; it already names the exact (adapter, source) that
            # exhausted and the explicit ``/login source`` switch hint.
            return tool_error(
                str(exc),
                error_type="permission",
                recoverable=False,
                hint=(
                    "Top up the exhausted credential, or switch source via "
                    "/login source <subscription|payg|cli>. No automatic fallback."
                ),
                context={"query": query, "provider": exc.provider},
            )
        except AdapterUnavailableError as exc:
            return tool_error(
                str(exc),
                error_type="dependency",
                recoverable=False,
                hint=(
                    "Your current source has no web_search-capable adapter. "
                    "Run /adapters to list available sources and /login source "
                    "<subscription|payg|cli> to switch explicitly."
                ),
                context={"query": query},
            )
        except AdapterDispatchError as exc:
            return tool_error(
                str(exc),
                error_type="connection",
                recoverable=True,
                hint=(
                    "Retry, rephrase the query, or check adapter availability via "
                    "/adapters. No automatic fallback — this is the single attempt result."
                ),
                context={"query": query},
            )
        return {
            "result": {
                "query": result.query,
                "search_results": result.text,
                "source": result.adapter_name,
                "source_urls": list(result.source_urls),
                # PR-DISPATCH-OBS-EXT (2026-05-28) — inline adapter
                # provider + source so ``tool_exec_end`` metadata answers
                # "which adapter handled this" without operators having to
                # cross-correlate by timestamp with ADAPTER_DISPATCH_ATTEMPT.
                "adapter_provider": result.adapter_provider,
                "adapter_source": result.adapter_source,
            }
        }

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        from core.async_runtime import run_process_coroutine

        return run_process_coroutine(self.aexecute(**kwargs))
