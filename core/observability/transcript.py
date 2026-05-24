"""SessionTranscript — JSONL event stream for session audit trail.

Tier 1 preservation: records every event in a session as an append-only
JSONL file. Complementary to :class:`SessionMetrics` (Tier 2, cumulative
aggregate roll-up) and Snapshot (Tier 3, pipeline state).

Captures: user messages, assistant responses, tool calls/results,
vault saves, costs, errors, **lifecycle events** (audit_started /
config_snapshot / per_dim_scores 등 — pre-PR-SESSION-METRICS 의
``SessionJournal`` 에서 흡수, 이후 PR-CLEANUP-7 에서
:class:`~core.self_improving_loop.run_transcript.RunTranscript` 로
이름·위치 정리) — everything needed to reconstruct "what exactly
happened in this session."

PR-SESSION-METRICS (2026-05-23) — ``SessionJournal`` folded into this
Tier-1 surface via :meth:`record_lifecycle_event`. Legacy
``~/.geode/journal/transcripts/<slug>/`` 디렉터리 한 depth 줄어서
``~/.geode/transcripts/<slug>/<session_id>.jsonl`` 로 단순화.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def _get_default_transcript_dir() -> Path:
    """Return ``~/.geode/transcripts/<project-slug>/``.

    Project slug is derived from CWD (same pattern as Claude Code).
    Falls back to 'default' if CWD cannot be resolved.

    PR-SESSION-METRICS (2026-05-23) — depth 한 단계 줄임. 이전엔
    ``~/.geode/journal/transcripts/<slug>/`` 였으나 ``journal/`` 디렉터리의
    의미가 SessionJournal alias-shim 이후 사라져서 ``transcripts/`` 만으로
    self-evident. Legacy ``~/.geode/journal/transcripts/`` 안에 있는 파일은
    layout migrator 가 옮기지 않음 — 30-day cleanup 이 자연 회수.
    """
    from core.paths import GLOBAL_TRANSCRIPTS_DIR

    try:
        slug = str(Path.cwd()).replace("/", "-")
    except OSError:
        slug = "default"
    return GLOBAL_TRANSCRIPTS_DIR / slug


DEFAULT_TRANSCRIPT_DIR = _get_default_transcript_dir()
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

    def record_lifecycle_event(
        self,
        *,
        event: str,
        session_id: str = "",
        gen_tag: str = "",
        component: str = "",
        level: str = "info",
        payload: dict[str, Any] | None = None,
        ts: float | None = None,
        file_path: Path | None = None,
    ) -> None:
        """Record a free-form lifecycle event — replaces the legacy
        ``SessionJournal.append(event, payload=...)`` path (renamed to
        :meth:`~core.self_improving_loop.run_transcript.RunTranscript.append`
        in PR-CLEANUP-7).

        PR-SESSION-METRICS (2026-05-23) — folded ``SessionJournal`` into the
        Tier-1 :class:`SessionTranscript`. Schema preserved
        (``{ts, session_id, gen_tag, component, level, event, payload}``)
        so existing readers (``tests/core/self_improving_loop/test_run_transcript.py``,
        operator grep on ``transcript.jsonl``) keep working.

        ``file_path`` overrides the default ``<dir>/<session_id>.jsonl``
        layout — used by
        :class:`~core.self_improving_loop.run_transcript.RunTranscript`
        (the post-PR-CLEANUP-7 name for the per-run binding that was
        ``SessionJournal``) to write to
        ``<self-improving-loop-dir>/<session_id>/transcript.jsonl``
        while still using this Tier-1 schema.
        """
        record: dict[str, Any] = {
            "ts": ts if ts is not None else time.time(),
            "session_id": session_id or self._session_id,
            "gen_tag": gen_tag,
            "component": component,
            "level": level,
            "event": event,
            "payload": payload or {},
        }
        target_path = file_path if file_path is not None else self.file_path
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with target_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
                self._event_count += 1
            except OSError as exc:
                log.warning("Transcript lifecycle-event write failed: %s", exc)

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
