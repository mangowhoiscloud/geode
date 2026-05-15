"""Baseline marker — generation N metadata for ``~/.geode/petri/logs/``.

본 module 의 책임:

1. ``mark(archive, generation_id, hypothesis_id, fitness, parent_baseline)``
   → ``<archive-basename>.meta.json`` 생성
2. ``find_latest_baseline()`` — latest promote 의 archive (다음 generation 의 baseline)
3. ``list_generations()`` — promote 누적 history
4. ``prune(retention_policy)`` — long-term / standard / experimental marker 별 retention 실행

Marker schema (``<archive>.meta.json``):

```json
{
  "archive": "2026-05-15T02-44-20-00-00_audit_bDdJWCD6Fyta.eval",
  "generation_id": 0,
  "hypothesis_id": "orchestration-gap-fix-H1-H2",
  "fitness": {
    "predictive": 0.91, "robustness": 0.27, "logic": 0.90,
    "diversity": 0.90, "stability": 3.13, "aggregate": 0.96
  },
  "verdict": "promote",
  "parent_baseline": null,
  "git_sha": "a3f2ac6a",
  "pr_url": "https://github.com/mangowhoiscloud/geode/pull/1135",
  "promote_timestamp": "2026-05-15T11:28:34+09:00",
  "retention": "long-term"
}
```

Retention policy:

- ``retention: long-term`` → 영구 keep (promote 의 default)
- ``retention: standard`` → 90 일 keep, 경과 시 prune
- ``retention: experimental`` → 30 일 keep (reject 의 default)
- marker 없는 archive (legacy) → 90 일 default

Spec: ``docs/architecture/autoresearch.md`` § 6 (Baseline marker spec).

Implementation: follow-up PR2.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from autoresearch.fitness import Fitness


@dataclass(frozen=True)
class Marker:
    """Parsed ``.meta.json`` companion of a ``~/.geode/petri/logs/*.eval``."""

    archive: Path
    generation_id: int
    hypothesis_id: str
    fitness: Fitness
    verdict: str  # "promote" | "reject" | "abort"
    parent_baseline: Path | None
    git_sha: str | None
    pr_url: str | None
    promote_timestamp: str
    retention: str  # "long-term" | "standard" | "experimental"


def mark(
    archive_path: Path,
    *,
    generation_id: int,
    hypothesis_id: str,
    fitness: Fitness,
    parent_baseline: Path | None = None,
    verdict: str = "promote",
    git_sha: str | None = None,
    pr_url: str | None = None,
    retention: str = "long-term",
) -> Path:
    """Write ``<archive-basename>.meta.json`` and return its path."""
    raise NotImplementedError("autoresearch/baseline_marker.py:mark — follow-up PR2")


def find_latest_baseline() -> Path | None:
    """Return the archive path of the latest ``verdict=promote`` marker.

    None when no promote marker exists (cycle not started or all rejected).
    """
    raise NotImplementedError(
        "autoresearch/baseline_marker.py:find_latest_baseline — follow-up PR2"
    )


def list_generations() -> list[Marker]:
    """Return all markers in ``~/.geode/petri/logs/`` sorted by generation_id."""
    raise NotImplementedError("autoresearch/baseline_marker.py:list_generations — follow-up PR2")


def prune(retention_policy: str = "default") -> int:
    """Remove archives whose retention has expired.

    Returns the number of pruned archives.
    """
    raise NotImplementedError("autoresearch/baseline_marker.py:prune — follow-up PR2")
