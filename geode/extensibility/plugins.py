"""Plugin Lifecycle Management — install, activate, deactivate, uninstall.

Layer 5 extensibility component for managing GEODE plugins with
a clean lifecycle state machine.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State Machine
# ---------------------------------------------------------------------------


class PluginState(str, Enum):
    """Lifecycle states for a plugin."""

    INSTALLED = "installed"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"


# Valid state transitions
_VALID_TRANSITIONS: dict[PluginState, set[PluginState]] = {
    PluginState.INSTALLED: {PluginState.ACTIVE, PluginState.INACTIVE},
    PluginState.ACTIVE: {PluginState.INACTIVE, PluginState.ERROR},
    PluginState.INACTIVE: {PluginState.ACTIVE},
    PluginState.ERROR: {PluginState.INACTIVE, PluginState.ACTIVE},
}


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class PluginMetadata(BaseModel):
    """Metadata describing a plugin."""

    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    dependencies: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Plugin ABC
# ---------------------------------------------------------------------------


class Plugin(ABC):
    """Abstract base class for GEODE plugins.

    Subclasses must implement the four lifecycle methods and provide metadata.
    State transitions are enforced automatically.
    """

    def __init__(self, metadata: PluginMetadata) -> None:
        self._metadata = metadata
        self._state = PluginState.INSTALLED

    @property
    def metadata(self) -> PluginMetadata:
        """Plugin metadata."""
        return self._metadata

    @property
    def name(self) -> str:
        """Convenience accessor for metadata.name."""
        return self._metadata.name

    @property
    def state(self) -> PluginState:
        """Current lifecycle state."""
        return self._state

    def _transition(self, target: PluginState) -> None:
        """Transition to a new state. Raises ValueError on invalid transitions."""
        allowed = _VALID_TRANSITIONS.get(self._state, set())
        if target not in allowed:
            raise ValueError(
                f"Invalid state transition: {self._state.value} -> {target.value}. "
                f"Allowed targets: {[s.value for s in allowed]}"
            )
        self._state = target

    @abstractmethod
    def install(self) -> None:
        """One-time setup. Called when plugin is first loaded."""
        ...

    @abstractmethod
    def activate(self) -> None:
        """Activate the plugin. Called when transitioning to ACTIVE."""
        ...

    @abstractmethod
    def deactivate(self) -> None:
        """Deactivate the plugin. Called when transitioning to INACTIVE."""
        ...

    @abstractmethod
    def uninstall(self) -> None:
        """Clean up resources. Called when plugin is removed."""
        ...

    def get_info(self) -> dict[str, Any]:
        """Return a summary dict of this plugin's status."""
        return {
            "name": self._metadata.name,
            "version": self._metadata.version,
            "state": self._state.value,
            "description": self._metadata.description,
            "author": self._metadata.author,
            "dependencies": self._metadata.dependencies,
        }


# ---------------------------------------------------------------------------
# Concrete Plugin Example
# ---------------------------------------------------------------------------


class LoggingPlugin(Plugin):
    """Example plugin that logs pipeline events."""

    def __init__(self) -> None:
        super().__init__(PluginMetadata(
            name="logging-plugin",
            version="1.0.0",
            description="Logs pipeline lifecycle events for observability.",
        ))

    def install(self) -> None:
        log.info("LoggingPlugin installed")

    def activate(self) -> None:
        log.info("LoggingPlugin activated")

    def deactivate(self) -> None:
        log.info("LoggingPlugin deactivated")

    def uninstall(self) -> None:
        log.info("LoggingPlugin uninstalled")


# ---------------------------------------------------------------------------
# Plugin Manager
# ---------------------------------------------------------------------------


class PluginManager:
    """Manages plugin lifecycle: load, activate, deactivate, unload."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def load(self, plugin: Plugin) -> None:
        """Load and install a plugin.

        Raises:
            ValueError: If a plugin with the same name is already loaded.
        """
        if plugin.name in self._plugins:
            raise ValueError(f"Plugin '{plugin.name}' already loaded")

        # Check dependencies
        for dep in plugin.metadata.dependencies:
            if dep not in self._plugins:
                raise ValueError(
                    f"Plugin '{plugin.name}' requires '{dep}' which is not loaded"
                )

        plugin.install()
        self._plugins[plugin.name] = plugin

    def activate(self, name: str) -> None:
        """Activate a loaded plugin.

        Raises:
            KeyError: If plugin not found.
            ValueError: If state transition is invalid.
        """
        plugin = self._get_plugin(name)
        plugin._transition(PluginState.ACTIVE)
        try:
            plugin.activate()
        except Exception as exc:
            plugin._state = PluginState.ERROR
            log.exception("Plugin activation failed for '%s': %s", name, exc)
            raise

    def deactivate(self, name: str) -> None:
        """Deactivate an active plugin.

        Raises:
            KeyError: If plugin not found.
            ValueError: If state transition is invalid.
        """
        plugin = self._get_plugin(name)
        plugin._transition(PluginState.INACTIVE)
        plugin.deactivate()

    def unload(self, name: str) -> None:
        """Uninstall and remove a plugin.

        Raises:
            KeyError: If plugin not found.
            ValueError: If other loaded plugins depend on this one.
        """
        plugin = self._get_plugin(name)

        # Check reverse dependencies
        dependents = [
            p.name
            for p in self._plugins.values()
            if name in p.metadata.dependencies and p.name != name
        ]
        if dependents:
            raise ValueError(
                f"Cannot unload '{name}': required by {dependents}"
            )

        # Deactivate if active
        if plugin.state == PluginState.ACTIVE:
            plugin._transition(PluginState.INACTIVE)
            plugin.deactivate()

        plugin.uninstall()
        del self._plugins[name]

    def get(self, name: str) -> Plugin | None:
        """Get a plugin by name. Returns None if not found."""
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all loaded plugins with their info."""
        return [plugin.get_info() for plugin in self._plugins.values()]

    def _get_plugin(self, name: str) -> Plugin:
        """Get a plugin by name. Raises KeyError if not found."""
        plugin = self._plugins.get(name)
        if plugin is None:
            raise KeyError(f"Plugin '{name}' not found")
        return plugin

    def __len__(self) -> int:
        return len(self._plugins)

    def __contains__(self, name: str) -> bool:
        return name in self._plugins
