"""Tests for ConfigWatcher — config hot reload."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
from core.orchestration.hot_reload import ConfigWatcher


class TestConfigWatcher:
    def test_stop_wakes_long_poll_interval(self) -> None:
        watcher = ConfigWatcher(poll_interval_s=60)
        watcher.start()
        thread = watcher._thread
        assert thread is not None
        watcher.stop()
        assert not thread.is_alive()
        assert not watcher.is_running
        watcher.start()
        try:
            assert watcher.is_running
            assert watcher._thread is not thread
        finally:
            watcher.stop()

    def test_blocked_callback_keeps_ownership_until_stop_can_finish(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text("old")
        entered = threading.Event()
        release = threading.Event()

        def reload(_path: Path, _mtime: float) -> None:
            entered.set()
            release.wait(timeout=10)

        watcher = ConfigWatcher(debounce_ms=0, poll_interval_s=0.01)
        watcher.watch(path, reload)
        path.write_text("new candidate")
        watcher.start()
        thread = watcher._thread
        assert thread is not None
        try:
            assert entered.wait(timeout=2)
            with pytest.raises(RuntimeError, match="retry stop"):
                watcher.stop()
            assert watcher.is_running
            assert watcher._thread is thread
            with pytest.raises(RuntimeError, match="still stopping"):
                watcher.start()
            assert watcher._thread is thread
        finally:
            release.set()
            watcher.stop()
        assert not thread.is_alive()
        assert not watcher.is_running

    def test_deletion_and_recreation_are_observable(self, tmp_path: Path) -> None:
        path = tmp_path / "config.toml"
        path.write_text("old")
        changes: list[float] = []
        watcher = ConfigWatcher(debounce_ms=0)
        watcher.watch(path, lambda _path, mtime: changes.append(mtime))

        path.unlink()
        assert watcher.check_now() == 1
        assert changes == [0.0]
        assert watcher.check_now() == 0
        path.write_text("new")
        assert watcher.check_now() == 1
        assert len(changes) == 2
        assert changes[-1] == pytest.approx(path.stat().st_mtime)

    @pytest.mark.parametrize("mtime_delta", [-60, 0])
    def test_replacement_does_not_require_newer_mtime(
        self, tmp_path: Path, mtime_delta: int
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_text("old")
        original = path.stat()
        changes: list[Path] = []
        watcher = ConfigWatcher(debounce_ms=0)
        watcher.watch(path, lambda path, _mtime: changes.append(path))

        replacement = tmp_path / "replacement.toml"
        replacement.write_text("new")
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns + mtime_delta))
        replacement.replace(path)

        assert watcher.check_now() == 1
        assert changes == [path]
        assert watcher.check_now() == 0

    def test_failed_callback_retries_after_debounce_without_another_edit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path = tmp_path / "config.toml"
        path.write_text("old")
        attempts: list[str] = []

        def reload(path: Path, _mtime: float) -> None:
            attempts.append(path.read_text())
            if len(attempts) == 1:
                raise ValueError("candidate unavailable")

        monkeypatch.setattr("core.orchestration.hot_reload.time.monotonic", lambda: 10.0)
        watcher = ConfigWatcher(debounce_ms=300)
        watcher.watch(path, reload)
        path.write_text("new candidate")
        assert watcher.check_now() == 1
        assert watcher.check_now() == 0
        monkeypatch.setattr("core.orchestration.hot_reload.time.monotonic", lambda: 10.4)
        assert watcher.check_now() == 1
        assert watcher.check_now() == 0
        assert attempts == ["new candidate", "new candidate"]
        assert watcher.stats.errors == 1

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

    def test_gateway_binding_reload_pattern(self, tmp_path: Path):
        """Simulate the gateway binding hot-reload pattern from build_gateway()."""
        import tomllib

        config_file = tmp_path / "config.toml"
        config_file.write_bytes(b'[gateway]\nbindings = ["#general"]\n')

        reload_calls: list[dict] = []

        def reload_bindings(path: Path, mtime: float) -> None:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            reload_calls.append(data)

        watcher = ConfigWatcher(debounce_ms=50)
        watcher.watch(config_file, reload_bindings, name="gateway-bindings")

        # Modify config
        time.sleep(0.1)
        config_file.write_bytes(b'[gateway]\nbindings = ["#alerts"]\n')

        detected = watcher.check_now()
        assert detected == 1
        assert len(reload_calls) == 1
        assert reload_calls[0]["gateway"]["bindings"] == ["#alerts"]
