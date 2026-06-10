"""Tests for MCP registry (Anthropic API-backed) and manager.get_status()."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from core.mcp.registry import RegistryEntry, _parse_entries, search_registry

# ---------------------------------------------------------------------------
# RegistryEntry
# ---------------------------------------------------------------------------


class TestRegistryEntry:
    def test_required_fields(self) -> None:
        entry = RegistryEntry(
            name="test/mcp",
            title="Test",
            description="Test server",
        )
        assert entry.name == "test/mcp"
        assert entry.title == "Test"
        assert entry.repository_url == ""

    def test_frozen(self) -> None:
        entry = RegistryEntry(name="x", title="X", description="d")
        with pytest.raises(AttributeError):
            entry.name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _parse_entries
# ---------------------------------------------------------------------------


class TestParseEntries:
    def test_parse_api_format(self) -> None:
        raw = [
            {
                "server": {
                    "name": "com.example/mcp",
                    "title": "Example",
                    "description": "An example server",
                    "repository": {"url": "https://github.com/example/mcp"},
                }
            }
        ]
        entries = _parse_entries(raw)
        assert len(entries) == 1
        assert entries[0].name == "com.example/mcp"
        assert entries[0].title == "Example"
        assert entries[0].repository_url == "https://github.com/example/mcp"

    def test_skip_empty_name(self) -> None:
        raw = [{"server": {"name": "", "description": "no name"}}]
        assert _parse_entries(raw) == []

    def test_missing_repository(self) -> None:
        raw = [{"server": {"name": "x", "title": "X", "description": "d"}}]
        entries = _parse_entries(raw)
        assert entries[0].repository_url == ""


# ---------------------------------------------------------------------------
# search_registry (with mocked fetch)
# ---------------------------------------------------------------------------


class TestSearchRegistry:
    @pytest.fixture()
    def _mock_entries(self) -> list[RegistryEntry]:
        return [
            RegistryEntry("com.github/mcp", "GitHub", "GitHub API access"),
            RegistryEntry("com.slack/mcp", "Slack", "Slack messaging"),
            RegistryEntry("com.steam/mcp", "Steam", "Steam game data"),
        ]

    def test_exact_name_match(self, _mock_entries: list[RegistryEntry]) -> None:
        with patch("core.mcp.registry.fetch_registry", return_value=_mock_entries):
            results = search_registry("github")
        assert results[0].name == "com.github/mcp"

    def test_description_match(self, _mock_entries: list[RegistryEntry]) -> None:
        with patch("core.mcp.registry.fetch_registry", return_value=_mock_entries):
            results = search_registry("messaging")
        assert results[0].name == "com.slack/mcp"

    def test_empty_query(self) -> None:
        assert search_registry("") == []

    def test_no_matches(self, _mock_entries: list[RegistryEntry]) -> None:
        with patch("core.mcp.registry.fetch_registry", return_value=_mock_entries):
            results = search_registry("nonexistent_xyz")
        assert results == []

    def test_limit_respected(self, _mock_entries: list[RegistryEntry]) -> None:
        with patch("core.mcp.registry.fetch_registry", return_value=_mock_entries):
            results = search_registry("mcp", limit=1)
        assert len(results) <= 1


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class TestRegistryCache:
    def test_cache_write_and_read(self, tmp_path: Path) -> None:
        import time

        from core.mcp import registry

        cache_file = tmp_path / "cache.json"
        with (
            patch.object(registry, "_CACHE_FILE", cache_file),
            patch.object(registry, "_CACHE_DIR", tmp_path),
        ):
            # Write cache
            cache_data = {
                "fetched_at": time.time(),
                "servers": [
                    {
                        "server": {
                            "name": "test/mcp",
                            "title": "Test",
                            "description": "cached",
                        }
                    }
                ],
            }
            cache_file.write_text(json.dumps(cache_data))

            # Should read from cache (not fetch)
            with patch.object(registry, "_fetch_from_api", return_value=None):
                entries = registry.fetch_registry()

            assert len(entries) == 1
            assert entries[0].name == "test/mcp"


# ---------------------------------------------------------------------------
# Manager.get_status (simplified)
# ---------------------------------------------------------------------------


class TestManagerGetStatus:
    def test_active_servers_listed(self, tmp_path: Path) -> None:
        from core.mcp.manager import MCPServerManager

        mgr = MCPServerManager()
        mgr._servers = {
            "steam": {"command": "npx", "args": ["-y", "steam-mcp"]},
        }
        status = mgr.get_status()
        assert status["active_count"] == 1
        assert status["active"][0]["name"] == "steam"

    def test_empty_status(self) -> None:
        from core.mcp.manager import MCPServerManager

        mgr = MCPServerManager()
        status = mgr.get_status()
        assert status["active_count"] == 0
        assert "available_inactive" not in status
