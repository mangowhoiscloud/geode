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
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_MS = 300.0
DEFAULT_POLL_INTERVAL_S = 1.0


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
        self._running = False
        self._thread: threading.Thread | None = None
        self._stats = _WatcherStats()

    @property
    def stats(self) -> _WatcherStats:
        return self._stats

    def watch(
        self,
        path: Path | str,
        callback: Any,
        *,
        name: str | None = None,
    ) -> None:
        """Register a file to watch.

        Args:
            path: File path to watch.
            callback: Called as callback(path, mtime) on change.
            name: Optional name for logging.
        """
        p = Path(path)
        mtime = p.stat().st_mtime if p.exists() else 0.0
        with self._lock:
            self._watches[p] = _WatchEntry(
                path=p,
                callback=callback,
                name=name or p.name,
                last_mtime=mtime,
                debounce_until=0.0,
            )
        log.debug("Watching %s (mtime=%.1f)", p, mtime)

    def unwatch(self, path: Path | str) -> bool:
        """Stop watching a file. Returns True if found."""
        p = Path(path)
        with self._lock:
            return self._watches.pop(p, None) is not None

    def start(self) -> None:
        """Start the polling thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="config-watcher",
        )
        self._thread.start()
        log.info("ConfigWatcher started (%d files)", len(self._watches))

    def stop(self) -> None:
        """Stop the polling thread."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        log.info("ConfigWatcher stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def watched_count(self) -> int:
        with self._lock:
            return len(self._watches)

    def check_now(self) -> int:
        """Manually check all watched files. Returns number of changes detected."""
        return self._check_all()

    def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._running:
            self._check_all()
            time.sleep(self._poll_interval)

    def _check_all(self) -> int:
        """Check all watched files for changes."""
        now = time.time()
        changes = 0

        with self._lock:
            entries = list(self._watches.values())

        for entry in entries:
            if not entry.path.exists():
                continue

            current_mtime = entry.path.stat().st_mtime
            if current_mtime <= entry.last_mtime:
                continue

            # Debounce: skip if within debounce window
            if now < entry.debounce_until:
                continue

            entry.last_mtime = current_mtime
            entry.debounce_until = now + self._debounce_s
            changes += 1
            self._stats.reloads += 1

            log.info("Config changed: %s (mtime=%.1f)", entry.name, current_mtime)
            try:
                entry.callback(entry.path, current_mtime)
            except Exception:
                self._stats.errors += 1
                log.exception("Reload callback failed for %s", entry.name)

        return changes


class _WatchEntry:
    """Internal tracking for a watched file."""

    __slots__ = ("path", "callback", "name", "last_mtime", "debounce_until")

    def __init__(
        self,
        *,
        path: Path,
        callback: Any,
        name: str,
        last_mtime: float,
        debounce_until: float,
    ) -> None:
        self.path = path
        self.callback = callback
        self.name = name
        self.last_mtime = last_mtime
        self.debounce_until = debounce_until


class _WatcherStats:
    """Track watcher statistics."""

    def __init__(self) -> None:
        self.reloads: int = 0
        self.errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return {"reloads": self.reloads, "errors": self.errors}
