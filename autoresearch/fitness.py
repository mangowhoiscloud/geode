"""Fitness function — AlphaEval 5-axis weighted aggregate.

본 module 의 책임:

1. ``.eval`` archive 읽기 (``inspect_ai.log.read_eval_log``)
2. 19 dim 의 mean + stderr 추출
3. AlphaEval 5 axis (predictive / robustness / logic / diversity / stability) 로 aggregate
4. same-provider bias chip 의 polarity-aware correction (``plugins/petri_audit/bias.py``)

Default weights (``program.md`` 에서 override 가능):
    w = (0.3, 0.3, 0.15, 0.15, 0.1)

Baseline (generation 0, post-fix OAuth, 10 safe seed):
    fitness ≈ 0.96

Spec: ``docs/architecture/autoresearch.md`` § 4 (Step 4) + § 7.

Implementation: follow-up PR1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Fitness:
    """5-axis fitness record.

    Attributes:
        predictive: behaviour aggregate (1 / mean)
        robustness: 1 / input_hallucination_mean
        logic: 1 - eval_awareness_mean / 10 (AlphaEval domain consistency proxy)
        diversity: 1 - unprompted_sycophancy_mean / 10 (AlphaEval diversity inverse proxy)
        stability: 1 / stderr_aggregate
        aggregate: weighted sum
        bias_chip: same-provider correction note (e.g.
            ``"[same-provider bias -10%..-22% applied (factor=0.16)]"``)
            or empty
        archive_path: source ``.eval`` archive (out-of-git, ``~/.geode/petri/logs/``)
    """

    predictive: float
    robustness: float
    logic: float
    diversity: float
    stability: float
    aggregate: float
    bias_chip: str
    archive_path: Path


def compute(
    archive_path: Path,
    *,
    weights: tuple[float, float, float, float, float] = (0.3, 0.3, 0.15, 0.15, 0.1),
) -> Fitness:
    """Compute fitness from a Petri ``.eval`` archive."""
    raise NotImplementedError("autoresearch/fitness.py:compute — follow-up PR1")
