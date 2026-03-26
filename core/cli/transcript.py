"""SessionTranscript — JSONL event stream for session audit trail.

Tier 1 preservation: records every event in a session as an append-only
JSONL file. Complementary to Journal (Tier 2, summaries) and Snapshot
(Tier 3, pipeline state).

Captures: user messages, assistant responses, tool calls/results,
vault saves, costs, errors — everything needed to reconstruct
"what exactly happened in this session."

Storage: .geode/journal/transcripts/{session_id}.jsonl
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_TRANSCRIPT_DIR = Path(".geode") / "journal" / "transcripts"
MAX_TEXT_CHARS = 500
MAX_INPUT_CHARS = 300
CLEANUP_AGE_DAYS = 30
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5MB per transcript


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


class SessionTranscript:
    """Append-only JSONL event recorder for a single session.

    Usage::

        tx = SessionTranscript("s-abc123")
        tx.record_session_start(model="claude-opus-4-6")
        tx.record_user_message("내 프로필 시그널 분석해줘")
        tx.record_tool_call("web_fetch", {"url": "https://..."})
        tx.record_tool_result("web_fetch", "ok", "channel data...")
        tx.record_assistant_message("분석 결과입니다...")
        tx.record_vault_save("vault/profile/signal-report.md", "profile")
        tx.record_cost("claude-opus-4-6", 1200, 350, 0.015)
        tx.record_session_end(duration_s=20, total_cost=0.015, rounds=3)
    """

    def __init__(
        self,
        session_id: str,
        transcript_dir: Path | str | None = None,
    ) -> None:
        self._session_id = session_id
        self._dir = Path(transcript_dir) if transcript_dir else DEFAULT_TRANSCRIPT_DIR
        self._lock = threading.Lock()
        self._event_count = 0

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def event_count(self) -> int:
        return self._event_count

    @property
    def file_path(self) -> Path:
        return self._dir / f"{self._session_id}.jsonl"

    # ------------------------------------------------------------------
    # Event recorders
    # ------------------------------------------------------------------

    def record_session_start(self, *, model: str = "", provider: str = "anthropic") -> None:
        self._append(
            {
                "event": "session_start",
                "model": model,
                "provider": provider,
                "session_id": self._session_id,
            }
        )

    def record_session_end(
        self,
        *,
        duration_s: float = 0,
        total_cost: float = 0,
        rounds: int = 0,
    ) -> None:
        self._append(
            {
                "event": "session_end",
                "duration_s": round(duration_s, 1),
                "total_cost": round(total_cost, 4),
                "rounds": rounds,
            }
        )
        self._update_index()

    def record_user_message(self, text: str) -> None:
        self._append(
            {
                "event": "user_message",
                "text": _truncate(text, MAX_TEXT_CHARS),
            }
        )

    def record_assistant_message(self, text: str) -> None:
        self._append(
            {
                "event": "assistant_message",
                "text": _truncate(text, MAX_TEXT_CHARS),
            }
        )

    def record_tool_call(self, tool: str, tool_input: dict[str, Any]) -> None:
        input_str = json.dumps(tool_input, ensure_ascii=False, default=str)
        self._append(
            {
                "event": "tool_call",
                "tool": tool,
                "input": _truncate(input_str, MAX_INPUT_CHARS),
            }
        )

    def record_tool_result(self, tool: str, status: str, summary: str = "") -> None:
        self._append(
            {
                "event": "tool_result",
                "tool": tool,
                "status": status,
                "summary": _truncate(summary, MAX_INPUT_CHARS),
            }
        )

    def record_vault_save(self, path: str, category: str) -> None:
        self._append(
            {
                "event": "vault_save",
                "path": path,
                "category": category,
            }
        )

    def record_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
    ) -> None:
        self._append(
            {
                "event": "cost",
                "model": model,
                "in": input_tokens,
                "out": output_tokens,
                "cost": round(cost_usd, 6),
            }
        )

    def record_error(self, error_type: str, message: str) -> None:
        self._append(
            {
                "event": "error",
                "type": error_type,
                "msg": _truncate(message, MAX_TEXT_CHARS),
            }
        )

    def record_subagent_start(self, task_id: str, task_type: str = "") -> None:
        self._append(
            {
                "event": "subagent_start",
                "task_id": task_id,
                "task_type": task_type,
            }
        )

    def record_subagent_complete(self, task_id: str, status: str, summary: str = "") -> None:
        self._append(
            {
                "event": "subagent_complete",
                "task_id": task_id,
                "status": status,
                "summary": _truncate(summary, MAX_INPUT_CHARS),
            }
        )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def read_events(self, limit: int = 100) -> list[dict[str, Any]]:
        """Read most recent N events from this transcript."""
        fpath = self.file_path
        if not fpath.exists():
            return []
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
            events = []
            for line in lines[-limit:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            return events
        except OSError:
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _append(self, data: dict[str, Any]) -> None:
        data["ts"] = time.time()
        line = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            fpath = self.file_path
            # Size guard
            if fpath.exists() and fpath.stat().st_size > MAX_FILE_BYTES:
                self._tail_truncate(fpath)
            try:
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
                self._event_count += 1
            except OSError as e:
                log.warning("Transcript write failed: %s", e)

    def _tail_truncate(self, fpath: Path) -> None:
        """Keep only the last half of lines when file exceeds size limit."""
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
            keep = lines[len(lines) // 2 :]
            fpath.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _update_index(self) -> None:
        """Update the session index file with this session's metadata."""
        index_path = self._dir / "index.json"
        index: dict[str, Any] = {}
        if index_path.exists():
            try:
                index = json.loads(index_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                index = {}

        if "sessions" not in index:
            index["sessions"] = {}

        index["sessions"][self._session_id] = {
            "event_count": self._event_count,
            "updated_at": time.time(),
        }

        import contextlib

        from core.utils.atomic_io import atomic_write_json

        with contextlib.suppress(OSError):
            atomic_write_json(index_path, index, indent=2)


# ---------------------------------------------------------------------------
# Cleanup utility
# ---------------------------------------------------------------------------


def cleanup_old_transcripts(
    transcript_dir: Path | str | None = None,
    max_age_days: int = CLEANUP_AGE_DAYS,
) -> int:
    """Remove transcript files older than max_age_days. Returns count removed."""
    tdir = Path(transcript_dir) if transcript_dir else DEFAULT_TRANSCRIPT_DIR
    if not tdir.exists():
        return 0

    cutoff = time.time() - (max_age_days * 86400)
    removed = 0
    for fpath in list(tdir.glob("*.jsonl")):
        try:
            if fpath.stat().st_mtime < cutoff:
                fpath.unlink()
                removed += 1
        except OSError:
            continue
    return removed
