"""MCP Server Registry — Anthropic API-backed discovery with local cache.

Replaces the static hardcoded catalog (catalog.py) with a live registry
that fetches from Anthropic's MCP registry API and caches locally.

Cache TTL: 24 hours. Falls back to stale cache if API is unreachable.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_REGISTRY_API = (
    "https://api.anthropic.com/mcp-registry/v0/servers"
    "?version=latest&visibility=commercial&limit=200"
)
_CACHE_TTL_S = 86400  # 24 hours
_CACHE_DIR = Path.home() / ".geode"
_CACHE_FILE = _CACHE_DIR / "mcp-registry-cache.json"


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    """A single MCP server from the Anthropic registry."""

    name: str
    title: str
    description: str
    repository_url: str = ""


def fetch_registry(*, force: bool = False) -> list[RegistryEntry]:
    """Fetch MCP server list from Anthropic registry API.

    Returns cached data if fresh (< 24h). Falls back to stale cache
    on network failure. Returns empty list if no cache and API fails.
    """
    # Check cache freshness
    if not force and _CACHE_FILE.exists():
        try:
            cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            age = time.time() - cache.get("fetched_at", 0)
            if age < _CACHE_TTL_S:
                return _parse_entries(cache.get("servers", []))
        except (json.JSONDecodeError, OSError):
            log.debug("Cache read failed", exc_info=True)

    # Fetch from API
    entries = _fetch_from_api()
    if entries is not None:
        return entries

    # Fallback: stale cache
    if _CACHE_FILE.exists():
        try:
            cache = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            log.info("Using stale registry cache (API unreachable)")
            return _parse_entries(cache.get("servers", []))
        except (json.JSONDecodeError, OSError):
            pass

    return []


def search_registry(query: str, limit: int = 5) -> list[RegistryEntry]:
    """Search the registry by keyword. Returns top matches."""
    if not query.strip():
        return []

    entries = fetch_registry()
    if not entries:
        return []

    tokens = query.lower().split()
    scored: list[tuple[float, RegistryEntry]] = []

    for entry in entries:
        score = 0.0
        name_lower = entry.name.lower()
        title_lower = entry.title.lower()
        desc_lower = entry.description.lower()

        for token in tokens:
            if token in (name_lower, title_lower):
                score += 10.0
            elif token in name_lower or token in title_lower:
                score += 5.0
            elif token in desc_lower:
                score += 1.5

        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:limit]]


def _fetch_from_api() -> list[RegistryEntry] | None:
    """Fetch all pages from the Anthropic registry API."""
    try:
        import httpx
    except ImportError:
        log.debug("httpx not available — skipping registry fetch")
        return None

    all_servers: list[dict[str, Any]] = []
    url = _REGISTRY_API

    try:
        client = httpx.Client(timeout=10.0)
        while url:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

            servers = data.get("servers", [])
            all_servers.extend(servers)

            cursor = data.get("metadata", {}).get("nextCursor")
            if cursor:
                url = (
                    "https://api.anthropic.com/mcp-registry/v0/servers"
                    f"?version=latest&visibility=commercial&limit=200"
                    f"&cursor={cursor}"
                )
            else:
                url = ""
        client.close()
    except Exception:
        log.debug("Registry API fetch failed", exc_info=True)
        return None

    # Save to cache
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_data = {
            "fetched_at": time.time(),
            "servers": all_servers,
        }
        _CACHE_FILE.write_text(
            json.dumps(cache_data, ensure_ascii=False),
            encoding="utf-8",
        )
        log.info("Registry cached: %d servers", len(all_servers))
    except OSError:
        log.debug("Cache write failed", exc_info=True)

    return _parse_entries(all_servers)


def _parse_entries(raw: list[dict[str, Any]]) -> list[RegistryEntry]:
    """Parse raw API response into RegistryEntry objects."""
    entries: list[RegistryEntry] = []
    for item in raw:
        server = item.get("server", item)
        name = server.get("name", "")
        if not name:
            continue
        repo = server.get("repository", {})
        entries.append(
            RegistryEntry(
                name=name,
                title=server.get("title", name),
                description=server.get("description", ""),
                repository_url=repo.get("url", "") if isinstance(repo, dict) else "",
            )
        )
    return entries
