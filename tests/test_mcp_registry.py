"""Tests for MCP manager load_config and get_status (registry-less)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from core.mcp.catalog import MCP_CATALOG, MCPCatalogEntry, search_catalog

# ---------------------------------------------------------------------------
# MCPCatalogEntry
# ---------------------------------------------------------------------------


class TestMCPCatalogEntry:
    def test_required_fields(self) -> None:
        entry = MCPCatalogEntry(
            name="test",
            description="Test server",
            tags=("test",),
        )
        assert entry.name == "test"
        assert entry.install_hint == ""
        assert entry.env_keys == ()

    def test_install_hint(self) -> None:
        entry = MCPCatalogEntry(
            name="playwright",
            description="Browser automation",
            tags=("browser",),
            install_hint="npx -y @playwright/mcp",
        )
        assert entry.install_hint == "npx -y @playwright/mcp"

    def test_frozen(self) -> None:
        entry = MCPCatalogEntry(name="x", description="x", tags=())
        with pytest.raises(AttributeError):
            entry.name = "y"  # type: ignore[misc]

    def test_no_package_field(self) -> None:
        """Catalog entries must not have package/command/extra_args."""
        entry = MCPCatalogEntry(name="x", description="x", tags=())
        assert not hasattr(entry, "package")
        assert not hasattr(entry, "extra_args")
        # command is not a field; install_hint encodes it
        assert not hasattr(entry, "command")


# ---------------------------------------------------------------------------
# MCP_CATALOG integrity
# ---------------------------------------------------------------------------


class TestCatalogIntegrity:
    def test_no_fetch_entry(self) -> None:
        """fetch (E404) must be removed from catalog."""
        assert "fetch" not in MCP_CATALOG

    def test_no_google_trends_entry(self) -> None:
        """google-trends (E404) must be removed from catalog."""
        assert "google-trends" not in MCP_CATALOG

    def test_playwriter_in_catalog(self) -> None:
        """playwriter should be in catalog (from mcp_servers.json)."""
        assert "playwriter" in MCP_CATALOG

    def test_all_install_hints_parseable(self) -> None:
        """All non-empty install_hints must be parseable to command + args."""
        for name, entry in MCP_CATALOG.items():
            if not entry.install_hint:
                continue
            parts = entry.install_hint.split()
            assert len(parts) >= 2, f"{name}: install_hint too short: {entry.install_hint!r}"
            assert parts[0] in ("npx", "uvx"), f"{name}: unexpected command: {parts[0]}"

    def test_env_keys_are_tuples(self) -> None:
        for name, entry in MCP_CATALOG.items():
            assert isinstance(entry.env_keys, tuple), f"{name}: env_keys must be tuple"

    def test_tags_are_tuples(self) -> None:
        for name, entry in MCP_CATALOG.items():
            assert isinstance(entry.tags, tuple), f"{name}: tags must be tuple"


# ---------------------------------------------------------------------------
# search_catalog
# ---------------------------------------------------------------------------


class TestSearchCatalog:
    def test_empty_query_returns_empty(self) -> None:
        assert search_catalog("") == []

    def test_exact_name_match_first(self) -> None:
        results = search_catalog("playwright")
        assert results[0].name == "playwright"

    def test_tag_match(self) -> None:
        results = search_catalog("browser")
        names = [r.name for r in results]
        assert any("playwright" in n or "puppeteer" in n for n in names)

    def test_limit_respected(self) -> None:
        results = search_catalog("search", limit=2)
        assert len(results) <= 2

    def test_install_hint_match(self) -> None:
        # Search for term in install_hint
        results = search_catalog("playwriter")
        names = [r.name for r in results]
        assert "playwriter" in names


# ---------------------------------------------------------------------------
# MCPServerManager.load_config — registry-free
# ---------------------------------------------------------------------------


class TestManagerLoadConfig:
    def test_no_config_returns_zero(self, tmp_path: Path) -> None:
        """Without config.toml or json, no servers loaded (no auto-discovery)."""
        from core.mcp.manager import MCPServerManager

        with patch("core.mcp.manager._PROJECT_ROOT", tmp_path):
            manager = MCPServerManager(config_path=tmp_path / "nonexistent.json")
            count = manager.load_config()
        assert count == 0

    def test_loads_from_json_file(self, tmp_path: Path) -> None:
        from core.mcp.manager import MCPServerManager

        config_path = tmp_path / "mcp_servers.json"
        config_path.write_text(
            json.dumps({"my-server": {"command": "npx", "args": ["-y", "pkg"]}}),
            encoding="utf-8",
        )
        with patch("core.mcp.manager._PROJECT_ROOT", tmp_path):
            manager = MCPServerManager(config_path=config_path)
            count = manager.load_config()
        assert count == 1
        assert "my-server" in manager._servers

    def test_loads_from_toml(self, tmp_path: Path) -> None:
        from core.mcp.manager import MCPServerManager

        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        toml_content = (
            "[mcp.servers.playwright]\n"
            'command = "npx"\n'
            'args = ["-y", "@playwright/mcp"]\n'
        )
        (geode_dir / "config.toml").write_text(toml_content, encoding="utf-8")

        with patch("core.mcp.manager._PROJECT_ROOT", tmp_path):
            manager = MCPServerManager(config_path=tmp_path / "nonexistent.json")
            count = manager.load_config()
        assert count == 1
        assert "playwright" in manager._servers
        assert manager._servers["playwright"]["command"] == "npx"

    def test_toml_overrides_json(self, tmp_path: Path) -> None:
        """config.toml entry takes priority over mcp_servers.json."""
        from core.mcp.manager import MCPServerManager

        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        (geode_dir / "config.toml").write_text(
            '[mcp.servers.steam]\ncommand = "npx"\nargs = ["-y", "steam-toml"]\n',
            encoding="utf-8",
        )
        config_path = tmp_path / "mcp_servers.json"
        config_path.write_text(
            json.dumps({"steam": {"command": "npx", "args": ["-y", "steam-json"]}}),
            encoding="utf-8",
        )

        with patch("core.mcp.manager._PROJECT_ROOT", tmp_path):
            manager = MCPServerManager(config_path=config_path)
            manager.load_config()
        assert manager._servers["steam"]["args"] == ["-y", "steam-toml"]

    def test_json_adds_extra_servers_not_in_toml(self, tmp_path: Path) -> None:
        from core.mcp.manager import MCPServerManager

        geode_dir = tmp_path / ".geode"
        geode_dir.mkdir()
        (geode_dir / "config.toml").write_text(
            '[mcp.servers.playwright]\ncommand = "npx"\nargs = ["-y", "@playwright/mcp"]\n',
            encoding="utf-8",
        )
        config_path = tmp_path / "mcp_servers.json"
        config_path.write_text(
            json.dumps({"custom-server": {"command": "python", "args": ["-m", "my_mcp"]}}),
            encoding="utf-8",
        )

        with patch("core.mcp.manager._PROJECT_ROOT", tmp_path):
            manager = MCPServerManager(config_path=config_path)
            count = manager.load_config()
        assert count == 2
        assert "playwright" in manager._servers
        assert "custom-server" in manager._servers


# ---------------------------------------------------------------------------
# MCPServerManager.get_status
# ---------------------------------------------------------------------------


class TestManagerGetStatus:
    def test_get_status_empty(self, tmp_path: Path) -> None:
        from core.mcp.manager import MCPServerManager

        with patch("core.mcp.manager._PROJECT_ROOT", tmp_path):
            manager = MCPServerManager(config_path=tmp_path / "nonexistent.json")
            manager.load_config()
            status = manager.get_status()
        assert status["active"] == []
        assert status["active_count"] == 0
        assert isinstance(status["available_inactive"], list)
        assert status["catalog_total"] == len(MCP_CATALOG)

    def test_get_status_active_servers(self, tmp_path: Path) -> None:
        from core.mcp.manager import MCPServerManager

        config_path = tmp_path / "mcp_servers.json"
        config_path.write_text(
            json.dumps({"playwright": {"command": "npx", "args": ["-y", "@playwright/mcp"]}}),
            encoding="utf-8",
        )
        with patch("core.mcp.manager._PROJECT_ROOT", tmp_path):
            manager = MCPServerManager(config_path=config_path)
            manager.load_config()
            status = manager.get_status()
        assert status["active_count"] == 1
        assert status["active"][0]["name"] == "playwright"
        assert status["active"][0]["description"]  # description from catalog

    def test_get_status_available_inactive(self, tmp_path: Path) -> None:
        """Catalog entries with missing env vars appear in available_inactive."""
        from core.mcp.manager import MCPServerManager

        nonexistent = tmp_path / "nonexistent"
        with (
            patch("core.mcp.manager._PROJECT_ROOT", tmp_path),
            patch("core.mcp.manager._GLOBAL_DOTENV_PATH", nonexistent),
            patch("core.mcp.manager._DOTENV_PATH", nonexistent),
            patch.dict(os.environ, {}, clear=False),
        ):
            os.environ.pop("BRAVE_API_KEY", None)
            manager = MCPServerManager(config_path=tmp_path / "nonexistent.json")
            manager.load_config()
            status = manager.get_status()
        inactive_names = [s["name"] for s in status["available_inactive"]]
        assert "brave-search" in inactive_names
