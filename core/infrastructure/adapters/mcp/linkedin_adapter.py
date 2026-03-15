"""LinkedIn MCP Adapter — profile and company data via linkedin-scraper-mcp."""

from __future__ import annotations

import logging
from typing import Any

from core.infrastructure.adapters.mcp.base import MCPClientBase

log = logging.getLogger(__name__)


class LinkedInMCPAdapter:
    """Fetch LinkedIn profiles and company data via MCP server.

    Implements LinkedInPort. Falls back gracefully if MCP unavailable.
    Tools provided by stickerdaniel/linkedin-mcp-server:
      get_person_profile, get_company_profile, search_people,
      search_jobs, get_job_details, get_company_posts, close_session
    """

    def __init__(self, mcp_client: MCPClientBase) -> None:
        self._client = mcp_client

    def get_person_profile(self, url: str) -> dict[str, Any]:
        """Fetch a person's LinkedIn profile by URL."""
        if not self._client.is_connected():
            return {}
        try:
            return self._client.call_tool("get_person_profile", {"url": url})
        except Exception as exc:
            log.warning("LinkedIn person profile fetch failed for %s: %s", url, exc)
            return {}

    def get_company_profile(self, url: str) -> dict[str, Any]:
        """Fetch a company's LinkedIn profile by URL."""
        if not self._client.is_connected():
            return {}
        try:
            return self._client.call_tool("get_company_profile", {"url": url})
        except Exception as exc:
            log.warning("LinkedIn company profile fetch failed for %s: %s", url, exc)
            return {}

    def search_people(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        """Search LinkedIn people by keyword."""
        if not self._client.is_connected():
            return []
        try:
            result = self._client.call_tool(
                "search_people",
                {"query": query, "limit": count},
            )
            results: list[dict[str, Any]] = result.get("results", [])
            return results
        except Exception as exc:
            log.warning("LinkedIn people search failed for '%s': %s", query, exc)
            return []

    def search_jobs(self, query: str, *, count: int = 5) -> list[dict[str, Any]]:
        """Search LinkedIn job postings."""
        if not self._client.is_connected():
            return []
        try:
            result = self._client.call_tool(
                "search_jobs",
                {"query": query, "limit": count},
            )
            results: list[dict[str, Any]] = result.get("results", [])
            return results
        except Exception as exc:
            log.warning("LinkedIn job search failed for '%s': %s", query, exc)
            return []

    def get_company_posts(self, url: str) -> list[dict[str, Any]]:
        """Fetch recent posts from a company page."""
        if not self._client.is_connected():
            return []
        try:
            result = self._client.call_tool("get_company_posts", {"url": url})
            posts: list[dict[str, Any]] = result.get("posts", [])
            return posts
        except Exception as exc:
            log.warning("LinkedIn company posts fetch failed for %s: %s", url, exc)
            return []

    def is_available(self) -> bool:
        return self._client.is_connected()
