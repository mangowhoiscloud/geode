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

Status: executable offline and subscription-runner contract; two score-bearing
diagnostics have been reported, neither with runtime promotion authority.

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

#### Observed GAP: OpenAI response-schema subset

The first frozen execution
`skill-attribution-sol-max-paired-20260826t110744z` is retained as an invalid
run. All 24 arms stopped before generation with `model_action_required` and
zero input/output tokens because the OpenAI Responses backend rejected
`uniqueItems` in the model-facing `evidence_ids` array schema. The aggregate is
therefore `not-measurable`; none of those arms may be relabelled or replaced.

The duplicate constraint belongs to `verify_skill_output()`, which already
fails closed on repeated identifiers. The response schema now keeps only the
provider-supported array/item shape instead of duplicating that verifier rule.
This is a source-schema correction, not adapter-side silent rewriting: the
other `uniqueItems` occurrences in this repository are persisted artifact
schemas and do not enter the OpenAI response-format path.

Acceptance requires a new run ID and output root, the same 12-case workload,
an exact post-fix GEODE revision, 24 non-infrastructure-invalid arms, and the
unchanged native verifier. The invalid run remains part of the attempt history
but never enters the score denominator.

#### Observed score-bearing diagnostic

The first valid frozen run
[`skill-attribution-sol-max-paired-20260826t113400z`](2026-08-26-skill-attribution-sol-max-paired.md)
met that acceptance boundary: 24/24 arms were valid, with-skill passed 6/12,
without-skill passed 2/12, and the signed native-verifier delta was +4/12.
Its preregistered diagnostic hypothesis was supported. The same run also found
zero lift for `deep-researcher`, 0/3 with-skill passes for explicit prompts,
and one negative-control skill activation. Those secondary results block
runtime promotion and package-release claims.

A post-run contract audit identified three measurement gaps without changing
the frozen score: hidden required finding IDs (SA-GAP-01), answer-only term
matching for structured grilling questions (SA-GAP-02), and a seeded,
trigger-bearing grilling negative control (SA-GAP-03). The evaluator now fails
closed on hidden IDs, scores question prose, and keeps negative controls free of
grill state. Only a new prospective run may measure the corrected contract.

That prospective repeated run is
[`skill-attribution-sol-max-paired-r3-20260826t130119z`](2026-08-26-skill-attribution-sol-max-paired-r3.md).
All 72 arms were valid, but repetition deltas were +4/12, -3/12, and -1/12.
The aggregate with-skill and without-skill pass counts were both 18/36, so the
frozen positive-lift hypothesis is not supported. All 18 negative-control arms
had zero activation and zero tool calls, closing SA-GAP-03 empirically; the run
also confirms that the one-repetition +4/12 result was not directionally
stable. SA-GAP-01 and SA-GAP-02 remain closed by the frozen loader and verifier
contracts rather than by score reinterpretation.

The current surface still exposes only `use_skill`, `get_grill`, and
`update_grill` over synthetic context. It therefore measures instruction and
registry availability, not the full native capability of research, repository,
or delegation skills. A broader suite requires a separately preregistered tool
surface and task-specific structured-output contract; this verifier must not be
changed post hoc to turn the zero result positive.

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
