"""EpisodicStore — append-only action-outcome ledger.

PR-4 C-3 of the cognitive-loop-uplift sprint
(``docs/plans/2026-05-21-cognitive-loop-uplift.md``).

Pre-PR-4 ``core.memory`` carried four memory types (user / project /
feedback / reference) but had no place to record *action → outcome*
triples. PR-5 (causal attribution) needs that signal to compute
"tool X succeeded in situation Y at rate Z" deltas; PR-3's
reflection node already populates ``CognitiveState.hypotheses`` /
``confidence`` but never persisted them anywhere cross-session.

This module persists one row per tool execution to
``~/.geode/memory/episodes.jsonl``:

  - timestamp_ns       (int)
  - session_id         (str)
  - round              (int, 0-based)
  - tool_name          (str)
  - tool_input_head    (str <= 200 chars — head of the input dict)
  - success            (bool)
  - error              (str | None, <= 200 chars)
  - duration_ms        (float)
  - cognitive_state    (dict — full snapshot, see CognitiveState.to_snapshot)

The file is rolling-capped at ``EPISODE_LOG_MAX_ROWS`` (default
1000) — when an append crosses the threshold the oldest rows are
dropped via an atomic write-and-rename so concurrent readers always
see a consistent file.

Retrieval API:
  - :meth:`EpisodicStore.recent` — most-recent N rows, optionally
    filtered by ``tool_name`` and/or ``session_id``.

PR-5 will add cosine-embedding-based retrieval on top of this base
layer (Voyager ``SkillLibrary`` pattern); PR-4 stops at the file +
recency filter so the foundation is committed before the embedding
dependency lands.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.paths import GLOBAL_EPISODES_LOG, GLOBAL_MEMORY_DIR

log = logging.getLogger(__name__)

EPISODE_LOG_MAX_ROWS = 1000


@dataclass
class Episode:
    """One row in the episodic ledger."""

    timestamp_ns: int
    session_id: str
    round: int
    tool_name: str
    tool_input_head: str
    success: bool
    error: str | None
    duration_ms: float
    cognitive_state: dict[str, Any] = field(default_factory=dict)

    def to_jsonl(self) -> str:
        """Serialize to a single JSONL line (no trailing newline)."""
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


def _summarise_tool_input(tool_input: dict[str, Any] | str | None, cap: int = 200) -> str:
    """Best-effort short string for the ``tool_input_head`` field.

    Dicts are dumped to JSON; strings pass through; None becomes
    ``""``. Output is trimmed to ``cap`` chars + ellipsis.
    """
    if tool_input is None:
        return ""
    if isinstance(tool_input, str):
        text = tool_input
    else:
        try:
            text = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            text = str(tool_input)
    text = text.replace("\n", " ").strip()
    if len(text) > cap:
        return text[:cap] + "…"
    return text


class EpisodicStore:
    """File-backed rolling-cap episodic ledger.

    The store is a thin wrapper around ``GLOBAL_EPISODES_LOG`` — every
    append writes one JSONL row; periodically (when the row count
    crosses ``max_rows + max_rows // 4``) the file is rewritten with
    only the most recent ``max_rows`` rows so the on-disk size stays
    bounded.

    The 25% overshoot tolerance is intentional — rewriting on every
    append would be wasteful. Worst case the file holds
    ``max_rows * 1.25`` rows for a moment.
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        max_rows: int = EPISODE_LOG_MAX_ROWS,
    ) -> None:
        self._path = path if path is not None else GLOBAL_EPISODES_LOG
        self._max_rows = max_rows
        # File access is serialised with a lock — multiple AgenticLoop
        # instances in the same process (sub-agents) can record
        # concurrently. Cross-process locking is not done here; the
        # final consumer is PR-5 which only reads.
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def append(self, episode: Episode) -> None:
        """Append ``episode`` to the log; rotate on overshoot."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(episode.to_jsonl())
                fh.write("\n")
            self._maybe_rotate()

    def _maybe_rotate(self) -> None:
        """Rewrite the log keeping only the last ``max_rows`` rows if
        the row count crosses the 25% overshoot threshold."""
        threshold = self._max_rows + self._max_rows // 4
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                rows = fh.readlines()
        except FileNotFoundError:
            return
        if len(rows) <= threshold:
            return
        keep = rows[-self._max_rows :]
        # Atomic rewrite — temp file + rename so a concurrent reader
        # never sees a partial file.
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text("".join(keep), encoding="utf-8")
        tmp.replace(self._path)

    def recent(
        self,
        *,
        tool_name: str | None = None,
        session_id: str | None = None,
        limit: int = 10,
    ) -> list[Episode]:
        """Return the most-recent ``limit`` episodes matching the
        optional ``tool_name`` and/or ``session_id`` filters.

        Returned list is ordered newest-first.

        Malformed rows (legacy schema, partial write) are skipped with
        a WARN — never raise. The retrieval API is read-side defensive
        because PR-5 will run it during every audit cycle.
        """
        try:
            with self._path.open("r", encoding="utf-8") as fh:
                rows = fh.readlines()
        except FileNotFoundError:
            return []
        matches: list[Episode] = []
        for raw in reversed(rows):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                log.warning("episodic log row not valid JSON; skipping. raw=%r", line[:120])
                continue
            if tool_name is not None and payload.get("tool_name") != tool_name:
                continue
            if session_id is not None and payload.get("session_id") != session_id:
                continue
            try:
                matches.append(Episode(**payload))
            except TypeError:
                log.warning(
                    "episodic log row missing fields; skipping. payload=%r",
                    {k: type(v).__name__ for k, v in payload.items()},
                )
                continue
            if len(matches) >= limit:
                break
        return matches


# ---------------------------------------------------------------------------
# Process-global singleton — bootstrap registers a TOOL_EXEC_ENDED hook
# handler that calls ``record_episode``; PR-5 readers consult the same
# instance via :func:`get_episodic_store`.
# ---------------------------------------------------------------------------

_singleton: EpisodicStore | None = None
_singleton_lock = threading.Lock()


def get_episodic_store() -> EpisodicStore:
    """Return the process-wide episodic store singleton.

    The store is lazily created on first call to keep cold-start free
    of the memory-dir mkdir. Tests can substitute a different store
    via :func:`set_episodic_store`.
    """
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = EpisodicStore()
    return _singleton


def set_episodic_store(store: EpisodicStore | None) -> None:
    """Replace the singleton (test seam). Pass ``None`` to reset."""
    global _singleton
    with _singleton_lock:
        _singleton = store


__all__ = [
    "EPISODE_LOG_MAX_ROWS",
    "GLOBAL_EPISODES_LOG",
    "GLOBAL_MEMORY_DIR",
    "Episode",
    "EpisodicStore",
    "get_episodic_store",
    "set_episodic_store",
]
