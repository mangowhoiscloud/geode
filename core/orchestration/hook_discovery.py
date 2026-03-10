"""Hook Plugin Discovery — directory-based plugin loading for HookSystem.

Scans directories for hook plugins in two formats:
  1. Python module: directory with ``hook.py`` containing a class implementing HookPlugin
  2. YAML config: directory with ``hook.yaml`` containing metadata + handler module path

External developers can add hooks by dropping a plugin directory into a
configured hooks path, without modifying core GEODE code.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from core.orchestration.hooks import HookEvent, HookSystem

log = logging.getLogger(__name__)


def _resolve_event(name: str) -> HookEvent:
    """Resolve a string event name to a HookEvent enum member.

    Accepts both the enum member name (e.g. ``NODE_EXIT``) and the
    enum value (e.g. ``node_exit``), case-insensitively.

    Raises ``ValueError`` for unrecognised names.
    """
    upper = name.strip().upper()

    # Try direct member name lookup first
    try:
        return HookEvent[upper]
    except KeyError:
        pass

    # Fall back to matching by enum .value
    for member in HookEvent:
        if member.value == name.strip().lower():
            return member

    valid = ", ".join(m.value for m in HookEvent)
    msg = f"Invalid hook event '{name}'. Valid events: {valid}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class HookPluginMetadata:
    """Metadata describing a discovered hook plugin."""

    name: str
    events: list[HookEvent]
    priority: int = 100
    description: str = ""
    requires: list[str] = field(default_factory=list)
    enabled: bool = True
    source_dir: Path = field(default_factory=lambda: Path("."))


@runtime_checkable
class HookPlugin(Protocol):
    """Protocol that class-based hook plugins must implement."""

    @property
    def metadata(self) -> HookPluginMetadata: ...

    def handle(self, event: HookEvent, data: dict[str, Any]) -> None: ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_module_from_path(module_name: str, file_path: Path) -> types.ModuleType:
    """Dynamically load a Python module from an arbitrary filesystem path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        msg = f"Cannot create module spec from {file_path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _find_plugin_class(module: types.ModuleType) -> type[Any] | None:
    """Find the first class in *module* that satisfies the ``HookPlugin`` protocol."""
    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        if (
            isinstance(obj, type)
            and obj is not HookPlugin
            and hasattr(obj, "handle")
            and hasattr(obj, "metadata")
        ):
            return obj
    return None


# ---------------------------------------------------------------------------
# YAML-based discovery
# ---------------------------------------------------------------------------


@dataclass
class _YAMLPlugin:
    """A loaded YAML-driven plugin — wraps a plain handler function."""

    _metadata: HookPluginMetadata
    _handler_fn: Any  # Callable[[HookEvent, dict], None]

    @property
    def metadata(self) -> HookPluginMetadata:
        return self._metadata

    def handle(self, event: HookEvent, data: dict[str, Any]) -> None:
        self._handler_fn(event, data)


def _load_yaml_plugin(plugin_dir: Path) -> _YAMLPlugin | None:
    """Load a plugin described by ``hook.yaml`` inside *plugin_dir*."""
    yaml_path = plugin_dir / "hook.yaml"
    with yaml_path.open("r") as fh:
        raw: Any = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        log.warning("hook.yaml in %s is not a valid mapping", plugin_dir)
        return None

    # Respect the ``enabled`` flag
    if not raw.get("enabled", True):
        log.info("Plugin '%s' is disabled, skipping", raw.get("name", plugin_dir.name))
        return None

    # Validate required keys
    name: str = raw.get("name", plugin_dir.name)
    raw_events: list[str] = raw.get("events", [])
    if not raw_events:
        log.warning("Plugin '%s' declares no events", name)
        return None

    events = [_resolve_event(e) for e in raw_events]
    priority: int = int(raw.get("priority", 100))
    description: str = raw.get("description", "")
    requires_cfg: dict[str, Any] | list[str] = raw.get("requires", {})
    if isinstance(requires_cfg, dict):
        requires: list[str] = requires_cfg.get("packages", [])
    else:
        requires = list(requires_cfg)

    handler_rel: str | None = raw.get("handler")
    if handler_rel is None:
        log.warning("Plugin '%s' has no handler path in hook.yaml", name)
        return None

    handler_path = plugin_dir / handler_rel
    if not handler_path.exists():
        log.warning("Handler file '%s' not found for plugin '%s'", handler_path, name)
        return None

    # Load the handler module
    mod_name = f"core_hook_plugin_{name.replace('-', '_')}_handler"
    handler_module = _load_module_from_path(mod_name, handler_path)
    handler_fn = getattr(handler_module, "handle", None)
    if handler_fn is None:
        log.warning(
            "Handler module '%s' has no handle() function for plugin '%s'",
            handler_path,
            name,
        )
        return None

    meta = HookPluginMetadata(
        name=name,
        events=events,
        priority=priority,
        description=description,
        requires=requires,
        enabled=True,
        source_dir=plugin_dir,
    )

    return _YAMLPlugin(_metadata=meta, _handler_fn=handler_fn)


# ---------------------------------------------------------------------------
# Class-based discovery (hook.py)
# ---------------------------------------------------------------------------


def _load_class_plugin(plugin_dir: Path) -> Any | None:
    """Load a class-based plugin from ``hook.py`` inside *plugin_dir*."""
    hook_py = plugin_dir / "hook.py"
    mod_name = f"core_hook_plugin_{plugin_dir.name.replace('-', '_')}"
    module = _load_module_from_path(mod_name, hook_py)

    cls = _find_plugin_class(module)
    if cls is None:
        log.warning("No HookPlugin class found in %s", hook_py)
        return None

    instance = cls()
    # Verify the instance satisfies the protocol
    if not hasattr(instance, "metadata") or not hasattr(instance, "handle"):
        log.warning("Plugin class in %s does not satisfy HookPlugin protocol", hook_py)
        return None

    return instance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_hooks(dirs: list[Path]) -> list[HookPluginMetadata]:
    """Scan directories for hook plugin metadata without loading handlers.

    Each entry in *dirs* should be a parent directory containing one or more
    plugin sub-directories.  A plugin sub-directory is recognised if it
    contains either ``hook.yaml`` or ``hook.py``.

    Returns metadata for all discovered (and enabled) plugins.
    """
    results: list[HookPluginMetadata] = []
    for parent in dirs:
        if not parent.is_dir():
            log.debug("Skipping non-existent hook directory: %s", parent)
            continue
        for child in sorted(parent.iterdir()):
            if not child.is_dir():
                continue
            yaml_path = child / "hook.yaml"
            hook_py = child / "hook.py"
            if yaml_path.exists():
                try:
                    with yaml_path.open("r") as fh:
                        raw_val: Any = yaml.safe_load(fh)
                    if not isinstance(raw_val, dict):
                        continue
                    raw = raw_val
                    if not raw.get("enabled", True):
                        continue
                    name = raw.get("name", child.name)
                    raw_events = raw.get("events", [])
                    events = [_resolve_event(e) for e in raw_events]
                    priority = int(raw.get("priority", 100))
                    description = raw.get("description", "")
                    requires_cfg = raw.get("requires", {})
                    if isinstance(requires_cfg, dict):
                        requires = requires_cfg.get("packages", [])
                    else:
                        requires = list(requires_cfg)
                    results.append(
                        HookPluginMetadata(
                            name=name,
                            events=events,
                            priority=priority,
                            description=description,
                            requires=requires,
                            enabled=True,
                            source_dir=child,
                        )
                    )
                except ValueError:
                    raise
                except Exception:
                    log.warning("Failed to read hook.yaml in %s", child, exc_info=True)
            elif hook_py.exists():
                try:
                    mod_name = f"core_hook_discover_{child.name.replace('-', '_')}"
                    module = _load_module_from_path(mod_name, hook_py)
                    cls = _find_plugin_class(module)
                    if cls is None:
                        continue
                    instance = cls()
                    meta: HookPluginMetadata = instance.metadata
                    if not meta.enabled:
                        continue
                    # Ensure source_dir is set
                    meta.source_dir = child
                    results.append(meta)
                except Exception:
                    log.warning("Failed to load hook.py in %s", child, exc_info=True)
    return results


class HookPluginLoader:
    """Load and manage hook plugins from the filesystem."""

    def __init__(self) -> None:
        self._loaded: list[Any] = []  # list of HookPlugin-compatible instances

    @property
    def loaded_plugins(self) -> list[Any]:
        """Return the list of loaded plugin instances."""
        return list(self._loaded)

    def load_from_dirs(self, dirs: list[Path]) -> list[Any]:
        """Discover and load all enabled hook plugins from *dirs*.

        Each entry in *dirs* is a parent directory containing plugin
        sub-directories.  Returns a list of loaded plugin instances.
        """
        plugins: list[Any] = []
        for parent in dirs:
            if not parent.is_dir():
                log.debug("Skipping non-existent hook directory: %s", parent)
                continue
            for child in sorted(parent.iterdir()):
                if not child.is_dir():
                    continue
                yaml_path = child / "hook.yaml"
                hook_py = child / "hook.py"
                try:
                    if yaml_path.exists():
                        plugin = _load_yaml_plugin(child)
                        if plugin is not None:
                            plugins.append(plugin)
                            log.info("Loaded YAML hook plugin '%s'", plugin.metadata.name)
                    elif hook_py.exists():
                        plugin = _load_class_plugin(child)
                        if plugin is not None:
                            meta: HookPluginMetadata = plugin.metadata
                            if not meta.enabled:
                                log.info(
                                    "Plugin '%s' is disabled, skipping",
                                    meta.name,
                                )
                                continue
                            plugins.append(plugin)
                            log.info("Loaded class hook plugin '%s'", meta.name)
                except Exception:
                    log.warning("Failed to load plugin from %s", child, exc_info=True)

        self._loaded = plugins
        return list(plugins)

    def register_all(self, hooks: HookSystem) -> None:
        """Register all loaded plugins into the given *HookSystem*."""
        for plugin in self._loaded:
            meta: HookPluginMetadata = plugin.metadata
            for event in meta.events:
                hooks.register(
                    event,
                    plugin.handle,
                    name=meta.name,
                    priority=meta.priority,
                )
            log.info(
                "Registered plugin '%s' for events: %s",
                meta.name,
                [e.value for e in meta.events],
            )

    def unregister_all(self, hooks: HookSystem) -> None:
        """Remove all loaded plugins from the given *HookSystem*."""
        for plugin in self._loaded:
            meta: HookPluginMetadata = plugin.metadata
            for event in meta.events:
                hooks.unregister(event, meta.name)
            log.info("Unregistered plugin '%s'", meta.name)
        self._loaded.clear()
