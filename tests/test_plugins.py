"""Tests for L5 Plugin lifecycle management."""

from __future__ import annotations

import pytest
from core.skills.plugins import (
    Plugin,
    PluginManager,
    PluginMetadata,
    PluginState,
)

# ---------------------------------------------------------------------------
# Test Plugin Implementations
# ---------------------------------------------------------------------------


class DummyPlugin(Plugin):
    """Minimal plugin for testing."""

    def __init__(
        self,
        name: str = "dummy",
        dependencies: list[str] | None = None,
    ) -> None:
        meta = PluginMetadata(
            name=name,
            version="1.0.0",
            description="A dummy plugin",
            author="test",
            dependencies=dependencies or [],
        )
        super().__init__(meta)
        self.install_called = False
        self.activate_called = False
        self.deactivate_called = False
        self.uninstall_called = False

    def install(self) -> None:
        self.install_called = True

    def activate(self) -> None:
        self.activate_called = True

    def deactivate(self) -> None:
        self.deactivate_called = True

    def uninstall(self) -> None:
        self.uninstall_called = True


class FailingPlugin(Plugin):
    """Plugin whose activate() raises an error."""

    def __init__(self) -> None:
        super().__init__(PluginMetadata(name="failing"))

    def install(self) -> None:
        pass

    def activate(self) -> None:
        raise RuntimeError("Activation failed")

    def deactivate(self) -> None:
        pass

    def uninstall(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPluginState:
    def test_enum_values(self):
        assert PluginState.INSTALLED.value == "installed"
        assert PluginState.ACTIVE.value == "active"
        assert PluginState.INACTIVE.value == "inactive"
        assert PluginState.ERROR.value == "error"


class TestPluginMetadata:
    def test_create_minimal(self):
        meta = PluginMetadata(name="test")
        assert meta.name == "test"
        assert meta.version == "0.1.0"
        assert meta.dependencies == []

    def test_create_full(self):
        meta = PluginMetadata(
            name="full",
            version="2.0.0",
            description="A full plugin",
            author="dev",
            dependencies=["base"],
        )
        assert meta.version == "2.0.0"
        assert meta.dependencies == ["base"]


class TestPlugin:
    def test_initial_state_is_installed(self):
        plugin = DummyPlugin()
        assert plugin.state == PluginState.INSTALLED

    def test_transition_installed_to_active(self):
        plugin = DummyPlugin()
        plugin._transition(PluginState.ACTIVE)
        assert plugin.state == PluginState.ACTIVE

    def test_transition_installed_to_inactive(self):
        plugin = DummyPlugin()
        plugin._transition(PluginState.INACTIVE)
        assert plugin.state == PluginState.INACTIVE

    def test_invalid_transition_raises(self):
        plugin = DummyPlugin()
        plugin._transition(PluginState.INACTIVE)
        # INACTIVE -> INSTALLED is not a valid transition
        with pytest.raises(ValueError, match="Invalid state transition"):
            plugin._transition(PluginState.INSTALLED)

    def test_get_info(self):
        plugin = DummyPlugin()
        info = plugin.get_info()
        assert info["name"] == "dummy"
        assert info["version"] == "1.0.0"
        assert info["state"] == "installed"

    def test_name_property(self):
        plugin = DummyPlugin(name="my_plugin")
        assert plugin.name == "my_plugin"


class TestPluginManager:
    def test_load_plugin(self):
        manager = PluginManager()
        plugin = DummyPlugin()
        manager.load(plugin)
        assert plugin.install_called
        assert "dummy" in manager

    def test_load_duplicate_raises(self):
        manager = PluginManager()
        manager.load(DummyPlugin())
        with pytest.raises(ValueError, match="already loaded"):
            manager.load(DummyPlugin())

    def test_activate_plugin(self):
        manager = PluginManager()
        plugin = DummyPlugin()
        manager.load(plugin)
        manager.activate("dummy")
        assert plugin.activate_called
        assert plugin.state == PluginState.ACTIVE

    def test_deactivate_plugin(self):
        manager = PluginManager()
        plugin = DummyPlugin()
        manager.load(plugin)
        manager.activate("dummy")
        manager.deactivate("dummy")
        assert plugin.deactivate_called
        assert plugin.state == PluginState.INACTIVE

    def test_activate_nonexistent_raises(self):
        manager = PluginManager()
        with pytest.raises(KeyError, match="not found"):
            manager.activate("ghost")

    def test_unload_plugin(self):
        manager = PluginManager()
        plugin = DummyPlugin()
        manager.load(plugin)
        manager.unload("dummy")
        assert plugin.uninstall_called
        assert "dummy" not in manager

    def test_unload_active_deactivates_first(self):
        manager = PluginManager()
        plugin = DummyPlugin()
        manager.load(plugin)
        manager.activate("dummy")
        manager.unload("dummy")
        assert plugin.deactivate_called
        assert plugin.uninstall_called

    def test_unload_with_dependents_raises(self):
        manager = PluginManager()
        base = DummyPlugin(name="base")
        child = DummyPlugin(name="child", dependencies=["base"])
        manager.load(base)
        manager.load(child)
        with pytest.raises(ValueError, match="required by"):
            manager.unload("base")

    def test_load_missing_dependency_raises(self):
        manager = PluginManager()
        plugin = DummyPlugin(name="needy", dependencies=["missing_dep"])
        with pytest.raises(ValueError, match="requires 'missing_dep'"):
            manager.load(plugin)

    def test_list_plugins(self):
        manager = PluginManager()
        manager.load(DummyPlugin(name="a"))
        manager.load(DummyPlugin(name="b"))
        plugins = manager.list_plugins()
        assert len(plugins) == 2
        names = {p["name"] for p in plugins}
        assert names == {"a", "b"}

    def test_get_plugin(self):
        manager = PluginManager()
        plugin = DummyPlugin()
        manager.load(plugin)
        assert manager.get("dummy") is plugin
        assert manager.get("nope") is None

    def test_activation_failure_sets_error_state(self):
        manager = PluginManager()
        plugin = FailingPlugin()
        manager.load(plugin)
        with pytest.raises(RuntimeError, match="Activation failed"):
            manager.activate("failing")
        assert plugin.state == PluginState.ERROR

    def test_len(self):
        manager = PluginManager()
        assert len(manager) == 0
        manager.load(DummyPlugin())
        assert len(manager) == 1
