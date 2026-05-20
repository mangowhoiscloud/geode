"""``ux_means`` fitness 축 — ADR-012 S1.

GEODE 의 self-improving loop 가 Petri 17-dim 의 음의 압력 (안 망가지기)
편향에 빠지는 risk 를 차단하기 위한 **양의 압력** fitness 축. RunLog +
LLMUsageAccumulator + git history + OTel trace 4 source 의 행동 metric 을
0-1 정규화 후 가중 합산.

**Schema** (4 field, 모두 0.0-1.0 normalized):

.. code-block:: python

    {
      "success_rate": 0.95,        # RunLog.success 누적률 (높을수록 좋음)
      "token_cost_norm": 0.30,     # 1 - clamp(token_cost/budget, 0, 1) (낮을수록 좋음 → invert)
      "revert_ratio_norm": 0.90,   # 1 - revert_ratio (낮을수록 좋음 → invert)
      "latency_norm": 0.80,        # 1 - clamp(latency/budget, 0, 1) (낮을수록 좋음 → invert)
    }

모든 필드는 정규화 후 **"높을수록 좋음"** 의미로 통일 (token_cost /
revert_ratio / latency 는 lower-is-better 이므로 invert). 가중치는
``UX_DIM_WEIGHTS`` 로 분배.

**ADR-012 §Decision.2 의 fitness 다축화**:

- ``dim_means`` (Petri 17-dim, 음의 압력) — 가중치 0.4
- ``ux_means`` (행동 4-field, 양의 압력) — 가중치 0.3 (이 모듈)
- ``admire_means`` (LLM-judge 체감, 양의 압력) — 가중치 0.3 (S2 신설 예정)

S1 은 schema + math + ``compute_fitness`` 호환만 신설. 실제 4 source
데이터 수집 wiring 은 S1b (별도 PR) — ``ux_means is None`` 일 때
``compute_fitness`` 는 기존 dim-only fitness 반환 (no-op).
"""

from __future__ import annotations

from typing import Any

# UX field 별 가중치 — 합 1.0. 운영하면서 TOML 으로 조정 가능.
# success_rate 가 가장 강한 신호 (task 완수 여부), token_cost 가 그 다음
# (구독 quota 압력), revert_ratio + latency 는 secondary.
UX_DIM_WEIGHTS: dict[str, float] = {
    "success_rate": 0.40,
    "token_cost_norm": 0.30,
    "revert_ratio_norm": 0.20,
    "latency_norm": 0.10,
}

assert abs(sum(UX_DIM_WEIGHTS.values()) - 1.0) < 1e-9, "UX_DIM_WEIGHTS must sum to 1.0"


def normalize_ux_field(value: float, *, budget: float, invert: bool) -> float:
    """Normalize ``value`` to 0-1 with optional invert.

    - ``invert=False`` (e.g. success_rate already 0-1): clamp(value, 0, 1)
    - ``invert=True`` (e.g. token_cost in USD, latency in seconds —
      lower-is-better): return ``1 - clamp(value/budget, 0, 1)``

    ``budget=0`` 가 invert=True 와 함께 들어오면 ``value=0`` 만 양호 신호
    (1.0), 그 외 0.0 (degenerate).
    """
    if not invert:
        return max(0.0, min(1.0, value))
    if budget <= 0:
        return 1.0 if value <= 0 else 0.0
    ratio = max(0.0, min(1.0, value / budget))
    return 1.0 - ratio


def compute_ux_aggregate(ux_means: dict[str, float] | None) -> float:
    """4-field weighted sum → 0-1 scalar. ``None`` → 0.5 (neutral)."""
    if ux_means is None:
        return 0.5  # neutral — fitness 가중치 0.3 × 0.5 = 0.15 기본 기여
    total = 0.0
    for field, weight in UX_DIM_WEIGHTS.items():
        value = ux_means.get(field, 0.5)  # 누락 필드 도 neutral
        total += weight * max(0.0, min(1.0, value))
    return total


def collect_ux_means_from_sources(*, _placeholder: bool = True) -> dict[str, float] | None:
    """Collect ``ux_means`` from RunLog + LLMUsageAccumulator + git + OTel.

    S1 (이 PR) 은 schema + math 만 신설. 4 source 의 실제 wiring 은 S1b
    (별도 PR) 로 분리 — 각 source 의 reader 구현이 독립적으로 ROI 명확.

    이 함수는 placeholder — S1b 전까지는 ``None`` 반환 (compute_fitness
    가 dim-only fallback 으로 작동). S1b 머지 후 4 source 로부터 데이터
    수집 후 normalize 해서 반환.

    Args:
        _placeholder: S1b 전까지 ``None`` 반환 강제. test 에서 override 가능.
    """
    if _placeholder:
        return None
    # S1b 에서 wiring:
    # - RunLog.success_rate (core/orchestration/run_log.py)
    # - LLMUsageAccumulator.token_cost (core/llm/token_tracker.py)
    # - git revert_ratio (subprocess + git log)
    # - OTel trace latency (있다면)
    return None  # pragma: no cover — S1b wiring placeholder


def validate_ux_schema(ux_means: Any) -> bool:
    """Validate ``ux_means`` schema — dict[str, float], 알려진 field 만,
    모두 0.0-1.0 범위. ``None`` 도 valid (no-op signal)."""
    if ux_means is None:
        return True
    if not isinstance(ux_means, dict):
        return False
    known_fields = set(UX_DIM_WEIGHTS)
    for key, value in ux_means.items():
        if key not in known_fields:
            return False
        if not isinstance(value, int | float):
            return False
        if not (0.0 <= float(value) <= 1.0):
            return False
    return True


__all__ = [
    "UX_DIM_WEIGHTS",
    "collect_ux_means_from_sources",
    "compute_ux_aggregate",
    "normalize_ux_field",
    "validate_ux_schema",
]
