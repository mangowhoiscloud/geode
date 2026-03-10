"""Tests for LLM commentary generation module."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

from core.llm.commentary import (
    build_analyze_context,
    build_compare_context,
    build_list_context,
    build_search_context,
    generate_commentary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class FakeSearchResult:
    """Mimics core.cli.search.SearchResult for testing."""

    ip_name: str
    score: float
    matches: list[str]


# ---------------------------------------------------------------------------
# TestContextBuilders — pure data transforms, no mock needed
# ---------------------------------------------------------------------------


class TestBuildAnalyzeContext:
    def test_full_fields(self):
        result: dict[str, Any] = {
            "tier": "S",
            "final_score": 82.2,
            "ip_name": "Berserk",
            "subscores": {"quality": 80, "momentum": 92},
            "cause": "conversion_failure",
            "synthesis": "A" * 500,
        }
        ctx = build_analyze_context(result)
        assert ctx["tier"] == "S"
        assert ctx["final_score"] == 82.2
        assert ctx["ip_name"] == "Berserk"
        assert ctx["subscores"] == {"quality": 80, "momentum": 92}
        assert ctx["cause"] == "conversion_failure"
        assert len(ctx["narrative"]) == 300  # truncated

    def test_partial_fields_no_synthesis(self):
        result: dict[str, Any] = {
            "tier": "B",
            "final_score": 55.0,
            "ip_name": "TestIP",
        }
        ctx = build_analyze_context(result)
        assert ctx["tier"] == "B"
        assert ctx["final_score"] == 55.0
        assert "narrative" not in ctx
        assert "subscores" not in ctx

    def test_empty_result(self):
        ctx = build_analyze_context({})
        assert ctx["tier"] == "?"
        assert ctx["final_score"] == 0
        assert ctx["ip_name"] == ""


class TestBuildSearchContext:
    def test_with_results(self):
        results = [
            FakeSearchResult("Berserk", 0.95, ["dark fantasy"]),
            FakeSearchResult("Cowboy Bebop", 0.70, ["action"]),
            FakeSearchResult("Akira", 0.50, ["sci-fi"]),
            FakeSearchResult("Extra", 0.30, ["misc"]),
        ]
        ctx = build_search_context("dark fantasy", results)
        assert ctx["query"] == "dark fantasy"
        assert ctx["result_count"] == 4
        assert len(ctx["top_matches"]) == 3  # capped at top 3
        assert ctx["top_matches"][0]["ip_name"] == "Berserk"
        assert ctx["top_matches"][0]["score"] == 0.95

    def test_empty_results(self):
        ctx = build_search_context("nonexistent", [])
        assert ctx["query"] == "nonexistent"
        assert ctx["result_count"] == 0
        assert "top_matches" not in ctx


class TestBuildListContext:
    def test_ip_list(self):
        names = ["Berserk", "Cowboy Bebop", "Ghost in Shell"]
        ctx = build_list_context(names)
        assert ctx["ip_count"] == 3
        assert ctx["ip_names"] == names

    def test_large_list_capped(self):
        names = [f"IP_{i}" for i in range(20)]
        ctx = build_list_context(names)
        assert ctx["ip_count"] == 20
        assert len(ctx["ip_names"]) == 10  # capped


class TestBuildCompareContext:
    def test_both_results(self):
        result_a: dict[str, Any] = {"tier": "S", "final_score": 82.2}
        result_b: dict[str, Any] = {"tier": "B", "final_score": 55.0}
        ctx = build_compare_context("Berserk", result_a, "Cowboy Bebop", result_b)
        assert ctx["ip_a"] == "Berserk"
        assert ctx["ip_b"] == "Cowboy Bebop"
        assert ctx["tier_a"] == "S"
        assert ctx["score_a"] == 82.2
        assert ctx["tier_b"] == "B"
        assert ctx["score_b"] == 55.0

    def test_one_side_failed(self):
        result_a: dict[str, Any] = {"tier": "A", "final_score": 70.0}
        ctx = build_compare_context("Berserk", result_a, "Unknown", None)
        assert ctx["tier_a"] == "A"
        assert ctx["tier_b"] == "N/A"
        assert ctx["score_b"] == 0

    def test_both_failed(self):
        ctx = build_compare_context("A", None, "B", None)
        assert ctx["tier_a"] == "N/A"
        assert ctx["tier_b"] == "N/A"


# ---------------------------------------------------------------------------
# TestGenerateCommentary — mock call_llm
# ---------------------------------------------------------------------------


class TestGenerateCommentary:
    @patch("core.llm.commentary.call_llm")
    def test_success_returns_text(self, mock_call: MagicMock):
        mock_call.return_value = "  This is a great IP.  "
        result = generate_commentary(
            user_query="Berserk 분석해줘",
            action="analyze",
            context={"tier": "S", "final_score": 82.2},
        )
        assert result == "This is a great IP."
        mock_call.assert_called_once()

    @patch("core.llm.commentary.call_llm")
    def test_api_error_returns_none(self, mock_call: MagicMock):
        mock_call.side_effect = RuntimeError("API down")
        result = generate_commentary(
            user_query="test",
            action="analyze",
            context={"tier": "B"},
        )
        assert result is None

    @patch("core.llm.commentary.call_llm")
    def test_empty_response_returns_none(self, mock_call: MagicMock):
        mock_call.return_value = "   "
        result = generate_commentary(
            user_query="test",
            action="list",
            context={"ip_count": 5},
        )
        # "   ".strip() == "" which is falsy → None
        assert result is None

    @patch("core.llm.commentary.call_llm")
    def test_custom_model_passed(self, mock_call: MagicMock):
        mock_call.return_value = "Commentary text"
        generate_commentary(
            user_query="test",
            action="search",
            context={},
            model="claude-haiku-4-5-20251001",
            max_tokens=128,
            temperature=0.2,
        )
        _, kwargs = mock_call.call_args
        assert kwargs["model"] == "claude-haiku-4-5-20251001"
        assert kwargs["max_tokens"] == 128
        assert kwargs["temperature"] == 0.2

    @patch("core.llm.commentary.call_llm")
    def test_prompt_contains_user_query_and_action(self, mock_call: MagicMock):
        mock_call.return_value = "ok"
        generate_commentary(
            user_query="다크 판타지 검색",
            action="search",
            context={"query": "다크 판타지", "result_count": 3},
        )
        args = mock_call.call_args[0]
        # args[0] = system, args[1] = user prompt
        assert "다크 판타지 검색" in args[1]
        assert "search" in args[1]


# ---------------------------------------------------------------------------
# TestShowCommentary — integration with console
# ---------------------------------------------------------------------------


class TestShowCommentary:
    @patch("core.cli.generate_commentary")
    @patch("core.cli.GeodeStatus")
    @patch("core.cli.console")
    def test_offline_skips(
        self, mock_console: MagicMock, mock_status: MagicMock, mock_gen: MagicMock
    ):
        from core.cli import _show_commentary

        _show_commentary("test", "analyze", {}, is_offline=True)
        mock_gen.assert_not_called()
        mock_status.assert_not_called()

    @patch("core.cli.generate_commentary")
    @patch("core.cli.GeodeStatus")
    @patch("core.cli.console")
    def test_success_prints_text(
        self, mock_console: MagicMock, mock_status_cls: MagicMock, mock_gen: MagicMock
    ):
        from core.cli import _show_commentary

        mock_gen.return_value = "Great insight here."
        mock_ctx = MagicMock()
        mock_status_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_status_cls.return_value.__exit__ = MagicMock(return_value=False)

        _show_commentary("query", "analyze", {"tier": "S"}, is_offline=False)

        mock_gen.assert_called_once()
        # Should print the commentary text
        printed = [str(c) for c in mock_console.print.call_args_list]
        assert any("Great insight here." in s for s in printed)

    @patch("core.cli.generate_commentary")
    @patch("core.cli.GeodeStatus")
    @patch("core.cli.console")
    def test_failure_no_crash(
        self, mock_console: MagicMock, mock_status_cls: MagicMock, mock_gen: MagicMock
    ):
        from core.cli import _show_commentary

        mock_gen.return_value = None
        mock_ctx = MagicMock()
        mock_status_cls.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_status_cls.return_value.__exit__ = MagicMock(return_value=False)

        # Should not raise
        _show_commentary("query", "list", {}, is_offline=False)
