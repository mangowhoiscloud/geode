"""Built-in MCP server catalog for auto-discovery and installation.

Provides a searchable catalog of well-known MCP servers so users can install
them via natural language (e.g. "LinkedIn MCP 달아줘").
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MCPCatalogEntry:
    """A single MCP server in the built-in catalog."""

    name: str  # unique key, e.g. "brave-search"
    package: str  # npm package or GitHub repo
    description: str  # one-line description
    tags: tuple[str, ...]  # searchable tags
    env_keys: tuple[str, ...] = ()  # required env vars
    command: str = "npx"  # default command
    extra_args: tuple[str, ...] = ()  # extra CLI args after package


# ---------------------------------------------------------------------------
# Built-in catalog (30+ entries)
# ---------------------------------------------------------------------------

MCP_CATALOG: dict[str, MCPCatalogEntry] = {
    # --- Official / Anthropic ---
    "brave-search": MCPCatalogEntry(
        name="brave-search",
        package="@anthropic/mcp-server-brave-search",
        description="Web search via Brave Search API",
        tags=("search", "web", "brave"),
        env_keys=("BRAVE_API_KEY",),
    ),
    "memory": MCPCatalogEntry(
        name="memory",
        package="@modelcontextprotocol/server-memory",
        description="Knowledge Graph persistent memory (entity-relation-observation)",
        tags=("memory", "knowledge", "graph", "kg"),
    ),
    "fetch": MCPCatalogEntry(
        name="fetch",
        package="@modelcontextprotocol/server-fetch",
        description="Web content fetcher with Markdown conversion",
        tags=("fetch", "web", "scrape", "url"),
    ),
    "filesystem": MCPCatalogEntry(
        name="filesystem",
        package="@modelcontextprotocol/server-filesystem",
        description="Local filesystem read/write operations",
        tags=("filesystem", "file", "local", "disk"),
    ),
    "git": MCPCatalogEntry(
        name="git",
        package="@modelcontextprotocol/server-git",
        description="Git operations (diff, log, commit, branch)",
        tags=("git", "version", "vcs"),
    ),
    "sequential-thinking": MCPCatalogEntry(
        name="sequential-thinking",
        package="@modelcontextprotocol/server-sequential-thinking",
        description="Complex reasoning chain with step-by-step thinking",
        tags=("thinking", "reasoning", "chain", "logic"),
    ),
    "puppeteer": MCPCatalogEntry(
        name="puppeteer",
        package="@modelcontextprotocol/server-puppeteer",
        description="Browser automation via Puppeteer",
        tags=("browser", "puppeteer", "automation", "web"),
    ),
    "github": MCPCatalogEntry(
        name="github",
        package="@modelcontextprotocol/server-github",
        description="GitHub API (repos, issues, PRs, search)",
        tags=("github", "git", "repo", "issue", "pr"),
        env_keys=("GITHUB_PERSONAL_ACCESS_TOKEN",),
    ),
    # --- Gaming ---
    "steam": MCPCatalogEntry(
        name="steam",
        package="algorhythmic/steam-mcp",
        description="Steam player counts, reviews, game info",
        tags=("steam", "game", "gaming", "player", "review"),
    ),
    "steam-reviews": MCPCatalogEntry(
        name="steam-reviews",
        package="fenxer/steam-review-mcp",
        description="Steam game reviews analysis and sentiment",
        tags=("steam", "review", "sentiment", "game", "gaming"),
    ),
    "igdb": MCPCatalogEntry(
        name="igdb",
        package="bielacki/igdb-mcp-server",
        description="IGDB game metadata (genre, platform, rating, franchise)",
        tags=("igdb", "game", "gaming", "metadata", "twitch"),
        env_keys=("TWITCH_CLIENT_ID", "TWITCH_CLIENT_SECRET"),
    ),
    # --- Social / Community ---
    "discord": MCPCatalogEntry(
        name="discord",
        package="v-3/discordmcp",
        description="Discord server activity, channels, member data",
        tags=("discord", "social", "community", "chat", "gaming"),
        env_keys=("DISCORD_BOT_TOKEN",),
    ),
    "linkedin": MCPCatalogEntry(
        name="linkedin",
        package="linkedin-mcp-runner",
        description="LinkedIn profile, company, job search (browser session)",
        tags=("linkedin", "social", "profile", "recruiting", "company", "job"),
    ),
    "reddit": MCPCatalogEntry(
        name="reddit",
        package="arindam200/reddit-mcp-server",
        description="Reddit subreddit analysis, posts, sentiment",
        tags=("reddit", "social", "community", "sentiment", "forum"),
    ),
    "twitter": MCPCatalogEntry(
        name="twitter",
        package="datawhisker/mcp-server-x",
        description="X (Twitter) mentions, trends, timeline",
        tags=("twitter", "x", "social", "trend", "tweet"),
        env_keys=("TWITTER_BEARER_TOKEN",),
    ),
    "youtube": MCPCatalogEntry(
        name="youtube",
        package="ZubeidHendricks/youtube-mcp-server",
        description="YouTube video search, stats, comments",
        tags=("youtube", "video", "social", "stream"),
        env_keys=("YOUTUBE_API_KEY",),
    ),
    # --- Search ---
    "tavily-search": MCPCatalogEntry(
        name="tavily-search",
        package="tavily-ai/tavily-mcp",
        description="Real-time web search and data extraction",
        tags=("search", "web", "tavily", "realtime"),
        env_keys=("TAVILY_API_KEY",),
    ),
    "firecrawl": MCPCatalogEntry(
        name="firecrawl",
        package="mendableai/firecrawl-mcp-server",
        description="Advanced web scraping with high success rate",
        tags=("scrape", "crawl", "web", "firecrawl"),
        env_keys=("FIRECRAWL_API_KEY",),
    ),
    "omnisearch": MCPCatalogEntry(
        name="omnisearch",
        package="erkinalp/omnisearch-mcp",
        description="Unified search across Tavily+Brave+Kagi+Perplexity",
        tags=("search", "unified", "multi", "omnisearch"),
    ),
    # --- Knowledge Graph ---
    "wikidata": MCPCatalogEntry(
        name="wikidata",
        package="zzaebok/mcp-wikidata",
        description="Wikidata knowledge graph (franchise, creator, studio metadata)",
        tags=("wikidata", "knowledge", "graph", "metadata", "wiki"),
    ),
    # --- Database / Vector ---
    "qdrant": MCPCatalogEntry(
        name="qdrant",
        package="qdrant/mcp-server-qdrant",
        description="Qdrant vector database for similarity search",
        tags=("vector", "db", "qdrant", "embedding", "rag"),
        env_keys=("QDRANT_URL",),
    ),
    "pinecone": MCPCatalogEntry(
        name="pinecone",
        package="pinecone-io/pinecone-mcp",
        description="Pinecone managed vector embeddings",
        tags=("vector", "db", "pinecone", "embedding", "rag"),
        env_keys=("PINECONE_API_KEY",),
    ),
    "sqlite": MCPCatalogEntry(
        name="sqlite",
        package="@modelcontextprotocol/server-sqlite",
        description="SQLite database operations",
        tags=("sqlite", "db", "sql", "database"),
    ),
    # --- Memory ---
    "mcp-memory-service": MCPCatalogEntry(
        name="mcp-memory-service",
        package="doobidoo/mcp-memory-service",
        description="Fast memory service with 5ms retrieval, causal KG",
        tags=("memory", "fast", "kg", "causal"),
    ),
    "zep": MCPCatalogEntry(
        name="zep",
        package="getzep/zep-mcp",
        description="Temporal knowledge graph for time-axis analysis",
        tags=("memory", "temporal", "kg", "zep", "history"),
        env_keys=("ZEP_API_KEY",),
    ),
    # --- Productivity / Utilities ---
    "slack": MCPCatalogEntry(
        name="slack",
        package="@anthropic/mcp-server-slack",
        description="Slack messaging and channel management",
        tags=("slack", "chat", "messaging", "team"),
        env_keys=("SLACK_BOT_TOKEN",),
    ),
    "notion": MCPCatalogEntry(
        name="notion",
        package="makenotion/notion-mcp-server",
        description="Notion pages, databases, and content",
        tags=("notion", "wiki", "docs", "productivity"),
        env_keys=("NOTION_API_KEY",),
    ),
    "google-drive": MCPCatalogEntry(
        name="google-drive",
        package="anthropics/mcp-server-google-drive",
        description="Google Drive file listing and content reading",
        tags=("google", "drive", "docs", "cloud", "storage"),
    ),
    "google-maps": MCPCatalogEntry(
        name="google-maps",
        package="@anthropic/mcp-server-google-maps",
        description="Google Maps places, directions, geocoding",
        tags=("google", "maps", "location", "geo"),
        env_keys=("GOOGLE_MAPS_API_KEY",),
    ),
    # --- Agent Infrastructure ---
    "e2b": MCPCatalogEntry(
        name="e2b",
        package="e2b-dev/mcp-server",
        description="Secure cloud sandbox for code execution (Python/JS)",
        tags=("sandbox", "code", "execution", "e2b", "isolated"),
        env_keys=("E2B_API_KEY",),
    ),
    "playwright": MCPCatalogEntry(
        name="playwright",
        package="executeautomation/mcp-playwright",
        description="Browser automation via Playwright (navigate, click, scrape)",
        tags=("browser", "playwright", "automation", "scrape"),
    ),
    # --- Financial ---
    "financial-datasets": MCPCatalogEntry(
        name="financial-datasets",
        package="financial-datasets/mcp-server",
        description="Stock prices, financials, SEC filings for gaming companies",
        tags=("finance", "stock", "market", "financial", "sec"),
    ),
    # --- Development ---
    "sentry": MCPCatalogEntry(
        name="sentry",
        package="getsentry/sentry-mcp",
        description="Sentry error tracking and issue management",
        tags=("sentry", "error", "monitoring", "debug"),
        env_keys=("SENTRY_AUTH_TOKEN",),
    ),
    "postgres": MCPCatalogEntry(
        name="postgres",
        package="@modelcontextprotocol/server-postgres",
        description="PostgreSQL database operations",
        tags=("postgres", "db", "sql", "database"),
    ),
    "docker": MCPCatalogEntry(
        name="docker",
        package="docker/mcp-server-docker",
        description="Docker container management",
        tags=("docker", "container", "devops"),
    ),
    # --- AI / LLM ---
    "langsmith": MCPCatalogEntry(
        name="langsmith",
        package="langchain-ai/langsmith-mcp-server",
        description="LangSmith tracing, datasets, and evaluation",
        tags=("langsmith", "tracing", "eval", "langchain"),
        env_keys=("LANGSMITH_API_KEY",),
    ),
    "exa": MCPCatalogEntry(
        name="exa",
        package="exa-labs/exa-mcp-server",
        description="Exa AI-powered semantic search",
        tags=("search", "semantic", "ai", "exa"),
        env_keys=("EXA_API_KEY",),
    ),
    # --- Data / Trends ---
    "google-trends": MCPCatalogEntry(
        name="google-trends",
        package="andrewlwn77/google-trends-mcp",
        description="Google Trends interest and search volume data",
        tags=("google", "trends", "interest", "popularity"),
    ),
}


def search_catalog(query: str, limit: int = 5) -> list[MCPCatalogEntry]:
    """Search the catalog by keyword matching on name, description, and tags.

    Returns up to *limit* entries sorted by relevance score (descending).
    """
    if not query.strip():
        return []

    tokens = query.lower().split()
    scored: list[tuple[float, MCPCatalogEntry]] = []

    for entry in MCP_CATALOG.values():
        score = 0.0
        name_lower = entry.name.lower()
        desc_lower = entry.description.lower()

        for tok in tokens:
            # Exact name match → highest weight
            if tok == name_lower:
                score += 10.0
            elif tok in name_lower:
                score += 5.0

            # Tag match → high weight
            for tag in entry.tags:
                if tok == tag.lower():
                    score += 4.0
                elif tok in tag.lower():
                    score += 2.0

            # Description match
            if tok in desc_lower:
                score += 1.5

            # Package match
            if tok in entry.package.lower():
                score += 1.0

        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:limit]]
