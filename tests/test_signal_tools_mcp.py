"""Tests for Signal Tools MCP live integration paths.

Verifies that each signal tool correctly:
1. Calls the appropriate MCP server when available
2. Falls back to fixture data when MCP is unavailable
3. Handles MCP errors gracefully
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from core.tools.signal_tools import (
    GoogleTrendsTool,
    RedditSentimentTool,
    SteamInfoTool,
    TwitchStatsTool,
    YouTubeSearchTool,
    _parse_mcp_content,
    _try_mcp_signal,
)

# Patch target: lazy import inside _try_mcp_signal
_MCP_MANAGER_PATCH = "core.mcp.manager.get_mcp_manager"


# ---------------------------------------------------------------------------
# _parse_mcp_content
# ---------------------------------------------------------------------------


class TestParseMCPContent:
    def test_direct_dict_passthrough(self):
        """Non-standard MCP servers returning data keys directly."""
        result = {"player_count": 123, "review_score": 85}
        assert _parse_mcp_content(result) == result

    def test_text_content_json(self):
        """Standard MCP content with JSON text."""
        result = {"content": [{"type": "text", "text": '{"views": 1000, "subscribers": 50}'}]}
        parsed = _parse_mcp_content(result)
        assert parsed == {"views": 1000, "subscribers": 50}

    def test_text_content_plain(self):
        """MCP content with plain text (not JSON)."""
        result = {"content": [{"type": "text", "text": "Game not found on platform."}]}
        parsed = _parse_mcp_content(result)
        assert parsed == {"text": "Game not found on platform."}

    def test_empty_content_list(self):
        """Empty content list returns original dict."""
        result = {"content": []}
        assert _parse_mcp_content(result) == result

    def test_non_list_content(self):
        """Non-list content returns original dict."""
        result = {"content": "not a list", "data": 42}
        assert _parse_mcp_content(result) == result

    def test_multiple_text_blocks(self):
        """Multiple text blocks concatenated."""
        result = {
            "content": [
                {"type": "text", "text": "Part 1"},
                {"type": "text", "text": "Part 2"},
            ]
        }
        parsed = _parse_mcp_content(result)
        assert parsed == {"text": "Part 1\nPart 2"}

    def test_first_json_wins(self):
        """First parseable JSON block wins."""
        result = {
            "content": [
                {"type": "text", "text": '{"key": "value"}'},
                {"type": "text", "text": "ignored plain text"},
            ]
        }
        parsed = _parse_mcp_content(result)
        assert parsed == {"key": "value"}


# ---------------------------------------------------------------------------
# _try_mcp_signal
# ---------------------------------------------------------------------------


class TestTryMCPSignal:
    def test_server_not_healthy(self):
        """Returns None when server is not in health check."""
        mock_manager = MagicMock()
        mock_manager.check_health.return_value = {"steam": False}

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=mock_manager,
        ):
            result = _try_mcp_signal("steam", "get_game_info", {"query": "Test"})
        assert result is None

    def test_server_healthy_success(self):
        """Returns parsed result when MCP call succeeds."""
        mock_manager = MagicMock()
        mock_manager.check_health.return_value = {"steam": True}
        mock_manager.call_tool.return_value = {
            "content": [{"type": "text", "text": '{"player_count": 500}'}]
        }

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=mock_manager,
        ):
            result = _try_mcp_signal("steam", "get_game_info", {"query": "Test"})
        assert result == {"player_count": 500}

    def test_mcp_returns_error(self):
        """Returns None when MCP returns error dict."""
        mock_manager = MagicMock()
        mock_manager.check_health.return_value = {"steam": True}
        mock_manager.call_tool.return_value = {"error": "tool not found"}

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=mock_manager,
        ):
            result = _try_mcp_signal("steam", "get_game_info", {"query": "Test"})
        assert result is None

    def test_manager_import_fails(self):
        """Returns None when MCPServerManager import fails."""
        with patch(
            _MCP_MANAGER_PATCH,
            side_effect=ImportError("no module"),
        ):
            result = _try_mcp_signal("steam", "get_game_info", {"query": "Test"})
        assert result is None

    def test_call_tool_exception(self):
        """Returns None when call_tool raises."""
        mock_manager = MagicMock()
        mock_manager.check_health.return_value = {"steam": True}
        mock_manager.call_tool.side_effect = ConnectionError("lost connection")

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=mock_manager,
        ):
            result = _try_mcp_signal("steam", "get_game_info", {"query": "Test"})
        assert result is None


# ---------------------------------------------------------------------------
# Helper to build a mock MCP manager for tool tests
# ---------------------------------------------------------------------------


def _make_mcp_manager(
    server_name: str,
    tool_result: dict[str, Any],
) -> MagicMock:
    """Create a mock MCPServerManager that returns tool_result for one server."""
    manager = MagicMock()
    manager.check_health.return_value = {server_name: True}
    manager.call_tool.return_value = tool_result
    return manager


# ---------------------------------------------------------------------------
# YouTubeSearchTool — MCP path
# ---------------------------------------------------------------------------


class TestYouTubeSearchToolMCP:
    def test_live_source(self):
        """Returns youtube_mcp_live when MCP succeeds."""
        manager = _make_mcp_manager(
            "youtube",
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"total_views": 999000, "video_count": 42}',
                    }
                ]
            },
        )
        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = YouTubeSearchTool().execute(ip_name="TestIP")
        data = result["result"]
        assert data["source"] == "youtube_mcp_live"
        assert data["total_views"] == 999000
        assert data["video_count"] == 42

    def test_fallback_to_fixture(self):
        """Falls back to fixture when MCP unavailable."""
        manager = MagicMock()
        manager.check_health.return_value = {}

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = YouTubeSearchTool().execute(ip_name="Berserk")
        data = result["result"]
        assert data["source"] == "youtube_api_stub"
        assert data["total_views"] == 25_000_000


# ---------------------------------------------------------------------------
# RedditSentimentTool — MCP path
# ---------------------------------------------------------------------------


class TestRedditSentimentToolMCP:
    def test_live_source(self):
        manager = _make_mcp_manager(
            "reddit",
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"subscribers": 120000, "posts_per_week": 85}',
                    }
                ]
            },
        )
        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = RedditSentimentTool().execute(ip_name="TestIP")
        data = result["result"]
        assert data["source"] == "reddit_mcp_live"
        assert data["subreddit_subscribers"] == 120000

    def test_fallback_to_fixture(self):
        manager = MagicMock()
        manager.check_health.return_value = {}

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = RedditSentimentTool().execute(ip_name="Berserk")
        data = result["result"]
        assert data["source"] == "reddit_api_stub"
        assert data["subreddit_subscribers"] == 520_000


# ---------------------------------------------------------------------------
# SteamInfoTool — MCP path
# ---------------------------------------------------------------------------


class TestSteamInfoToolMCP:
    def test_live_source(self):
        manager = _make_mcp_manager(
            "steam",
            {"player_count": 5000, "review_score": 92, "review_count": 1500},
        )
        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = SteamInfoTool().execute(ip_name="TestIP")
        data = result["result"]
        assert data["source"] == "steam_mcp_live"
        assert data["dau_peak"] == 5000
        assert data["review_score"] == 92

    def test_fallback_to_fixture(self):
        manager = MagicMock()
        manager.check_health.return_value = {}

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = SteamInfoTool().execute(ip_name="Berserk")
        data = result["result"]
        assert data["source"] == "steam_api_stub"
        assert data["metacritic_score"] == 58


# ---------------------------------------------------------------------------
# TwitchStatsTool — MCP path
# ---------------------------------------------------------------------------


class TestTwitchStatsToolMCP:
    def test_live_source(self):
        manager = _make_mcp_manager(
            "igdb",
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"avg_concurrent_viewers": 300, "peak_concurrent_viewers": 1200}',
                    }
                ]
            },
        )
        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = TwitchStatsTool().execute(ip_name="TestIP")
        data = result["result"]
        assert data["source"] == "igdb_mcp_live"
        assert data["avg_concurrent_viewers"] == 300

    def test_fallback_to_fixture(self):
        manager = MagicMock()
        manager.check_health.return_value = {}

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = TwitchStatsTool().execute(ip_name="Cowboy Bebop")
        data = result["result"]
        assert data["source"] == "twitch_api_stub"
        assert data["avg_concurrent_viewers"] > 0


# ---------------------------------------------------------------------------
# GoogleTrendsTool — MCP path
# ---------------------------------------------------------------------------


class TestGoogleTrendsToolMCP:
    def test_live_source(self):
        manager = _make_mcp_manager(
            "google-trends",
            {
                "content": [
                    {
                        "type": "text",
                        "text": '{"interest_index": 85, "related_queries": ["game", "anime"]}',
                    }
                ]
            },
        )
        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = GoogleTrendsTool().execute(ip_name="TestIP")
        data = result["result"]
        assert data["source"] == "google_trends_mcp_live"
        assert data["trends_index"] == 85
        assert data["trend_direction"] == "rising"
        assert data["related_queries"] == ["game", "anime"]

    def test_fallback_to_fixture(self):
        manager = MagicMock()
        manager.check_health.return_value = {}

        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = GoogleTrendsTool().execute(ip_name="Berserk")
        data = result["result"]
        assert data["source"] == "google_trends_stub"
        assert data["trends_index"] == 78

    def test_live_with_region(self):
        manager = _make_mcp_manager(
            "google-trends",
            {"content": [{"type": "text", "text": '{"interest_index": 45}'}]},
        )
        with patch(
            _MCP_MANAGER_PATCH,
            return_value=manager,
        ):
            result = GoogleTrendsTool().execute(ip_name="TestIP", region="KR")
        data = result["result"]
        assert data["region"] == "KR"
        assert data["trend_direction"] == "stable"  # 45 <= 60


# ---------------------------------------------------------------------------
# MCP error handling — all tools
# ---------------------------------------------------------------------------


class TestMCPErrorHandling:
    @pytest.mark.parametrize(
        "tool_cls,ip_name,expected_stub_source",
        [
            (YouTubeSearchTool, "Berserk", "youtube_api_stub"),
            (RedditSentimentTool, "Berserk", "reddit_api_stub"),
            (TwitchStatsTool, "Berserk", "twitch_api_stub"),
            (SteamInfoTool, "Berserk", "steam_api_stub"),
            (GoogleTrendsTool, "Berserk", "google_trends_stub"),
        ],
    )
    def test_mcp_exception_falls_back(
        self, tool_cls: type, ip_name: str, expected_stub_source: str
    ):
        """All tools gracefully fall back when MCP raises."""
        with patch(
            _MCP_MANAGER_PATCH,
            side_effect=RuntimeError("MCP down"),
        ):
            result = tool_cls().execute(ip_name=ip_name)
        assert result["result"]["source"] == expected_stub_source
