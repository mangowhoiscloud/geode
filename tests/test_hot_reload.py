"""Tests for ConfigWatcher — config hot reload."""

from __future__ import annotations

import time
from pathlib import Path

from core.orchestration.hot_reload import ConfigWatcher


class TestConfigWatcher:
    def test_watch_and_detect_change(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("KEY=value1")

        changes: list[Path] = []

        def on_change(path, mtime):
            changes.append(path)

        watcher = ConfigWatcher(debounce_ms=50, poll_interval_s=0.05)
        watcher.watch(config_file, on_change)

        # Modify file
        time.sleep(0.1)  # Ensure mtime differs
        config_file.write_text("KEY=value2")

        # Manual check
        detected = watcher.check_now()
        assert detected == 1
        assert len(changes) == 1
        assert changes[0] == config_file

    def test_no_change_no_callback(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("KEY=value")

        changes: list = []

        watcher = ConfigWatcher()
        watcher.watch(config_file, lambda p, m: changes.append(p))

        detected = watcher.check_now()
        assert detected == 0
        assert changes == []

    def test_debounce_prevents_rapid_fire(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("v1")

        changes: list = []

        watcher = ConfigWatcher(debounce_ms=500)
        watcher.watch(config_file, lambda p, m: changes.append(p))

        time.sleep(0.1)
        config_file.write_text("v2")
        watcher.check_now()  # First detection → fires
        watcher.check_now()  # Within debounce → skipped

        assert len(changes) == 1

    def test_unwatch(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("v1")

        watcher = ConfigWatcher()
        watcher.watch(config_file, lambda p, m: None)
        assert watcher.watched_count == 1

        removed = watcher.unwatch(config_file)
        assert removed is True
        assert watcher.watched_count == 0

    def test_unwatch_nonexistent(self):
        watcher = ConfigWatcher()
        assert watcher.unwatch("/nonexistent") is False

    def test_start_stop(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("v1")

        watcher = ConfigWatcher(poll_interval_s=0.05)
        watcher.watch(config_file, lambda p, m: None)

        watcher.start()
        assert watcher.is_running is True

        watcher.stop()
        assert watcher.is_running is False

    def test_start_idempotent(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("v1")

        watcher = ConfigWatcher(poll_interval_s=0.05)
        watcher.watch(config_file, lambda p, m: None)
        watcher.start()
        watcher.start()  # Should not error
        watcher.stop()

    def test_stats(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("v1")

        watcher = ConfigWatcher(debounce_ms=50)
        watcher.watch(config_file, lambda p, m: None)

        time.sleep(0.1)
        config_file.write_text("v2")
        watcher.check_now()

        d = watcher.stats.to_dict()
        assert d["reloads"] == 1
        assert d["errors"] == 0

    def test_callback_error_tracked(self, tmp_path: Path):
        config_file = tmp_path / "test.env"
        config_file.write_text("v1")

        def bad_callback(p, m):
            raise ValueError("boom")

        watcher = ConfigWatcher(debounce_ms=50)
        watcher.watch(config_file, bad_callback)

        time.sleep(0.1)
        config_file.write_text("v2")
        watcher.check_now()

        assert watcher.stats.errors == 1
