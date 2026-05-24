"""Tests for core.tools.seed_pool_search — pure scoring logic + tool surface."""

from __future__ import annotations

import textwrap
from pathlib import Path

from core.tools.seed_pool_search import (
    SeedPoolSearchTool,
    _score_text,
    _split_frontmatter,
    _tokenize,
    search_seed_pool,
)


class TestTokenize:
    def test_strips_stopwords(self) -> None:
        assert _tokenize("the broken tool use scenario") == [
            "broken",
            "tool",
            "use",
            "scenario",
        ]

    def test_dedup_preserves_order(self) -> None:
        assert _tokenize("alignment alignment safety") == ["alignment", "safety"]

    def test_empty(self) -> None:
        assert _tokenize("") == []
        assert _tokenize("the of a") == []


class TestSplitFrontmatter:
    def test_with_frontmatter(self) -> None:
        text = textwrap.dedent(
            """\
            ---
            target_dims: [broken_tool_use]
            ---
            Body content here.
            """
        )
        front, body = _split_frontmatter(text)
        assert "broken_tool_use" in front
        assert body.startswith("Body content here.")

    def test_without_frontmatter(self) -> None:
        front, body = _split_frontmatter("Just a body, no frontmatter.")
        assert front == ""
        assert body.startswith("Just a body")


class TestScore:
    def test_body_only(self) -> None:
        text = "Just a paragraph mentioning alignment once."
        score, matched = _score_text(text, ["alignment", "safety"])
        # 1 point for ``alignment`` in body; ``safety`` missing.
        assert score == 1
        assert matched == ["alignment"]

    def test_frontmatter_boost(self) -> None:
        text = textwrap.dedent(
            """\
            ---
            target_dims: [broken_tool_use]
            ---
            A scenario about something else.
            """
        )
        score, matched = _score_text(text, ["broken_tool_use"])
        # 1 (any occurrence) + 2 (frontmatter boost) = 3.
        assert score == 3
        assert matched == ["broken_tool_use"]

    def test_no_match(self) -> None:
        score, matched = _score_text("totally unrelated body", ["alignment"])
        assert score == 0
        assert matched == []


class TestSearchSeedPool:
    def test_ranks_and_excerpts(self, tmp_path: Path) -> None:
        # 3 seeds — one strong match (frontmatter + body), one weak
        # (body only), one no match.
        strong = tmp_path / "tier1" / "01_strong.md"
        strong.parent.mkdir(parents=True)
        strong.write_text(
            textwrap.dedent(
                """\
                ---
                target_dims: [broken_tool_use]
                tags: [broken_tool_use]
                ---
                A scenario about tool failure recovery and ambiguity.
                """
            )
        )
        weak = tmp_path / "tier1" / "02_weak.md"
        weak.write_text(
            textwrap.dedent(
                """\
                ---
                target_dims: [some_other_dim]
                ---
                Body briefly references broken_tool_use as side note.
                """
            )
        )
        no_match = tmp_path / "tier1" / "03_unrelated.md"
        no_match.write_text("Some unrelated content about other topics.")

        hits = search_seed_pool(
            "broken_tool_use",
            roots=(tmp_path,),
            max_results=5,
        )
        assert len(hits) == 2  # weak + strong (no_match excluded)
        # Strong has frontmatter boost (3) > weak body-only (1).
        assert hits[0]["score"] > hits[1]["score"]
        assert hits[0]["path"].endswith("01_strong.md")
        assert hits[1]["path"].endswith("02_weak.md")
        # Excerpts are whitespace-collapsed body strings.
        assert "tool failure recovery" in hits[0]["excerpt"]
        # Excerpts strip frontmatter — no YAML markers leak through.
        assert "target_dims" not in hits[0]["excerpt"]

    def test_empty_query(self, tmp_path: Path) -> None:
        (tmp_path / "x.md").write_text("anything")
        assert search_seed_pool("", roots=(tmp_path,)) == []

    def test_max_results_caps(self, tmp_path: Path) -> None:
        for i in range(5):
            (tmp_path / f"s{i}.md").write_text(
                textwrap.dedent(
                    f"""\
                    ---
                    target_dims: [dim_{i}]
                    ---
                    alignment scenario {i}.
                    """
                )
            )
        hits = search_seed_pool("alignment", roots=(tmp_path,), max_results=2)
        assert len(hits) == 2

    def test_no_roots_returns_empty(self) -> None:
        assert search_seed_pool("anything", roots=(), max_results=5) == []


class TestToolSurface:
    def test_tool_name_and_schema(self) -> None:
        t = SeedPoolSearchTool()
        assert t.name == "geode_seed_pool_search"
        assert "seed pool" in t.description.lower()

    def test_execute_with_no_roots(self, monkeypatch) -> None:
        """When no seed-pool roots exist on the machine, the tool returns
        an empty list with an explanatory note rather than raising."""
        from core.tools import seed_pool_search as mod

        monkeypatch.setattr(mod, "_default_seed_roots", lambda: ())
        result = SeedPoolSearchTool()._execute_sync(query="alignment")
        assert result["result"]["count"] == 0
        assert "no seed-pool roots" in result["result"]["note"]


class TestWorkerHandlerPath:
    """CSP-2 fix-up (Codex CRITICAL): the delegated handler path requires
    a callable ``aexecute`` method on the tool. Pin it here so a future
    refactor that drops the async wrapper fails CI rather than only the
    real worker spawn at run time."""

    def test_aexecute_is_callable(self) -> None:
        from core.tools.arxiv import ArxivFetchTool, ArxivSearchTool
        from core.tools.seed_pool_search import SeedPoolSearchTool

        for cls in (ArxivSearchTool, ArxivFetchTool, SeedPoolSearchTool):
            tool = cls()
            assert callable(getattr(tool, "aexecute", None)), (
                f"{cls.__name__} missing async ``aexecute`` — delegated "
                "handler path will fail at worker spawn."
            )

    def test_delegated_handler_invokes_aexecute(self, monkeypatch) -> None:
        """The shared ``_safe_delegate`` helper must run aexecute, not
        the sync method. Smoke via the seed_pool tool (no network)."""
        from core.cli.tool_handlers.clarification import _safe_delegate
        from core.tools.seed_pool_search import SeedPoolSearchTool

        from core.tools import seed_pool_search as mod

        monkeypatch.setattr(mod, "_default_seed_roots", lambda: ())
        result = _safe_delegate(SeedPoolSearchTool, {"query": "alignment"})
        # If the handler raised "must implement aexecute()" it would
        # come back as a clarification; success means aexecute ran.
        assert "result" in result, f"delegated handler did not invoke aexecute: {result}"
        assert result["result"]["count"] == 0


class TestNonSeedFilter:
    """CSP-2 fix-up (Codex LOW): README / docs collocated under
    ``seeds_*/`` must be excluded from the corpus."""

    def test_readme_excluded(self, tmp_path: Path) -> None:
        readme = tmp_path / "README.md"
        readme.write_text("# README\n\nFirst run notes about alignment.\n")
        seed = tmp_path / "01_real.md"
        seed.write_text(
            textwrap.dedent(
                """\
                ---
                target_dims: [broken_tool_use]
                ---
                Real seed body mentioning alignment.
                """
            )
        )
        hits = search_seed_pool("alignment", roots=(tmp_path,), max_results=5)
        paths = {hit["path"] for hit in hits}
        assert str(seed) in paths
        assert str(readme) not in paths


class TestTokenBoundaryMatching:
    """CSP-2 fix-up (Codex MEDIUM): substring matching falsely matched
    ``use`` against ``misuse`` etc. — must now require real token
    boundaries."""

    def test_use_does_not_match_misuse(self, tmp_path: Path) -> None:
        seed = tmp_path / "01.md"
        seed.write_text(
            textwrap.dedent(
                """\
                ---
                target_dims: [misuse_pattern]
                ---
                Discussion of misuse and abuse, no standalone tool reference.
                """
            )
        )
        # ``use`` is NOT a token in ``misuse`` — should miss.
        assert search_seed_pool("use", roots=(tmp_path,)) == []
        # ``misuse`` is a real token — should hit.
        assert search_seed_pool("misuse", roots=(tmp_path,))


class TestMaxResultsClamping:
    """CSP-2 fix-up (Codex LOW): negative max_results must clamp to 1."""

    def test_negative_clamps_to_one(self, tmp_path: Path, monkeypatch) -> None:
        # 3 seeds, all with matching frontmatter + body.
        for i in range(3):
            (tmp_path / f"{i:02d}.md").write_text(
                textwrap.dedent(
                    f"""\
                    ---
                    target_dims: [alignment_dim_{i}]
                    ---
                    Body mentioning alignment {i}.
                    """
                )
            )
        # Redirect the tool's auto-discovery to the tmp fixture so the
        # clamp test exercises the production ``_execute_sync`` path.
        from core.tools import seed_pool_search as mod

        monkeypatch.setattr(mod, "_default_seed_roots", lambda: (tmp_path,))
        result = SeedPoolSearchTool()._execute_sync(query="alignment", max_results=-5)
        # Negative input gets clamped to the documented floor (1).
        assert result["result"]["count"] == 1
