---
eval_id: eval-data-model
eval_family: eval-data-model
eval_kind: contract
eval_status: canonical
eval_authority: derived-view-contract
eval_summary: Versioned joins for examples, rollouts, immutable trajectories, and evaluator-owned rewards.
eval_triggers:
  - example rollout trajectory reward
  - learning data
  - evaluation data model
eval_contracts:
  - docs/eval/schemas/example.schema.json
  - docs/eval/schemas/rollout.schema.json
  - docs/eval/schemas/reward.schema.json
  - docs/eval/schemas/learning-view-manifest.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Evaluation data model

The canonical join is `example → rollout → trajectory → reward`.

- An **example** is a versioned benchmark input. Native task IDs remain source
  identity; `example_id` is the cross-suite join key.
- A **rollout** is one policy interacting with one example under one seed.
  Infrastructure retries are rollout attempts and never increase rollout count.
- A **trajectory** remains `geode.trajectory@1`. A rollout selects its own
  session scope by digest and session IDs instead of copying or editing that
  immutable record.
- A **reward** is an evaluator-owned derived label. A zero is observed data;
  `null` means missing. Validity and safety vetoes remain rollout properties and
  cannot be averaged into reward.

`geode.eval-learning-view@2` versions the joined release, not the native
benchmark receipt. Native results, retry manifests, verifier receipts, and
session records remain their respective authorities.

## Admission rules

1. Every rollout references one existing example and a digest-matching native
   receipt and trajectory.
2. `selected_attempt_id` must be one of the rollout's attempt IDs.
3. Invalid or aborted rollouts cannot be selected for reward.
4. Every reward references one valid, selected rollout and the same example.
5. Reward locators must resolve in the digest-bound native receipt. Missing
   labels remain explicit and are never rewritten as zero.

The v2 view is a post-training candidate only. Training admission additionally
requires privacy review, deduplication, lineage-safe splits, replay semantics,
and label-quality checks.
