"""Layered MCP server configuration and environment resolution."""

from __future__ import annotations

import json
import logging
import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from core.paths import GLOBAL_CONFIG_TOML, GLOBAL_ENV_FILE, get_project_root

log = logging.getLogger(__name__)


class MCPConfigCatalog:
    """Own configured MCP servers and their persisted configuration."""

    def __init__(
        self,
        config_path: Path,
        *,
        global_env_path: Callable[[], Path] | None = None,
        project_root: Callable[[], Path] | None = None,
    ) -> None:
        self.config_path = config_path
        self.servers: dict[str, dict[str, Any]] = {}
        self.origins: dict[str, str] = {}
        self.collisions: list[dict[str, str]] = []
        self.dotenv_cache: dict[str, str | None] = {}
        self._global_env_path = global_env_path or (lambda: GLOBAL_ENV_FILE)
        self._project_root = project_root or get_project_root

    def load(self) -> int:
        """Load global/project TOML plus the legacy JSON fallback."""
        self.servers = {}
        self.origins = {}
        self.collisions = []
        for config_toml in (
            GLOBAL_CONFIG_TOML,
            self._project_root() / ".geode" / "config.toml",
        ):
            if not config_toml.exists():
                continue
            try:
                with config_toml.open("rb") as file:
                    mcp_section = tomllib.load(file).get("mcp", {}).get("servers", {})
                for name, config in mcp_section.items():
                    entry: dict[str, Any] = dict(config)
                    if previous := self.origins.get(name):
                        self.collisions.append(
                            {
                                "name": name,
                                "replaced": previous,
                                "selected": str(config_toml),
                            }
                        )
                        log.warning(
                            "MCP config collision %s: %s replaced by %s",
                            name,
                            previous,
                            config_toml,
                        )
                    self.servers[name] = entry
                    self.origins[name] = str(config_toml)
                if mcp_section:
                    log.info("MCP %s: %d servers", config_toml, len(mcp_section))
            except Exception as exc:
                log.debug("Failed to load MCP from %s: %s", config_toml, exc)

        if self.config_path.exists():
            try:
                file_servers: dict[str, dict[str, Any]] = json.loads(
                    self.config_path.read_text(encoding="utf-8")
                )
                added = 0
                for name, config in file_servers.items():
                    if name not in self.servers:
                        self.servers[name] = config
                        self.origins[name] = str(self.config_path)
                        added += 1
                    else:
                        self.collisions.append(
                            {
                                "name": name,
                                "replaced": str(self.config_path),
                                "selected": self.origins[name],
                            }
                        )
                        log.warning(
                            "MCP config collision %s: %s ignored; selected %s",
                            name,
                            self.config_path,
                            self.origins[name],
                        )
                if added:
                    log.info("MCP mcp_servers.json: %d additional servers", added)
            except (json.JSONDecodeError, OSError) as exc:
                log.debug("Failed to load MCP config file: %s", exc)

        total = len(self.servers)
        if total:
            log.info("MCP total: %d servers configured", total)
        else:
            log.debug("MCP: no servers configured")
        return total

    def status(self) -> dict[str, Any]:
        active = [{"name": name, "description": ""} for name in sorted(self.servers)]
        return {
            "active": active,
            "active_count": len(active),
            "collisions": list(self.collisions),
        }

    def resolve_env(self, env: dict[str, str]) -> dict[str, str]:
        """Resolve ``${VAR}`` from the process, project env, then global env."""
        self._load_dotenv_cache()
        resolved: dict[str, str] = {}
        for key, value in env.items():
            if value.startswith("${") and value.endswith("}"):
                name = value[2:-1]
                resolved[key] = os.environ.get(name, self.dotenv_cache.get(name) or "")
            else:
                resolved[key] = value
        return resolved

    def add(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> bool:
        entry: dict[str, Any] = {"command": command}
        if args:
            entry["args"] = args
        if env:
            entry["env"] = env
        self.servers[name] = entry
        self.origins[name] = str(self.config_path)
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            self.config_path.write_text(
                json.dumps(self.servers, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            log.info("Added MCP server '%s' and saved config", name)
            return True
        except OSError as exc:
            log.error("Failed to save MCP config after adding '%s': %s", name, exc)
            return False

    def _load_dotenv_cache(self) -> None:
        if self.dotenv_cache:
            return
        for path in (self._project_root() / ".env", self._global_env_path()):
            if not path.exists():
                continue
            for key, value in dotenv_values(str(path)).items():
                if value:
                    self.dotenv_cache[key] = value
