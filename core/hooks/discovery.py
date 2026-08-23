"""Hook Plugin Discovery — directory-based plugin loading for RuntimeEventBus.

Scans ``hook.yaml`` manifests without importing their handler modules. Legacy
class-only ``hook.py`` directories are rejected because their metadata cannot
be inspected without executing third-party code.

External developers can add hooks by dropping a plugin directory into a
configured hooks path, without modifying core GEODE code.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
import types
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

import yaml

from core.extensions import (
    ExtensionDecision,
    ExtensionDescriptor,
    ExtensionExecution,
    ExtensionPolicy,
    ExtensionState,
    ExtensionSurface,
    decide_extension,
    extension_context,
    load_default_extension_policy,
)
from core.hooks.system import RuntimeEvent, RuntimeEventBus, resolve_event_value

log = logging.getLogger(__name__)


def _resolve_event(name: str) -> RuntimeEvent:
    """Resolve a string event name to a RuntimeEvent enum member.

    Accepts the enum member name (e.g. ``SESSION_ENDED``), the enum value
    (e.g. ``session_ended``), and legacy pre-rename values
    (``session_end`` — see ``core.hooks.system.LEGACY_EVENT_VALUES``),
    case-insensitively.

    Raises ``ValueError`` for unrecognised names.
    """
    upper = name.strip().upper()

    # Try direct member name lookup first
    try:
        return RuntimeEvent[upper]
    except KeyError:
        pass

    # Fall back to matching by enum .value (with legacy-value aliasing)
    try:
        return resolve_event_value(name.strip().lower())
    except ValueError:
        pass

    valid = ", ".join(m.value for m in RuntimeEvent)
    msg = f"Invalid hook event '{name}'. Valid events: {valid}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class HookPluginMetadata:
    """Metadata describing a discovered hook plugin."""

    name: str
    events: list[RuntimeEvent]
    priority: int = 100
    description: str = ""
    requires: list[str] = field(default_factory=list)
    enabled: bool = True
    source_dir: Path = field(default_factory=lambda: Path("."))
    handler_path: Path | None = None
    capabilities: tuple[str, ...] = ()
    resource_keys: tuple[str, ...] = ()


@runtime_checkable
class HookPlugin(Protocol):
    """Protocol that class-based hook plugins must implement."""

    @property
    def metadata(self) -> HookPluginMetadata: ...

    def handle(self, event: RuntimeEvent, data: dict[str, Any]) -> Any: ...


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_module_from_path(module_name: str, file_path: Path) -> types.ModuleType:
    """Load a module without leaking its synthetic name into ``sys.modules``."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        msg = f"Cannot create module spec from {file_path}"
        raise ImportError(msg)
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(module_name)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = previous
    return module


# ---------------------------------------------------------------------------
# YAML-based discovery
# ---------------------------------------------------------------------------


@dataclass
class _YAMLPlugin:
    """A loaded YAML-driven plugin — wraps a plain handler function."""

    _metadata: HookPluginMetadata
    _handler_fn: Any  # Callable[[RuntimeEvent, dict], None]
    _cleanup_fn: Any = None

    @property
    def metadata(self) -> HookPluginMetadata:
        return self._metadata

    def handle(self, event: RuntimeEvent, data: dict[str, Any]) -> Any:
        return self._handler_fn(event, data)

    def close(self) -> None:
        if callable(self._cleanup_fn):
            self._cleanup_fn()


def _read_yaml_metadata(plugin_dir: Path) -> HookPluginMetadata | None:
    """Read one non-executing hook manifest."""
    yaml_path = plugin_dir / "hook.yaml"
    with yaml_path.open("r") as fh:
        raw: Any = yaml.safe_load(fh)

    if not isinstance(raw, dict):
        log.warning("hook.yaml in %s is not a valid mapping", plugin_dir)
        return None
    if unknown := sorted(
        set(raw)
        - {
            "name",
            "events",
            "priority",
            "description",
            "requires",
            "enabled",
            "handler",
            "capabilities",
            "resource_keys",
        }
    ):
        raise ValueError(f"Unknown hook manifest fields: {unknown}")

    # Validate required keys
    name: str = raw.get("name", plugin_dir.name)
    enabled = raw.get("enabled", True)
    if not isinstance(name, str) or not isinstance(enabled, bool):
        raise ValueError("hook name/enabled must be a string and boolean")
    raw_events: Any = raw.get("events", [])
    if not isinstance(raw_events, list) or any(not isinstance(event, str) for event in raw_events):
        raise ValueError(f"Plugin {name!r} events must be a list of strings")
    if enabled and not raw_events:
        log.warning("Plugin '%s' declares no events", name)
        return None

    events = [_resolve_event(e) for e in raw_events]
    priority: int = int(raw.get("priority", 100))
    description: str = raw.get("description", "")
    if not isinstance(description, str):
        raise TypeError(f"Plugin {name!r} description must be a string")
    requires_cfg: dict[str, Any] | list[str] = raw.get("requires", {})
    if isinstance(requires_cfg, dict):
        if set(requires_cfg) - {"packages"}:
            raise ValueError(f"Plugin {name!r} requires supports only packages")
        requires = requires_cfg.get("packages", [])
    elif isinstance(requires_cfg, list):
        requires = list(requires_cfg)
    else:
        raise TypeError(f"Plugin {name!r} requires must be a list or object")
    if any(not isinstance(value, str) for value in requires):
        raise TypeError(f"Plugin {name!r} requires packages must be strings")

    handler_rel: str | None = raw.get("handler")
    if handler_rel is not None and not isinstance(handler_rel, str):
        raise TypeError(f"Plugin {name!r} handler must be a string")
    if enabled and handler_rel is None:
        log.warning("Plugin '%s' has no handler path in hook.yaml", name)
        return None
    handler_path = (plugin_dir / handler_rel).resolve() if handler_rel is not None else None
    if handler_path is not None:
        if not handler_path.is_relative_to(plugin_dir.resolve()):
            raise ValueError(f"Handler path {handler_path!s} escapes plugin {name!r}")
        if enabled and not handler_path.exists():
            raise ValueError(f"Handler file {handler_path!s} not found for plugin {name!r}")

    capabilities_raw = raw.get("capabilities", [])
    resource_keys_raw = raw.get("resource_keys", [])
    if not isinstance(capabilities_raw, list) or any(
        not isinstance(value, str) for value in capabilities_raw
    ):
        raise ValueError(f"Plugin {name!r} capabilities must be a list of strings")
    if not isinstance(resource_keys_raw, list) or any(
        not isinstance(value, str) for value in resource_keys_raw
    ):
        raise ValueError(f"Plugin {name!r} resource_keys must be a list of strings")
    return HookPluginMetadata(
        name=name,
        events=events,
        priority=priority,
        description=description,
        requires=requires,
        enabled=enabled,
        source_dir=plugin_dir,
        handler_path=handler_path,
        capabilities=tuple(capabilities_raw),
        resource_keys=tuple(resource_keys_raw),
    )


def _hook_descriptor(meta: HookPluginMetadata) -> ExtensionDescriptor:
    return ExtensionDescriptor(
        name=meta.name,
        surface=ExtensionSurface.HOOK,
        origin=str(meta.source_dir / "hook.yaml"),
        execution=ExtensionExecution.TRUSTED,
        enabled=meta.enabled,
        capabilities=meta.capabilities,
        resource_keys=meta.resource_keys,
    )


def _load_yaml_plugin(
    meta: HookPluginMetadata,
    decision: ExtensionDecision,
    ports: Mapping[str, Any],
) -> _YAMLPlugin:
    """Import one handler only after its manifest has been authorized."""
    assert meta.handler_path is not None
    mod_name = f"core_hook_plugin_{meta.name.replace('-', '_')}_handler"
    handler_module = _load_module_from_path(mod_name, meta.handler_path)
    context = extension_context(
        decision,
        {name: value for name, value in ports.items() if name in meta.capabilities},
    )
    factory = getattr(handler_module, "build_extension", None)
    handler_fn = factory(context) if callable(factory) else getattr(handler_module, "handle", None)
    if not callable(handler_fn):
        raise TypeError(
            f"Handler module {meta.handler_path!s} has no handle() or build_extension() function"
        )
    return _YAMLPlugin(
        _metadata=meta,
        _handler_fn=handler_fn,
        _cleanup_fn=getattr(handler_fn, "close", None) or getattr(handler_module, "close", None),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def discover_hooks(dirs: list[Path]) -> list[HookPluginMetadata]:
    """Scan directories for hook plugin metadata without loading handlers.

    Each entry in *dirs* should be a parent directory containing one or more
    plugin sub-directories. A plugin sub-directory is loadable only when it
    contains a non-executing ``hook.yaml`` manifest; class-only ``hook.py``
    directories are reported as rejected by :class:`HookPluginLoader`.

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
            if yaml_path.exists():
                try:
                    if meta := _read_yaml_metadata(child):
                        results.append(meta)
                except ValueError:
                    raise
                except Exception:
                    log.warning("Failed to read hook.yaml in %s", child, exc_info=True)
            elif (child / "hook.py").exists():
                log.warning("Ignoring class-only hook %s: hook.yaml manifest required", child)
    return results


class HookPluginLoader:
    """Load and manage hook plugins from the filesystem."""

    def __init__(
        self,
        *,
        policy: ExtensionPolicy | None = None,
        ports: Mapping[str, Any] | None = None,
    ) -> None:
        self._loaded: list[Any] = []  # list of HookPlugin-compatible instances
        self._policy = policy or load_default_extension_policy()
        self._ports = MappingProxyType(dict(ports or {}))
        self._decisions: list[ExtensionDecision] = []

    @property
    def loaded_plugins(self) -> list[Any]:
        """Return the list of loaded plugin instances."""
        return list(self._loaded)

    @property
    def decisions(self) -> tuple[ExtensionDecision, ...]:
        return tuple(self._decisions)

    def load_from_dirs(self, dirs: list[Path]) -> list[Any]:
        """Discover and load all enabled hook plugins from *dirs*.

        Each entry in *dirs* is a parent directory containing plugin
        sub-directories.  Returns a list of loaded plugin instances.
        """
        plugins: list[Any] = []
        metadata = discover_hooks(dirs)
        origins: dict[str, str] = {}
        for meta in metadata:
            origin = str(meta.source_dir / "hook.yaml")
            if previous := origins.get(meta.name):
                raise ValueError(
                    f"hook {meta.name!r} discovered from multiple origins: {previous}, {origin}"
                )
            origins[meta.name] = origin

        class_only = [
            child
            for parent in dirs
            if parent.is_dir()
            for child in sorted(parent.iterdir())
            if child.is_dir()
            and (child / "hook.py").is_file()
            and not (child / "hook.yaml").is_file()
        ]
        rejected_class_hooks = [
            ExtensionDecision(
                ExtensionDescriptor(
                    name=child.name,
                    surface=ExtensionSurface.HOOK,
                    origin=str(child / "hook.py"),
                    execution=ExtensionExecution.TRUSTED,
                ),
                ExtensionState.REJECTED,
                False,
                False,
                reason="hook.yaml manifest required",
            )
            for child in class_only
        ]
        for decision in rejected_class_hooks:
            log.warning(
                "Hook extension %s: %s (%s)",
                decision.descriptor.extension_id,
                decision.state,
                decision.reason,
            )
        decisions = [decide_extension(_hook_descriptor(meta), self._policy) for meta in metadata]
        self._decisions = [*rejected_class_hooks, *decisions]
        for index, (meta, decision) in enumerate(zip(metadata, decisions, strict=True)):
            if not decision.may_load_in_process:
                log.warning(
                    "Hook extension %s: %s (%s)",
                    decision.descriptor.extension_id,
                    decision.state,
                    decision.reason,
                )
                continue
            try:
                plugin = _load_yaml_plugin(meta, decision, self._ports)
            except Exception:
                self._decisions[len(rejected_class_hooks) + index] = decision.degraded(
                    "handler load failed"
                )
                log.warning("Failed to load trusted hook from %s", meta.source_dir, exc_info=True)
                continue
            plugins.append(plugin)
            log.info("Loaded trusted hook plugin '%s'", plugin.metadata.name)

        self._loaded = plugins
        return list(plugins)

    def register_all(self, hooks: RuntimeEventBus) -> None:
        """Register all loaded plugins into the given runtime event bus."""
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

    def unregister_all(self, hooks: RuntimeEventBus) -> None:
        """Remove all loaded plugins from the given runtime event bus."""
        for plugin in reversed(self._loaded):
            meta: HookPluginMetadata = plugin.metadata
            for event in meta.events:
                hooks.unregister(event, meta.name)
            log.info("Unregistered plugin '%s'", meta.name)
            close = getattr(plugin, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    log.warning("Hook plugin '%s' cleanup failed", meta.name, exc_info=True)
        self._loaded.clear()
