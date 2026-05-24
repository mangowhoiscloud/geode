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

    PR-COMM-4 (2026-05-24) — every row now carries a per-instance
    monotonic ``seq`` field (starts at 1, increments by 1 per
    appended event) under :attr:`_event_count`. Concurrent same-
    instance callers are serialised by ``self._lock`` so seq order
    matches file write order. Multiple SessionTranscript instances
    (different processes / different in-process objects) writing to
    the *same* file each maintain their own counter, so cross-writer
    timelines must be re-sorted by ``(ts, seq)`` — a fundamental
    consequence of having no cross-process coordination on the seq
    counter, intentional to keep the hot path lock-free across
    process boundaries.

    ``last_touched_at()`` + ``is_stale(threshold_s)`` expose the file
    mtime so external watchdogs can detect hung runs that stopped
    appending events without firing PIPELINE_TIMEOUT / PIPELINE_ERROR.

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

        # PR-COMM-4 liveness:
        if tx.is_stale(threshold_s=300):
            log.warning("Transcript %s has been idle for 5+ minutes", tx.session_id)
    """

    def __init__(
        self,
        session_id: str,
        transcript_dir: Path | str | None = None,
    ) -> None:
        self._session_id = session_id
        # PR-Q (2026-05-24) — when an active run_dir is bound and the
        # caller didn't pass an explicit transcript_dir, route the
        # per-session jsonl into ``<run_dir>/sub_agents/<session_id>/``
        # and override the filename to ``dialogue.jsonl`` (vs the
        # legacy ``<session_id>.jsonl`` under the cwd-slug global).
        # Explicit ``transcript_dir=`` overrides this (orchestrator
        # paths like RunTranscript still control their own location).
        self._dialogue_filename_override: str | None = None
        if transcript_dir is not None:
            self._dir = Path(transcript_dir)
        else:
            from core.observability.run_dir import resolve_sub_agent_path

            consolidated_dialogue = resolve_sub_agent_path(session_id, "dialogue.jsonl")
            if consolidated_dialogue is not None:
                # ``resolve_sub_agent_path`` already mkdir'd the parent.
                self._dir = consolidated_dialogue.parent
                self._dialogue_filename_override = consolidated_dialogue.name
            else:
                self._dir = DEFAULT_TRANSCRIPT_DIR
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
        # PR-Q — when ``_dialogue_filename_override`` is set the
        # SessionTranscript was bound to a run_dir-anchored location and
        # writes ``<dir>/dialogue.jsonl`` instead of the legacy
        # ``<dir>/<session_id>.jsonl``. The override is only set by
        # ``__init__`` when ``transcript_dir`` was left empty AND
        # :func:`resolve_sub_agent_path` returned a binding.
        if self._dialogue_filename_override is not None:
            return self._dir / self._dialogue_filename_override
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
        truncated = _truncate(text, MAX_TEXT_CHARS)
        self._append({"event": "user_message", "text": truncated})
        self._mirror_to_run_transcript(
            action="agent.user_message",
            entity_type="task",
            entity_id=self._session_id,
            details={"text": truncated},
        )

    def record_assistant_message(self, text: str) -> None:
        truncated = _truncate(text, MAX_TEXT_CHARS)
        self._append({"event": "assistant_message", "text": truncated})
        self._mirror_to_run_transcript(
            action="agent.assistant_message",
            entity_type="task",
            entity_id=self._session_id,
            details={"text": truncated},
        )

    def record_tool_call(self, tool: str, tool_input: dict[str, Any]) -> None:
        input_str = json.dumps(tool_input, ensure_ascii=False, default=str)
        truncated_input = _truncate(input_str, MAX_INPUT_CHARS)
        self._append({"event": "tool_call", "tool": tool, "input": truncated_input})
        self._mirror_to_run_transcript(
            action="agent.tool_call",
            entity_type="task",
            entity_id=self._session_id,
            details={"tool": tool, "input": truncated_input},
        )

    def record_tool_result(self, tool: str, status: str, summary: str = "") -> None:
        truncated_summary = _truncate(summary, MAX_INPUT_CHARS)
        self._append(
            {
                "event": "tool_result",
                "tool": tool,
                "status": status,
                "summary": truncated_summary,
            }
        )
        self._mirror_to_run_transcript(
            action="agent.tool_result",
            entity_type="task",
            entity_id=self._session_id,
            details={"tool": tool, "status": status, "summary": truncated_summary},
        )

    def _mirror_to_run_transcript(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any],
    ) -> None:
        """Mirror this SessionTranscript event into the active RunTranscript
        as a paperclip-style activity_log row.

        PR-U (2026-05-24, F4 in docs/plans/2026-05-24-transcript-
        standardization-and-claude-resume.md). Pre-PR-U the pipeline
        transcript at ``<run_dir>/transcript.jsonl`` only carried
        orchestrator phase events (phase_started / phase_finished /
        cost_preview / preflight_passed); the per-sub-agent dialogue
        lived in a separate ``sub_agents/<task_id>/dialogue.jsonl`` with
        no inline reference in the pipeline timeline. Operators
        following ``tail -F transcript.jsonl`` saw 4 markers per cycle
        but no agent dialogue, even though that was the highest-value
        signal.

        This mirror lifts a truncated preview of every agent dialogue
        event up into the pipeline transcript with the
        ``actor_type="agent"`` + ``action="agent.<verb>"`` classification
        quintuple paperclip's activity_log uses, so the timeline is
        unified without duplicating the full body (which stays in
        dialogue.jsonl — paperclip-style activity_log ↔ issue_comments
        navigation). ``actor_id == entity_id == task_id == self._session_id``
        because PR-Q.5's single-anchor invariant (I1) collapsed the four
        identifiers (WorkerRequest.task_id / IsolationConfig.session_id
        / AgenticLoop.session_id / SessionTranscript._session_id) into
        one value.

        No-op when no active RunTranscript is bound — outside the
        seed-generation orchestrator (REPL / gateway / tests) the
        pipeline transcript SoT does not exist, so the mirror has
        nowhere to go.
        """
        from core.self_improving_loop.run_transcript import current_run_transcript

        run_transcript = current_run_transcript()
        if run_transcript is None:
            return
        # ``event`` field uses the verb portion of the dotted action so
        # legacy ``.event`` readers see a meaningful tag.
        verb = action.split(".", 1)[1] if "." in action else action
        run_transcript.append(
            verb,
            actor_type="agent",
            actor_id=self._session_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            task_id=self._session_id,
            payload=details,
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
        actor_type: str | None = None,
        actor_id: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        task_id: str | None = None,
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

        PR-U (2026-05-24, paperclip activity_log parity, F3 in
        docs/plans/2026-05-24-transcript-standardization-and-claude-resume.md):
        the optional ``actor_type`` / ``actor_id`` / ``action`` /
        ``entity_type`` / ``entity_id`` / ``task_id`` fields land in the
        row when supplied (orchestrator's explicit
        ``RunTranscript.append`` + SessionTranscript's mirror path
        both fill them). Omitted keys are simply absent from the row so
        legacy readers that only look at ``event`` / ``payload`` /
        ``session_id`` keep working.
        """
        # PR-COMM-4 (2026-05-24) — seq stamping + write held under a
        # single lock so concurrent same-instance callers can't
        # interleave (Codex MCP review catch: releasing the seq lock
        # before re-acquiring the write lock would let thread A stamp
        # seq=N+1 then thread B stamp seq=N+2 and write before A).
        # Per-instance counter; cross-process writers to the SAME file
        # still produce interleaved seqs that readers must re-sort by
        # ``(ts, seq)`` — documented at the class docstring.
        target_path = file_path if file_path is not None else self.file_path
        with self._lock:
            self._event_count += 1
            record: dict[str, Any] = {
                "ts": ts if ts is not None else time.time(),
                "seq": self._event_count,
                "session_id": session_id or self._session_id,
                "gen_tag": gen_tag,
                "component": component,
                "level": level,
                "event": event,
                "payload": payload or {},
            }
            # PR-U classification quintuple — only emit when caller
            # supplied them so legacy rows stay compact.
            for field_name, field_value in (
                ("actor_type", actor_type),
                ("actor_id", actor_id),
                ("action", action),
                ("entity_type", entity_type),
                ("entity_id", entity_id),
                ("task_id", task_id),
            ):
                if field_value is not None:
                    record[field_name] = field_value
            line = json.dumps(record, ensure_ascii=False)
            try:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with target_path.open("a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                log.warning("Transcript lifecycle-event write failed: %s", exc)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # PR-COMM-4 (2026-05-24) — liveness watchdog API
    # ------------------------------------------------------------------

    def last_touched_at(self) -> float | None:
        """Return the transcript file's mtime, or None if the file
        doesn't exist yet (no events appended in this run).

        External watchdogs (operator daemons, stuck-run detectors) use
        this to spot transcripts that have stopped receiving events —
        evidence that the run hung or crashed without firing
        ``PIPELINE_TIMEOUT`` / ``PIPELINE_ERROR``.
        """
        try:
            return self.file_path.stat().st_mtime
        except FileNotFoundError:
            return None
        except OSError as exc:
            log.debug("Transcript stat failed for %s: %s", self.file_path, exc)
            return None

    def is_stale(self, threshold_s: float, *, now: float | None = None) -> bool:
        """Return True if the transcript hasn't been touched in
        ``threshold_s`` seconds. False when the file doesn't exist
        (a never-started run isn't "stale" — it just hasn't begun).

        ``now`` is an injectable wall-clock for deterministic tests;
        defaults to ``time.time()``.
        """
        touched = self.last_touched_at()
        if touched is None:
            return False
        current = now if now is not None else time.time()
        return (current - touched) > threshold_s

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
        # PR-COMM-4 (2026-05-24) — seq stamping + write held under a
        # single lock so concurrent same-instance callers can't
        # interleave (Codex MCP review catch). Per-instance monotonic;
        # cross-process writers must re-sort by ``(ts, seq)`` —
        # documented at the class docstring.
        with self._lock:
            self._event_count += 1
            data["seq"] = self._event_count
            data["ts"] = time.time()
            line = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
            self._dir.mkdir(parents=True, exist_ok=True)
            fpath = self.file_path
            # Size guard
            if fpath.exists() and fpath.stat().st_size > MAX_FILE_BYTES:
                self._tail_truncate(fpath)
            try:
                with open(fpath, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
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
