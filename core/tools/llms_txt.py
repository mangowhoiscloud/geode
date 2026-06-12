"""llms.txt index tool — structured documentation-site index discovery.

PR-LLMS-TXT-TOOL (2026-06-12). Upgrades the instruction-level
llms.txt-first heuristic (PR-LLMS-TXT, v0.99.156) to a dedicated tool,
following the LangChain mcpdoc convergence (explicit tool pair + prompt
rule; github.com/langchain-ai/mcpdoc ``list_doc_sources``/``fetch_docs``,
plus the same two-tool shape in the LLMS.txt Documentation and Langfuse
docs MCP servers). GEODE keeps page fetch on the existing ``web_fetch``
tool and adds only the missing half: fetching the index itself through
``web_fetch`` truncates at 10k chars — larger indexes silently lose their
tail sections — and leaves the markdown parsing to the model.
``llms_txt_index`` fetches the full index and returns it as structured
sections of links instead.

Spec shape (llmstxt.org): H1 title → blockquote summary → H2 link-list
sections (``- [name](url): notes``) → ``## Optional``. The publication
side of the same spec is pinned by
``tests/core/llm/test_llms_txt_discovery.py`` over
``site/public/llms.txt``; the consumption parser here is pinned against
that same file so publication and consumption cannot drift apart.

No silent auto-probing: this tool only runs when the loop explicitly
calls it (the router heuristic instructs the order) — ``web_fetch`` never
probes ``/llms.txt`` behind the model's back, matching the PR-LLMS-TXT
frontier-convergence decision.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

log = logging.getLogger(__name__)

# Direct index filenames accepted as-is (no probing). llms-full.txt is
# routed to web_fetch by the router heuristic (it is a content dump, not
# a link index), but a user-supplied direct URL is still honoured.
_INDEX_FILENAMES = frozenset({"llms.txt", "llms-full.txt"})

# llmstxt.org link line: ``- [name](url)`` with optional ``: notes`` tail.
# Relative targets are tolerated on consumption (resolved via urljoin)
# even though the publication guard requires absolute URLs.
_LINK_LINE_RE = re.compile(r"^- \[(?P<name>[^\]]+)\]\((?P<target>[^)\s]+)\)(?::\s*(?P<notes>.*))?$")

_MAX_LINKS_DEFAULT = 200
_MAX_LINKS_CEILING = 1000


def candidate_index_urls(url: str) -> list[str]:
    """Derive the llms.txt URLs to probe from a user-supplied URL.

    A direct ``llms.txt`` / ``llms-full.txt`` URL is returned verbatim.
    Otherwise probe path-relative first (handles sub-path indexes like
    developers.openai.com/codex/llms.txt), then the origin root. A
    file-like leaf (``/docs/page.html``) probes its parent directory
    (``/docs/llms.txt``), not ``page.html/llms.txt`` (Codex review of
    PR #2213, finding 1).

    Raises ValueError on URLs without an http(s) scheme + host.
    """
    split = urlsplit(url)
    if split.scheme not in ("http", "https") or not split.netloc:
        msg = f"not an absolute http(s) URL: {url!r}"
        raise ValueError(msg)

    leaf = split.path.rsplit("/", 1)[-1]
    if leaf in _INDEX_FILENAMES:
        return [url]

    base = url.split("?", 1)[0].split("#", 1)[0]
    if "." in leaf:
        # file-like leaf — sibling resolution drops it (RFC 3986 merge)
        path_relative = urljoin(base, "llms.txt")
    else:
        path_relative = urljoin(base.rstrip("/") + "/", "llms.txt")
    origin_root = f"{split.scheme}://{split.netloc}/llms.txt"
    candidates = [path_relative]
    if origin_root != path_relative:
        candidates.append(origin_root)
    return candidates


def parse_llms_txt(text: str, *, base_url: str) -> dict[str, Any] | None:
    """Parse llmstxt.org-shaped *text* into title / summary / sections.

    Returns ``None`` only when the text has neither an H1 title nor any
    link lines — by the graceful contract of this module that means "not
    an llms.txt index" (e.g. an SPA's catch-all HTML route or an
    unrelated text file), and the caller treats it as a probe miss. The
    spec requires only the H1; a sparse-but-valid index (title, no link
    sections yet) parses to empty ``sections`` instead of a false
    "site publishes no llms.txt" miss (Codex review of PR #2213,
    finding 2).

    Links that appear before any H2 land in an unnamed root section
    (``name: ""``). Sections without link lines are dropped — the value
    of the index is its links. ``same_origin`` compares scheme + host
    (web origin), and a leading UTF-8 BOM is tolerated.
    """
    index_split = urlsplit(base_url)
    index_origin = (index_split.scheme, index_split.netloc)
    text = text.lstrip("﻿")
    title = ""
    summary_parts: list[str] = []
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] = {"name": "", "links": []}
    seen_h2 = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not title and line.startswith("# "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            if current["links"]:
                sections.append(current)
            current = {"name": line[3:].strip(), "links": []}
            seen_h2 = True
            continue
        if not seen_h2 and not current["links"] and line.startswith("> "):
            summary_parts.append(line[2:].strip())
            continue
        matched = _LINK_LINE_RE.match(line)
        if matched:
            resolved = urljoin(base_url, matched.group("target"))
            resolved_split = urlsplit(resolved)
            current["links"].append(
                {
                    "name": matched.group("name").strip(),
                    "url": resolved,
                    "notes": (matched.group("notes") or "").strip(),
                    "same_origin": (resolved_split.scheme, resolved_split.netloc) == index_origin,
                }
            )
    if current["links"]:
        sections.append(current)

    if not sections and not title:
        return None
    return {"title": title, "summary": " ".join(summary_parts).strip(), "sections": sections}


class LlmsTxtIndexTool:
    """Fetch + parse a documentation site's /llms.txt into structured links."""

    @property
    def name(self) -> str:
        return "llms_txt_index"

    @property
    def description(self) -> str:
        return (
            "Fetch a documentation site's /llms.txt index (llmstxt.org) "
            "parsed into structured sections of links."
        )

    def _execute_sync(self, **kwargs: Any) -> dict[str, Any]:
        from core.tools.base import tool_error

        url: str = kwargs["url"]
        section_filter: str = str(kwargs.get("section", "") or "").strip()
        # Graceful contract — schema says integer, but a non-numeric LLM
        # arg must classify as validation, not raise out of the tool.
        try:
            max_links = int(kwargs.get("max_links", _MAX_LINKS_DEFAULT))
        except (TypeError, ValueError):
            return tool_error(
                f"max_links must be an integer, got {kwargs.get('max_links')!r}",
                error_type="validation",
                hint="Pass max_links as a number, e.g. 200.",
                context={"url": url},
            )
        max_links = max(1, min(max_links, _MAX_LINKS_CEILING))

        try:
            candidates = candidate_index_urls(url)
        except ValueError as exc:
            return tool_error(
                str(exc),
                error_type="validation",
                hint="Pass an absolute http(s) URL, e.g. https://example.com/docs.",
                context={"url": url},
            )

        try:
            import httpx  # noqa: F401  # availability check for the fetch below

            from core.tools.web_tools import http_get_with_tls_fallback
        except ImportError:
            return tool_error(
                "httpx not installed",
                error_type="dependency",
                recoverable=False,
                hint="Install httpx: pip install httpx",
            )

        misses: list[dict[str, str]] = []
        for candidate in candidates:
            try:
                resp, tls_verified = http_get_with_tls_fallback(candidate)
            except Exception as exc:
                misses.append({"url": candidate, "reason": f"fetch failed: {exc}"})
                continue
            if resp.status_code != 200:
                misses.append({"url": candidate, "reason": f"HTTP {resp.status_code}"})
                continue
            body = resp.text
            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type or body.lstrip()[:1] == "<":
                misses.append({"url": candidate, "reason": "HTML page returned, not an llms.txt"})
                continue
            final_url = str(resp.url) or candidate
            parsed = parse_llms_txt(body, base_url=final_url)
            if parsed is None:
                misses.append(
                    {
                        "url": candidate,
                        "reason": (
                            "no H1 title and no '- [name](url)' link lines — not llmstxt.org shape"
                        ),
                    }
                )
                continue
            return self._build_result(
                parsed,
                index_url=final_url,
                section_filter=section_filter,
                max_links=max_links,
                tls_verified=tls_verified,
                misses=misses,
            )

        return tool_error(
            f"no llms.txt index found for {url}",
            error_type="not_found",
            hint=(
                "The site publishes no llms.txt — fall back to "
                "general_web_search scoped to the site, or web_fetch a "
                "known docs page directly."
            ),
            context={"url": url, "probed": misses},
        )

    def _build_result(
        self,
        parsed: dict[str, Any],
        *,
        index_url: str,
        section_filter: str,
        max_links: int,
        tls_verified: bool,
        misses: list[dict[str, str]],
    ) -> dict[str, Any]:
        from core.tools.base import tool_error

        sections: list[dict[str, Any]] = parsed["sections"]
        if section_filter:
            wanted = section_filter.lower()
            filtered = [s for s in sections if wanted in s["name"].lower()]
            if not filtered:
                return tool_error(
                    f"no section matching {section_filter!r} in {index_url}",
                    error_type="not_found",
                    hint="Call again without `section` or pick one of the available names.",
                    context={
                        "url": index_url,
                        "available_sections": [s["name"] for s in sections],
                    },
                )
            sections = filtered

        total_links = sum(len(s["links"]) for s in sections)
        shown = 0
        truncated = False
        capped_sections: list[dict[str, Any]] = []
        for section in sections:
            if shown >= max_links:
                truncated = True
                break
            links = section["links"][: max_links - shown]
            if len(links) < len(section["links"]):
                truncated = True
            shown += len(links)
            capped_sections.append({"name": section["name"], "links": links})

        result: dict[str, Any] = {
            "url": index_url,
            "source": index_url,  # explicit source tag for grounding
            "title": parsed["title"],
            "summary": parsed["summary"],
            "sections": capped_sections,
            "link_count": shown,
            "total_links": total_links,
            "truncated": truncated,
            "tls_verified": tls_verified,
        }
        if section_filter:
            result["section_filter"] = section_filter
        if truncated:
            result["hint"] = (
                "index truncated — narrow with the `section` parameter or raise max_links"
            )
        if misses:
            result["probed_misses"] = misses
        return {"result": result}

    async def aexecute(self, **kwargs: Any) -> dict[str, Any]:
        """Run blocking HTTP fetch off the event loop."""
        return await asyncio.to_thread(self._execute_sync, **kwargs)
