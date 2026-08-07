"""Project Journal — append-only run record for the .geode/journal/ directory.

Context Layer C2: "What have we done so far?"

The journal answers what analyses and tasks ran in this project. Session
timelines own call costs and errors; active memory owns accepted learning.

Files:
  .geode/journal/runs.jsonl     — execution history (1 line per run)

Historical costs.jsonl, learned.md, and errors.jsonl files are left untouched.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.time_format import format_age

log = logging.getLogger(__name__)

# Default resolves to ~/.geode/projects/{id}/journal/ with fallback to .geode/journal/
_DEFAULT_JOURNAL_DIR: Path | None = None


def _get_default_journal_dir() -> Path:
    global _DEFAULT_JOURNAL_DIR
    if _DEFAULT_JOURNAL_DIR is None:
        from core.paths import resolve_journal_dir

        _DEFAULT_JOURNAL_DIR = resolve_journal_dir()
    return _DEFAULT_JOURNAL_DIR


@dataclass(slots=True)
class RunRecord:
    """Single execution record for runs.jsonl."""

    ts: float
    session_id: str
    run_type: str  # analysis, research, automation, chat
    summary: str  # 1-line human-readable summary
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"  # ok, error, partial
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        d: dict[str, Any] = {
            "ts": self.ts,
            "sid": self.session_id,
            "type": self.run_type,
            "summary": self.summary,
            "status": self.status,
        }
        if self.cost_usd:
            d["cost"] = round(self.cost_usd, 4)
        if self.duration_ms:
            d["dur_ms"] = round(self.duration_ms, 1)
        if self.metadata:
            d["meta"] = self.metadata
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_json(cls, line: str) -> RunRecord:
        d = json.loads(line)
        return cls(
            ts=d.get("ts", 0.0),
            session_id=d.get("sid", ""),
            run_type=d.get("type", ""),
            summary=d.get("summary", ""),
            cost_usd=d.get("cost", 0.0),
            duration_ms=d.get("dur_ms", 0.0),
            status=d.get("status", "ok"),
            metadata=d.get("meta", {}),
        )


class ProjectJournal:
    """Append-only project journal backed by .geode/journal/.

    Usage::

        journal = ProjectJournal()
        journal.record_run("s1", "analysis", "Repository audit complete", cost_usd=0.15)
        recent = journal.get_recent_runs(5)
    """

    def __init__(self, journal_dir: Path | str | None = None) -> None:
        self._dir = Path(journal_dir) if journal_dir else _get_default_journal_dir()
        self._lock = threading.Lock()

    @property
    def journal_dir(self) -> Path:
        return self._dir

    def ensure_structure(self) -> None:
        """Create journal directory if missing."""
        self._dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # C2.1: Runs (execution history)
    # ------------------------------------------------------------------

    def record_run(
        self,
        session_id: str,
        run_type: str,
        summary: str,
        *,
        cost_usd: float = 0.0,
        duration_ms: float = 0.0,
        status: str = "ok",
        metadata: dict[str, Any] | None = None,
    ) -> RunRecord:
        """Append a run record to runs.jsonl."""
        record = RunRecord(
            ts=time.time(),
            session_id=session_id,
            run_type=run_type,
            summary=summary,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            status=status,
            metadata=metadata or {},
        )
        self._append_jsonl("runs.jsonl", record.to_json())
        return record

    def get_recent_runs(self, limit: int = 5) -> list[RunRecord]:
        """Read most recent N run records."""
        lines = self._read_jsonl_tail("runs.jsonl", limit)
        records = []
        for line in lines:
            try:
                records.append(RunRecord.from_json(line))
            except (json.JSONDecodeError, KeyError):
                continue
        return records

    def get_learned_patterns(self) -> list[str]:
        """Read historical learned patterns for the explicit context facade."""
        learned_path = self._dir / "learned.md"
        if not learned_path.exists():
            return []
        return [
            line for line in learned_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    # ------------------------------------------------------------------
    # C2.2: Context summary (for explicit context assembly)
    # ------------------------------------------------------------------

    def get_context_summary(self, max_runs: int = 3) -> str:
        """Build a 1-line summary for system prompt injection (P6 L2 extraction).

        Format: "Project history: Repository audit complete (2h ago) | Research done (1d ago)"
        """
        runs = self.get_recent_runs(max_runs)
        if not runs:
            return ""

        now = time.time()
        parts = []
        for r in runs:
            age = format_age(now - r.ts)
            parts.append(f"{r.summary} ({age})")
        return "Project history: " + " | ".join(parts)

    # ------------------------------------------------------------------
    # Internal file I/O
    # ------------------------------------------------------------------

    def _append_jsonl(self, filename: str, line: str) -> None:
        fpath = self._dir / filename
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            try:
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
                    import os

                    os.fsync(f.fileno())
            except OSError as e:
                log.warning("Failed to write journal %s: %s", filename, e)

    def _read_jsonl_tail(self, filename: str, limit: int) -> list[str]:
        fpath = self._dir / filename
        if not fpath.exists():
            return []
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
            return [ln for ln in lines[-limit:] if ln.strip()]
        except OSError:
            return []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_journal: ProjectJournal | None = None
_journal_lock = threading.Lock()


def get_project_journal(journal_dir: Path | str | None = None) -> ProjectJournal:
    """Get or create the module-level ProjectJournal singleton."""
    global _journal
    if _journal is not None:
        return _journal
    with _journal_lock:
        if _journal is None:
            _journal = ProjectJournal(journal_dir)
        return _journal


def reset_project_journal(journal: ProjectJournal | None = None) -> None:
    """Reset singleton (for testing)."""
    global _journal
    _journal = journal
