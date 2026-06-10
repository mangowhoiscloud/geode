"""Run logs — JSONL execution history with auto-pruning (single home).

S-6 observability fold (2026-06-11): the former ``core/orchestration/``
run log (``RunLog``, per-session execution history) and ``core/scheduler/``
run log (``JobRunLog``, per-job scheduler history) implemented the same JSONL +
threading.Lock + size-gated atomic prune pattern twice with no shared
base. Both were live; bug fixes had to land twice. This module is now the
one home: :class:`JsonlAppendLog` carries the shared primitives, the two
public classes keep their existing APIs (callers unchanged beyond the
import path).

Pattern lineage: OpenClaw's run log (JSONL, newest-first reads,
max_bytes=2MB / keep_lines=2000 prune).
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

from core.paths import GLOBAL_RUNS_DIR

log = logging.getLogger(__name__)

DEFAULT_LOG_DIR: Path = GLOBAL_RUNS_DIR
DEFAULT_MAX_BYTES = 2 * 1024 * 1024  # 2MB
DEFAULT_KEEP_LINES = 2000


class JsonlAppendLog:
    """Shared JSONL primitives: locked append, newest-first read, atomic prune.

    Subclasses decide the file layout (one file per session vs one file
    per job) and the row schema; this base owns the I/O discipline so the
    prune/lock/atomic-replace logic exists exactly once.
    """

    def __init__(
        self,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        keep_lines: int = DEFAULT_KEEP_LINES,
    ) -> None:
        self._max_bytes = max_bytes
        self._keep_lines = keep_lines
        self._lock = threading.Lock()

    @staticmethod
    def _sanitize(name: str) -> str:
        """Filesystem-safe file stem (``:`` and ``/`` → ``_``)."""
        return name.replace(":", "_").replace("/", "_")

    def _append_line(self, path: Path, line: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def _read_lines_newest_first(path: Path) -> list[str]:
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        return [raw.strip() for raw in reversed(lines) if raw.strip()]

    def _prune_file(
        self,
        path: Path,
        *,
        label: str,
        max_bytes: int | None = None,
        keep_lines: int | None = None,
    ) -> int:
        """Trim *path* to the newest ``keep_lines`` once it exceeds
        ``max_bytes``. Atomic (tmp + ``os.replace``). Returns lines removed.

        ``max_bytes`` / ``keep_lines`` override the instance limits at call
        time — ``JobRunLog`` reads its (test-mutable) ``MAX_*`` attributes
        live, preserving the pre-fold contract."""
        bytes_cap = max_bytes if max_bytes is not None else self._max_bytes
        lines_cap = keep_lines if keep_lines is not None else self._keep_lines
        with self._lock:
            if not path.exists():
                return 0
            if path.stat().st_size <= bytes_cap:
                return 0
            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            original = len(lines)
            if original <= lines_cap:
                return 0
            kept = lines[-lines_cap:]
            removed = original - len(kept)
            tmp_path = path.with_suffix(".jsonl.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.writelines(kept)
            os.replace(str(tmp_path), str(path))
        log.info(
            "Pruned %s run log: %d -> %d lines (%d removed)", label, original, len(kept), removed
        )
        return removed


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


class RunLog(JsonlAppendLog):
    """Per-session JSONL run log.

    Usage:
        run_log = RunLog("subject:demo:full_pipeline")
        run_log.append(RunLogEntry(
            session_key="subject:demo:full_pipeline",
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
        super().__init__(max_bytes=max_bytes, keep_lines=keep_lines)
        self._log_dir = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
        self._file_path = self._log_dir / f"{self._sanitize(session_key)}.jsonl"

    @property
    def file_path(self) -> Path:
        return self._file_path

    def append(self, entry: RunLogEntry) -> None:
        """Append an entry to the log file."""
        self._append_line(self._file_path, entry.to_json())

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
        entries: list[RunLogEntry] = []
        skipped = 0
        for line in self._read_lines_newest_first(self._file_path):
            try:
                entry = RunLogEntry.from_json(line)
            except (json.JSONDecodeError, TypeError):
                log.warning("Skipping malformed log line: %s", line[:80])
                continue

            if event_filter and entry.event != event_filter:
                continue
            if node_filter and entry.node != node_filter:
                continue
            if status_filter and entry.status != status_filter:
                continue
            if run_id_filter and entry.run_id != run_id_filter:
                continue

            if skipped < offset:
                skipped += 1
                continue

            entries.append(entry)
            if len(entries) >= limit:
                break

        return entries

    def prune(self) -> int:
        """Prune log file if it exceeds size/line limits."""
        return self._prune_file(self._file_path, label="session")

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


class JobRunLog(JsonlAppendLog):
    """Per-job JSONL run log — each job gets ``{job_id}.jsonl`` under *log_dir*.

    The scheduler resolves its own default directory
    (``core.scheduler.models.DEFAULT_LOG_DIR``) at the call site so this
    module stays scheduler-agnostic.
    """

    MAX_LINES: int = DEFAULT_KEEP_LINES
    MAX_BYTES: int = DEFAULT_MAX_BYTES

    def __init__(self, log_dir: Path) -> None:
        super().__init__(max_bytes=self.MAX_BYTES, keep_lines=self.MAX_LINES)
        self._log_dir = log_dir

    def _path(self, job_id: str) -> Path:
        return self._log_dir / f"{self._sanitize(job_id)}.jsonl"

    def append(self, job_id: str, entry: dict[str, Any]) -> None:
        """Append a run entry for *job_id*."""
        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        self._append_line(self._path(job_id), line)

    def get_runs(self, job_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Read the most recent *limit* entries (newest first)."""
        entries: list[dict[str, Any]] = []
        for raw in self._read_lines_newest_first(self._path(job_id)):
            try:
                entries.append(json.loads(raw))
            except json.JSONDecodeError:
                log.warning("Skipping malformed run log line: %s", raw[:80])
            if len(entries) >= limit:
                break
        return entries

    def prune(self, job_id: str) -> int:
        """Prune the job's log file if it exceeds size/line limits."""
        return self._prune_file(
            self._path(job_id),
            label=job_id,
            max_bytes=self.MAX_BYTES,
            keep_lines=self.MAX_LINES,
        )
