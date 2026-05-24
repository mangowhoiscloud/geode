"""DPO canonical pack JSONL writer — ADR-012 M4.1.

Consumes the ``eval_response_recorded`` RunTranscript event stream
(M4.0) and emits a canonical preference pack — one JSONL row per
``(prompt, chosen, rejected)`` tuple — that any downstream DPO trainer
(OpenAI fine-tuning, Bedrock DPO, HuggingFace TRL ``DPOTrainer``)
can consume directly. M4.2 will adapt this pack to per-provider
publisher formats; M4.1 is the format-agnostic substrate.

**Pairing rule** — for each unique ``prompt`` text seen across the
journal(s):

* Group emitted ``eval_response_recorded`` events by ``prompt``.
* Within the group, split into ``chosen`` pile (``rollback_flag = False``)
  and ``rejected`` pile (``rollback_flag = True``).
* If both piles are non-empty, pair the **highest-fitness chosen** with
  the **lowest-fitness rejected**. This gives the steepest
  ``fitness_delta`` signal per prompt — DPO learns best from clear
  margins. Other potential pairings (cross-product, random, top-K) are
  deferred to M4.3+.

**Idempotency** — each pair is hashed by ``(prompt, chosen_response,
rejected_response)`` → 16-hex signature. The writer skips any signature
already present in the pack file, so re-running the builder over an
expanded journal stream only appends new pairs.

**Pack location** — ``GLOBAL_DPO_PACK_PATH`` (``~/.geode/self-improving-loop/dpo/pack.jsonl``).
The parent directory is created lazily on first append. The pack is
NOT git-tracked — preference data can be sensitive and is operator-local
until an explicit publish step (M4.2) ships a redacted copy.

**Schema** (one row per emitted pair)::

    {
      "signature": "...16-hex...",
      "prompt": "...",
      "chosen": "...",
      "rejected": "...",
      "fitness_chosen": 0.91,
      "fitness_rejected": 0.32,
      "fitness_delta": 0.59,
      "ts_chosen": 1731957600.123,
      "ts_rejected": 1731957800.456,
      "session_id_chosen": "...",
      "session_id_rejected": "...",
      "source_chosen": "petri_audit",
      "source_rejected": "live_session"
    }
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.self_improving_loop.eval_journaling import EVENT_NAME

log = logging.getLogger(__name__)

__all__ = [
    "BuildResult",
    "build_dpo_pack",
    "pair_signature",
]


@dataclass(frozen=True, slots=True)
class _EvalEvent:
    """Parsed view of one ``eval_response_recorded`` JSONL row."""

    prompt: str
    response: str
    fitness_score: float
    rollback_flag: bool
    ts: float
    session_id: str
    source: str


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Outcome of a single :func:`build_dpo_pack` invocation.

    Counts are reported separately so M4.2/M4.3 can ratchet on
    *pairs_appended* (genuine new signal) vs *events_seen* (volume) vs
    *prompts_unpaired* (chosen-only or rejected-only piles that still
    need their counterpart).
    """

    pairs_appended: int
    pairs_skipped_duplicate: int
    events_seen: int
    prompts_unpaired: int


def pair_signature(prompt: str, chosen: str, rejected: str) -> str:
    """Deterministic 16-hex pair signature — idempotency key for the pack."""
    blob = f"{prompt}\x1f{chosen}\x1f{rejected}".encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _iter_eval_events(journal_path: Path) -> list[_EvalEvent]:
    """Read one ``transcript.jsonl`` file → list of ``eval_response_recorded`` rows.

    Lines that fail to parse, lack the canonical event name, or are
    missing required payload fields are silently skipped (the journal
    is intentionally lossy — a stray malformed line shouldn't kill the
    builder).
    """
    if not journal_path.is_file():
        return []
    out: list[_EvalEvent] = []
    try:
        text = journal_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("dpo_pack: failed to read journal %s: %s", journal_path, exc)
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        if row.get("event") != EVENT_NAME:
            continue
        payload = row.get("payload") or {}
        if not isinstance(payload, dict):
            continue
        prompt = payload.get("prompt")
        response = payload.get("response")
        fitness = payload.get("fitness_score")
        if not isinstance(prompt, str) or not isinstance(response, str):
            continue
        if not isinstance(fitness, (int, float, str)):
            continue
        try:
            fitness_f = float(fitness)
        except (TypeError, ValueError):
            continue
        ts_raw = row.get("ts", 0.0)
        if not isinstance(ts_raw, (int, float, str)):
            ts_raw = 0.0
        try:
            ts_f = float(ts_raw)
        except (TypeError, ValueError):
            ts_f = 0.0
        out.append(
            _EvalEvent(
                prompt=prompt,
                response=response,
                fitness_score=fitness_f,
                rollback_flag=bool(payload.get("rollback_flag", False)),
                ts=ts_f,
                session_id=str(row.get("session_id", "")),
                source=str(payload.get("source", "")),
            )
        )
    return out


def _existing_signatures(pack_path: Path) -> set[str]:
    """Collect signatures already present in the pack — idempotency guard."""
    if not pack_path.is_file():
        return set()
    sigs: set[str] = set()
    try:
        text = pack_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("dpo_pack: failed to read pack %s: %s", pack_path, exc)
        return sigs
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        sig = row.get("signature") if isinstance(row, dict) else None
        if isinstance(sig, str):
            sigs.add(sig)
    return sigs


def _select_pair(events: list[_EvalEvent]) -> tuple[_EvalEvent, _EvalEvent] | None:
    """Top-fitness chosen × bottom-fitness rejected — clearest margin."""
    chosen = [e for e in events if not e.rollback_flag]
    rejected = [e for e in events if e.rollback_flag]
    if not chosen or not rejected:
        return None
    best_chosen = max(chosen, key=lambda e: e.fitness_score)
    worst_rejected = min(rejected, key=lambda e: e.fitness_score)
    return best_chosen, worst_rejected


def build_dpo_pack(
    *,
    journal_paths: list[Path],
    pack_path: Path,
) -> BuildResult:
    """Walk ``journal_paths`` → group by prompt → append new pairs to ``pack_path``.

    Args:
        journal_paths: ``transcript.jsonl`` files to scan. Missing files are
            treated as empty (graceful).
        pack_path: Destination JSONL. Created lazily; existing rows are
            preserved + their signatures are honoured for dedup.

    Returns:
        :class:`BuildResult` with append / dedup / unpaired counts.
    """
    events: list[_EvalEvent] = []
    for jp in journal_paths:
        events.extend(_iter_eval_events(jp))
    events_seen = len(events)

    grouped: dict[str, list[_EvalEvent]] = {}
    for ev in events:
        grouped.setdefault(ev.prompt, []).append(ev)

    existing = _existing_signatures(pack_path)
    appended = 0
    skipped_dupe = 0
    unpaired = 0
    new_rows: list[dict[str, Any]] = []

    for prompt, group in grouped.items():
        pair = _select_pair(group)
        if pair is None:
            unpaired += 1
            continue
        chosen_ev, rejected_ev = pair
        sig = pair_signature(prompt, chosen_ev.response, rejected_ev.response)
        if sig in existing:
            skipped_dupe += 1
            continue
        new_rows.append(
            {
                "signature": sig,
                "prompt": prompt,
                "chosen": chosen_ev.response,
                "rejected": rejected_ev.response,
                "fitness_chosen": chosen_ev.fitness_score,
                "fitness_rejected": rejected_ev.fitness_score,
                "fitness_delta": chosen_ev.fitness_score - rejected_ev.fitness_score,
                "ts_chosen": chosen_ev.ts,
                "ts_rejected": rejected_ev.ts,
                "session_id_chosen": chosen_ev.session_id,
                "session_id_rejected": rejected_ev.session_id,
                "source_chosen": chosen_ev.source,
                "source_rejected": rejected_ev.source,
            }
        )
        existing.add(sig)
        appended += 1

    if new_rows:
        try:
            pack_path.parent.mkdir(parents=True, exist_ok=True)
            with pack_path.open("a", encoding="utf-8") as fh:
                for row in new_rows:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("dpo_pack: append to %s failed: %s", pack_path, exc)
            return BuildResult(
                pairs_appended=0,
                pairs_skipped_duplicate=skipped_dupe,
                events_seen=events_seen,
                prompts_unpaired=unpaired,
            )

    return BuildResult(
        pairs_appended=appended,
        pairs_skipped_duplicate=skipped_dupe,
        events_seen=events_seen,
        prompts_unpaired=unpaired,
    )
