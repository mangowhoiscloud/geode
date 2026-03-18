"""Project Journal — append-only execution record for the .geode/journal/ directory.

Context Layer C2: "What have we done so far?"

All writes are append-only (immutable log). The journal answers:
- What analyses/tasks were run in this project?
- What patterns did the agent learn?
- How much did it cost?
- What errors occurred?

Files:
  .geode/journal/runs.jsonl     — execution history (1 line per run)
  .geode/journal/costs.jsonl    — per-call LLM cost records
  .geode/journal/learned.md     — project-level learned patterns
  .geode/journal/errors.jsonl   — error records
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_JOURNAL_DIR = Path(".geode") / "journal"
MAX_LEARNED_PATTERNS = 100


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
        journal.record_run("s1", "analysis", "Berserk S/81.3", cost_usd=0.15)
        journal.record_cost("claude-opus-4-6", 1200, 350, 0.015)
        journal.add_learned("Dark fantasy IPs tend to score S tier", "domain")
        recent = journal.get_recent_runs(5)
    """

    def __init__(self, journal_dir: Path | str | None = None) -> None:
        self._dir = Path(journal_dir) if journal_dir else DEFAULT_JOURNAL_DIR
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

    # ------------------------------------------------------------------
    # C2.2: Costs (project-level LLM cost)
    # ------------------------------------------------------------------

    def record_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        *,
        session_id: str = "",
    ) -> None:
        """Append a cost record to costs.jsonl."""
        d = {
            "ts": time.time(),
            "model": model,
            "in": input_tokens,
            "out": output_tokens,
            "cost": round(cost_usd, 6),
        }
        if session_id:
            d["sid"] = session_id
        self._append_jsonl("costs.jsonl", json.dumps(d, separators=(",", ":")))

    def get_project_cost_summary(self) -> dict[str, Any]:
        """Aggregate project-level costs from costs.jsonl."""
        lines = self._read_jsonl_all("costs.jsonl")
        total_cost = 0.0
        total_calls = 0
        by_model: dict[str, float] = {}
        for line in lines:
            try:
                d = json.loads(line)
                cost = d.get("cost", 0.0)
                model = d.get("model", "unknown")
                total_cost += cost
                total_calls += 1
                by_model[model] = by_model.get(model, 0.0) + cost
            except (json.JSONDecodeError, KeyError):
                continue
        return {
            "total_cost": round(total_cost, 4),
            "total_calls": total_calls,
            "by_model": by_model,
        }

    # ------------------------------------------------------------------
    # C2.3: Learned patterns (project-level)
    # ------------------------------------------------------------------

    def add_learned(self, pattern: str, category: str = "general") -> None:
        """Append a learned pattern to learned.md (dedup + rotation)."""
        learned_path = self._dir / "learned.md"
        self._dir.mkdir(parents=True, exist_ok=True)

        existing_lines: list[str] = []
        if learned_path.exists():
            existing_lines = learned_path.read_text(encoding="utf-8").splitlines()

        # Dedup: skip if pattern already present
        for line in existing_lines:
            if pattern in line:
                return

        # Format: "- [category] pattern (YYYY-MM-DD)"
        today = date.today().isoformat()
        entry = f"- [{category}] {pattern} ({today})"

        with self._lock:
            existing_lines.append(entry)
            # Rotation: keep most recent MAX entries
            if len(existing_lines) > MAX_LEARNED_PATTERNS:
                existing_lines = existing_lines[-MAX_LEARNED_PATTERNS:]
            learned_path.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")

    def get_learned_patterns(self) -> list[str]:
        """Read all learned patterns."""
        learned_path = self._dir / "learned.md"
        if not learned_path.exists():
            return []
        return [
            line for line in learned_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]

    # ------------------------------------------------------------------
    # C2.4: Errors
    # ------------------------------------------------------------------

    def record_error(
        self,
        session_id: str,
        error_type: str,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append an error record to errors.jsonl."""
        d: dict[str, Any] = {
            "ts": time.time(),
            "sid": session_id,
            "type": error_type,
            "msg": message[:500],
        }
        if metadata:
            d["meta"] = metadata
        self._append_jsonl("errors.jsonl", json.dumps(d, separators=(",", ":")))

    # ------------------------------------------------------------------
    # C2.5: Context summary (for LLM injection)
    # ------------------------------------------------------------------

    def get_context_summary(self, max_runs: int = 3) -> str:
        """Build a 1-line summary for system prompt injection (P6 L2 extraction).

        Format: "Project history: Berserk S/81.3 (2h ago) | Research done (1d ago)"
        """
        runs = self.get_recent_runs(max_runs)
        if not runs:
            return ""

        now = time.time()
        parts = []
        for r in runs:
            age = _format_age(now - r.ts)
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

    def _read_jsonl_all(self, filename: str) -> list[str]:
        fpath = self._dir / filename
        if not fpath.exists():
            return []
        try:
            return [ln for ln in fpath.read_text(encoding="utf-8").splitlines() if ln.strip()]
        except OSError:
            return []


def _format_age(seconds: float) -> str:
    """Format elapsed seconds as human-readable age."""
    if seconds < 60:
        return "now"
    minutes = seconds / 60
    if minutes < 60:
        return f"{int(minutes)}m ago"
    hours = minutes / 60
    if hours < 24:
        return f"{int(hours)}h ago"
    days = hours / 24
    return f"{int(days)}d ago"


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
