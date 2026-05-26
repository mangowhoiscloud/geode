"""C.4 (2026-05-25) — credit assignment 사전 매핑 (PR-16).

PR-5 의 ``attribution.py`` 가 사후 (post-audit) ``observed_dim - expected_dim``
delta 를 계산하지만, group sampling 시 **사전적으로** "이 mutation 의
group_advantage 가 어느 dim 에 attributable 한가?" 는 추적 불가.

본 module 의 두 함수:

- :func:`compute_credit_assignment` — single ``Mutation`` + ``group_advantage``
  scalar 를 받아 ``expected_dim`` magnitude-weighted partition 으로 dim 별
  signed credit 분배.
- :func:`aggregate_credit_history` — mutations.jsonl 의 ``ApplyRecord`` list
  (PR-12 ``read_recent_applies`` 결과) 를 받아 history 전체의 dim 별
  cumulative credit aggregate.

이는 **selection-layer observability** — weight 학습 X, mutator API frozen
유지. 후속 caller (CLI 또는 operator dashboard) 가 결과를 visualise.

Frontier reference: Quality-Diversity (Mouret & Clune 2015) 의
behavior-characterization mapping + GRPO-inspired group-relative
advantage decomposition (formula only; no policy update).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.self_improving_loop.runner import ApplyRecord, Mutation


def compute_credit_assignment(
    mutation: Mutation,
    group_advantage: float | None,
) -> dict[str, float]:
    """Partition ``group_advantage`` across ``mutation.expected_dim`` keys
    by magnitude-weighted share.

    Formula::

        total_abs = sum(|expected_dim[d]| for d in dims)
        credit[d] = group_advantage * (|expected_dim[d]| / total_abs)

    The credit is unsigned in magnitude (positive advantage → positive
    credit per dim) since the operator's *intent* on a dim is encoded
    in the ``expected_dim`` sign, not the partition. A caller that
    needs the *direction* multiplied by intent uses
    ``credit[d] * sign(expected_dim[d])``.

    Returns empty dict when:
    - ``group_advantage is None`` (legacy non-group mode)
    - ``mutation.expected_dim`` is empty (mutator didn't commit dims)
    - ``sum(|expected_dim|)`` is 0 (degenerate)
    """
    if group_advantage is None:
        return {}
    if not mutation.expected_dim:
        return {}
    total_abs = sum(abs(float(v)) for v in mutation.expected_dim.values())
    if total_abs == 0.0:
        return {}
    return {
        dim: group_advantage * (abs(float(weight)) / total_abs)
        for dim, weight in mutation.expected_dim.items()
    }


def aggregate_credit_history(
    records: Iterable[ApplyRecord],
) -> dict[str, float]:
    """Aggregate signed credit across an iterable of ``ApplyRecord`` rows.

    Each record contributes its mutation's per-dim credit (computed from
    its ``expected_dim`` + ``group_advantage``). Records with no
    ``group_advantage`` or empty ``expected_dim`` are skipped silently.

    Returns ``{dim_name: cumulative_credit}`` — operator dashboard can
    rank dims by total credit to see which dims the mutator has been
    investing in.
    """
    out: dict[str, float] = defaultdict(float)
    for record in records:
        advantage = getattr(record, "group_advantage", None)
        expected = getattr(record, "expected_dim", None)
        if advantage is None or not expected:
            continue
        total_abs = sum(abs(float(v)) for v in expected.values())
        if total_abs == 0.0:
            continue
        for dim, weight in expected.items():
            out[dim] += float(advantage) * (abs(float(weight)) / total_abs)
    return dict(out)


__all__ = [
    "aggregate_credit_history",
    "compute_credit_assignment",
]
