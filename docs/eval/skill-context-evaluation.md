---
eval_id: skill-context-evaluation
eval_family: skill-context-evaluation
eval_kind: benchmark
eval_status: canonical
eval_authority: measurement-contract
eval_summary: Paired runtime-skill attribution and deterministic context-recoverability profiles over existing GEODE evidence authorities.
eval_triggers:
  - skill lift
  - ACES
  - context recoverability
  - Scroll
  - compaction
  - tool offload
eval_contracts:
  - core/observability/schemas/trajectory.schema.json
  - docs/eval/schemas/analysis.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/run-spec.schema.json
---

# Skill Attribution and Context Recoverability

Status: executable offline and subscription-runner contract; no score-bearing
result has been reported.

This profile turns two frontier observations into separate GEODE measurements:

- [ACES, arXiv:2608.20614v1](https://arxiv.org/abs/2608.20614v1) evaluates a
  capability package through paired live trials with and without that package.
- [Scroll, arXiv:2608.21690v1](https://arxiv.org/abs/2608.21690v1) treats
  context as an append-only event environment whose evicted detail remains
  addressable.

GEODE adopts the measurable boundary, not either implementation wholesale.
Skill attribution uses the existing run-spec, attempt, trajectory, verifier,
reward, and analysis authorities. Context recoverability reads the existing
`sessions.db:session_events` and bounded tool-offload store. It creates no
second raw log, persistent Python kernel, eviction index, or unbounded state.

## 1. Paired skill attribution

[`evals/benchmarks/skill_attribution.py`](../../evals/benchmarks/skill_attribution.py)
requires one frozen `geode.eval-run-spec@1`. Model, route, reasoning, task,
workspace, initial-state reference, scorer, timeout, budget, seed schedule, and
repetition count are shared by both arms. The only treatment difference is
whether the target skill appears in `available_skills`.

The runner alternates arm order and rejects result or initial-state drift.
`live_test_approved` must be true before its callback can execute. Creating or
validating this profile does not authorize a model call.

### Initial case matrix

Each target has four prompt classes. Negative controls detect needless skill
activation instead of rewarding activation by itself.

| Target | Tier in this repository | Explicit | Implicit | Contextual | Negative control |
|---|---|---:|---:|---:|---:|
| `slop-audit` | project/repository | 1 | 1 | 1 | 1 |
| `deep-researcher` | bundled runtime | 1 | 1 | 1 | 1 |
| `grilling` | bundled runtime | 1 | 1 | 1 | 1 |

The 12 case IDs are the ordered workload IDs in the run spec. The tracked
[`skill-attribution-pilot.json`](../../evals/benchmarks/fixtures/skill-attribution-pilot.json)
fixture binds every case to exact evidence, finding, answer-term, and decision-
question expectations. `load_skill_fixtures()` rejects missing, additional,
duplicate, or reordered case identity, and `verify_skill_output()` fails closed
on malformed output before applying those deterministic expectations. Prompt
prose alone is not a score.

The fixture and verifier are offline measurement authorities.
[`skill_attribution_live.py`](../../evals/benchmarks/skill_attribution_live.py)
is the concrete subscription execution adapter. It accepts only a separately
frozen, explicitly approved run spec pinned to `openai` / `subscription` /
`gpt-5.6-sol` / `max`, requires a clean matching GEODE revision, confirms that
both arms expose the same three tool schemas, and launches every arm in a fresh
child process with a unique `GEODE_STATE_ROOT`. The model-visible tool set is
limited to `use_skill`, `get_grill`, and `update_grill`; only the target skill's
registry availability differs between matched arms.

```bash
uv run python -m evals.benchmarks.skill_attribution_live run \
  --run-spec <frozen-run-spec.json> \
  --fixture evals/benchmarks/fixtures/skill-attribution-pilot.json \
  --output-dir <new-run-directory>
```

The output directory must not exist. A retry uses a fresh root. Each accepted
run binds native results, deterministic verifier receipts, per-arm digest
trajectories, evaluator rewards, attempts, analysis, and the validated v2
learning view. Private child-process state and logs remain outside the artifact
bundle. The runner supplies execution and evidence closure; it does not itself
authorize publication, promotion, release, or a second model call.

### Metrics

The primary result is the signed native verifier delta for each pair:

`int(with_skill.verifier_passed) - int(without_skill.verifier_passed)`

Activation, irrelevant actions, input/output tokens, elapsed time, and safety
violations are reported as separate secondary deltas. GEODE does not average
them into an equal-weight composite. Every arm binds an existing attempt ID,
native result, verifier receipt, immutable trajectory, and evaluator-owned
reward by SHA-256; the aggregate remains owned by the existing analysis
contract.

## 2. Context recoverability

[`evals/benchmarks/context_recoverability.py`](../../evals/benchmarks/context_recoverability.py)
classifies a frozen evidence reference against current runtime authorities:

| Status | Exact meaning |
|---|---|
| `exact` | The referenced canonical JSON bytes remain digest-identical in a session event or offloaded result. |
| `summary-only` | Exact bytes are gone, but the frozen reference retains a non-empty summary. |
| `unavailable` | Neither exact bytes nor a summary can be recovered. |
| `corrupt` | Event identity/digest or offload JSON conflicts with the frozen reference. |

The reference binds session ID, global event ordinal, event ID, stored payload
digest, desired content digest, and optional offload reference. This separates
an intentionally bounded session-event projection from the full large result.

The deterministic fixture covers:

- exact evidence after reopening `sessions.db`;
- conflicting later updates and far-away evidence;
- compaction summaries that do not downgrade still-present exact events;
- summary-only recovery through the current session-artifact FTS API;
- large outputs recovered through bounded offload;
- expired offload with and without a summary; and
- tampered event or offload bytes.

Counts are a transparent distribution over the four statuses. They are not a
claim that GEODE matches Scroll's LongMemEval, BEAM, or LOCA scores.

## 3. Adoption boundary

| Source pattern | Decision | GEODE boundary |
|---|---|---|
| ACES paired with/without trials | Adopt | Freeze all non-skill fields and report native verifier lift. |
| ACES multi-metric composite | Do not use for promotion | Keep process and safety deltas separate from verifier outcomes. |
| Scroll append-only event log and exact addresses | Adapt | Reuse session-event ordinal/event IDs plus offload references. |
| Scroll persistent Python kernel and eviction index | Defer | Add only after this benchmark demonstrates unrecoverable cases that current stores cannot address. |
| New raw evaluation or context store | Reject | Existing native receipts and runtime stores remain authoritative. |

Runtime changes require a later measured GAP. This profile can identify that
need; it cannot silently turn an evaluation result into runtime architecture.
