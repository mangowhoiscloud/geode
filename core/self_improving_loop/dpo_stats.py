"""DPO pack stats — ADR-012 M4.3 companion to :mod:`dpo_redaction`.

Operator-side inspection helper: given a canonical pack JSONL (M4.1),
return aggregate counts + per-axis distribution. Used both for
day-to-day "what's in my pack?" CLI inspection (``geode dpo stats``
will land in a later wire-up PR) and as the data source for M4.3's CI
ratchet, which fails the build if a pack regresses on fundamental
shape (zero pairs, all-zero fitness deltas, etc.).

Stats keys (all optional — missing if the pack has zero parsable rows):

* ``pair_count`` — total rows successfully parsed.
* ``unique_prompts`` — distinct ``prompt`` values seen (catches the
  degenerate "single prompt repeated" pack).
* ``fitness_delta_min`` / ``_max`` / ``_mean`` / ``_median`` —
  ``fitness_chosen − fitness_rejected`` distribution. The mean is a
  rough proxy for "how steep is the average DPO margin?"; small means
  often signal that the chosen/rejected piles are noisy and the pack
  isn't yet worth fine-tuning on.
* ``source_chosen_histogram`` / ``source_rejected_histogram`` — how
  many rows came from each ``source_*`` tag (e.g. ``petri_audit`` vs
  ``live_session``). Distribution skew hints at sampling bias.
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

__all__ = ["pack_stats"]


def pack_stats(pack_path: Path) -> dict[str, Any]:
    """Aggregate stats over the canonical pack file at ``pack_path``.

    Returns an empty dict when the file is missing or has zero parsable
    rows. Malformed lines are silently dropped (consistent with the rest
    of the M4 pipeline).
    """
    if not pack_path.is_file():
        return {}
    try:
        text = pack_path.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("dpo_stats: failed to read pack %s: %s", pack_path, exc)
        return {}
    deltas: list[float] = []
    prompts: set[str] = set()
    chosen_sources: Counter[str] = Counter()
    rejected_sources: Counter[str] = Counter()
    row_count = 0
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
        prompt = row.get("prompt")
        delta = row.get("fitness_delta")
        if not isinstance(prompt, str) or not isinstance(delta, (int, float)):
            continue
        row_count += 1
        prompts.add(prompt)
        deltas.append(float(delta))
        chosen_sources[str(row.get("source_chosen", ""))] += 1
        rejected_sources[str(row.get("source_rejected", ""))] += 1
    if row_count == 0:
        return {}
    return {
        "pair_count": row_count,
        "unique_prompts": len(prompts),
        "fitness_delta_min": min(deltas),
        "fitness_delta_max": max(deltas),
        "fitness_delta_mean": statistics.fmean(deltas),
        "fitness_delta_median": statistics.median(deltas),
        "source_chosen_histogram": dict(chosen_sources),
        "source_rejected_histogram": dict(rejected_sources),
    }
