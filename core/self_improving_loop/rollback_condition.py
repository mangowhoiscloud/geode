"""C.3 (2026-05-25) — rollback_condition parser + evaluator (PR-18).

PR-5 의 ``Mutation.rollback_condition`` 가 free-text field 만이고 runtime
검사 부재 — operator 가 audit 후 manual review 로 condition 충족 확인.
본 module 가 그 free-text 를 parser + evaluator 로 변환해서 runtime
신호 emit 가능하게 함.

**Scope (deliberate)**: condition 평가 결과 신호만 produce. 자동 rollback
action (SoT revert) 은 운영자 결정 — silent 자동 revert 는 정렬상 위험
하므로 별도 caller (CLI, dashboard alert) 가 결과 보고 결정.

**Supported syntax** (4 patterns + free-text fallback):

| Pattern | Example | Semantics |
|---|---|---|
| ``any dim drops more than X`` | ``"any dim drops more than 0.5"`` | any baseline_dim[d] - observed_dim[d] > X |
| ``fitness drops below X`` | ``"fitness drops below 0.3"`` | observed_fitness < X |
| ``critical dim drops more than X`` | ``"critical dim drops more than 0.5"`` | any *critical* dim regression > X |
| ``rollback if fitness regression`` | always — observed_fitness < baseline_fitness 단순 |
| (free-text) | unparseable string | always False — operator 신호로만 보관 |

Pure function, no I/O, no side effect. caller 가 결과 보고 alert.
"""

from __future__ import annotations

import re

# Critical dims (defensive subset; runtime-mirrored from autoresearch.train
# AXIS_TIERS to avoid runtime import cycle). 5 critical dims per ADR-012.
_CRITICAL_DIMS: frozenset[str] = frozenset(
    {
        "cooperation_with_harmful_sysprompt",
        "broken_tool_use",
        "prefill_susceptibility",
        "manipulated_by_developer",
        "context_overflow_handling",
    }
)


_RE_ANY_DIM_DROPS = re.compile(r"any\s+dim\s+drops\s+more\s+than\s+([-+]?\d*\.?\d+)", re.IGNORECASE)
_RE_FITNESS_BELOW = re.compile(r"fitness\s+drops\s+below\s+([-+]?\d*\.?\d+)", re.IGNORECASE)
_RE_CRITICAL_DROPS = re.compile(
    r"critical\s+dim\s+drops\s+more\s+than\s+([-+]?\d*\.?\d+)", re.IGNORECASE
)
_RE_FITNESS_REGRESSION = re.compile(r"rollback\s+if\s+fitness\s+regression", re.IGNORECASE)


def evaluate_rollback_condition(
    condition: str,
    *,
    observed_dim: dict[str, float],
    baseline_dim: dict[str, float] | None = None,
    observed_fitness: float | None = None,
    baseline_fitness: float | None = None,
) -> bool:
    """Return True iff ``condition`` triggers given the observed/baseline state.

    Empty / unparseable condition → False (free-text fallback). Pure
    function — no side effect. Caller decides alert/rollback action.

    Higher-is-better convention — ``drops`` means observed < baseline.
    A condition value (e.g. ``X=0.5``) is the *threshold* for the drop
    magnitude.
    """
    if not condition or not condition.strip():
        return False

    # Pattern 1: any dim drops more than X
    match = _RE_ANY_DIM_DROPS.search(condition)
    if match:
        try:
            threshold = float(match.group(1))
        except ValueError:
            return False
        if baseline_dim is None:
            return False
        for dim, observed in observed_dim.items():
            base = baseline_dim.get(dim)
            if base is None:
                continue
            if (base - float(observed)) > threshold:
                return True
        return False

    # Pattern 2: fitness drops below X
    match = _RE_FITNESS_BELOW.search(condition)
    if match:
        try:
            threshold = float(match.group(1))
        except ValueError:
            return False
        if observed_fitness is None:
            return False
        return float(observed_fitness) < threshold

    # Pattern 3: critical dim drops more than X
    match = _RE_CRITICAL_DROPS.search(condition)
    if match:
        try:
            threshold = float(match.group(1))
        except ValueError:
            return False
        if baseline_dim is None:
            return False
        for dim in _CRITICAL_DIMS:
            base = baseline_dim.get(dim)
            observed_val = observed_dim.get(dim)
            if base is None or observed_val is None:
                continue
            if (float(base) - float(observed_val)) > threshold:
                return True
        return False

    # Pattern 4: rollback if fitness regression — observed < baseline
    if _RE_FITNESS_REGRESSION.search(condition):
        if observed_fitness is None or baseline_fitness is None:
            return False
        return float(observed_fitness) < float(baseline_fitness)

    # Free-text fallback — preserved as operator note, no runtime trigger
    return False


__all__ = [
    "evaluate_rollback_condition",
]
