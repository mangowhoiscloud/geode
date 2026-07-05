#!/usr/bin/env python3
"""Crucible G3b sequential gate — reject accelerator for paired S5 evaluation.

Observes discordant pairs (flip = base-fail→s5-pass, regression = base-pass→
s5-fail) one at a time and, after each, renders a Bayesian verdict so a
hopeless mutation dies before a full 114×2 paired run is spent. Early stop is
REJECT-ONLY: full benchmark stays the promotion authority (mid-run numbers
never promote to core), but mid-run evidence may safely kill a candidate.

Model: per-task outcome is concordant (both pass / both fail) or discordant
(flip / regression). Improvement effect delta = s5_pass_rate − base_pass_rate
over N tasks; discordant pairs alone move delta = (n_flip − n_reg) / N.
Posterior via Beta-Binomial (Beta(1,1) priors): flip-share θ over discordant,
and discordant-rate d over all tasks. Posterior-predictive Monte Carlo over
the unseen tasks gives P(final delta > +3pp) for the futility rule.

Rules (crucible.md §4.2):
  HARD_REJECT   : ≥12 discordant and n_reg ≥ n_flip + 4
  FUTILITY_STOP : P(final delta > +3pp) < 0.05
  PROMOTE_CAND  : P(final delta > +3pp) > 0.95  (advance to G3c full, not core)
  CONTINUE      : otherwise

Contamination filter (clop48 incident): drop infrastructure_error and any
task whose transcript carries an injected rate-limit error, plus non-user_stop
terminations — those are measurement artifacts, not agent behaviour.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

N_TOTAL_DEFAULT = 114
TARGET_DELTA_PP = 0.03  # +3pp promotion-worthy effect
MC_SAMPLES = 4000
RNG_SEED = 20260706  # fixed — Date/random reproducibility


def _clean_rewards(results_path: Path) -> dict[str, float]:
    """task_id → reward, keeping only clean, user_stop-terminated tasks."""
    d = json.loads(results_path.read_text())
    out: dict[str, float] = {}
    for s in d.get("simulations", []):
        if s.get("termination_reason") != "user_stop":
            continue
        msgs = s.get("messages", [])
        if any("rate limit" in str(m.get("content", "")).lower() for m in msgs):
            continue
        out[str(s["task_id"])] = (s.get("reward_info") or {}).get("reward", 0)
    return out


@dataclass
class GateState:
    n_flip: int = 0
    n_reg: int = 0
    n_conc: int = 0

    @property
    def n_disc(self) -> int:
        return self.n_flip + self.n_reg

    @property
    def n_seen(self) -> int:
        return self.n_disc + self.n_conc


def _beta_sample(rng: random.Random, a: int, b: int) -> float:
    x = rng.gammavariate(a, 1.0)
    y = rng.gammavariate(b, 1.0)
    return x / (x + y)


def p_final_delta_gt_target(
    st: GateState, n_total: int, rng: random.Random, target_pp: float = TARGET_DELTA_PP
) -> float:
    """Posterior-predictive P(final delta > target) over unseen tasks."""
    n_remaining = max(0, n_total - st.n_seen)
    hits = 0
    for _ in range(MC_SAMPLES):
        theta = _beta_sample(rng, 1 + st.n_flip, 1 + st.n_reg)  # flip-share
        d_rate = _beta_sample(rng, 1 + st.n_disc, 1 + st.n_conc)  # discordant-rate
        f_future = r_future = 0
        for _ in range(n_remaining):
            if rng.random() < d_rate:
                if rng.random() < theta:
                    f_future += 1
                else:
                    r_future += 1
        final = (st.n_flip + f_future) - (st.n_reg + r_future)
        if final / n_total > target_pp:
            hits += 1
    return hits / MC_SAMPLES


def verdict(st: GateState, n_total: int, rng: random.Random) -> tuple[str, float]:
    if st.n_disc >= 12 and st.n_reg >= st.n_flip + 4:
        return "HARD_REJECT", p_final_delta_gt_target(st, n_total, rng)
    p = p_final_delta_gt_target(st, n_total, rng)
    if p < 0.05:
        return "FUTILITY_STOP", p
    if p > 0.95:
        return "PROMOTE_CAND", p
    return "CONTINUE", p


def run(base_path: Path, s5_path: Path, n_total: int = N_TOTAL_DEFAULT) -> GateState:
    base = _clean_rewards(base_path)
    s5 = _clean_rewards(s5_path)
    common = sorted(set(base) & set(s5))
    rng = random.Random(RNG_SEED)
    rng.shuffle(common)  # deterministic order — avoid task-id ordering bias
    st = GateState()
    final_v, final_p = "CONTINUE", 0.0
    for t in common:
        b, s = base[t] >= 1, s5[t] >= 1
        if b and not s:
            st.n_reg += 1
        elif s and not b:
            st.n_flip += 1
        else:
            st.n_conc += 1
        final_v, final_p = verdict(st, n_total, rng)
        if final_v in ("HARD_REJECT", "FUTILITY_STOP"):
            print(
                f"[stop @ {st.n_seen} seen] {final_v} — "
                f"flip {st.n_flip} reg {st.n_reg} conc {st.n_conc} | "
                f"P(final>+3pp)={final_p:.3f}"
            )
            return st
    print(
        f"[end of clean data @ {st.n_seen} seen] {final_v} — "
        f"flip {st.n_flip} reg {st.n_reg} conc {st.n_conc} | "
        f"P(final>+3pp)={final_p:.3f} | discordant p-value(one-sided) "
        f"needs more pairs" if st.n_disc < 12 else ""
    )
    return st


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        run(Path(sys.argv[1]), Path(sys.argv[2]))
    else:
        SIMS = Path(
            "/Users/mango/workspace/geode/artifacts/eval/harnesses/tau2-bench/"
            "data/simulations"
        )
        for dom in ("retail", "telecom"):
            print(f"\n===== clop48 {dom.upper()} (clean, sequential) =====")
            run(
                SIMS / f"geode-clop48-{dom}-base-20260705" / "results.json",
                SIMS / f"geode-clop48-{dom}-s5-20260705" / "results.json",
            )
