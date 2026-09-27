"""Config Hot Reload — watch config files and reload without restart.

Inspired by OpenClaw's chokidar-based hot reload:
- File change detection via polling (no external dependency)
- 300ms debounce to avoid rapid-fire reloads
- Callback-based reload notification
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_MS = 300.0
DEFAULT_POLL_INTERVAL_S = 1.0


def _file_signature(path: Path) -> tuple[int, int, int, int] | None:
    """Observe identity, modification time and size; absence is a distinct state."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_size


class ConfigWatcher:
    """Watch config files for changes and trigger reload callbacks.

    Uses polling (no external deps) with debounce.

    Usage:
        watcher = ConfigWatcher()

        def on_config_change(path, mtime):
            print(f"Config changed: {path}")
            # Re-read and apply config

        watcher.watch(Path(".env"), on_config_change)
        watcher.start()
        # ... later ...
        watcher.stop()
    """

    def __init__(
        self,
        *,
        debounce_ms: float = DEFAULT_DEBOUNCE_MS,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
    ) -> None:
        self._debounce_s = debounce_ms / 1000.0
        self._poll_interval = poll_interval_s
        self._watches: dict[Path, _WatchEntry] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stats = _WatcherStats()

    @property
    def stats(self) -> _WatcherStats:
        return self._stats

    def watch(
        self,
        path: Path | str,
        callback: Callable[[Path, float], None],
        *,
        name: str | None = None,
    ) -> None:
        """Register a file to watch.

        Args:
            path: File path to watch.
            callback: Called as callback(path, mtime) on change (0.0 on deletion).
                A failed callback is retried after the debounce window.
            name: Optional name for logging.
        """
        p = Path(path)
        signature = _file_signature(p)
        with self._lock:
            self._watches[p] = _WatchEntry(
                path=p,
                callback=callback,
                name=name or p.name,
                last_signature=signature,
                debounce_until=0.0,
            )
        log.debug("Watching %s", p)

    def unwatch(self, path: Path | str) -> bool:
        """Stop watching a file. Returns True if found."""
        p = Path(path)
        with self._lock:
            return self._watches.pop(p, None) is not None

    def start(self) -> None:
        """Start the polling thread."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                if self._stop_event.is_set():
                    raise RuntimeError(
                        "ConfigWatcher is still stopping; retry after its callback exits"
                    )
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._poll_loop,
                daemon=True,
                name="config-watcher",
            )
            self._thread.start()
        log.info("ConfigWatcher started (%d files)", len(self._watches))

    def stop(self) -> None:
        """Stop the polling thread."""
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
            if thread.is_alive():
                raise RuntimeError(
                    "ConfigWatcher callback is still running; retry stop after it exits"
                )
            with self._lock:
                if self._thread is thread:
                    self._thread = None
        log.info("ConfigWatcher stopped")

    @property
    def is_running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    @property
    def watched_count(self) -> int:
        with self._lock:
            return len(self._watches)

    def check_now(self) -> int:
        """Manually check all watched files. Returns number of changes detected."""
        return self._check_all()

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while not self._stop_event.is_set():
            self._check_all()
            self._stop_event.wait(self._poll_interval)

    def _check_all(self) -> int:
        """Check all watched files for changes."""
        now = time.monotonic()
        changes = 0

        with self._lock:
            entries = list(self._watches.values())

        for entry in entries:
            try:
                signature = _file_signature(entry.path)
            except OSError:
                self._stats.errors += 1
                log.exception("Cannot inspect watched config %s", entry.name)
                continue
            if signature == entry.last_signature:
                continue

            # Debounce: skip if within debounce window
            if now < entry.debounce_until:
                continue

            entry.debounce_until = now + self._debounce_s
            changes += 1
            self._stats.reloads += 1

            current_mtime = signature[2] / 1_000_000_000 if signature is not None else 0.0
            log.info("Config changed: %s (mtime=%.1f)", entry.name, current_mtime)
            try:
                entry.callback(entry.path, current_mtime)
            except Exception:
                self._stats.errors += 1
                log.exception("Reload callback failed for %s", entry.name)
            else:
                entry.last_signature = signature

        return changes


class _WatchEntry:
    """Internal tracking for a watched file."""

    __slots__ = ("callback", "debounce_until", "last_signature", "name", "path")

    def __init__(
        self,
        *,
        path: Path,
        callback: Callable[[Path, float], None],
        name: str,
        last_signature: tuple[int, int, int, int] | None,
        debounce_until: float,
    ) -> None:
        self.path = path
        self.callback = callback
        self.name = name
        self.last_signature = last_signature
        self.debounce_until = debounce_until


class _WatcherStats:
    """Track watcher statistics."""

    def __init__(self) -> None:
        self.reloads: int = 0
        self.errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"reloads": self.reloads, "errors": self.errors}
