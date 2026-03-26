"""Built-in MCP server catalog — search metadata for known MCP servers.

Provides a searchable catalog so users can discover and install servers via
natural language (e.g. "LinkedIn MCP 달아줘").

Execution configuration (command, args, env) lives in .geode/config.toml or
.claude/mcp_servers.json — NOT in this catalog.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MCPCatalogEntry:
    """A single MCP server in the built-in catalog."""

    name: str  # unique key, e.g. "brave-search"
    description: str  # one-line description
    tags: tuple[str, ...]  # searchable tags
    install_hint: str = ""  # e.g. "npx -y @playwright/mcp" or "uvx linkedin-scraper-mcp"
    env_keys: tuple[str, ...] = ()  # required env vars for operation


# ---------------------------------------------------------------------------
# Built-in catalog (44 entries)
# ---------------------------------------------------------------------------

MCP_CATALOG: dict[str, MCPCatalogEntry] = {
    # --- Official / Anthropic ---
    "brave-search": MCPCatalogEntry(
        name="brave-search",
        description="Web search via Brave Search API",
        tags=("search", "web", "brave"),
        install_hint="npx -y @brave/brave-search-mcp-server",
        env_keys=("BRAVE_API_KEY",),
    ),
    "memory": MCPCatalogEntry(
        name="memory",
        description="Knowledge Graph persistent memory (entity-relation-observation)",
        tags=("memory", "knowledge", "graph", "kg"),
        install_hint="npx -y @modelcontextprotocol/server-memory",
    ),
    "filesystem": MCPCatalogEntry(
        name="filesystem",
        description="Local filesystem read/write operations",
        tags=("filesystem", "file", "local", "disk"),
        install_hint="npx -y @modelcontextprotocol/server-filesystem",
    ),
    "git": MCPCatalogEntry(
        name="git",
        description="Git operations (diff, log, commit, branch)",
        tags=("git", "version", "vcs"),
        install_hint="npx -y @modelcontextprotocol/server-git",
    ),
    "sequential-thinking": MCPCatalogEntry(
        name="sequential-thinking",
        description="Complex reasoning chain with step-by-step thinking",
        tags=("thinking", "reasoning", "chain", "logic"),
        install_hint="npx -y @modelcontextprotocol/server-sequential-thinking",
    ),
    "puppeteer": MCPCatalogEntry(
        name="puppeteer",
        description="Browser automation via Puppeteer",
        tags=("browser", "puppeteer", "automation", "web"),
        install_hint="npx -y @modelcontextprotocol/server-puppeteer",
    ),
    "github": MCPCatalogEntry(
        name="github",
        description="GitHub API (repos, issues, PRs, search)",
        tags=("github", "git", "repo", "issue", "pr"),
        install_hint="npx -y @modelcontextprotocol/server-github",
        env_keys=("GITHUB_PERSONAL_ACCESS_TOKEN",),
    ),
    # --- Gaming ---
    "steam": MCPCatalogEntry(
        name="steam",
        description="Steam player counts, reviews, game info",
        tags=("steam", "game", "gaming", "player", "review"),
        install_hint="npx -y steam-mcp-server",
    ),
    "steam-reviews": MCPCatalogEntry(
        name="steam-reviews",
        description="Steam game reviews analysis and sentiment",
        tags=("steam", "review", "sentiment", "game", "gaming"),
        install_hint="npx -y fenxer/steam-review-mcp",
    ),
    "igdb": MCPCatalogEntry(
        name="igdb",
        description="IGDB game metadata (genre, platform, rating, franchise)",
        tags=("igdb", "game", "gaming", "metadata", "twitch"),
        install_hint="npx -y igdb-mcp-server",
        env_keys=("IGDB_CLIENT_ID", "IGDB_CLIENT_SECRET"),
    ),
    # --- Social / Community ---
    "discord": MCPCatalogEntry(
        name="discord",
        description="Discord server activity, channels, member data",
        tags=("discord", "social", "community", "chat", "gaming"),
        install_hint="npx -y v-3/discordmcp",
        env_keys=("DISCORD_BOT_TOKEN",),
    ),
    "linkedin-reader": MCPCatalogEntry(
        name="linkedin-reader",
        description="LinkedIn people/company/job search + profile scraping (Patchright browser)",
        tags=("linkedin", "social", "profile", "recruiting", "company", "job", "career"),
        install_hint="uvx linkedin-scraper-mcp",
    ),
    "reddit": MCPCatalogEntry(
        name="reddit",
        description="Reddit subreddit analysis, posts, sentiment",
        tags=("reddit", "social", "community", "sentiment", "forum"),
        install_hint="npx -y reddit-mcp-server",
    ),
    "twitter": MCPCatalogEntry(
        name="twitter",
        description="X (Twitter) mentions, trends, timeline",
        tags=("twitter", "x", "social", "trend", "tweet"),
        install_hint="npx -y datawhisker/mcp-server-x",
        env_keys=("TWITTER_BEARER_TOKEN",),
    ),
    "youtube": MCPCatalogEntry(
        name="youtube",
        description="YouTube video search, stats, comments",
        tags=("youtube", "video", "social", "stream"),
        install_hint="npx -y ZubeidHendricks/youtube-mcp-server",
        env_keys=("YOUTUBE_API_KEY",),
    ),
    "arxiv": MCPCatalogEntry(
        name="arxiv",
        description="arXiv paper search and metadata retrieval",
        tags=("arxiv", "paper", "research", "academic", "science"),
        install_hint="npx -y @fre4x/arxiv",
    ),
    # --- Search ---
    "tavily-search": MCPCatalogEntry(
        name="tavily-search",
        description="Real-time web search and data extraction",
        tags=("search", "web", "tavily", "realtime"),
        install_hint="npx -y tavily-ai/tavily-mcp",
        env_keys=("TAVILY_API_KEY",),
    ),
    "firecrawl": MCPCatalogEntry(
        name="firecrawl",
        description="Advanced web scraping with high success rate",
        tags=("scrape", "crawl", "web", "firecrawl"),
        install_hint="npx -y mendableai/firecrawl-mcp-server",
        env_keys=("FIRECRAWL_API_KEY",),
    ),
    "omnisearch": MCPCatalogEntry(
        name="omnisearch",
        description="Unified search across Tavily+Brave+Kagi+Perplexity",
        tags=("search", "unified", "multi", "omnisearch"),
        install_hint="npx -y erkinalp/omnisearch-mcp",
    ),
    # --- Knowledge Graph ---
    "wikidata": MCPCatalogEntry(
        name="wikidata",
        description="Wikidata knowledge graph (franchise, creator, studio metadata)",
        tags=("wikidata", "knowledge", "graph", "metadata", "wiki"),
        install_hint="npx -y zzaebok/mcp-wikidata",
    ),
    # --- Database / Vector ---
    "qdrant": MCPCatalogEntry(
        name="qdrant",
        description="Qdrant vector database for similarity search",
        tags=("vector", "db", "qdrant", "embedding", "rag"),
        install_hint="npx -y qdrant/mcp-server-qdrant",
        env_keys=("QDRANT_URL",),
    ),
    "pinecone": MCPCatalogEntry(
        name="pinecone",
        description="Pinecone managed vector embeddings",
        tags=("vector", "db", "pinecone", "embedding", "rag"),
        install_hint="npx -y pinecone-io/pinecone-mcp",
        env_keys=("PINECONE_API_KEY",),
    ),
    "sqlite": MCPCatalogEntry(
        name="sqlite",
        description="SQLite database operations",
        tags=("sqlite", "db", "sql", "database"),
        install_hint="npx -y @modelcontextprotocol/server-sqlite",
    ),
    # --- Memory ---
    "mcp-memory-service": MCPCatalogEntry(
        name="mcp-memory-service",
        description="Fast memory service with 5ms retrieval, causal KG",
        tags=("memory", "fast", "kg", "causal"),
        install_hint="npx -y doobidoo/mcp-memory-service",
    ),
    "zep": MCPCatalogEntry(
        name="zep",
        description="Temporal knowledge graph for time-axis analysis",
        tags=("memory", "temporal", "kg", "zep", "history"),
        install_hint="npx -y getzep/zep-mcp",
        env_keys=("ZEP_API_KEY",),
    ),
    # --- Messaging ---
    "gmail": MCPCatalogEntry(
        name="gmail",
        description="Gmail email read, send, search, label, and attachment management",
        tags=("email", "gmail", "messaging", "notification", "google"),
        install_hint="npx -y @gongrzhe/server-gmail-autoauth-mcp",
    ),
    "slack": MCPCatalogEntry(
        name="slack",
        description="Slack messaging and channel management",
        tags=("slack", "chat", "messaging", "team"),
        install_hint="npx -y @modelcontextprotocol/server-slack",
        env_keys=("SLACK_BOT_TOKEN", "SLACK_TEAM_ID"),
    ),
    "telegram": MCPCatalogEntry(
        name="telegram",
        description="Telegram bot messaging and chat management",
        tags=("telegram", "chat", "messaging", "bot"),
        install_hint="npx -y punkpeye/telegram-mcp",
        env_keys=("TELEGRAM_BOT_TOKEN",),
    ),
    # --- Calendar ---
    "google-calendar": MCPCatalogEntry(
        name="google-calendar",
        description="Google Calendar event management",
        tags=("google", "calendar", "schedule", "event"),
        install_hint="npx -y @anthropic/mcp-server-google-calendar",
        env_keys=("GOOGLE_CALENDAR_CREDENTIALS",),
    ),
    "caldav": MCPCatalogEntry(
        name="caldav",
        description="CalDAV calendar access (Apple Calendar, Nextcloud, etc.)",
        tags=("caldav", "calendar", "apple", "ical", "schedule"),
        install_hint="npx -y vatsalaggarwal/caldav-mcp-server",
        env_keys=("CALDAV_URL", "CALDAV_USERNAME", "CALDAV_PASSWORD"),
    ),
    # --- Productivity / Utilities ---
    "notion": MCPCatalogEntry(
        name="notion",
        description="Notion pages, databases, and content",
        tags=("notion", "wiki", "docs", "productivity"),
        install_hint="npx -y makenotion/notion-mcp-server",
        env_keys=("NOTION_API_KEY",),
    ),
    "google-drive": MCPCatalogEntry(
        name="google-drive",
        description="Google Drive file listing and content reading",
        tags=("google", "drive", "docs", "cloud", "storage"),
        install_hint="npx -y anthropics/mcp-server-google-drive",
    ),
    "google-maps": MCPCatalogEntry(
        name="google-maps",
        description="Google Maps places, directions, geocoding",
        tags=("google", "maps", "location", "geo"),
        install_hint="npx -y @modelcontextprotocol/server-google-maps",
        env_keys=("GOOGLE_MAPS_API_KEY",),
    ),
    # --- Agent Infrastructure ---
    "e2b": MCPCatalogEntry(
        name="e2b",
        description="Secure cloud sandbox for code execution (Python/JS)",
        tags=("sandbox", "code", "execution", "e2b", "isolated"),
        install_hint="npx -y @e2b/mcp-server",
        env_keys=("E2B_API_KEY",),
    ),
    "playwright": MCPCatalogEntry(
        name="playwright",
        description="Browser automation via Playwright (navigate, click, scrape)",
        tags=("browser", "playwright", "automation", "scrape"),
        install_hint="npx -y @playwright/mcp",
    ),
    "playwriter": MCPCatalogEntry(
        name="playwriter",
        description="Chrome extension bridge — control existing Chrome with logins/cookies intact",
        tags=("browser", "chrome", "auth", "login", "playwriter"),
        install_hint="npx -y playwriter@latest",
    ),
    "youtube-transcript": MCPCatalogEntry(
        name="youtube-transcript",
        description="YouTube video transcript extraction with language selection and timestamps",
        tags=("youtube", "transcript", "video", "chapter", "subtitle", "timeline"),
        install_hint="npx -y @fabriqa.ai/youtube-transcript-mcp@latest",
    ),
    # --- Financial ---
    "financial-datasets": MCPCatalogEntry(
        name="financial-datasets",
        description="Stock prices, financials, SEC filings for gaming companies",
        tags=("finance", "stock", "market", "financial", "sec"),
        install_hint="npx -y financial-datasets/mcp-server",
    ),
    # --- Development ---
    "sentry": MCPCatalogEntry(
        name="sentry",
        description="Sentry error tracking and issue management",
        tags=("sentry", "error", "monitoring", "debug"),
        install_hint="npx -y getsentry/sentry-mcp",
        env_keys=("SENTRY_AUTH_TOKEN",),
    ),
    "postgres": MCPCatalogEntry(
        name="postgres",
        description="PostgreSQL database operations",
        tags=("postgres", "db", "sql", "database"),
        install_hint="npx -y @modelcontextprotocol/server-postgres",
    ),
    "docker": MCPCatalogEntry(
        name="docker",
        description="Docker container management",
        tags=("docker", "container", "devops"),
        install_hint="npx -y docker/mcp-server-docker",
    ),
    # --- AI / LLM ---
    "langsmith": MCPCatalogEntry(
        name="langsmith",
        description="LangSmith tracing, datasets, and evaluation",
        tags=("langsmith", "tracing", "eval", "langchain"),
        install_hint="npx -y langsmith-mcp-server",
        env_keys=("LANGSMITH_API_KEY",),
    ),
    "exa": MCPCatalogEntry(
        name="exa",
        description="Exa AI-powered semantic search",
        tags=("search", "semantic", "ai", "exa"),
        install_hint="npx -y exa-labs/exa-mcp-server",
        env_keys=("EXA_API_KEY",),
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

            # install_hint match
            if entry.install_hint and tok in entry.install_hint.lower():
                score += 1.0

        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in scored[:limit]]
