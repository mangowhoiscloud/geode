"""Hypothesis space + prune logic.

본 module 의 책임:

1. 최근 audit archive 의 rationale 추출 (``rationale_extractor``)
2. fitness 의 dim 별 weakness ranking
3. mutation candidate 생성 (file_path + line_range + mutation_text)
4. Karpathy Simplicity Selection 적용 — small diff 우선
5. ``failure_log.jsonl`` 의 rejected hypothesis 회피

Spec: ``docs/architecture/autoresearch.md`` § 4 (Step 1).

Implementation: follow-up PR1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Hypothesis:
    """Single mutation hypothesis — the smallest unit of an autoresearch
    generation.

    Attributes:
        id: human-readable identifier (e.g. ``"H1-shell-safe-summarization"``)
        file_path: file to mutate (within ``program.md`` 의 allowlist)
        line_range: (start, end) — Karpathy Single-File Constraint 의 단위
        mutation_text: new content to replace the line range
        rationale_quote: explanation snippet from the latest audit's
            rationale that motivated this hypothesis
        expected_fitness_delta: rough prediction (+/- aggregate)
    """

    id: str
    file_path: Path
    line_range: tuple[int, int]
    mutation_text: str
    rationale_quote: str
    expected_fitness_delta: float


def generate_candidates(
    state_dir: Path,
    program_md: Path,
    *,
    n: int = 1,
) -> list[Hypothesis]:
    """Generate the next N hypothesis candidates.

    Input: ``state_dir`` (current generation, results.tsv, failure_log,
    latest audit archive path), ``program_md`` (allowlist + blocklist).

    Output: N-element list, ranked by predicted ``expected_fitness_delta``.
    """
    raise NotImplementedError("autoresearch/hypothesis.py:generate_candidates — follow-up PR1")
