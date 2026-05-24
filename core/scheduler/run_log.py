"""Per-job JSONL run log with auto-pruning."""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from core.scheduler.models import DEFAULT_LOG_DIR

log = logging.getLogger(__name__)


class JobRunLog:
    """Per-job JSONL run log with auto-pruning.

    Each job gets its own ``{job_id}.jsonl`` file under *log_dir*.
    """

    MAX_LINES: int = 2000
    MAX_BYTES: int = 2 * 1024 * 1024  # 2 MB

    def __init__(self, log_dir: Path | None = None) -> None:
        self._log_dir = log_dir if log_dir is not None else DEFAULT_LOG_DIR
        self._lock = threading.Lock()

    def _path(self, job_id: str) -> Path:
        safe = job_id.replace(":", "_").replace("/", "_")
        return self._log_dir / f"{safe}.jsonl"

    def append(self, job_id: str, entry: dict[str, Any]) -> None:
        """Append a run entry for *job_id*."""
        path = self._path(job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with self._lock, open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def get_runs(self, job_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read the most recent *limit* entries (newest first)."""
        path = self._path(job_id)
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        entries: list[dict[str, Any]] = []
        for raw in reversed(lines):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                log.warning("Skipping malformed run log line: %s", raw[:80])
            if len(entries) >= limit:
                break
        return entries

    def prune(self, job_id: str) -> int:
        """Prune log file if it exceeds size/line limits.

        Returns the number of lines removed.
        """
        with self._lock:
            path = self._path(job_id)
            if not path.exists():
                return 0
            file_size = path.stat().st_size
            if file_size <= self.MAX_BYTES:
                return 0
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            original = len(lines)
            if original <= self.MAX_LINES:
                return 0
            kept = lines[-self.MAX_LINES :]
            removed = original - len(kept)
            # Atomic write: tmp + rename
            tmp_path = path.with_suffix(".jsonl.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(str(tmp_path), str(path))
            log.info(
                "Pruned job run log %s: %d -> %d lines (%d removed)",
                job_id,
                original,
                len(kept),
                removed,
            )
            return removed
