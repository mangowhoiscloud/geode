"""Promote/reject ratchet + git ops.

본 module 의 책임:

1. ``apply(hypothesis)`` — mutation 적용 + pre-mutation git stash + quality gate
2. ``verdict(fitness_new, fitness_baseline)`` — promote/reject 결정
3. ``commit_or_reset(verdict, ...)`` — git ops (promote = commit / reject = reset --hard)
4. ``failure_log.jsonl`` append on reject

Promote 조건 (``program.md`` override 가능):
- ``fitness_new.aggregate > fitness_baseline.aggregate + stderr_aggregate``
- 5 axis 어느 것도 ``baseline - stderr`` 위로 회귀 X
- audit 의 sample 수 >= minimum (default 10)

Spec: ``docs/architecture/autoresearch.md`` § 4 (Step 2 + Step 5 + Step 6).

Implementation: follow-up PR1.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from autoresearch.fitness import Fitness
from autoresearch.hypothesis import Hypothesis


class Verdict(StrEnum):
    """Outcome of the generation cycle."""

    PROMOTE = "promote"
    REJECT = "reject"
    ABORT = "abort"  # audit fail / content filter / quality gate fail


@dataclass(frozen=True)
class VerdictRecord:
    """Full verdict + provenance for ``results.tsv``."""

    verdict: Verdict
    fitness_new: Fitness
    fitness_baseline: Fitness
    hypothesis: Hypothesis
    git_sha: str | None  # promote 시 commit sha, reject 시 None
    failure_reason: str | None  # ABORT 시 detail


def apply(hypothesis: Hypothesis) -> None:
    """Apply mutation + pre-mutation stash + quality gate.

    On quality gate fail (ruff format / check / mypy), raises and the
    caller should call ``commit_or_reset(ABORT, ...)``.
    """
    raise NotImplementedError("autoresearch/ratchet.py:apply — follow-up PR1")


def verdict(fitness_new: Fitness, fitness_baseline: Fitness) -> Verdict:
    """Decide promote/reject from fitness comparison."""
    raise NotImplementedError("autoresearch/ratchet.py:verdict — follow-up PR1")


def commit_or_reset(record: VerdictRecord) -> None:
    """Execute the git ops + baseline_marker + failure_log side effects.

    - PROMOTE: ``git commit`` + ``baseline_marker.mark(...)``
    - REJECT: ``git reset --hard HEAD`` + ``failure_log.jsonl.append(...)``
    - ABORT: ``git reset --hard HEAD`` + ``failure_log`` 에 reason 명시
    """
    raise NotImplementedError("autoresearch/ratchet.py:commit_or_reset — follow-up PR1")
