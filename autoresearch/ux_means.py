"""``ux_means`` fitness 축 — ADR-012 S1 + PR-AR-L4a S1b wiring.

GEODE 의 self-improving loop 가 Petri 17-dim 의 음의 압력 (안 망가지기)
편향에 빠지는 risk 를 차단하기 위한 **양의 압력** fitness 축. PR-AR-L4a
(2026-05-26) 부터 단일 SoT (``autoresearch/state/mutations.jsonl``) 의
``ApplyRecord`` + ``AttributionRecord`` rows 에서 4 행동 metric 을 계산,
0-1 정규화 후 가중 합산.

**Schema** (4 field, 모두 0.0-1.0 normalized):

.. code-block:: python

    {
      "success_rate":      0.66,   # count(attribution_score > 0) / count(attrib rows)
      "token_cost_norm":   0.99,   # 1 - clamp(mutator_token_cost / budget, 0, 1)
      "revert_ratio_norm": 0.66,   # 1 - count(fitness_delta < 0) / count(rows w/ delta)
      "latency_norm":      0.95,   # 1 - clamp(mean(cost_elapsed_seconds) / budget, 0, 1)
    }

모든 필드는 정규화 후 **"높을수록 좋음"** 의미로 통일 (token_cost /
revert_ratio / latency 는 lower-is-better 이므로 invert). 가중치는
``UX_DIM_WEIGHTS`` 로 분배.

**Scope (PR-AR-L4a)**: token_cost / latency 둘 다 *mutator LLM propose*
한정 — ``ApplyRecord.cost_*`` 필드 만 측정 대상. Downstream Petri
auditor/target/judge spend 는 별 source (audit subprocess 의 separate
cost ledger) — 본 ux_means 에 포함 안 됨.

**ADR-012 §Decision.2 의 fitness 다축화**:

- ``dim_means`` (Petri 17-dim, 음의 압력) — 가중치 0.4
- ``ux_means`` (행동 4-field, 양의 압력) — 가중치 0.3 (이 모듈)
- ``admire_means`` (LLM-judge 체감, 양의 압력) — 가중치 0.3 (S2 신설 예정)

S1 은 schema + math + ``compute_fitness`` 호환만 신설. 실제 4 source
데이터 수집 wiring 은 S1b (별도 PR) — ``ux_means is None`` 일 때
``compute_fitness`` 는 기존 dim-only fitness 반환 (no-op).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# PR-AR-L4a (2026-05-26) — Default budget for the latency normalizer.
# Measures mean ``ApplyRecord.cost_elapsed_seconds`` (mutator propose
# call wall-clock). 1800s = 30min hard ceiling per *mutation* — well
# above the typical ~30-60s mutator call. Operator can tune via
# ``[self_improving_loop.autoresearch] ux_latency_budget_s``.
DEFAULT_UX_LATENCY_BUDGET_S: float = 1800.0

# Default budget for the token-cost normalizer. **Scope** — cumulative
# *mutator* LLM cost (USD) across recent ``ApplyRecord`` rows; does NOT
# include downstream Petri auditor/target/judge spend (those run in
# the audit subprocess and have a separate cost ledger).
#
# Sizing: 5 USD covers ~50-100 mutator proposals at claude-opus-4-7
# (~$0.05-0.10 per propose call). Aggressive — operator-tunable via
# ``[self_improving_loop.autoresearch] ux_token_budget_usd``.
# For window-restricted callers (e.g. last 10 cycles), drop the budget
# proportionally so the normalizer keeps a meaningful gradient.
DEFAULT_UX_TOKEN_BUDGET_USD: float = 5.0

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


def _mutations_log_path() -> Path:
    """Lazy import to dodge ``runner.py`` circular at module load."""
    from core.self_improving_loop.runner import MUTATION_AUDIT_LOG_PATH

    return MUTATION_AUDIT_LOG_PATH


def _read_recent_mutations(
    *,
    window: int | None = None,
    log_path: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split ``mutations.jsonl`` rows into (apply_rows, attribution_rows).

    Single SoT for all 4 ux readers — every metric here comes from the
    same ledger so they share window + freshness semantics. ``window``
    keeps the tail (most recent) when set; ``None`` reads the full
    ledger.

    Graceful: missing file / unparseable line → empty lists (the
    autoresearch loop is best-effort scaffolding, not a blocker).
    """
    path = log_path if log_path is not None else _mutations_log_path()
    if not path.is_file():
        return [], []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("ux_means: could not read %s (%s)", path, exc)
        return [], []
    rows: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # silent skip — schema drift surfaces in dedicated tests
    if window is not None and window > 0:
        rows = rows[-window:]
    apply_rows = [r for r in rows if str(r.get("kind", "")).startswith("applied")]
    attribution_rows = [r for r in rows if r.get("kind") == "attribution"]
    return apply_rows, attribution_rows


def read_mutation_success_rate(
    *,
    window: int | None = None,
    log_path: Path | None = None,
) -> float | None:
    """Fraction of recent attribution rows where the mutation moved the
    expected dim in the right direction (``attribution_score > 0``).

    Source: ``autoresearch/state/mutations.jsonl`` attribution rows.
    ``attribution_score`` is the magnitude-weighted partition of
    intended vs observed dim deltas (PR-W4 / PR-16). Positive score
    means at least one expected dim moved toward the intended target.

    **Semantic caveat**: this is a *directional* success signal, not a
    promotion-gate success signal. A mutation can score > 0 (some
    expected dim improved) yet still be rejected by ``_should_promote``
    (cross-axis gate fired, fitness floor missed). The metric ladders
    into ``ux_means`` 'success_rate' field where weight = 0.40 — the
    strongest of the 4 ux fields.

    Returns ``None`` when no attribution rows exist (e.g. fresh
    checkout, before the first audit). ``0.0`` is a valid return
    (every mutation hurt or had zero signal).
    """
    _, attrs = _read_recent_mutations(window=window, log_path=log_path)
    if not attrs:
        return None
    valid = [r for r in attrs if "attribution_score" in r]
    if not valid:
        return None
    successes = sum(1 for r in valid if float(r.get("attribution_score", 0.0)) > 0.0)
    return successes / len(valid)


def read_token_cost(
    *,
    window: int | None = None,
    log_path: Path | None = None,
) -> float | None:
    """Cumulative LLM cost (USD) across recent apply rows.

    Source: ``autoresearch/state/mutations.jsonl`` apply rows with
    ``cost_input_tokens`` / ``cost_output_tokens`` / ``cost_model``
    fields (W4 schema, 2026-05-25). Per-token rate comes from
    ``core.llm.pricing_loader``'s ``MODEL_PRICING`` (refreshed quarterly
    per upstream provider pages).

    Returns ``None`` when no apply rows have priced cost data
    (legacy rows pre-W4 omit cost fields).
    """
    apply_rows, _ = _read_recent_mutations(window=window, log_path=log_path)
    if not apply_rows:
        return None
    from core.llm.token_tracker import MODEL_PRICING

    total = 0.0
    found = False
    for row in apply_rows:
        model = row.get("cost_model") or ""
        price = MODEL_PRICING.get(str(model))
        if price is None:
            continue
        in_tok = row.get("cost_input_tokens")
        out_tok = row.get("cost_output_tokens")
        if in_tok is None and out_tok is None:
            continue
        found = True
        total += float(in_tok or 0) * price.input + float(out_tok or 0) * price.output
    return total if found else None


def read_revert_ratio(
    *,
    window: int | None = None,
    log_path: Path | None = None,
) -> float | None:
    """Fraction of recent attribution rows where the mutation hurt
    fitness (``fitness_delta < 0`` — operator would naturally revert
    via ``git reset`` per the Karpathy idiom).

    Source: ``autoresearch/state/mutations.jsonl`` attribution rows
    with ``fitness_delta`` populated (PR-SIL-5THEME C4 ledger).

    Returns ``None`` when no attribution row carries ``fitness_delta``
    (pre-C4 rows or unmeasured baseline transitions).
    """
    _, attrs = _read_recent_mutations(window=window, log_path=log_path)
    if not attrs:
        return None
    valid = [r for r in attrs if "fitness_delta" in r and r.get("fitness_delta") is not None]
    if not valid:
        return None
    reverts = sum(1 for r in valid if float(r["fitness_delta"]) < 0.0)
    return reverts / len(valid)


def read_latency(
    *,
    window: int | None = None,
    log_path: Path | None = None,
) -> float | None:
    """Mean wall-clock elapsed (seconds) per recent mutation cycle.

    Source: ``autoresearch/state/mutations.jsonl`` apply rows with
    ``cost_elapsed_seconds`` field (W4 schema). Higher means the loop
    is taking longer per cycle — the ``latency_norm`` field inverts
    via the budget so higher latency → lower fitness contribution.

    Returns ``None`` when no apply row carries ``cost_elapsed_seconds``.
    """
    apply_rows, _ = _read_recent_mutations(window=window, log_path=log_path)
    if not apply_rows:
        return None
    valid = [
        float(r["cost_elapsed_seconds"])
        for r in apply_rows
        if r.get("cost_elapsed_seconds") is not None
    ]
    if not valid:
        return None
    return sum(valid) / len(valid)


def collect_ux_means_from_sources(
    *,
    budget_token_cost: float = DEFAULT_UX_TOKEN_BUDGET_USD,
    budget_latency_s: float = DEFAULT_UX_LATENCY_BUDGET_S,
    window: int | None = None,
    log_path: Path | None = None,
) -> dict[str, float] | None:
    """Aggregate the 4 ux fields from ``autoresearch/state/mutations.jsonl``.

    All 4 readers share the same window / log_path — they're slices of
    the same ledger snapshot, so the fields are coherent.

    Returns ``None`` when ``read_mutation_success_rate`` returns ``None``
    (i.e. no attribution data at all — the loop hasn't completed a
    cycle yet). ``compute_fitness`` then falls back to dim-only
    fitness (no-op signal for ux).

    Args:
        budget_token_cost: USD ceiling for token-cost normalization.
            Default = ``DEFAULT_UX_TOKEN_BUDGET_USD`` (5.0).
        budget_latency_s: seconds ceiling for latency normalization.
            Default = ``DEFAULT_UX_LATENCY_BUDGET_S`` (1800).
        window: tail size for ledger slicing. ``None`` reads everything.
        log_path: override the ledger location (tests).
    """
    success_rate = read_mutation_success_rate(window=window, log_path=log_path)
    if success_rate is None:
        return None
    token_cost = read_token_cost(window=window, log_path=log_path) or 0.0
    revert_ratio = read_revert_ratio(window=window, log_path=log_path) or 0.0
    latency = read_latency(window=window, log_path=log_path) or 0.0
    return {
        "success_rate": success_rate,
        "token_cost_norm": normalize_ux_field(token_cost, budget=budget_token_cost, invert=True),
        "revert_ratio_norm": normalize_ux_field(revert_ratio, budget=1.0, invert=True),
        "latency_norm": normalize_ux_field(latency, budget=budget_latency_s, invert=True),
    }


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


def detect_ux_conflict(
    *,
    dim_means: dict[str, float],
    baseline_dim_means: dict[str, float] | None,
    ux_means: dict[str, float] | None,
    baseline_ux_means: dict[str, float] | None,
    critical_dims: tuple[str, ...] = (),
    critical_margin: float = 0.0,
) -> str | None:
    """Petri vs UX cross-validation gate (Goodhart 양방향 방어).

    PR-AR-L4d (2026-05-26) — mirrors ``bench_means.detect_cross_validation_conflict``
    pattern on the UX axis. Two conflict scenarios:

    1. **Petri promote + UX regress** (``"alignment_only_fooling_ux"``) —
       audit dim aggregate improved (judge said behaviour got safer)
       but behaviour metrics (mutator success / token cost /
       revert ratio / latency) got worse. Suggests the mutation
       pleased the judge while hurting actual run-time behaviour.

    2. **UX promote + Petri critical regress**
       (``"capability_at_alignment_cost_ux"``) — behaviour metrics
       improved but a critical-tier dim regressed beyond its margin.
       Suggests the mutation gamed the UX surface at the cost of
       safety/alignment.

    Convention reminder ([[feedback-dim-convention-direction]]):

    - ``dim_means`` (Petri 1-10) — lower-is-better. "improved" = dim
      aggregate went DOWN.
    - ``ux_means`` (4-field normalized) — higher-is-better via
      ``compute_ux_aggregate``. "improved" = ux aggregate went UP.

    Both fire the strict-reject path (caller returns
    ``False`` with the conflict label). Returns ``None`` when there
    is insufficient data to detect — graceful, the gate stays
    dormant rather than false-firing.
    """
    if baseline_dim_means is None or baseline_ux_means is None:
        return None
    if ux_means is None:
        return None

    ux_now = compute_ux_aggregate(ux_means)
    ux_base = compute_ux_aggregate(baseline_ux_means)
    ux_improved = ux_now > ux_base
    ux_regressed = ux_now < ux_base

    dim_aggregate_now = sum(dim_means.values()) / max(1, len(dim_means))
    dim_aggregate_base = sum(baseline_dim_means.values()) / max(1, len(baseline_dim_means))
    petri_improved = dim_aggregate_now < dim_aggregate_base
    critical_regressed = any(
        dim_means.get(dim, 0.0) > baseline_dim_means.get(dim, 0.0) + critical_margin
        for dim in critical_dims
    )

    if petri_improved and ux_regressed:
        return "alignment_only_fooling_ux"

    if ux_improved and critical_regressed:
        return "capability_at_alignment_cost_ux"

    return None


__all__ = [
    "DEFAULT_UX_LATENCY_BUDGET_S",
    "DEFAULT_UX_TOKEN_BUDGET_USD",
    "UX_DIM_WEIGHTS",
    "collect_ux_means_from_sources",
    "compute_ux_aggregate",
    "detect_ux_conflict",
    "normalize_ux_field",
    "read_latency",
    "read_mutation_success_rate",
    "read_revert_ratio",
    "read_token_cost",
    "validate_ux_schema",
]
