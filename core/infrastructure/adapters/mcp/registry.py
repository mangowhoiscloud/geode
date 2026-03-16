"""MCP Server Registry — code-level server registration for session persistence.

Builds MCP server configs from the built-in catalog based on environment
variable availability.  Servers whose required env vars are present are
auto-discovered; servers with no required env vars (e.g. steam, arxiv)
are registered as "always available" defaults.

The registry output is a plain dict[str, ServerConfig] that MCPServerManager
can merge with the file-based .claude/mcp_servers.json overrides.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

from dotenv import dotenv_values

from core.infrastructure.adapters.mcp.catalog import MCP_CATALOG, MCPCatalogEntry

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPServerConfig:
    """Resolved MCP server connection configuration."""

    command: str
    args: list[str]
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to the dict format MCPServerManager expects."""
        d: dict[str, Any] = {"command": self.command, "args": self.args}
        if self.env:
            d["env"] = self.env
        return d


# ---------------------------------------------------------------------------
# Default servers — always registered (no API key required)
# ---------------------------------------------------------------------------

DEFAULT_SERVERS: tuple[str, ...] = (
    "steam",
    "fetch",
    "sequential-thinking",
    "playwright",
)

# ---------------------------------------------------------------------------
# Auto-discovered servers — registered when their env vars are present
# ---------------------------------------------------------------------------

AUTO_DISCOVER_SERVERS: tuple[str, ...] = (
    "brave-search",
    "linkedin",
    "github",
    "slack",
    "tavily-search",
    "langsmith",
    "youtube",
    "sentry",
    "google-maps",
    "notion",
    "firecrawl",
    "exa",
    "twitter",
    "discord",
    "igdb",
    "qdrant",
    "pinecone",
    "zep",
    "e2b",
)


def _catalog_entry_to_config(entry: MCPCatalogEntry) -> MCPServerConfig:
    """Convert a catalog entry to a server config."""
    args = ["-y", entry.package, *entry.extra_args]
    env = {k: f"${{{k}}}" for k in entry.env_keys}
    return MCPServerConfig(command=entry.command, args=args, env=env)


def _has_env_keys(
    keys: tuple[str, ...],
    dotenv_cache: dict[str, str | None],
) -> bool:
    """Check whether all required env vars are set (os.environ or .env)."""
    for key in keys:
        val = os.environ.get(key) or dotenv_cache.get(key)
        if not val:
            return False
    return True


class MCPRegistry:
    """Builds MCP server configs from catalog + environment detection.

    Usage::

        registry = MCPRegistry()
        servers = registry.discover()
        # servers: dict[str, dict] ready for MCPServerManager
    """

    def __init__(
        self,
        *,
        dotenv_path: str = ".env",
        defaults: tuple[str, ...] = DEFAULT_SERVERS,
        auto_discover: tuple[str, ...] = AUTO_DISCOVER_SERVERS,
    ) -> None:
        self._dotenv_path = dotenv_path
        self._defaults = defaults
        self._auto_discover = auto_discover
        self._dotenv_cache: dict[str, str | None] = {}
        if os.path.exists(dotenv_path):
            self._dotenv_cache = dotenv_values(dotenv_path)

    def discover(self) -> dict[str, dict[str, Any]]:
        """Return server configs for all available MCP servers.

        1. Always include DEFAULT_SERVERS (no env requirement).
        2. Include AUTO_DISCOVER_SERVERS whose env vars are present.
        3. Return as dict[server_name, config_dict] for MCPServerManager.
        """
        result: dict[str, dict[str, Any]] = {}

        # 1. Default servers (no env keys required)
        for name in self._defaults:
            entry = MCP_CATALOG.get(name)
            if entry is None:
                continue
            config = _catalog_entry_to_config(entry)
            result[name] = config.to_dict()
            log.debug("MCP registry: default server '%s'", name)

        # 2. Auto-discover servers (env keys required)
        for name in self._auto_discover:
            entry = MCP_CATALOG.get(name)
            if entry is None:
                continue
            if not entry.env_keys:
                # No env required — treat as default
                config = _catalog_entry_to_config(entry)
                result[name] = config.to_dict()
                log.debug("MCP registry: auto server '%s' (no env required)", name)
                continue
            if _has_env_keys(entry.env_keys, self._dotenv_cache):
                config = _catalog_entry_to_config(entry)
                result[name] = config.to_dict()
                log.debug("MCP registry: auto-discovered '%s'", name)
            else:
                log.debug(
                    "MCP registry: skipped '%s' (missing: %s)",
                    name,
                    ", ".join(entry.env_keys),
                )

        return result

    def list_available(self) -> list[str]:
        """Return names of servers that would be registered."""
        return sorted(self.discover().keys())

    def list_missing_env(self) -> dict[str, list[str]]:
        """Return servers that could be enabled with missing env vars.

        Useful for showing users what they need to configure.
        """
        missing: dict[str, list[str]] = {}
        for name in self._auto_discover:
            entry = MCP_CATALOG.get(name)
            if entry is None or not entry.env_keys:
                continue
            if not _has_env_keys(entry.env_keys, self._dotenv_cache):
                absent = [
                    k
                    for k in entry.env_keys
                    if not (os.environ.get(k) or self._dotenv_cache.get(k))
                ]
                missing[name] = absent
        return missing
