"""Seed-pipeline cost preview — estimate per-phase + total USD spend.

Surfaced to the user as a pre-run confirm prompt (S11 CLI) so a 15-
candidate gen2 with a 3-voter Elo tournament doesn't quietly burn
through the user's subscription quota or PAYG budget. The estimate is
derived from:

1. The picker-resolved per-role :class:`RoleBinding` (model name).
2. The :data:`core.llm.token_tracker.MODEL_PRICING` catalogue
   (per-million-token input / output).
3. The role-specific token budgets in :data:`_ROLE_TOKEN_BUDGETS` —
   empirical typical-call sizes calibrated by ADR-001 paper §5
   (10-15 candidates × 2 judges × 3 rounds ≈ 100 LLM calls per gen).

For roles bound to a subscription source (claude-cli / openai-codex)
the OAuth quota absorbs the cost — we still surface the *equivalent*
USD figure so the user can compare "subscription burn rate" vs PAYG.

P-checklist application:

- **P4 Environment Anchor**: pricing is loaded once at import time
  via :data:`core.llm.token_tracker.MODEL_PRICING`; the cost preview
  never reads `~/.geode/config.toml` directly.
- **P7 Caller-Callee Contract**: every estimate row exposes the
  fields the S11 CLI needs (role, model, family, source, calls,
  est_usd) so the prompt renderer doesn't have to compute deltas.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

from core.llm.token_tracker import MODEL_PRICING

from plugins.seed_pipeline.picker import PickerResult, RoleBinding

log = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CANDIDATE_COUNT",
    "CostEstimate",
    "CostRow",
    "estimate_cost",
    "format_cost_summary",
]


DEFAULT_CANDIDATE_COUNT: int = 15


@dataclass(frozen=True)
class _RoleBudget:
    """Empirical typical-call sizes per role per candidate or per match.

    ``per`` is what the ``calls`` count scales with — ``"candidate"``,
    ``"match"``, or ``"run"`` (one-shot per pipeline run).
    """

    input_tokens: int
    output_tokens: int
    per: str  # "candidate" | "match" | "run"


# Calibrated from ADR-001 paper §5 + S2/S3/S5/S6 observed dispatch
# patterns. Conservative upper bounds (worst-case typical call).
_ROLE_TOKEN_BUDGETS: dict[str, _RoleBudget] = {
    "generator": _RoleBudget(input_tokens=3000, output_tokens=1000, per="candidate"),
    "critic": _RoleBudget(input_tokens=2000, output_tokens=400, per="candidate"),
    "proximity": _RoleBudget(input_tokens=3000, output_tokens=0, per="run"),
    "pilot": _RoleBudget(input_tokens=5000, output_tokens=1000, per="candidate"),
    "ranker": _RoleBudget(input_tokens=3000, output_tokens=300, per="match-voter"),
    "evolver": _RoleBudget(input_tokens=3000, output_tokens=1000, per="candidate"),
    "meta_reviewer": _RoleBudget(input_tokens=4000, output_tokens=1000, per="run"),
}


@dataclass(frozen=True)
class CostRow:
    """One row in the cost-preview table — per role."""

    role: str
    model: str
    family: str
    source: str
    calls: int
    est_usd: float
    subscription_backed: bool


@dataclass(frozen=True)
class CostEstimate:
    """Aggregate cost preview across all enabled roles."""

    rows: list[CostRow]
    total_usd: float
    subscription_usd: float
    payg_usd: float
    candidate_count: int
    match_count: int
    voter_count: int


def _calls_for(budget: _RoleBudget, *, candidates: int, matches: int, voters: int) -> int:
    """Translate a role's token budget into total LLM call count."""
    if budget.per == "candidate":
        return candidates
    if budget.per == "match":
        return matches
    if budget.per == "match-voter":
        return matches * voters
    return 1  # "run"


def _per_call_cost(model: str, budget: _RoleBudget) -> float:
    """Per-call USD using :data:`MODEL_PRICING`.

    Returns ``0.0`` when the model is unknown (proximity's embedding
    pricing is the obvious case — :data:`MODEL_PRICING` only ships
    completion-model rates). The caller can override or supplement
    when an embedding-specific catalogue lands.
    """
    price = MODEL_PRICING.get(model)
    if price is None:
        log.debug(
            "seed-pipeline cost_preview: model %r missing from MODEL_PRICING — $0 estimate",
            model,
        )
        return 0.0
    return budget.input_tokens * price.input + budget.output_tokens * price.output


def _match_count_for(candidate_count: int) -> int:
    """Default tournament match schedule — ceil(N log₂ N).

    Mirrors :func:`plugins.seed_pipeline.tournament.plan_matches`'s
    default to keep the preview consistent with what the Ranker
    actually dispatches.
    """
    if candidate_count < 2:
        return 0
    n_pairs = candidate_count * (candidate_count - 1) // 2
    return min(n_pairs, math.ceil(candidate_count * math.log2(max(candidate_count, 2))))


def estimate_cost(
    picker_result: PickerResult,
    *,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    match_count: int | None = None,
) -> CostEstimate:
    """Compute per-role + aggregate cost for one full pipeline run.

    Parameters
    ----------
    picker_result
        :class:`PickerResult` from
        :func:`plugins.seed_pipeline.picker.pick_bindings`.
    candidate_count
        Target N for the generator phase (default 15).
    match_count
        Override for the Elo tournament size. Defaults to the same
        ``ceil(N log₂ N)`` schedule the Ranker plans.
    """
    matches = match_count if match_count is not None else _match_count_for(candidate_count)
    voter_count = len(picker_result.voters)

    rows: list[CostRow] = []
    subscription_usd = 0.0
    payg_usd = 0.0
    for role, binding in picker_result.bindings.items():
        row = _estimate_role(
            role,
            binding,
            candidates=candidate_count,
            matches=matches,
            voters=voter_count,
        )
        rows.append(row)
        if row.subscription_backed:
            subscription_usd += row.est_usd
        else:
            payg_usd += row.est_usd

    return CostEstimate(
        rows=rows,
        total_usd=subscription_usd + payg_usd,
        subscription_usd=subscription_usd,
        payg_usd=payg_usd,
        candidate_count=candidate_count,
        match_count=matches,
        voter_count=voter_count,
    )


def _estimate_role(
    role: str,
    binding: RoleBinding,
    *,
    candidates: int,
    matches: int,
    voters: int,
) -> CostRow:
    budget = _ROLE_TOKEN_BUDGETS.get(role)
    if budget is None:
        # Unknown role — defer to a single-run conservative call.
        budget = _RoleBudget(input_tokens=2000, output_tokens=500, per="run")
    calls = _calls_for(budget, candidates=candidates, matches=matches, voters=voters)
    est_usd = calls * _per_call_cost(binding.model, budget)
    from plugins.seed_pipeline.picker import SUBSCRIPTION_SOURCES

    return CostRow(
        role=role,
        model=binding.model,
        family=binding.family,
        source=binding.source,
        calls=calls,
        est_usd=est_usd,
        subscription_backed=binding.source in SUBSCRIPTION_SOURCES,
    )


def format_cost_summary(estimate: CostEstimate) -> str:
    """Render the estimate as a human-readable summary table.

    Output is plain text (no Rich markup) so it can be embedded in
    a CLI confirm prompt or a serialized run-context note.
    """
    lines: list[str] = []
    lines.append("seed-pipeline cost preview")
    lines.append(
        f"  candidates: {estimate.candidate_count}  "
        f"matches: {estimate.match_count}  voters: {estimate.voter_count}"
    )
    lines.append("")
    lines.append("  role           model                       calls    est_usd")
    lines.append("  ─────────────  ──────────────────────────  ─────  ─────────")
    for row in estimate.rows:
        marker = "*" if row.subscription_backed else " "
        lines.append(
            f"  {row.role:<13}  {row.model:<26}  {row.calls:>5}  ${row.est_usd:>7.4f}{marker}"
        )
    lines.append("  ─────────────────────────────────────────────────────────────")
    total_calls = sum(r.calls for r in estimate.rows)
    lines.append(
        f"  total                                              {total_calls:>5}  "
        f"${estimate.total_usd:>7.4f}"
    )
    if estimate.subscription_usd > 0:
        lines.append(
            f"    * subscription-backed (quota burn equivalent): ${estimate.subscription_usd:.4f}"
        )
    if estimate.payg_usd > 0:
        lines.append(f"      PAYG (will be charged):                      ${estimate.payg_usd:.4f}")
    return "\n".join(lines)
