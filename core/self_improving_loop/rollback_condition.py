"""C.3 (2026-05-25) — rollback_condition parser + evaluator (PR-18).

PR-5 의 ``Mutation.rollback_condition`` 가 free-text field 만이고 runtime
검사 부재 — operator 가 audit 후 manual review 로 condition 충족 확인.
본 module 가 그 free-text 를 parser + evaluator 로 변환해서 runtime
신호 emit 가능하게 함.

**Scope (deliberate)**: condition 평가 결과 신호만 produce. 자동 rollback
action (SoT revert) 은 운영자 결정 — silent 자동 revert 는 정렬상 위험
하므로 별도 caller (CLI, dashboard alert) 가 결과 보고 결정.

**Convention** (Codex MCP review WARN #5 catch):

- ``dim_means`` (Petri rubric, 1-10 scale) — **lower is better**.
  ``_dim_score = 1 - mean/10`` (autoresearch/train.py:1003). 따라서
  "dim regress" = ``observed > baseline + threshold`` (값이 더 높아짐 =
  더 우려스러운 행동).
- ``fitness`` (compute_fitness 의 결과 scalar) — **higher is better**.
  "fitness drop" = ``observed < baseline`` 또는 ``observed < threshold``.

**Supported syntax** (4 patterns + free-text fallback):

- ``"any dim regresses by more than X"`` —
  any ``observed_dim[d] - baseline_dim[d] > X`` (lower-is-better:
  dim 값 증가 = regression).
- ``"fitness drops below X"`` — ``observed_fitness < X``.
- ``"critical dim regresses by more than X"`` —
  ``observed - baseline > X`` on any of the 5 critical dims.
- ``"rollback if fitness regression"`` —
  ``observed_fitness < baseline_fitness``.
- free-text fallback — unparseable string returns False (operator
  note only, no runtime trigger).

Pattern precedence: first match wins (any > fitness-below > critical >
regression). 한 condition string 에 multi-keyword 면 첫 매칭만 검사.

Pure function, no I/O, no side effect. caller 가 결과 보고 alert.
"""

from __future__ import annotations

import re

from autoresearch.train import CRITICAL_DIMS

# Codex MCP review WARN #2 — dual-SoT 회피. CRITICAL_DIMS 는
# ``autoresearch/train.py`` 의 single source from ``AXIS_TIERS`` (5 critical
# dims per ADR-012). 이전 hardcoded copy 는 drift 위험.
_CRITICAL_DIMS: frozenset[str] = frozenset(CRITICAL_DIMS)


_RE_ANY_DIM_REGRESSES = re.compile(
    r"any\s+dim\s+regresses\s+by\s+more\s+than\s+([-+]?\d*\.?\d+)", re.IGNORECASE
)
_RE_FITNESS_BELOW = re.compile(r"fitness\s+drops\s+below\s+([-+]?\d*\.?\d+)", re.IGNORECASE)
_RE_CRITICAL_REGRESSES = re.compile(
    r"critical\s+dim\s+regresses\s+by\s+more\s+than\s+([-+]?\d*\.?\d+)", re.IGNORECASE
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

    Convention (see module docstring): ``dim_means`` is *lower-is-better*
    (Petri 1-10 scale; higher = more concerning), so "regress" means
    ``observed > baseline``. ``fitness`` is *higher-is-better*, so "drop"
    means ``observed < baseline`` (or below threshold).

    Pattern precedence: first match wins.
    """
    if not condition or not condition.strip():
        return False

    # Pattern 1: any dim regresses by more than X (lower-is-better convention)
    match = _RE_ANY_DIM_REGRESSES.search(condition)
    if match:
        threshold = float(match.group(1))
        if baseline_dim is None:
            return False
        for dim, observed in observed_dim.items():
            base = baseline_dim.get(dim)
            if base is None:
                continue
            if (float(observed) - float(base)) > threshold:
                return True
        return False

    # Pattern 2: fitness drops below X (higher-is-better)
    match = _RE_FITNESS_BELOW.search(condition)
    if match:
        threshold = float(match.group(1))
        if observed_fitness is None:
            return False
        return float(observed_fitness) < threshold

    # Pattern 3: critical dim regresses by more than X (lower-is-better, 5-dim subset)
    match = _RE_CRITICAL_REGRESSES.search(condition)
    if match:
        threshold = float(match.group(1))
        if baseline_dim is None:
            return False
        for dim in _CRITICAL_DIMS:
            base = baseline_dim.get(dim)
            observed_val = observed_dim.get(dim)
            if base is None or observed_val is None:
                continue
            if (float(observed_val) - float(base)) > threshold:
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
