"""Tests for Signal Collection Tools."""

from __future__ import annotations

from core.tools.base import Tool
from core.tools.registry import ToolRegistry
from core.tools.signal_tools import (
    GoogleTrendsTool,
    RedditSentimentTool,
    SteamInfoTool,
    TwitchStatsTool,
    YouTubeSearchTool,
)


class TestYouTubeSearchTool:
    def test_satisfies_protocol(self):
        assert isinstance(YouTubeSearchTool(), Tool)

    def test_name(self):
        assert YouTubeSearchTool().name == "youtube_search"

    def test_execute_known_ip(self):
        tool = YouTubeSearchTool()
        result = tool.execute(ip_name="Berserk")
        data = result["result"]
        assert data["ip_name"] == "Berserk"
        assert data["total_views"] == 25_000_000
        assert data["top_video_views"] > 0
        assert data["source"] == "youtube_api_stub"

    def test_execute_unknown_ip(self):
        tool = YouTubeSearchTool()
        result = tool.execute(ip_name="Unknown IP")
        data = result["result"]
        assert data["total_views"] == 0
        assert data["video_count"] == 0


class TestRedditSentimentTool:
    def test_satisfies_protocol(self):
        assert isinstance(RedditSentimentTool(), Tool)

    def test_name(self):
        assert RedditSentimentTool().name == "reddit_sentiment"

    def test_execute_known_ip(self):
        tool = RedditSentimentTool()
        result = tool.execute(ip_name="Berserk")
        data = result["result"]
        assert data["subreddit_subscribers"] == 520_000
        assert data["posts_per_week"] > 0

    def test_execute_unknown_ip_zero_subs(self):
        tool = RedditSentimentTool()
        result = tool.execute(ip_name="Unknown")
        assert result["result"]["subreddit_subscribers"] == 0


class TestTwitchStatsTool:
    def test_satisfies_protocol(self):
        assert isinstance(TwitchStatsTool(), Tool)

    def test_name(self):
        assert TwitchStatsTool().name == "twitch_stats"

    def test_execute_known_ip(self):
        tool = TwitchStatsTool()
        result = tool.execute(ip_name="Cowboy Bebop")
        data = result["result"]
        assert data["ip_name"] == "Cowboy Bebop"
        assert data["avg_concurrent_viewers"] > 0
        assert data["source"] == "twitch_api_stub"


class TestSteamInfoTool:
    def test_satisfies_protocol(self):
        assert isinstance(SteamInfoTool(), Tool)

    def test_name(self):
        assert SteamInfoTool().name == "steam_info"

    def test_execute_berserk(self):
        tool = SteamInfoTool()
        result = tool.execute(ip_name="Berserk")
        data = result["result"]
        assert data["metacritic_score"] == 58
        assert data["platform"] == "ps4_pc"

    def test_execute_unknown_ip_returns_defaults(self):
        tool = SteamInfoTool()
        result = tool.execute(ip_name="Unknown")
        data = result["result"]
        assert data["metacritic_score"] == 0
        assert data["platform"] == "none"


class TestGoogleTrendsTool:
    def test_satisfies_protocol(self):
        assert isinstance(GoogleTrendsTool(), Tool)

    def test_name(self):
        assert GoogleTrendsTool().name == "google_trends"

    def test_execute_berserk_rising(self):
        tool = GoogleTrendsTool()
        result = tool.execute(ip_name="Berserk")
        data = result["result"]
        assert data["trends_index"] == 78
        assert data["trend_direction"] == "rising"

    def test_execute_ghost_stable(self):
        tool = GoogleTrendsTool()
        result = tool.execute(ip_name="Ghost in the Shell")
        data = result["result"]
        assert data["trends_index"] == 55
        assert data["trend_direction"] == "stable"


class TestSignalToolsRegistry:
    def test_register_all_signal_tools(self):
        registry = ToolRegistry()
        registry.register(YouTubeSearchTool())
        registry.register(RedditSentimentTool())
        registry.register(TwitchStatsTool())
        registry.register(SteamInfoTool())
        registry.register(GoogleTrendsTool())

        assert len(registry) == 5
        assert "youtube_search" in registry
        assert "reddit_sentiment" in registry
        assert "twitch_stats" in registry
        assert "steam_info" in registry
        assert "google_trends" in registry
