"""arXiv Tools — paper search + fetch as LLM-callable tools (CSP-2).

Domain-appropriate replacement for the co-scientist port's PubMed/INDRA
literature surface. GEODE's domain is LLM self-improving loops + Petri
audit, so "literature grounding" means alignment / interpretability /
LLM safety papers — which live on arXiv (cs.AI / cs.CL / cs.LG), not
PubMed (biology).

Provides:
- ``ArxivSearchTool`` (``arxiv_search``) — query the arXiv API, return
  a ranked list of paper metadata (title / authors / abstract / pdf_url).
- ``ArxivFetchTool`` (``paper_fetch_arxiv``) — fetch one paper's full
  abstract + metadata by its arXiv id (e.g. ``2502.18864``).

Why not reuse ``general_web_search`` / ``web_fetch``?
=====================================================

Both already exist but routing every search through Google then
parsing arxiv.org HTML costs an extra round-trip and gives the LLM
noisy snippets instead of the structured Atom feed. The arXiv API is
free, no-auth, and returns clean per-paper records — the right primitive
for grounding rather than free-text web fetch.

External dependency
===================

The arXiv API is a public, no-auth HTTP endpoint at
``https://export.arxiv.org/api/query``. The response is an Atom XML
feed. Parsing uses Python's stdlib ``xml.etree.ElementTree`` (no new
dependency); rate limits are advisory (3s between calls per arXiv ToS
— enforced at the tool layer by a module-level last-call timestamp).

Frontier prior art: LangChain ``ArxivAPIWrapper``
(`langchain-community/utilities/arxiv.py`), open-coscientist
``literature_tools/draft.py`` PubMed pattern (this module is the
domain-shifted port).
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

# CSP-2 fix-up (2026-05-22) — switched from stdlib ``xml.etree.ElementTree``
# to ``defusedxml.ElementTree`` to harden the Atom-feed parser against
# billion-laughs / external-entity / DTD attacks. arxiv.org is a trusted
# endpoint today, but the policy lift is cheap and bandit's B405/B314
# scanner pins the rule across the repo so a future module can't quietly
# re-introduce the stdlib import.
import defusedxml.ElementTree as ET  # type: ignore[import-untyped]  # noqa: N817

log = logging.getLogger(__name__)

__all__ = [
    "ARXIV_API_URL",
    "ArxivFetchTool",
    "ArxivSearchTool",
]


ARXIV_API_URL = "https://export.arxiv.org/api/query"
_ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# arXiv ToS — at most one request per 3 seconds per IP. Enforced
# module-globally so concurrent tool calls within the same process
# serialise on the lock + wait if needed. The wait is bounded by the
# tool's own ``timeout_s`` (passed to ``httpx.get``).
_RATE_LIMIT_S = 3.0
_last_call_at: float = 0.0
_rate_limit_lock = threading.Lock()


class ArxivSearchTool:
    """Search arXiv for papers matching a query."""

    @property
    def name(self) -> str:
        return "arxiv_search"

    @property
    def description(self) -> str:
        return (
            "Search arXiv for scholarly preprints (alignment, "
            "interpretability, LLM safety, ML). Returns ranked metadata "
            "(title, authors, abstract, arxiv_id, pdf_url) for grounding "
            "research-style hypotheses. Free, no-auth. Use this instead "
            "of general_web_search when the user wants the actual papers/"
            "preprints behind a topic."
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Async entry point — required by ``_safe_delegate`` worker path.

        CSP-2 fix-up (Codex MCP CRITICAL): the delegated handler in
        ``core/cli/tool_handlers/_helpers.py:_safe_delegate`` looks up
        a callable ``aexecute`` on the tool instance; tools that expose
        only ``_execute_sync`` fail at spawn time with "must implement
        aexecute()". We wrap the sync body via ``asyncio.to_thread`` so
        ArxivSearchTool is callable from both the worker subprocess
        and direct sync tests.
        """
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        # CSP-2 fix-up (Codex LOW) — clamp BOTH sides so a negative
        # ``max_results`` (which would otherwise slice from the tail of
        # the scored list) gets normalised to the documented bounds.
        max_results: int = max(1, min(int(kwargs.get("max_results", 5)), 20))
        sort_by: str = kwargs.get("sort_by", "relevance")
        if sort_by not in ("relevance", "lastUpdatedDate", "submittedDate"):
            sort_by = "relevance"

        params: dict[str, str | int] = {
            "search_query": query,
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": "descending",
        }
        return _arxiv_get_and_parse(params, action="search", subject=query)


class ArxivFetchTool:
    """Fetch one arXiv paper's metadata by id."""

    @property
    def name(self) -> str:
        return "paper_fetch_arxiv"

    @property
    def description(self) -> str:
        return (
            "Fetch full metadata for ONE arXiv paper by its id (e.g. "
            "'2502.18864' or 'arXiv:2502.18864'). Returns title, authors, "
            "abstract, categories, publication dates, pdf_url. Use after "
            "arxiv_search to get the full abstract of a specific paper."
        )

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Async entry point — see :meth:`ArxivSearchTool.aexecute`."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        arxiv_id_raw: str = str(kwargs["arxiv_id"]).strip()
        arxiv_id = _normalize_arxiv_id(arxiv_id_raw)
        if not arxiv_id:
            from core.tools.base import tool_error

            return tool_error(
                f"invalid arxiv_id format: {arxiv_id_raw!r}",
                error_type="validation",
                recoverable=False,
                hint="Expected '2502.18864' or 'arXiv:2502.18864'.",
            )

        result = _arxiv_get_and_parse(
            {"id_list": arxiv_id},
            action="fetch",
            subject=arxiv_id,
        )
        # ``_arxiv_get_and_parse`` returns ``{"result": {"papers": [...]}}``
        # for the unified path; the fetch-by-id contract is a single
        # paper, so we narrow the result here. Errors pass through.
        if "result" not in result:
            return result
        papers = result["result"].get("papers", [])
        if not papers:
            from core.tools.base import tool_error

            return tool_error(
                f"arxiv id {arxiv_id!r} returned no paper (id may be invalid)",
                error_type="not_found",
                recoverable=False,
            )
        return {
            "result": {
                "arxiv_id": arxiv_id,
                "paper": papers[0],
                "source": "arxiv.org",
            }
        }


# ----------------------------------------------------------------------
# Module helpers — pure, testable without HTTP.
# ----------------------------------------------------------------------


def _arxiv_get_and_parse(
    params: dict[str, str | int],
    *,
    action: str,
    subject: str,
) -> dict[str, Any]:
    """Hold the rate-limit lock across BOTH the spacing wait AND the HTTP
    request — single-connection-at-a-time per arXiv ToU.

    CSP-2 fix-up (Codex HIGH): the pre-fix ``_respect_rate_limit()`` only
    enforced 3s start-spacing; the lock released before ``httpx.get`` so
    two concurrent callers could overlap (caller A still streaming
    bytes at 4s while caller B started a new request at 3.1s). arXiv's
    `info.arxiv.org/help/api/tou.html` mandates "single connection at a
    time", so the lock now spans the entire request lifetime. Multi-
    process compliance (worker subprocess pool) still needs a user-
    level file lock — documented but not enforced here.

    Returns the unified parsed result or a ``tool_error`` dict.
    """
    global _last_call_at
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
    with _rate_limit_lock:
        now = time.monotonic()
        elapsed = now - _last_call_at
        if elapsed < _RATE_LIMIT_S:
            time.sleep(_RATE_LIMIT_S - elapsed)
        try:
            resp = httpx.get(ARXIV_API_URL, params=params, timeout=15.0)
            resp.raise_for_status()
        except Exception as exc:
            _last_call_at = time.monotonic()
            from core.tools.base import tool_error

            return tool_error(
                f"arXiv API {action} for {subject!r} failed: {type(exc).__name__}: {exc}",
                error_type="connection",
                recoverable=True,
                hint="Retry after a few seconds; arXiv enforces ~3s/request.",
            )
        _last_call_at = time.monotonic()
        body = resp.text
    try:
        papers = _parse_arxiv_atom(body)
    except ET.ParseError as exc:
        from core.tools.base import tool_error

        return tool_error(
            f"arXiv API returned malformed XML: {exc}",
            error_type="internal",
            recoverable=True,
        )
    return {
        "result": {
            "query": subject if action == "search" else None,
            "count": len(papers),
            "papers": papers,
            "source": "arxiv.org",
        }
    }


def _normalize_arxiv_id(raw: str) -> str:
    """Return the canonical arXiv id or empty string if unrecognised.

    Accepts ``2502.18864`` (new) or ``cond-mat/9904001`` (old) with or
    without the ``arXiv:`` prefix and an optional version suffix
    (``v1``). Returns the stripped id (no prefix, no version) so the
    arXiv API treats ``id_list=<id>`` uniformly.

    Validation is structural only — the actual existence check happens
    at the API layer (empty ``papers`` → ``not_found`` error).
    """
    s = raw.strip()
    if s.lower().startswith("arxiv:"):
        s = s[len("arxiv:") :]
    # Strip optional version suffix (v1, v2, …).
    if "v" in s:
        head, _, tail = s.rpartition("v")
        if tail.isdigit():
            s = head
    # New-style: ``NNNN.NNNNN``  Old-style: ``archive/NNNNNNN``.
    parts_new = s.split(".")
    if len(parts_new) == 2 and parts_new[0].isdigit() and parts_new[1].isdigit():
        return s
    if "/" in s:
        archive, _, num = s.partition("/")
        if archive and num.isdigit():
            return s
    return ""


def _parse_arxiv_atom(xml_text: str) -> list[dict[str, Any]]:
    """Parse the Atom feed returned by arXiv's ``/api/query`` endpoint.

    Each ``<entry>`` becomes one dict::

        {
          "arxiv_id": "2502.18864",
          "title": "…",
          "authors": ["…"],
          "abstract": "…",
          "categories": ["cs.AI"],
          "published": "2026-02-25T…Z",
          "updated":   "2026-02-26T…Z",
          "pdf_url":   "https://arxiv.org/pdf/2502.18864",
          "abs_url":   "https://arxiv.org/abs/2502.18864",
        }

    Missing optional fields collapse to empty strings / lists — the
    caller (LLM) does not need to special-case ``None`` for grounding
    text concatenation.
    """
    root = ET.fromstring(xml_text)
    out: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", _ATOM_NS):
        id_url = (entry.findtext("atom:id", default="", namespaces=_ATOM_NS) or "").strip()
        arxiv_id = _arxiv_id_from_url(id_url)
        title = " ".join(
            (entry.findtext("atom:title", default="", namespaces=_ATOM_NS) or "").split()
        )
        summary = (entry.findtext("atom:summary", default="", namespaces=_ATOM_NS) or "").strip()
        authors = [
            (a.findtext("atom:name", default="", namespaces=_ATOM_NS) or "").strip()
            for a in entry.findall("atom:author", _ATOM_NS)
        ]
        categories = [
            (c.get("term") or "").strip()
            for c in entry.findall("atom:category", _ATOM_NS)
            if c.get("term")
        ]
        published = (
            entry.findtext("atom:published", default="", namespaces=_ATOM_NS) or ""
        ).strip()
        updated = (entry.findtext("atom:updated", default="", namespaces=_ATOM_NS) or "").strip()
        pdf_url = ""
        abs_url = ""
        for link in entry.findall("atom:link", _ATOM_NS):
            href = (link.get("href") or "").strip()
            rel = link.get("rel") or ""
            link_title = link.get("title") or ""
            if link_title == "pdf":
                pdf_url = href
            elif rel == "alternate":
                abs_url = href
        out.append(
            {
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": [a for a in authors if a],
                "abstract": summary,
                "categories": categories,
                "published": published,
                "updated": updated,
                "pdf_url": pdf_url,
                "abs_url": abs_url,
            }
        )
    return out


def _arxiv_id_from_url(url: str) -> str:
    """Extract the bare id from ``http://arxiv.org/abs/<id>[vN]``."""
    if not url:
        return ""
    tail = url.rsplit("/", 1)[-1]
    return _normalize_arxiv_id(tail)
