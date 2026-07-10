"""Bounded per-job scheduler history in JSONL.

Operational HookSystem events live in SQLite. Scheduler job logs remain JSONL
because each file is a small, portable tail owned by one scheduled job.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 2 * 1024 * 1024
DEFAULT_KEEP_LINES = 2_000


class JobRunLog:
    """Per-job JSONL tail with automatic size and row-count pruning."""

    MAX_LINES: int = DEFAULT_KEEP_LINES
    MAX_BYTES: int = DEFAULT_MAX_BYTES

    def __init__(self, log_dir: Path) -> None:
        self._log_dir = log_dir
        self._lock = threading.Lock()

    @staticmethod
    def _sanitize(name: str) -> str:
        return name.replace(":", "_").replace("/", "_")

    def _path(self, job_id: str) -> Path:
        return self._log_dir / f"{self._sanitize(job_id)}.jsonl"

    def append(self, job_id: str, entry: dict[str, Any]) -> None:
        """Append one row and enforce the live class-level bounds."""
        path = self._path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self._lock, path.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
        self.prune(job_id)

    def get_runs(self, job_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read the newest valid rows, skipping malformed lines."""
        if limit <= 0:
            return []
        path = self._path(job_id)
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as file:
            lines = file.readlines()

        entries: list[dict[str, Any]] = []
        for raw in reversed(lines):
            if not raw.strip():
                continue
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                log.warning("Skipping malformed run log line: %s", raw[:80])
                continue
            if isinstance(parsed, dict):
                entries.append(parsed)
            if len(entries) >= limit:
                break
        return entries

    def prune(self, job_id: str) -> int:
        """Atomically retain the newest ``MAX_LINES`` after ``MAX_BYTES``."""
        path = self._path(job_id)
        with self._lock:
            if not path.exists() or path.stat().st_size <= self.MAX_BYTES:
                return 0
            with path.open(encoding="utf-8") as file:
                lines = file.readlines()
            original = len(lines)
            if original <= self.MAX_LINES:
                return 0
            kept = lines[-self.MAX_LINES :] if self.MAX_LINES > 0 else []
            tmp_path = path.with_suffix(".jsonl.tmp")
            with tmp_path.open("w", encoding="utf-8") as file:
                file.writelines(kept)
            os.replace(tmp_path, path)

        removed = original - len(kept)
        log.info(
            "Pruned %s scheduler log: %d -> %d lines (%d removed)",
            job_id,
            original,
            len(kept),
            removed,
        )
        return removed


__all__ = ["DEFAULT_KEEP_LINES", "DEFAULT_MAX_BYTES", "JobRunLog"]
