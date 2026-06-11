"""llms_txt_index tool — parser, probe, and delegation guards.

PR-LLMS-TXT-TOOL (2026-06-12). Dedicated-tool upgrade of the
instruction-level llms.txt-first heuristic (PR-LLMS-TXT, v0.99.156),
following the mcpdoc convergence (explicit tool + prompt rule). The
consumption parser is pinned against the repo's own published index
(``site/public/llms.txt``) so the publication shape (guarded by
``tests/core/llm/test_llms_txt_discovery.py``) and the consumption
parser cannot drift apart.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from core.tools.llms_txt import (
    LlmsTxtIndexTool,
    candidate_index_urls,
    parse_llms_txt,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_LLMS_TXT = REPO_ROOT / "site" / "public" / "llms.txt"

SAMPLE_INDEX = """\
# Sample Docs

> One-line summary of the docs.

- [Root guide](https://docs.example.com/guide): entry point

## Reference

- [API](https://docs.example.com/api): full API surface
- [CLI](/cli.md)

## Optional

- [Changelog](https://other.example.org/changelog): release notes
"""


# ---------------------------------------------------------------------------
# candidate_index_urls
# ---------------------------------------------------------------------------


def test_candidates_origin_base_is_single_probe() -> None:
    assert candidate_index_urls("https://example.com") == ["https://example.com/llms.txt"]


def test_candidates_subpath_probes_path_then_origin() -> None:
    probes = candidate_index_urls("https://developers.example.com/codex")
    assert probes == [
        "https://developers.example.com/codex/llms.txt",
        "https://developers.example.com/llms.txt",
    ]


def test_candidates_direct_index_url_is_verbatim() -> None:
    direct = "https://example.com/docs/llms.txt"
    assert candidate_index_urls(direct) == [direct]
    full = "https://example.com/llms-full.txt"
    assert candidate_index_urls(full) == [full]


def test_candidates_rejects_non_http_url() -> None:
    with pytest.raises(ValueError, match="absolute http"):
        candidate_index_urls("ftp://example.com")
    with pytest.raises(ValueError, match="absolute http"):
        candidate_index_urls("docs/llms.txt")


# ---------------------------------------------------------------------------
# parse_llms_txt
# ---------------------------------------------------------------------------


def test_parse_extracts_title_summary_sections() -> None:
    index = parse_llms_txt(SAMPLE_INDEX, base_url="https://docs.example.com/llms.txt")
    assert index is not None
    assert index["title"] == "Sample Docs"
    assert index["summary"] == "One-line summary of the docs."
    assert [s["name"] for s in index["sections"]] == ["", "Reference", "Optional"]


def test_parse_resolves_relative_links_and_tags_origin() -> None:
    index = parse_llms_txt(SAMPLE_INDEX, base_url="https://docs.example.com/llms.txt")
    assert index is not None
    reference = index["sections"][1]
    cli_link = reference["links"][1]
    assert cli_link["url"] == "https://docs.example.com/cli.md"
    assert cli_link["same_origin"] is True
    optional = index["sections"][2]
    assert optional["links"][0]["same_origin"] is False
    assert optional["links"][0]["notes"] == "release notes"


def test_parse_returns_none_without_link_lines() -> None:
    assert parse_llms_txt("# Title\n\nprose only\n", base_url="https://x.test/llms.txt") is None
    assert parse_llms_txt("<!doctype html><html>", base_url="https://x.test/llms.txt") is None


def test_parse_accepts_published_site_index() -> None:
    """Publication-consumption pin: the index GEODE itself publishes must
    parse with the consumption parser (same llmstxt.org spec, both ends)."""
    published = PUBLISHED_LLMS_TXT.read_text(encoding="utf-8")
    index = parse_llms_txt(published, base_url="https://mangowhoiscloud.github.io/geode/llms.txt")
    assert index is not None
    assert index["title"] == "GEODE"
    assert index["summary"], "blockquote summary must survive parsing"
    section_names = [s["name"] for s in index["sections"]]
    assert len(section_names) >= 3
    assert "Optional" in section_names
    for section in index["sections"]:
        for link in section["links"]:
            assert link["url"].startswith("http"), link


# ---------------------------------------------------------------------------
# LlmsTxtIndexTool — probe behaviour (httpx patched, no network)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        text: str,
        *,
        status_code: int = 200,
        content_type: str = "text/plain; charset=utf-8",
        url: str = "https://docs.example.com/llms.txt",
    ) -> None:
        self.text = text
        self.status_code = status_code
        self.headers = {"content-type": content_type}
        self.url = url


def _run(tool_kwargs: dict[str, Any], responses: dict[str, _FakeResponse]) -> dict[str, Any]:
    """Execute the tool with httpx.get answering from *responses* by URL."""

    def _fake_get(url: str, **_kwargs: Any) -> _FakeResponse:
        fake = responses.get(url)
        if fake is None:
            return _FakeResponse("not found", status_code=404, url=url)
        return fake

    with patch.object(httpx, "get", side_effect=_fake_get):
        return asyncio.run(LlmsTxtIndexTool().aexecute(**tool_kwargs))


def test_tool_returns_structured_index() -> None:
    verdict = _run(
        {"url": "https://docs.example.com"},
        {"https://docs.example.com/llms.txt": _FakeResponse(SAMPLE_INDEX)},
    )
    index = verdict["result"]
    assert index["title"] == "Sample Docs"
    assert index["link_count"] == index["total_links"] == 4
    assert index["truncated"] is False
    assert index["tls_verified"] is True
    assert index["source"] == "https://docs.example.com/llms.txt"


def test_tool_falls_through_subpath_to_origin_probe() -> None:
    verdict = _run(
        {"url": "https://docs.example.com/codex"},
        {"https://docs.example.com/llms.txt": _FakeResponse(SAMPLE_INDEX)},
    )
    index = verdict["result"]
    assert index["url"] == "https://docs.example.com/llms.txt"
    assert index["probed_misses"][0]["url"] == "https://docs.example.com/codex/llms.txt"
    assert "404" in index["probed_misses"][0]["reason"]


def test_tool_missing_index_is_not_found_with_fallback_hint() -> None:
    verdict = _run({"url": "https://nodocs.example.com"}, {})
    assert verdict["error_type"] == "not_found"
    assert "general_web_search" in verdict["hint"]
    assert verdict["context"]["probed"][0]["reason"] == "HTTP 404"


def test_tool_html_spa_fallback_page_is_a_miss() -> None:
    spa_page = _FakeResponse(
        "<!doctype html><html><body>app</body></html>",
        content_type="text/html; charset=utf-8",
    )
    verdict = _run(
        {"url": "https://spa.example.com"},
        {"https://spa.example.com/llms.txt": spa_page},
    )
    assert verdict["error_type"] == "not_found"
    assert "HTML" in verdict["context"]["probed"][0]["reason"]


def test_tool_section_filter_narrows_and_unknown_filter_lists_names() -> None:
    responses = {"https://docs.example.com/llms.txt": _FakeResponse(SAMPLE_INDEX)}
    narrowed = _run({"url": "https://docs.example.com", "section": "reference"}, responses)
    assert [s["name"] for s in narrowed["result"]["sections"]] == ["Reference"]
    assert narrowed["result"]["section_filter"] == "reference"

    unknown = _run({"url": "https://docs.example.com", "section": "zzz"}, responses)
    assert unknown["error_type"] == "not_found"
    assert unknown["context"]["available_sections"] == ["", "Reference", "Optional"]


def test_tool_max_links_truncates_observably() -> None:
    verdict = _run(
        {"url": "https://docs.example.com", "max_links": 1},
        {"https://docs.example.com/llms.txt": _FakeResponse(SAMPLE_INDEX)},
    )
    index = verdict["result"]
    assert index["link_count"] == 1
    assert index["total_links"] == 4
    assert index["truncated"] is True
    assert "section" in index["hint"]


def test_tool_bad_inputs_classify_as_validation() -> None:
    no_scheme = asyncio.run(LlmsTxtIndexTool().aexecute(url="not-a-url"))
    assert no_scheme["error_type"] == "validation"
    bad_max = asyncio.run(LlmsTxtIndexTool().aexecute(url="https://x.test", max_links="lots"))
    assert bad_max["error_type"] == "validation"


def test_delegated_handler_executes_end_to_end() -> None:
    """E2E through the production delegation path (registry → lazy import
    → async aexecute), not just the class directly."""
    from core.cli.tool_handlers.delegated import _build_delegated_handlers

    handler = _build_delegated_handlers()["llms_txt_index"]

    def _fake_get(url: str, **_kwargs: Any) -> _FakeResponse:
        return _FakeResponse(SAMPLE_INDEX, url=url)

    with patch.object(httpx, "get", side_effect=_fake_get):
        verdict = asyncio.run(handler(url="https://docs.example.com"))
    assert verdict["result"]["title"] == "Sample Docs"
