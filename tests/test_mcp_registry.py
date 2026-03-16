"""Tests for MCP server registry — code-level server registration."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from core.infrastructure.adapters.mcp.catalog import MCP_CATALOG
from core.infrastructure.adapters.mcp.registry import (
    AUTO_DISCOVER_SERVERS,
    DEFAULT_SERVERS,
    MCPRegistry,
    MCPServerConfig,
    _catalog_entry_to_config,
    _has_env_keys,
)

# ---------------------------------------------------------------------------
# MCPServerConfig
# ---------------------------------------------------------------------------


class TestMCPServerConfig:
    def test_to_dict_basic(self) -> None:
        config = MCPServerConfig(command="npx", args=["-y", "some-pkg"])
        d = config.to_dict()
        assert d == {"command": "npx", "args": ["-y", "some-pkg"]}

    def test_to_dict_with_env(self) -> None:
        config = MCPServerConfig(
            command="npx",
            args=["-y", "pkg"],
            env={"API_KEY": "${API_KEY}"},
        )
        d = config.to_dict()
        assert d["env"] == {"API_KEY": "${API_KEY}"}

    def test_to_dict_no_env_omits_key(self) -> None:
        config = MCPServerConfig(command="npx", args=[])
        d = config.to_dict()
        assert "env" not in d

    def test_frozen(self) -> None:
        config = MCPServerConfig(command="npx", args=[])
        with pytest.raises(AttributeError):
            config.command = "uvx"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# _catalog_entry_to_config
# ---------------------------------------------------------------------------


class TestCatalogEntryToConfig:
    def test_converts_steam_entry(self) -> None:
        entry = MCP_CATALOG["steam"]
        config = _catalog_entry_to_config(entry)
        assert config.command == "npx"
        assert "-y" in config.args
        assert entry.package in config.args
        assert config.env == {}

    def test_converts_brave_entry_with_env(self) -> None:
        entry = MCP_CATALOG["brave-search"]
        config = _catalog_entry_to_config(entry)
        assert config.env == {"BRAVE_API_KEY": "${BRAVE_API_KEY}"}

    def test_converts_entry_with_extra_args(self) -> None:
        from core.infrastructure.adapters.mcp.catalog import MCPCatalogEntry

        entry = MCPCatalogEntry(
            name="test",
            package="test-pkg",
            description="Test",
            tags=("test",),
            extra_args=("--flag", "value"),
        )
        config = _catalog_entry_to_config(entry)
        assert config.args == ["-y", "test-pkg", "--flag", "value"]


# ---------------------------------------------------------------------------
# _has_env_keys
# ---------------------------------------------------------------------------


class TestHasEnvKeys:
    def test_empty_keys_returns_true(self) -> None:
        assert _has_env_keys((), {}) is True

    def test_key_in_environ(self) -> None:
        with patch.dict(os.environ, {"MY_KEY": "val"}):
            assert _has_env_keys(("MY_KEY",), {}) is True

    def test_key_in_dotenv(self) -> None:
        assert _has_env_keys(("MY_KEY",), {"MY_KEY": "val"}) is True

    def test_key_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            # Ensure MY_MISSING_KEY is not in environ
            os.environ.pop("MY_MISSING_KEY", None)
            assert _has_env_keys(("MY_MISSING_KEY",), {}) is False

    def test_partial_keys_returns_false(self) -> None:
        with patch.dict(os.environ, {"KEY_A": "val"}):
            os.environ.pop("KEY_B", None)
            assert _has_env_keys(("KEY_A", "KEY_B"), {}) is False


# ---------------------------------------------------------------------------
# MCPRegistry
# ---------------------------------------------------------------------------


class TestMCPRegistry:
    def test_discover_returns_default_servers(self) -> None:
        registry = MCPRegistry(dotenv_path="/nonexistent/.env")
        result = registry.discover()
        for name in DEFAULT_SERVERS:
            if name in MCP_CATALOG:
                assert name in result, f"Default server '{name}' not in discovery result"

    def test_discover_includes_auto_servers_when_env_present(self) -> None:
        with patch.dict(os.environ, {"BRAVE_API_KEY": "test-key"}):
            registry = MCPRegistry(dotenv_path="/nonexistent/.env")
            result = registry.discover()
            assert "brave-search" in result

    def test_discover_excludes_auto_servers_when_env_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAVE_API_KEY", None)
            registry = MCPRegistry(dotenv_path="/nonexistent/.env")
            result = registry.discover()
            # brave-search requires BRAVE_API_KEY
            assert "brave-search" not in result

    def test_discover_server_config_structure(self) -> None:
        registry = MCPRegistry(dotenv_path="/nonexistent/.env")
        result = registry.discover()
        for name, config in result.items():
            assert "command" in config, f"Server '{name}' missing 'command'"
            assert "args" in config, f"Server '{name}' missing 'args'"

    def test_list_available(self) -> None:
        registry = MCPRegistry(dotenv_path="/nonexistent/.env")
        available = registry.list_available()
        assert isinstance(available, list)
        assert available == sorted(available)  # sorted

    def test_list_missing_env(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BRAVE_API_KEY", None)
            registry = MCPRegistry(dotenv_path="/nonexistent/.env")
            missing = registry.list_missing_env()
            assert "brave-search" in missing
            assert "BRAVE_API_KEY" in missing["brave-search"]

    def test_defaults_all_in_catalog(self) -> None:
        """All DEFAULT_SERVERS must exist in MCP_CATALOG."""
        for name in DEFAULT_SERVERS:
            assert name in MCP_CATALOG, f"Default '{name}' not in MCP_CATALOG"

    def test_auto_discover_all_in_catalog(self) -> None:
        """All AUTO_DISCOVER_SERVERS must exist in MCP_CATALOG."""
        for name in AUTO_DISCOVER_SERVERS:
            assert name in MCP_CATALOG, f"Auto-discover '{name}' not in MCP_CATALOG"

    def test_custom_defaults(self) -> None:
        registry = MCPRegistry(
            dotenv_path="/nonexistent/.env",
            defaults=("steam",),
            auto_discover=(),
        )
        result = registry.discover()
        assert "steam" in result
        assert len(result) == 1

    def test_custom_auto_discover_empty(self) -> None:
        registry = MCPRegistry(
            dotenv_path="/nonexistent/.env",
            defaults=(),
            auto_discover=(),
        )
        result = registry.discover()
        assert result == {}


# ---------------------------------------------------------------------------
# MCPServerManager integration with registry
# ---------------------------------------------------------------------------


class TestManagerRegistryIntegration:
    def test_load_config_uses_registry(self, tmp_path: Path) -> None:
        """Manager.load_config() should include registry-discovered servers."""
        from core.infrastructure.adapters.mcp.manager import MCPServerManager

        config_path = tmp_path / "mcp_servers.json"
        # No config file exists
        manager = MCPServerManager(config_path=config_path)
        count = manager.load_config()
        # Should have at least the default servers
        assert count >= len(DEFAULT_SERVERS)

    def test_file_overrides_registry(self, tmp_path: Path) -> None:
        """File config should override registry defaults."""
        from core.infrastructure.adapters.mcp.manager import MCPServerManager

        config_path = tmp_path / "mcp_servers.json"
        # Write a file override for steam with custom args
        override: dict[str, Any] = {
            "steam": {
                "command": "node",
                "args": ["custom-steam-server.js"],
            }
        }
        config_path.write_text(json.dumps(override), encoding="utf-8")

        manager = MCPServerManager(config_path=config_path)
        manager.load_config()

        # Steam should use the file override, not the registry default
        assert manager._servers["steam"]["command"] == "node"
        assert manager._servers["steam"]["args"] == ["custom-steam-server.js"]

    def test_file_adds_extra_servers(self, tmp_path: Path) -> None:
        """File config can add servers not in the registry."""
        from core.infrastructure.adapters.mcp.manager import MCPServerManager

        config_path = tmp_path / "mcp_servers.json"
        override: dict[str, Any] = {
            "my-custom-server": {
                "command": "python",
                "args": ["-m", "my_mcp_server"],
            }
        }
        config_path.write_text(json.dumps(override), encoding="utf-8")

        manager = MCPServerManager(config_path=config_path)
        manager.load_config()

        assert "my-custom-server" in manager._servers

    def test_load_config_no_file_still_works(self, tmp_path: Path) -> None:
        """Without a config file, registry defaults should still load."""
        from core.infrastructure.adapters.mcp.manager import MCPServerManager

        config_path = tmp_path / "nonexistent.json"
        manager = MCPServerManager(config_path=config_path)
        count = manager.load_config()
        # At minimum, default servers
        assert count >= 1
