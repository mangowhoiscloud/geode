---
eval_id: skill-attribution-sol-max-paired-20260826t113400z
eval_family: skill-context-evaluation
eval_kind: ledger
eval_status: historical
eval_authority: paired-skill-diagnostic
eval_summary: Prospective 12-case paired diagnostic of three GEODE runtime skills with gpt-5.6-sol/max; all 24 arms were valid and the signed native-verifier delta was +4/12.
eval_triggers:
  - skill attribution
  - gpt-5.6-sol
  - ACES
  - paired runtime skill
  - context recoverability
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - docs/eval/schemas/publication.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Runtime skill attribution — Sol/max paired diagnostic

## 판정

동일한 12개 synthetic case, runtime, model, route, reasoning effort, 세 도구
schema, initial-state fixture, timeout, concurrency에서 target skill의 registry
가용성만 바꾼 paired run을 실행했다. 24개 arm이 모두 유효했고 retry는
없었다. With-skill은 6개, without-skill은 2개 case를 native verifier에서
통과하여 사전등록 primary delta는 **+4/12 = +0.3333**이다. “delta가 0보다
크다”는 동결 가설은 supported다.

이 판정은 한 번의 12-case diagnostic에만 적용된다. 특히 explicit class의
with-skill 통과는 0/3이고, `deep-researcher`의 positive case 통과는 0/3이며,
`grill-negative`에서는 skill activation과 irrelevant action이 관측됐다.
따라서 artifact publication에는 적합하지만 runtime/package 승격 근거로는
부족하다.

## Frozen contract

| Field | Value |
|---|---|
| Run ID | `skill-attribution-sol-max-paired-20260826t113400z` |
| Freeze | prospective, `2026-08-26T11:34:00Z` |
| Run-spec SHA-256 | `293a6027141cba4b86a123d733ea2127ae657420241cac54a6fa670e5ce5d489` |
| GEODE revision | `abdd09a2f25700b2b01abc1a199aa1f0578ba440` (`develop`) |
| Fixture SHA-256 | `705572d7a06a502640073b5e11d05d05313b74ef9d686786155f7e667187f982` |
| Tool-schema SHA-256 | `ca0d86355f7296738d952c98de19115f43cd7ecf4527dba8503de89b827539b5` |
| Model | `gpt-5.6-sol`, max, OpenAI subscription |
| Treatment | exactly one target skill available vs unavailable |
| Model-visible tools | `use_skill`, `get_grill`, `update_grill` |
| Timeout / concurrency / repetitions | 180s per arm / 1 / 1 |
| Initial-state reset | fresh child process, state root, and session per arm |
| Promotion authority | none |

## Primary and secondary results

| Metric | Result |
|---|---:|
| Valid arms | 24/24 |
| Infrastructure-invalid arms | 0 |
| Retries | 0 |
| With-skill verifier passes | 6/12 |
| Without-skill verifier passes | 2/12 |
| Signed pass delta | **+4/12 (+0.3333)** |
| Skill activations | 9 net treatment activations |
| Safety violations | 0 |
| Irrelevant actions | 19 across both arms |
| Input tokens | 192,207 |
| Output tokens | 26,165 |
| Sum of arm elapsed time | 775.358s |

### By target skill

| Skill | Pairs | With pass | Without pass | Delta | Token delta |
|---|---:|---:|---:|---:|---:|
| `slop-audit` | 4 | 3 | 1 | +2 | +13,804 |
| `deep-researcher` | 4 | 1 | 1 | 0 | -4,661 |
| `grilling` | 4 | 2 | 0 | +2 | +11,821 |

The `deep-researcher` pass in each arm is its negative control; its explicit,
implicit, and contextual positive cases all failed the frozen verifier.

### By prompt class

| Prompt class | Pairs | With pass | Without pass | Delta | Token delta |
|---|---:|---:|---:|---:|---:|
| explicit | 3 | 0 | 1 | -1 | +6,641 |
| implicit | 3 | 2 | 0 | +2 | -53 |
| contextual | 3 | 1 | 0 | +1 | +10,244 |
| negative control | 3 | 3 | 1 | +2 | +4,132 |

## Case ledger

| Case | Skill | Class | With | Without | Delta | Activated with skill | Token delta |
|---|---|---|---:|---:|---:|---:|---:|
| `slop-explicit` | `slop-audit` | explicit | 0 | 1 | -1 | 1 | +4,613 |
| `slop-implicit` | `slop-audit` | implicit | 1 | 0 | +1 | 1 | +4,424 |
| `slop-contextual` | `slop-audit` | contextual | 1 | 0 | +1 | 1 | +4,806 |
| `slop-negative` | `slop-audit` | negative | 1 | 0 | +1 | 0 | -39 |
| `research-explicit` | `deep-researcher` | explicit | 0 | 0 | 0 | 1 | +716 |
| `research-implicit` | `deep-researcher` | implicit | 0 | 0 | 0 | 1 | -5,859 |
| `research-contextual` | `deep-researcher` | contextual | 0 | 0 | 0 | 0 | +379 |
| `research-negative` | `deep-researcher` | negative | 1 | 1 | 0 | 0 | +103 |
| `grill-explicit` | `grilling` | explicit | 0 | 0 | 0 | 1 | +1,312 |
| `grill-implicit` | `grilling` | implicit | 1 | 0 | +1 | 1 | +1,382 |
| `grill-contextual` | `grilling` | contextual | 0 | 0 | 0 | 1 | +5,059 |
| `grill-negative` | `grilling` | negative | 1 | 0 | +1 | 1 | +4,068 |

## Observed follow-up gaps

| Gap | Evidence | Required next evidence |
|---|---|---|
| Explicit request underperformance | with-skill explicit 0/3; `slop-explicit` regressed by one pass | inspect skill-to-answer contract, then preregister an independent repeated run |
| Research skill output mismatch | three positive `deep-researcher` cases missed frozen finding IDs or answer terms | decide whether the skill contract or fixture expectation owns the mismatch before editing either |
| Negative-control activation | `grill-negative` activated the skill; both arms recorded four irrelevant actions | add a promotion guard for negative activation/irrelevant action without changing the frozen primary score |
| Variance unknown | one repetition on one synthetic matrix | repeat with a new run ID and frozen seed/order policy before estimating population lift |
| Replay intentionally incomplete | digest trajectory omits system/session/model content | keep content private; use the reviewed scope-complete release for audit, not replay claims |

These gaps do not invalidate the observed primary metric. They block broader
claims and runtime promotion.

## Attempt lineage

The earlier frozen run
`skill-attribution-sol-max-paired-20260826t110744z` remains infrastructure-
invalid: all 24 arms were rejected before generation because the OpenAI
response-schema subset did not accept `uniqueItems`; input/output tokens were
zero. No arm was relabelled or replaced. PR
[#3218](https://github.com/mangowhoiscloud/geode/pull/3218) corrected the source
schema while the deterministic duplicate-ID verifier remained unchanged. This
run used a new ID, output root, run-spec digest, and exact post-fix revision.

## Artifact and privacy contract

The native run bundle and learning view passed their repository validators:
24 attempts, 12 examples, 24 rollouts, 24 rewards, four declared run artifacts,
and one analysis record. Public candidates are the frozen spec and fixture,
aggregate metrics, typed lineage, deterministic receipts, per-arm request and
score metadata, and a reviewed digest-only trajectory.

Raw per-arm native results, model text, tool payloads, child stdout/stderr,
runtime state, OAuth material, and operator logs remain private. The public
trajectory is scope-complete for the 24 outcomes and intentionally not replay-
complete. Its release manifest verifies 27 source digests and 231 events with
zero configured secret-scan findings.

## Publication

The append-only artifact PR
[mangowhoiscloud/geode-eval-artifacts#31](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/31)
was squash-merged as
[`fa352cb5f54e9f0ad6198c03dd180e27be388b5b`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/fa352cb5f54e9f0ad6198c03dd180e27be388b5b).
The immutable destination is
[`skill-attribution/results-paired/skill-attribution-sol-max-paired-20260826t113400z/`](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/fa352cb5f54e9f0ad6198c03dd180e27be388b5b/skill-attribution/results-paired/skill-attribution-sol-max-paired-20260826t113400z).

All 111 public entries (502,060 bytes) were downloaded again from the exact
merge revision and matched their frozen sizes and SHA-256 digests; mismatch
count was zero. The final publication manifest is
`docs/eval/2026-08-26-skill-attribution-sol-max-paired.publication.json`
(SHA-256
`9b2a35b21054dea4296b447bc9a9f0f4a52f4897b23c31a09336bf69c3f28d41`).

## Release readiness

Current judgment: **measurement-valid and artifact-publication ready; runtime
promotion and package release not ready**. No tag, PyPI upload, package-version
change, leaderboard claim, or main promotion is authorized by this diagnostic.
