"""Tests for LLM commentary generation module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from core.config import ANTHROPIC_BUDGET
from core.llm.commentary import generate_commentary

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
            model=ANTHROPIC_BUDGET,
            max_tokens=128,
            temperature=0.2,
        )
        _, kwargs = mock_call.call_args
        assert kwargs["model"] == ANTHROPIC_BUDGET
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
