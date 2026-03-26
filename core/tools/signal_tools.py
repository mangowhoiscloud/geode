"""Signal Collection Tools — external signal retrieval as LLM-callable tools.

Layer 4 tools for external signal collection:
- YouTubeSearchTool: YouTube engagement data (MCP -> fixture fallback)
- RedditSentimentTool: Reddit community sentiment (MCP -> fixture fallback)
- TwitchStatsTool: Twitch streaming statistics (MCP -> fixture fallback)
- SteamInfoTool: Steam store/review data (MCP -> fixture fallback)
- GoogleTrendsTool: Google Trends interest data (MCP -> fixture fallback)
- WebSearchTool: Anthropic native web search for real-time signal enrichment

Each tool tries MCP server first, then falls back to fixture data.
The ``source`` field in results indicates data provenance.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.config import ANTHROPIC_BUDGET
from core.domains.game_ip.fixtures import load_fixture

log = logging.getLogger(__name__)

# Load parameter schemas from centralized JSON
_SCHEMAS_PATH = Path(__file__).resolve().parent / "tool_schemas.json"
with _SCHEMAS_PATH.open(encoding="utf-8") as _f:
    _TOOL_SCHEMAS: dict[str, dict[str, Any]] = json.load(_f)


# ---------------------------------------------------------------------------
# MCP helpers
# ---------------------------------------------------------------------------


def _parse_mcp_content(result: dict[str, Any]) -> dict[str, Any]:
    """Extract structured data from MCP tool result.

    MCP tools return ``content`` array with text/image blocks.
    Tries to parse text content as JSON, falls back to raw text dict.
    Some non-standard servers may return data keys directly.
    """
    content = result.get("content")
    if not isinstance(content, list) or not content:
        # Direct dict with data keys (non-standard) — return as-is
        return result

    texts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            # Try parsing as JSON first
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except (json.JSONDecodeError, TypeError):
                pass
            texts.append(text)

    if texts:
        return {"text": "\n".join(texts)}
    return result


def _try_mcp_signal(
    server_name: str,
    tool_name: str,
    args: dict[str, Any],
) -> dict[str, Any] | None:
    """Try calling an MCP tool. Returns parsed result dict or None on failure.

    Lazily imports MCPServerManager to avoid circular imports.
    Never raises -- all errors are caught and logged.
    """
    try:
        from core.mcp.manager import get_mcp_manager

        manager = get_mcp_manager()
        health = manager.check_health()
        if not health.get(server_name, False):
            return None

        result = manager.call_tool(server_name, tool_name, args)
        if "error" in result:
            log.debug(
                "MCP signal %s/%s error: %s",
                server_name,
                tool_name,
                result["error"],
            )
            return None

        return _parse_mcp_content(result)
    except Exception as exc:
        log.debug("MCP signal %s/%s failed: %s", server_name, tool_name, exc)
        return None


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _load_signal(ip_name: str, key: str, default: Any = None) -> Any:
    """Safely load a signal value from fixtures."""
    try:
        fixture = load_fixture(ip_name)
        return fixture.get("signals", {}).get(key, default)
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Signal Tools
# ---------------------------------------------------------------------------


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

        # Tier 1: YouTube MCP server
        mcp = _try_mcp_signal("youtube", "search_videos", {"query": ip_name})
        if mcp is not None:
            return {
                "result": {
                    "ip_name": ip_name,
                    "total_views": mcp.get("total_views", mcp.get("view_count", 0)),
                    "top_video_views": mcp.get("top_video_views", 0),
                    "avg_comment_sentiment": mcp.get("avg_sentiment", 0.0),
                    "video_count": mcp.get("video_count", mcp.get("total_results", 0)),
                    "source": "youtube_mcp_live",
                    "raw_mcp": mcp.get("text") if "text" in mcp else None,
                }
            }

        # Tier 2: Fixture fallback
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

        # Tier 1: Reddit MCP server
        mcp = _try_mcp_signal("reddit", "search_posts", {"query": ip_name})
        if mcp is not None:
            return {
                "result": {
                    "ip_name": ip_name,
                    "subreddit_subscribers": mcp.get(
                        "subscribers", mcp.get("subreddit_subscribers", 0)
                    ),
                    "posts_per_week": mcp.get("posts_per_week", 0),
                    "avg_sentiment": mcp.get("avg_sentiment", 0.0),
                    "top_topics": mcp.get("top_topics", []),
                    "source": "reddit_mcp_live",
                    "raw_mcp": mcp.get("text") if "text" in mcp else None,
                }
            }

        # Tier 2: Fixture fallback
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

        # Tier 1: IGDB MCP server (Twitch/IGDB share Twitch API ecosystem)
        mcp = _try_mcp_signal("igdb", "search_games", {"query": ip_name})
        if mcp is not None:
            return {
                "result": {
                    "ip_name": ip_name,
                    "avg_concurrent_viewers": mcp.get("avg_concurrent_viewers", 0),
                    "peak_concurrent_viewers": mcp.get("peak_concurrent_viewers", 0),
                    "total_stream_hours_30d": mcp.get("total_stream_hours_30d", 0),
                    "unique_streamers_30d": mcp.get("unique_streamers_30d", 0),
                    "source": "igdb_mcp_live",
                    "raw_mcp": mcp.get("text") if "text" in mcp else None,
                }
            }

        # Tier 2: Fixture fallback (derive from YouTube views as proxy)
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

        # Tier 1: Steam MCP server (tool name confirmed: get_game_info)
        mcp = _try_mcp_signal("steam", "get_game_info", {"query": ip_name})
        if mcp is not None:
            return {
                "result": {
                    "ip_name": ip_name,
                    "metacritic_score": mcp.get("metacritic_score", 0),
                    "store_page_score": mcp.get("store_page_score", 0),
                    "dau_peak": mcp.get("player_count", mcp.get("dau_peak", 0)),
                    "price_tier": mcp.get("price_tier", "unknown"),
                    "game_sales_data": mcp.get("game_sales_data", "N/A"),
                    "platform": mcp.get("platform", "unknown"),
                    "review_score": mcp.get("review_score", 0),
                    "review_count": mcp.get("review_count", 0),
                    "source": "steam_mcp_live",
                    "raw_mcp": mcp.get("text") if "text" in mcp else None,
                }
            }

        # Tier 2: Fixture fallback
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

        # Tier 1: Google Trends MCP server
        mcp = _try_mcp_signal(
            "google-trends",
            "get_interest_over_time",
            {"keyword": ip_name, "region": region},
        )
        if mcp is not None:
            trends_val = mcp.get(
                "interest_index", mcp.get("trends_index", mcp.get("average_interest", 0))
            )
            return {
                "result": {
                    "ip_name": ip_name,
                    "trends_index": trends_val,
                    "region": region,
                    "trend_direction": "rising" if trends_val > 60 else "stable",
                    "related_queries": mcp.get("related_queries", []),
                    "source": "google_trends_mcp_live",
                    "raw_mcp": mcp.get("text") if "text" in mcp else None,
                }
            }

        # Tier 2: Fixture fallback
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
            from core.llm.router import get_anthropic_client

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
