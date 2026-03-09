"""Run Log — JSONL execution history with auto-pruning.

Inspired by OpenClaw's run log pattern:
- File: JSONL format (one JSON object per line)
- Auto pruning: max_bytes=2MB, keep_lines=2000
- Thread-safe append via threading.Lock
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_LOG_DIR = Path.home() / ".geode" / "runs"
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2MB
DEFAULT_KEEP_LINES = 2000


@dataclass
class RunLogEntry:
    """A single run log entry."""

    session_key: str
    event: str  # e.g. "pipeline_start", "node_exit", "pipeline_end"
    node: str = ""
    status: str = "ok"  # "ok", "error", "skip"
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    run_id: str = ""  # Unique ID per pipeline execution

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> RunLogEntry:
        data = json.loads(line)
        return cls(**data)


class RunLog:
    """JSONL run log with auto-pruning.

    Usage:
        run_log = RunLog("ip:berserk:full_pipeline")
        run_log.append(RunLogEntry(
            session_key="ip:berserk:full_pipeline",
            event="pipeline_start",
        ))
        entries = run_log.read(limit=10)
        run_log.prune()
    """

    def __init__(
        self,
        session_key: str,
        *,
        log_dir: Path | str | None = None,
        max_bytes: int = DEFAULT_MAX_BYTES,
        keep_lines: int = DEFAULT_KEEP_LINES,
    ) -> None:
        self._log_dir = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
        self._max_bytes = max_bytes
        self._keep_lines = keep_lines

        # Sanitize session key for filename
        safe_name = session_key.replace(":", "_").replace("/", "_")
        self._file_path = self._log_dir / f"{safe_name}.jsonl"
        self._lock = threading.Lock()

    @property
    def file_path(self) -> Path:
        return self._file_path

    def append(self, entry: RunLogEntry) -> None:
        """Append an entry to the log file."""
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(self._file_path, "a", encoding="utf-8") as f:
            f.write(entry.to_json() + "\n")

    def read(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        event_filter: str | None = None,
        node_filter: str | None = None,
        status_filter: str | None = None,
        run_id_filter: str | None = None,
    ) -> list[RunLogEntry]:
        """Read log entries (newest first) with optional filters.

        Args:
            limit: Maximum entries to return.
            offset: Skip this many entries from the end.
            event_filter: Only return entries with this event type.
            node_filter: Only return entries for this node.
            status_filter: Only return entries with this status.
            run_id_filter: Only return entries with this run_id.
        """
        if not self._file_path.exists():
            return []

        with open(self._file_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Reverse for newest-first
        lines = list(reversed(lines))

        entries = []
        skipped = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = RunLogEntry.from_json(line)
            except (json.JSONDecodeError, TypeError):
                log.warning("Skipping malformed log line: %s", line[:80])
                continue

            # Apply filters
            if event_filter and entry.event != event_filter:
                continue
            if node_filter and entry.node != node_filter:
                continue
            if status_filter and entry.status != status_filter:
                continue
            if run_id_filter and entry.run_id != run_id_filter:
                continue

            # Apply offset
            if skipped < offset:
                skipped += 1
                continue

            entries.append(entry)
            if len(entries) >= limit:
                break

        return entries

    def prune(self) -> int:
        """Prune log file if it exceeds size/line limits.

        Returns:
            Number of lines removed.
        """
        with self._lock:
            if not self._file_path.exists():
                return 0

            file_size = self._file_path.stat().st_size
            if file_size <= self._max_bytes:
                return 0

            with open(self._file_path, encoding="utf-8") as f:
                lines = f.readlines()

            original_count = len(lines)
            if original_count <= self._keep_lines:
                return 0

            # Keep the most recent lines
            kept = lines[-self._keep_lines :]
            removed = original_count - len(kept)

            # Atomic write: tmp + rename
            tmp_path = self._file_path.with_suffix(".jsonl.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(str(tmp_path), str(self._file_path))

        log.info("Pruned run log: %d → %d lines (%d removed)", original_count, len(kept), removed)
        return removed

    def clear(self) -> None:
        """Delete the log file."""
        with self._lock:
            if self._file_path.exists():
                self._file_path.unlink()

    def count(self) -> int:
        """Count total log entries."""
        if not self._file_path.exists():
            return 0
        with open(self._file_path, encoding="utf-8") as f:
            return sum(1 for line in f if line.strip())
