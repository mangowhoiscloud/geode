"""Tests for core.tools.arxiv — pure parsing + id normalisation (no HTTP)."""

from __future__ import annotations

import textwrap

from core.tools.arxiv import (
    _arxiv_id_from_url,
    _normalize_arxiv_id,
    _parse_arxiv_atom,
)


class TestNormalizeArxivId:
    def test_new_style(self) -> None:
        assert _normalize_arxiv_id("2502.18864") == "2502.18864"

    def test_with_prefix(self) -> None:
        assert _normalize_arxiv_id("arXiv:2502.18864") == "2502.18864"
        assert _normalize_arxiv_id("ARXIV:2502.18864") == "2502.18864"

    def test_with_version(self) -> None:
        assert _normalize_arxiv_id("2502.18864v2") == "2502.18864"
        assert _normalize_arxiv_id("arXiv:2502.18864v1") == "2502.18864"

    def test_old_style(self) -> None:
        assert _normalize_arxiv_id("cond-mat/9904001") == "cond-mat/9904001"

    def test_old_style_with_version(self) -> None:
        assert _normalize_arxiv_id("cond-mat/9904001v3") == "cond-mat/9904001"

    def test_garbage(self) -> None:
        assert _normalize_arxiv_id("not-an-id") == ""
        assert _normalize_arxiv_id("") == ""
        assert _normalize_arxiv_id("   ") == ""


class TestArxivIdFromUrl:
    def test_abs_url(self) -> None:
        assert _arxiv_id_from_url("http://arxiv.org/abs/2502.18864v1") == "2502.18864"

    def test_pdf_url(self) -> None:
        assert _arxiv_id_from_url("https://arxiv.org/pdf/2502.18864") == "2502.18864"

    def test_empty(self) -> None:
        assert _arxiv_id_from_url("") == ""


# A minimal but realistic arXiv Atom response — one entry with all
# fields the parser advertises in its docstring. Real fixtures are
# heavier; this slice is enough to pin the parse contract.
_FAKE_ATOM = textwrap.dedent(
    """\
    <?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2502.18864v1</id>
        <updated>2026-02-26T00:00:00Z</updated>
        <published>2026-02-25T00:00:00Z</published>
        <title>
          Towards an AI Co-Scientist
        </title>
        <summary>
          We present an AI co-scientist that produces grounded hypotheses.
        </summary>
        <author><name>Alice Researcher</name></author>
        <author><name>Bob Engineer</name></author>
        <link href="http://arxiv.org/abs/2502.18864v1" rel="alternate"/>
        <link href="http://arxiv.org/pdf/2502.18864v1" rel="related" title="pdf"/>
        <category term="cs.AI"/>
        <category term="cs.CL"/>
      </entry>
    </feed>
    """
)


class TestParseArxivAtom:
    def test_single_entry(self) -> None:
        papers = _parse_arxiv_atom(_FAKE_ATOM)
        assert len(papers) == 1
        p = papers[0]
        assert p["arxiv_id"] == "2502.18864"
        # Whitespace-collapsed title.
        assert p["title"] == "Towards an AI Co-Scientist"
        assert p["authors"] == ["Alice Researcher", "Bob Engineer"]
        assert "co-scientist" in p["abstract"].lower()
        assert p["categories"] == ["cs.AI", "cs.CL"]
        assert p["published"] == "2026-02-25T00:00:00Z"
        assert p["pdf_url"] == "http://arxiv.org/pdf/2502.18864v1"
        assert p["abs_url"] == "http://arxiv.org/abs/2502.18864v1"

    def test_empty_feed(self) -> None:
        empty = textwrap.dedent(
            """\
            <?xml version="1.0" encoding="UTF-8"?>
            <feed xmlns="http://www.w3.org/2005/Atom"/>
            """
        )
        assert _parse_arxiv_atom(empty) == []


class TestToolSurface:
    """The tool classes expose the LLM-callable contract."""

    def test_search_tool_name_and_schema(self) -> None:
        from core.tools.arxiv import ArxivSearchTool

        t = ArxivSearchTool()
        assert t.name == "arxiv_search"
        assert "arXiv" in t.description

    def test_fetch_tool_name_and_schema(self) -> None:
        from core.tools.arxiv import ArxivFetchTool

        t = ArxivFetchTool()
        assert t.name == "paper_fetch_arxiv"
        assert "arXiv" in t.description

    def test_fetch_invalid_id_returns_error(self) -> None:
        """No network: invalid arxiv_id short-circuits to a validation error."""
        from core.tools.arxiv import ArxivFetchTool

        result = ArxivFetchTool()._execute_sync(arxiv_id="not-an-id")
        assert "error" in result
        assert result["error_type"] == "validation"
