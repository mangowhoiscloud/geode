"""Signal Collection Tools — external signal retrieval as LLM-callable tools.

Layer 5 tools for external signal collection (demo/stub):
- YouTubeSearchTool: YouTube engagement data
- RedditSentimentTool: Reddit community sentiment
- TwitchStatsTool: Twitch streaming statistics
- SteamInfoTool: Steam store/review data
- GoogleTrendsTool: Google Trends interest data
- WebSearchTool: Anthropic native web search for real-time signal enrichment

All tools return fixture data for known IPs and plausible
stub data for unknown IPs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import ANTHROPIC_BUDGET
from core.domains.game_ip.fixtures import load_fixture

# Load parameter schemas from centralized JSON
_SCHEMAS_PATH = Path(__file__).resolve().parent / "tool_schemas.json"
with _SCHEMAS_PATH.open(encoding="utf-8") as _f:
    _TOOL_SCHEMAS: dict[str, dict[str, Any]] = json.load(_f)


def _load_signal(ip_name: str, key: str, default: Any = None) -> Any:
    """Safely load a signal value from fixtures."""
    try:
        fixture = load_fixture(ip_name)
        return fixture.get("signals", {}).get(key, default)
    except ValueError:
        return default


class YouTubeSearchTool:
    """Tool for retrieving YouTube engagement signals."""

    @property
    def name(self) -> str:
        return "youtube_search"

    @property
    def description(self) -> str:
        return (
            "Search YouTube for IP-related content and return engagement "
            "metrics (total views, top video views, comment sentiment)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["YouTubeSearchTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name: str = kwargs["ip_name"]
        views = _load_signal(ip_name, "youtube_views", 0)
        return {
            "result": {
                "ip_name": ip_name,
                "total_views": views,
                "top_video_views": int(views * 0.3) if views else 0,
                "avg_comment_sentiment": 0.72 if views else 0.0,
                "video_count": 50 if views else 0,
                "source": "youtube_api_stub",
            }
        }


class RedditSentimentTool:
    """Tool for retrieving Reddit community sentiment signals."""

    @property
    def name(self) -> str:
        return "reddit_sentiment"

    @property
    def description(self) -> str:
        return (
            "Analyze Reddit sentiment for an IP across relevant subreddits. "
            "Returns subscriber count, post frequency, and sentiment scores."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["RedditSentimentTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name: str = kwargs["ip_name"]
        subscribers = _load_signal(ip_name, "reddit_subscribers", 0)
        return {
            "result": {
                "ip_name": ip_name,
                "subreddit_subscribers": subscribers,
                "posts_per_week": max(1, subscribers // 5000) if subscribers else 0,
                "avg_sentiment": 0.68 if subscribers else 0.0,
                "top_topics": ["game adaptation", "character design", "story potential"],
                "source": "reddit_api_stub",
            }
        }


class TwitchStatsTool:
    """Tool for retrieving Twitch streaming statistics."""

    @property
    def name(self) -> str:
        return "twitch_stats"

    @property
    def description(self) -> str:
        return (
            "Get Twitch streaming statistics for an IP including "
            "concurrent viewers, stream hours, and streamer count."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["TwitchStatsTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name: str = kwargs["ip_name"]
        # Derive Twitch metrics from YouTube views as proxy
        views = _load_signal(ip_name, "youtube_views", 0)
        has_data = views > 0
        return {
            "result": {
                "ip_name": ip_name,
                "avg_concurrent_viewers": int(views * 0.001) if has_data else 0,
                "peak_concurrent_viewers": int(views * 0.005) if has_data else 0,
                "total_stream_hours_30d": int(views * 0.0002) if has_data else 0,
                "unique_streamers_30d": int(views * 0.00005) if has_data else 0,
                "source": "twitch_api_stub",
            }
        }


class SteamInfoTool:
    """Tool for retrieving Steam store and review data."""

    @property
    def name(self) -> str:
        return "steam_info"

    @property
    def description(self) -> str:
        return (
            "Get Steam store information for an IP including "
            "review scores, player counts, and pricing data."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["SteamInfoTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name: str = kwargs["ip_name"]
        try:
            fixture = load_fixture(ip_name)
            monolake = fixture.get("monolake", {})
            signals = fixture.get("signals", {})
            return {
                "result": {
                    "ip_name": ip_name,
                    "metacritic_score": monolake.get("metacritic_score", 0),
                    "store_page_score": monolake.get("store_page_score", 0),
                    "dau_peak": monolake.get("dau_peak", 0),
                    "price_tier": monolake.get("price_tier", "none"),
                    "game_sales_data": signals.get("game_sales_data", "N/A"),
                    "platform": monolake.get("platform", "none"),
                    "source": "steam_api_stub",
                }
            }
        except ValueError:
            return {
                "result": {
                    "ip_name": ip_name,
                    "metacritic_score": 0,
                    "store_page_score": 0,
                    "dau_peak": 0,
                    "price_tier": "none",
                    "game_sales_data": "N/A",
                    "platform": "none",
                    "source": "steam_api_stub",
                }
            }


class GoogleTrendsTool:
    """Tool for retrieving Google Trends interest data."""

    @property
    def name(self) -> str:
        return "google_trends"

    @property
    def description(self) -> str:
        return (
            "Get Google Trends interest index and related queries "
            "for an IP over the past 12 months."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["GoogleTrendsTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        ip_name: str = kwargs["ip_name"]
        region: str = kwargs.get("region", "global")
        trends_index = _load_signal(ip_name, "google_trends_index", 0)
        genre_keywords = _load_signal(ip_name, "genre_fit_keywords", [])
        return {
            "result": {
                "ip_name": ip_name,
                "trends_index": trends_index,
                "region": region,
                "trend_direction": "rising" if trends_index > 60 else "stable",
                "related_queries": genre_keywords[:5] if genre_keywords else [],
                "source": "google_trends_stub",
            }
        }


class WebSearchTool:
    """Tool for real-time web search via Anthropic native web_search.

    Leverages Anthropic's built-in web search capability for live signal
    enrichment (YouTube, Reddit, Steam, news). Falls back to stub data
    when the API is unavailable.
    """

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for real-time information about an IP. "
            "Useful for finding recent news, community discussions, "
            "sales data, and market signals that may not be in fixtures."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return _TOOL_SCHEMAS["WebSearchTool"]

    def execute(self, **kwargs: Any) -> dict[str, Any]:
        query: str = kwargs["query"]
        max_results: int = kwargs.get("max_results", 5)

        # Attempt real web search via Anthropic SDK
        try:
            from core.config import settings
            from core.llm.client import get_anthropic_client

            if not settings.anthropic_api_key:
                return self._stub_result(query, "no_api_key")

            client = get_anthropic_client()
            response = client.messages.create(
                model=ANTHROPIC_BUDGET,
                max_tokens=1024,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Search the web for: {query}. "
                            f"Return up to {max_results} relevant results "
                            "with titles, URLs, and brief summaries."
                        ),
                    }
                ],
                timeout=30.0,
            )
            # Extract text from response
            text_parts: list[str] = []
            for block in response.content:
                if hasattr(block, "text"):
                    text_parts.append(block.text)
            return {
                "result": {
                    "query": query,
                    "search_results": "\n".join(text_parts),
                    "source": "anthropic_web_search",
                }
            }
        except Exception:
            return self._stub_result(query, "api_error")

    @staticmethod
    def _stub_result(query: str, reason: str) -> dict[str, Any]:
        return {
            "result": {
                "query": query,
                "search_results": f"Web search unavailable ({reason}). "
                "Use fixture data or retry later.",
                "source": "web_search_stub",
            }
        }
