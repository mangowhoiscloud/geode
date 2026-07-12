# Crucible evidence dossier — 2026-07-10 deep research

> Historical companion to [`crucible-kernel.md`](crucible-kernel.md), which is
> the normative current design. This file preserves the externally sourced
> evidence gathered around v0.99.289/290 so the research survives the later
> withdrawal of those implementations. The fitted calibration, rich excerpt
> feedback, and class-prior writer were removed by the standalone-kernel
> hardening; their measurements below are hypotheses, not current promotion
> evidence. Method: a deep-research
> harness (102 agents: 5 search angles, 20 sources fetched, 97 claims
> extracted, top 25 adversarially verified by 3 independent refuters each;
> 4 verifier agents lost to a session limit). Tier 1 claims survived 3-0 or
> 2-1 refutation votes; tier 2 claims were fetch-extracted with quotes but not
> adversarially verified; tier 3 are our own code-grounded measurements.

## How this evidence changed Crucible

| Evidence cluster | Design consequence | Landed in |
|---|---|---|
| Paired designs halve sample size; question-level pairing is "free" variance reduction | Paired evaluator kept, unchanged | kernel v1 (validated) |
| tau2-scale packs are severely underpowered for 5pp at fixed 95%; v1 gate needed 10-30pp (our measurement) | `paired_bootstrap.v2` kept the LB > 0 existence test plus an explicit economic materiality floor; the unvalidated threshold-derivation scaffold was withdrawn, and inference now uses preregistered independent families | v2 scorer retained; #2601 derivation withdrawn |
| Successful self-improvement systems expose useful evaluation signals, but richer feedback also widens contamination channels | Current feedback v3 exposes only closed failure codes and frozen train task IDs; candidate-authored excerpts and all INVALID evaluator feedback were withdrawn | #2602 approach narrowed by hardening |
| Single-lineage loops stall (SICA documented); but the strongest "archives are decisive" claims were REFUTED | Minimal archive only: campaign seeding over pinned baseline refs, no in-process population | policy (kernel non-goals kept) |
| Offline KEEP does not imply online gain; canary + guardrails is the standard bridge | KEEP = canary candidacy, not promotion; Stage 4 protocol adopted | roadmap (post-PR-D) |
| Benchmark task packs themselves carry defects (tau2 expected-action policy violations; SWE-bench memorization) | Exact task content and adapter-owned family identities are bound by `task_pack_sha256`; train/test overlap is rejected by ID, family, and content hash. The class-prior store was withdrawn | current kernel + task #5 |

## Tier 1 — adversarially verified claims (vote ≥ 2-1)

### Search-space and archive design

- **DGM's loop produced large validated gains**: SWE-bench 20.0%→50.0%,
  Polyglot 14.2%→30.7%, each change empirically validated on coding
  benchmarks. (arXiv:2505.22954, 3-0)
- **DGM's minimal archive recipe**: parent selection ∝ benchmark score and
  ∝ 1/(functioning children); every compiled, still-code-editing agent enters
  the archive — a low-complexity alternative to MAP-Elites. (arXiv:2505.22954, 3-0)
- **SICA is single-lineage hill-climbing** (best-so-far agent becomes the
  meta-agent; no population/island/MAP-Elites) and still improved SWE-bench
  Verified 17%→53% on a 50-task subset over ~15 iterations.
  (arXiv:2504.15228, 3-0 / 2-1)
- **SICA documents path dependency as a failure mode**: early feature ideas
  constrain later ones, raising run-to-run variance. (arXiv:2504.15228, 3-0)
- **Metaproductivity-Performance Mismatch**: selecting parents by immediate
  benchmark score correlates weakly with long-term clade productivity
  (Pearson 0.285 DGM / 0.444 SICA vs 0.778 for HGM's clade estimator).
  (arXiv:2510.21614, 3-0)
- **AlphaEvolve maintains diversity** via MAP-Elites + island models; ablating
  evolution or prompt context each significantly degrades results.
  (arXiv:2506.13131, 3-0)

### Feedback bandwidth

- **DGM parents read their full benchmark evaluation logs** and self-diagnose
  the next feature, handed to the producer as the problem statement.
  (arXiv:2505.22954, 3-0)
- **SICA exposes an archive analysis tool** with per-iteration stats and
  drill-down into best/worst problems. (arXiv:2504.15228, 3-0)
- **AlphaEvolve prompts carry prior programs + execution output + scores**,
  positioned as a deliberate upgrade over FunSearch's minimal context.
  (arXiv:2506.13131, 3-0)

### Small-sample statistics

- **Question-level paired differences are the recommended inference unit**;
  positively correlated scores make pairing a free variance reduction.
  (Miller, Anthropic — arXiv:2411.00640, 3-0)
- **Detecting a 3pp difference needs ~969 questions** (80% power, 5% FPR);
  new evals should have 1,000+ questions. (arXiv:2411.00640, 3-0)
- **Trial replication has diminishing returns**: n=198, K 1→10 shrinks the
  minimum detectable effect only 13.2pp→7.5pp. (arXiv:2411.00640, 3-0)
- **Paired McNemar needs ~2.15× fewer samples** than unpaired, matching the
  1/(1−ρ) textbook prediction. (arXiv:2605.30315, 3-0)
- **Even at thousands of items, ≤2pp gaps are unresolved** at (α=.05, 80%);
  >5pp gaps resolve. (arXiv:2605.30315, 3-0)
- **Anytime-valid thresholds inflate required n ~2.15×** at fixed scale —
  sequential testing is not a free lunch. (arXiv:2605.30315, 3-0)
- **Continuous monitoring invalidates fixed-horizon p-values**; always-valid
  p-values/CIs exist as the formal alternative. (Johari et al.,
  arXiv:1512.04922, 3-0 both)
- **Sequential e-values control type I error under continuous monitoring**,
  and permit optional continuation (add trials later without breaking error
  control). (arXiv:2606.00878, 3-0 both)

### Promotion to production

- **AlphaEvolve's Borg heuristic completed the full offline→production
  protocol**: unseen-holdout check → fleet rollout → post-deployment
  confirmation, recovering ~0.7% of fleet compute; interpretability cited as
  a reason to prefer code mutations. (arXiv:2506.13131, 3-0)

## Refuted claims (negative results worth remembering)

- ~~"DGM's ablations show archive-based open-ended exploration is
  load-bearing (single-lineage variant clearly worse)"~~ — **0-3 refuted**;
  the paper does not support the strong reading. (arXiv:2505.22954)
- ~~"HGM tree-search materially outperforms DGM/SICA under matched budgets
  with 2.4-6.9× less compute"~~ — **1-2 refuted** as stated.
  (arXiv:2510.21614)

Consequence: we kept Crucible's no-population design and implemented only the
cheap archive (campaign seeding over pinned baseline refs) rather than an
in-process population — the pro-archive evidence justifies insurance against
stalls, not heavy machinery.

## Tier 2 — fetch-extracted, not adversarially verified

Use with the quote-level confidence of a single careful reader; re-verify
before load-bearing use.

- **False success is 45-48% of failures in single-control tau2 domains**
  (retail wrong-write signature) **but only ~3% in dual-control telecom** —
  domains need different mutation operators. (arXiv:2601.17087)
- **LLM judges cannot reliably detect false success** (AUROC ≤ 0.65 across 5
  judges × 5 prompts); judges are fooled by confident closing language.
  Lightweight domain-calibrated TF-IDF detectors reach AUROC 0.83-0.95 at
  3,300× lower latency — use deterministic monitors, not judges, as canary
  guardrails. (arXiv:2601.17087)
- **Agent-computer interface changes alone moved SWE-bench Lite 11%→18%**
  (same model); a lint guardrail on the edit action added +3pp. (SWE-agent,
  arXiv:2405.15793)
- **User-simulator choice shifts tau-bench retail success by up to 9pp**
  with the agent fixed — the user simulator must be inside the frozen
  contract. (arXiv:2606.09863)
- **SWE-bench Verified gains are partly memorization**: 76% file-path
  identification in-benchmark vs ≤53% outside it. (arXiv:2506.12286)
- **RL-enhanced reasoning causally increases tool hallucination**, even from
  inference-time step-by-step elicitation; mitigation pays a capability cost
  (supports keeping the absolute floor). (arXiv:2510.22977)
- **Original tau2-bench contains tasks whose gold actions violate its own
  domain policies**; tau2-bench-verified fixes the dataset only, so adoption
  is a task-pack hash swap. (github.com/amazon-agi/tau2-bench-verified)
- **Offline metrics can predict one online KPI positively and another
  negatively** (Recall@20: CTR +0.9%/1%, CVR −0.2%); offline counterfactual
  estimators mislead promotion without bias modelling. (arXiv:2507.09566,
  arXiv:1801.07030)
- **Staged deployment protocol**: shadow (0%) → canary → staged expansion
  with probe/SLO gates, feature flags, kill-switch; concept drift shows in
  the first 24-72h, so canary holds must span that window. (arXiv:2411.13768)

## Tier 3 — historical measurements and hypotheses

These measurements explain why the earlier gate was questioned, but they are
not a current calibration dataset and do not authorize parameter choice or
promotion. The synthetic estimator, prior store, and their pinning tests were
removed; reproducing a claim now requires checking out the historical code and
rebuilding its inputs.

- **v1 gate power audit** (real `_paired_bootstrap_lower_bound` import):
  KEEP required +30pp at n=10, ~17-23pp at n=30, ~10pp at n=115 — the gate
  was arithmetically closed under that audit's assumptions. The v2 role split
  remains, but the former power-test scaffold is no longer active authority.
- **Noise fit**: M1 null run (flips 12 / regressions 10 / n=114, p=0.416)
  → discordance 0.193 (Wilson95 0.131-0.275) → π_flaky ≈ 0.386 at K=1.
- **Guard-class prior**: G1 trace replay 24/27 supported, 4/87 controls
  falsely blocked → fix rate ~Beta(24.5, 3.5), regression ~Beta(4.5, 83.5).
- **Historical derived-design hypothesis**: guard-class candidates need only n=15, k=2
  (~60 conversations/attempt) at ~full power; weak/prompt-class candidates
  are unmeasurable at any reasonable budget (power ≤ 0.45 at n=40, k=6) —
  replay-layer class priors decide whether live measurement is worth buying.
- **Historical train α\* hypothesis**: cost-ratio derivation gives α ≈ 0.115-0.207 (sealed
  test is the economic backstop), replacing the 0.95-confidence tradition.

## Source index

arXiv:2505.22954 (DGM) · arXiv:2504.15228 (SICA) · arXiv:2510.21614 (HGM) ·
arXiv:2506.13131 (AlphaEvolve) · arXiv:2411.00640 (Adding Error Bars to
Evals) · arXiv:2605.30315 (paired McNemar / anytime-valid resolution) ·
arXiv:1512.04922 (always-valid inference) · arXiv:2606.00878 (e-values) ·
arXiv:2405.15793 (SWE-agent) · arXiv:2506.12286 (SWE-bench memorization) ·
arXiv:2606.09863 (user-simulator sensitivity) · arXiv:2510.22977 (tool
hallucination) · arXiv:2601.17087 (false-success taxonomy/judges) ·
arXiv:1801.07030 (offline A/B, Criteo) · arXiv:2507.09566 (offline→online
exchange rate) · arXiv:2411.13768 (staged deployment) ·
github.com/amazon-agi/tau2-bench-verified
