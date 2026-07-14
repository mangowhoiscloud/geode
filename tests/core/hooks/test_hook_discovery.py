"""Tests for Hook Plugin Discovery system."""

from __future__ import annotations

from pathlib import Path

import pytest
from core.hooks import HookEvent, HookSystem
from core.hooks.discovery import HookPluginLoader, discover_hooks

# ---------------------------------------------------------------------------
# Fixtures for creating temporary plugin directories
# ---------------------------------------------------------------------------


@pytest.fixture()
def hooks_dir(tmp_path: Path) -> Path:
    """Return a temporary parent directory for hook plugins."""
    d = tmp_path / "hooks"
    d.mkdir()
    return d


def _make_yaml_plugin(
    parent: Path,
    name: str,
    *,
    events: list[str] | None = None,
    priority: int = 50,
    enabled: bool = True,
    handler_body: str | None = None,
    handler_filename: str = "handler.py",
    extra_yaml: str = "",
) -> Path:
    """Helper: create a YAML-based hook plugin directory."""
    plugin_dir = parent / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    if events is None:
        events = ["tool_exec_end"]

    events_str = ", ".join(f'"{e}"' for e in events)
    yaml_content = (
        f"name: {name}\n"
        f'description: "Test plugin {name}"\n'
        f"events: [{events_str}]\n"
        f"priority: {priority}\n"
        f"handler: {handler_filename}\n"
        f"enabled: {str(enabled).lower()}\n"
    )
    if extra_yaml:
        yaml_content += extra_yaml

    (plugin_dir / "hook.yaml").write_text(yaml_content)

    if handler_body is None:
        handler_body = (
            "calls = []\n"
            "def handle(event, data):\n"
            "    calls.append({'event': event, 'data': data})\n"
        )
    (plugin_dir / handler_filename).write_text(handler_body)
    return plugin_dir


def _make_class_plugin(
    parent: Path,
    name: str,
    *,
    events: list[str] | None = None,
    priority: int = 50,
    enabled: bool = True,
    class_body: str | None = None,
) -> Path:
    """Helper: create a class-based hook plugin directory (hook.py)."""
    plugin_dir = parent / name
    plugin_dir.mkdir(parents=True, exist_ok=True)

    if events is None:
        events = ["HookEvent.SESSION_STARTED"]
    events_list = ", ".join(events)

    if class_body is None:
        class_body = (
            "from __future__ import annotations\n"
            "from dataclasses import dataclass, field\n"
            "from pathlib import Path\n"
            "from typing import Any\n"
            "from core.hooks import HookEvent\n"
            "from core.hooks.discovery import HookPluginMetadata\n"
            "\n"
            "calls: list[dict[str, Any]] = []\n"
            "\n"
            f"class {name.replace('-', '_').title().replace('_', '')}Plugin:\n"
            "    @property\n"
            "    def metadata(self) -> HookPluginMetadata:\n"
            "        return HookPluginMetadata(\n"
            f"            name='{name}',\n"
            f"            events=[{events_list}],\n"
            f"            priority={priority},\n"
            f"            description='Class plugin {name}',\n"
            f"            enabled={enabled},\n"
            "        )\n"
            "\n"
            "    def handle(self, event: HookEvent, data: dict[str, Any]) -> None:\n"
            "        calls.append({'event': event, 'data': data})\n"
        )

    (plugin_dir / "hook.py").write_text(class_body)
    return plugin_dir


# ---------------------------------------------------------------------------
# Tests: YAML-based discovery
# ---------------------------------------------------------------------------


class TestYAMLDiscovery:
    def test_discover_yaml_plugin(self, hooks_dir: Path) -> None:
        _make_yaml_plugin(hooks_dir, "my-yaml-hook", events=["tool_exec_end", "tool_exec_failed"])

        found = discover_hooks([hooks_dir])
        assert len(found) == 1
        meta = found[0]
        assert meta.name == "my-yaml-hook"
        assert HookEvent.TOOL_EXEC_ENDED in meta.events
        assert HookEvent.TOOL_EXEC_FAILED in meta.events
        assert meta.priority == 50

    def test_discover_yaml_with_handler_fires(self, hooks_dir: Path) -> None:
        _make_yaml_plugin(hooks_dir, "fire-test", events=["session_start"])

        loader = HookPluginLoader()
        plugins = loader.load_from_dirs([hooks_dir])
        assert len(plugins) == 1

        hooks = HookSystem()
        loader.register_all(hooks)

        results = hooks.trigger(HookEvent.SESSION_STARTED, {"subject": "test"})
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].handler_name == "fire-test"


# ---------------------------------------------------------------------------
# Tests: Class-based discovery
# ---------------------------------------------------------------------------


class TestClassDiscovery:
    def test_discover_class_plugin(self, hooks_dir: Path) -> None:
        _make_class_plugin(hooks_dir, "my-class-hook", events=["HookEvent.SESSION_STARTED"])

        found = discover_hooks([hooks_dir])
        assert len(found) == 1
        meta = found[0]
        assert meta.name == "my-class-hook"
        assert HookEvent.SESSION_STARTED in meta.events

    def test_class_plugin_fires(self, hooks_dir: Path) -> None:
        _make_class_plugin(hooks_dir, "class-fire", events=["HookEvent.SESSION_ENDED"])

        loader = HookPluginLoader()
        plugins = loader.load_from_dirs([hooks_dir])
        assert len(plugins) == 1

        hooks = HookSystem()
        loader.register_all(hooks)

        results = hooks.trigger(HookEvent.SESSION_ENDED, {"node": "analyst"})
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].handler_name == "class-fire"


# ---------------------------------------------------------------------------
# Tests: Registration and triggering
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_register_discovered_hooks_into_hook_system(self, hooks_dir: Path) -> None:
        # Deliberately uses the LEGACY pre-rename event values — a
        # ``.geode/hooks/`` manifest written before PR-HOOK-TAXONOMY D5
        # must keep loading, resolved onto the canonical members via
        # ``LEGACY_EVENT_VALUES``.
        _make_yaml_plugin(
            hooks_dir, "hook-a", events=["tool_exec_start", "tool_exec_end"], priority=40
        )
        _make_yaml_plugin(hooks_dir, "hook-b", events=["session_start"], priority=60)

        loader = HookPluginLoader()
        loader.load_from_dirs([hooks_dir])

        hooks = HookSystem()
        loader.register_all(hooks)

        all_hooks = hooks.list_hooks()
        assert "hook-a" in all_hooks.get("tool_exec_started", [])
        assert "hook-a" in all_hooks.get("tool_exec_ended", [])
        assert "hook-b" in all_hooks.get("session_started", [])

    def test_priority_ordering_respected(self, hooks_dir: Path) -> None:
        """Plugins with lower priority number should run first."""
        order: list[str] = []

        handler_high = (
            "import sys\n"
            "order_ref = None\n"
            "def handle(event, data):\n"
            "    data['order'].append('high')\n"
        )
        handler_low = (
            "import sys\n"
            "order_ref = None\n"
            "def handle(event, data):\n"
            "    data['order'].append('low')\n"
        )

        _make_yaml_plugin(
            hooks_dir,
            "high-prio",
            events=["tool_exec_end"],
            priority=10,
            handler_body=handler_high,
        )
        _make_yaml_plugin(
            hooks_dir,
            "low-prio",
            events=["tool_exec_end"],
            priority=90,
            handler_body=handler_low,
        )

        loader = HookPluginLoader()
        loader.load_from_dirs([hooks_dir])

        hooks = HookSystem()
        loader.register_all(hooks)

        results = hooks.trigger(HookEvent.TOOL_EXEC_ENDED, {"order": order})
        assert len(results) == 2
        assert all(r.success for r in results)
        assert order == ["high", "low"]

    def test_unregister_all_removes_discovered_hooks(self, hooks_dir: Path) -> None:
        _make_yaml_plugin(hooks_dir, "removable", events=["tool_exec_start", "tool_exec_end"])

        loader = HookPluginLoader()
        loader.load_from_dirs([hooks_dir])

        hooks = HookSystem()
        loader.register_all(hooks)
        assert hooks.list_hooks() != {}

        loader.unregister_all(hooks)
        # All events should have no hooks left
        remaining = hooks.list_hooks()
        for event_name, names in remaining.items():
            assert names == [], f"Event {event_name} still has hooks: {names}"


# ---------------------------------------------------------------------------
# Tests: Edge cases and error handling
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_invalid_directory_handled_gracefully(self, tmp_path: Path) -> None:
        """Non-existent directories should be silently skipped."""
        nonexistent = tmp_path / "does-not-exist"
        found = discover_hooks([nonexistent])
        assert found == []

    def test_empty_directory_returns_no_plugins(self, hooks_dir: Path) -> None:
        found = discover_hooks([hooks_dir])
        assert found == []

    def test_disabled_yaml_hook_not_loaded(self, hooks_dir: Path) -> None:
        _make_yaml_plugin(hooks_dir, "disabled-hook", enabled=False)

        found = discover_hooks([hooks_dir])
        assert len(found) == 0

        loader = HookPluginLoader()
        plugins = loader.load_from_dirs([hooks_dir])
        assert len(plugins) == 0

    def test_disabled_class_hook_not_loaded(self, hooks_dir: Path) -> None:
        _make_class_plugin(
            hooks_dir,
            "disabled-class",
            events=["HookEvent.SESSION_STARTED"],
            enabled=False,
        )

        found = discover_hooks([hooks_dir])
        assert len(found) == 0

        loader = HookPluginLoader()
        plugins = loader.load_from_dirs([hooks_dir])
        assert len(plugins) == 0

    def test_invalid_event_name_raises_error(self, hooks_dir: Path) -> None:
        _make_yaml_plugin(hooks_dir, "bad-event", events=["not_a_real_event"])

        with pytest.raises(ValueError, match="Invalid hook event"):
            discover_hooks([hooks_dir])

    def test_missing_handler_file_skipped(self, hooks_dir: Path) -> None:
        """YAML plugin pointing to non-existent handler file is skipped."""
        plugin_dir = hooks_dir / "missing-handler"
        plugin_dir.mkdir()
        (plugin_dir / "hook.yaml").write_text(
            'name: missing-handler\nevents: ["tool_exec_end"]\nhandler: nonexistent.py\nenabled: true\n'
        )

        loader = HookPluginLoader()
        plugins = loader.load_from_dirs([hooks_dir])
        assert len(plugins) == 0

    def test_directory_with_plain_files_ignored(self, hooks_dir: Path) -> None:
        """Files (not directories) at the top level should be skipped."""
        (hooks_dir / "random_file.txt").write_text("not a plugin")
        found = discover_hooks([hooks_dir])
        assert found == []

    def test_yaml_without_events_skipped(self, hooks_dir: Path) -> None:
        """YAML plugin with empty events list is skipped."""
        plugin_dir = hooks_dir / "no-events"
        plugin_dir.mkdir()
        (plugin_dir / "hook.yaml").write_text(
            "name: no-events\nevents: []\nhandler: handler.py\nenabled: true\n"
        )
        (plugin_dir / "handler.py").write_text("def handle(event, data): pass\n")

        loader = HookPluginLoader()
        plugins = loader.load_from_dirs([hooks_dir])
        assert len(plugins) == 0

    def test_multiple_directories_scanned(self, tmp_path: Path) -> None:
        """Plugins from multiple parent directories are all discovered."""
        dir_a = tmp_path / "hooks_a"
        dir_a.mkdir()
        dir_b = tmp_path / "hooks_b"
        dir_b.mkdir()

        _make_yaml_plugin(dir_a, "plugin-a", events=["tool_exec_start"])
        _make_yaml_plugin(dir_b, "plugin-b", events=["tool_exec_end"])

        found = discover_hooks([dir_a, dir_b])
        names = {m.name for m in found}
        assert names == {"plugin-a", "plugin-b"}

    def test_loaded_plugins_property(self, hooks_dir: Path) -> None:
        _make_yaml_plugin(hooks_dir, "prop-test", events=["session_start"])

        loader = HookPluginLoader()
        assert loader.loaded_plugins == []

        loader.load_from_dirs([hooks_dir])
        assert len(loader.loaded_plugins) == 1

    def test_yaml_requires_packages_field(self, hooks_dir: Path) -> None:
        """The requires.packages field is correctly parsed."""
        extra = 'requires:\n  packages: ["pandas", "numpy"]\n'
        _make_yaml_plugin(
            hooks_dir,
            "with-deps",
            events=["tool_exec_end"],
            extra_yaml=extra,
        )

        found = discover_hooks([hooks_dir])
        assert len(found) == 1
        assert found[0].requires == ["pandas", "numpy"]
