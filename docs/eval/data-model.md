---
eval_id: eval-data-model
eval_family: eval-data-model
eval_kind: contract
eval_status: canonical
eval_authority: derived-view-contract
eval_summary: Versioned joins for examples, rollouts, immutable trajectories, and evaluator-owned rewards, with supplementary usage and cache-accounting evidence.
eval_triggers:
  - example rollout trajectory reward
  - learning data
  - evaluation data model
  - cache accounting
  - usage and cost evidence
eval_contracts:
  - docs/eval/schemas/example.schema.json
  - docs/eval/schemas/example-v2.schema.json
  - docs/eval/schemas/rollout.schema.json
  - docs/eval/schemas/rollout-v2.schema.json
  - docs/eval/schemas/reward.schema.json
  - docs/eval/schemas/reward-v2.schema.json
  - docs/eval/schemas/learning-view-manifest.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Evaluation data model

The canonical join is `example → rollout → trajectory → reward`.

- An **example** is a versioned benchmark input. Native task IDs remain source
  identity; `example_id` is the cross-suite join key.
- A **rollout** is one policy interacting with one example under one seed or an
  explicit unseeded repetition label. A label such as
  `unseeded-repetition-1` identifies a paired repetition but does not claim RNG
  control. Infrastructure retries are rollout attempts and never increase
  rollout count.
- A **trajectory** remains `geode.trajectory@1`. A rollout selects its own
  session scope by digest and session IDs instead of copying or editing that
  immutable record.
- A **reward** is an evaluator-owned derived label. A zero is observed data;
  `null` means missing. Validity and safety vetoes remain rollout properties and
  cannot be averaged into reward.

`geode.eval-learning-view@2` versions the joined release, not the native
benchmark receipt. Native results, retry manifests, verifier receipts, and
session records remain their respective authorities.

Usage and cache accounting is supplementary evidence, not a reward label.
Read the [usage accounting contract](../architecture/usage-accounting.md) for
the field map, existing data formats, normalized-zero limitations, and
interrupted-call coverage. Reference the original result/ledger or a reviewed
derived audit with the existing attempt `other` evidence kind; do not copy
usage into immutable trajectories or redefine a frozen score denominator.
Accounting coverage, task outcome and observability integrity stay separate.

## Admission rules

1. Every rollout references one existing example and a digest-matching native
   receipt and trajectory.
2. `selected_attempt_id` must be one of the rollout's attempt IDs.
3. Invalid or aborted rollouts cannot be selected for reward.
4. Every reward references one valid, selected rollout and the same example.
5. Reward locators must resolve in the digest-bound native receipt. Missing
   labels remain explicit and are never rewritten as zero.

## Collection for learning data (v2 records)

Agent outputs are not reproducible on the subscription routes: provider seeds
are not sent, GPT-5-family requests drop `temperature`, and same-config
baselines have disagreed on 5 of 12 tasks. One trajectory's reward is a fact
about that run, not an estimate for the task. New collection therefore uses the
v2 records and `evals/collection_protocol.py`:

- `geode.eval-rollout@2` replaces `seed` with `sampling` (harness seed,
  provider seed or `not-sent`, repetition purpose, index, and planned k) and
  adds `policy.model_served`, candidate patch, system-prompt and tool-schema
  digests, `user_simulator`, `environment` budgets (`max_steps`, timeout,
  `max_errors`), `outcome.agent_completed` separate from
  `outcome.verifier_pass`, and `label_hygiene`. A served model that differs
  from the requested one, or an invalid hygiene record, cannot be `valid`.
  Per-call evidence is the `llm.call.ended` activity row's `call_identity`
  (activity schema v13).
- `geode.eval-reward@2` gives every component a `grader_kind` (`code`,
  `model`, `human`), grader ID, and `grader_stochastic`; model graders are
  stochastic.
- `geode.eval-example@2` adds `split`, `family_id`, `source_benchmark`,
  `benchmark_eval_set`, `license`, `redistribution`, `canary`, and
  `output_terms`. The learning-view validator keeps a source task and a family
  in one split and refuses train rows that are public benchmark eval items or
  whose output terms are `prohibited` or `unknown`.

Repeat minimums (`REPEAT_MINIMUMS`) are 2 same-config A/A baselines per
campaign, 3 runs per task for evaluation gates (exact k from power admission),
4 same-config runs before preference pairs, and 16 per group for group-relative
RL. Materiality must exceed the measured A/A width; groups whose rewards are
all equal are dropped; each preference pair records its first divergence
ordinal and the actor there. A run spec opts in with
`execution.repetition_plan`. Variance reports give per-task passes/k with
Wilson intervals, within-task disagreement, pass@k and pass^k, and place the
A/A width beside a bootstrap difference interval.

The contamination detector (`geode.contamination-detector@1`) flags relayed
model-action diagnostics and provider throttle errors in agent or simulator
turns; both invalidate the episode, and the Crucible tau2 evaluator treats
them as infrastructure errors. Empty turns are flagged for review only.
`python -m evals.collection_protocol annotate-tau2` writes the same record onto
every simulation of a native tau2 receipt without changing its reward.

The v2 view is a post-training candidate only. Training admission additionally
requires privacy review, deduplication, lineage-safe splits, replay semantics,
and label-quality checks. All arms, repetitions, and retries derived from one
source `example_id` stay in the same split.
