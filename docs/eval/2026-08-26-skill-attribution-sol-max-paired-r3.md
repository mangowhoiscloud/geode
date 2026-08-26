---
eval_id: skill-attribution-sol-max-paired-r3-20260826t130119z
eval_family: skill-context-evaluation
eval_kind: ledger
eval_status: historical
eval_authority: paired-skill-diagnostic
eval_summary: Prospective three-repetition diagnostic after SA-GAP-01 through SA-GAP-03 closure; all 72 arms were valid, repetition deltas were +4, -3, and -1, and the aggregate signed native-verifier delta was 0/36.
eval_triggers:
  - skill attribution
  - gpt-5.6-sol
  - ACES
  - paired runtime skill
  - repeated diagnostic
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - docs/eval/schemas/publication.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Runtime skill attribution — Sol/max repeated paired diagnostic

## 판정

SA-GAP-01부터 SA-GAP-03까지 닫은 뒤 동일한 12개 synthetic case를 세 번
반복했다. 각 pair는 runtime, model, route, reasoning effort, tool schema,
initial-state fixture, timeout, concurrency를 고정하고 target skill의 registry
가용성만 바꿨다. 72개 arm이 모두 유효했고 retry와 safety violation은 없었다.

With-skill과 without-skill은 각각 **18/36**을 통과했다. 사전등록 primary
delta는 **0/36 = 0.0**이므로 “총 signed delta가 0보다 크다”는 가설은
**not-supported**다. 반복별 delta도 `+4/12`, `-3/12`, `-1/12`로 방향이
안정적이지 않았다. 이 결과는 측정 및 artifact publication에는 유효하지만,
runtime/package 승격이나 일반적인 skill 효과 주장에는 사용할 수 없다.

## Frozen contract

| Field | Value |
|---|---|
| Run ID | `skill-attribution-sol-max-paired-r3-20260826t130119z` |
| Freeze | prospective, `2026-08-26T13:01:19Z` |
| Run-spec SHA-256 | `4b9aae3140bc6dbf82247893cdd6128294d29f944df254ea87563e60d68744dd` |
| GEODE revision | `9ff286071aab68825afa8158aa7ee982cea9c4b8` (`develop`) |
| Fixture SHA-256 | `cf41a9ddcc10dca76c921f71e09537505f76d9a01281180a8e2ba2e39650b3ea` |
| Tool-schema SHA-256 | `ca0d86355f7296738d952c98de19115f43cd7ecf4527dba8503de89b827539b5` |
| Model | `gpt-5.6-sol`, max, OpenAI subscription |
| Treatment | exactly one target skill available vs unavailable |
| Model-visible tools | `use_skill`, `get_grill`, `update_grill` |
| Timeout / concurrency / repetitions | 180s per arm / 1 / 3 |
| Initial-state reset | fresh child process, state root, and session per arm |
| Promotion authority | none |

## Primary and secondary results

| Metric | With skill | Without skill | Delta / total |
|---|---:|---:|---:|
| Valid arms | 36 | 36 | 72/72 |
| Verifier passes | 18 | 18 | **0/36 (0.0)** |
| Skill activations | 25 | 0 | +25 |
| Irrelevant actions | 9 | 20 | -11 |
| Input tokens | 262,187 | 188,285 | +73,902 |
| Output tokens | 32,138 | 33,466 | -1,328 |
| Total tokens | 294,325 | 221,751 | +72,574 |
| Sum of arm elapsed time | 973.580s | 919.527s | +54.054s |

Infrastructure-invalid arms, retries, and safety violations were all zero.
The run used 450,472 input tokens and 65,604 output tokens, or 516,076 total.

### By repetition

| Repetition | With pass | Without pass | +1 / tie / -1 | Signed delta |
|---|---:|---:|---:|---:|
| r1 | 8 | 4 | 4 / 8 / 0 | +4/12 |
| r2 | 5 | 8 | 0 / 9 / 3 | -3/12 |
| r3 | 5 | 6 | 2 / 7 / 3 | -1/12 |
| Total | 18 | 18 | 6 / 24 / 6 | **0/36** |

Discordant pair는 treatment win 6개와 control win 6개로 정확히 같았다.
세 반복만으로 모집단 효과를 추정하지 않으며, 이 표는 방향 불안정성을
보이는 기술 통계다.

### By target skill

| Skill | Pairs | With pass | Without pass | Delta | Activation delta | Irrelevant-action delta | Token delta |
|---|---:|---:|---:|---:|---:|---:|---:|
| `deep-researcher` | 12 | 6 | 7 | -1 | +7 | -6 | +9,262 |
| `grilling` | 12 | 8 | 7 | +1 | +9 | -4 | +27,775 |
| `slop-audit` | 12 | 4 | 4 | 0 | +9 | -1 | +35,537 |

### By prompt class

| Prompt class | Pairs | With pass | Without pass | Delta |
|---|---:|---:|---:|---:|
| contextual | 9 | 6 | 7 | -1 |
| explicit | 9 | 3 | 3 | 0 |
| implicit | 9 | 5 | 3 | +2 |
| negative control | 9 | 4 | 5 | -1 |

세 skill의 negative control 18개 arm에서는 skill activation과 tool call이
모두 0이었다. 따라서 이전 run의 seeded, trigger-bearing control 문제는 새
측정에서 재현되지 않았다.

## GAP closure and remaining limits

| Gap | Closure evidence | Status / next evidence |
|---|---|---|
| SA-GAP-01 — hidden verifier IDs | fixture loader가 model-visible context에 없는 required evidence/finding/question ID를 거부하고, research fixture가 required finding ID를 노출한다 | closed before freeze; all 72 arms admitted under the corrected invariant |
| SA-GAP-02 — answer-only grilling terms | verifier가 answer, question options, recommendation을 하나의 structured prose surface로 채점한다 | closed before freeze; frozen verifier was unchanged during the run |
| SA-GAP-03 — biased negative control | negative fixture에서 decision trigger와 seeded `GrillStore` state를 제거했다 | closed empirically; 18/18 negative-control arms had zero activation and zero tool calls |
| SA-GAP-04 — narrow capability surface | model-visible tools are only `use_skill`, `get_grill`, and `update_grill`; context is synthetic | a separately preregistered native-capability suite needs web/file/delegation authorities before claiming full skill value |
| SA-GAP-05 — unstable treatment direction | repetition deltas were +4, -3, and -1, with aggregate 0 | redesign the intervention hypothesis before another run; do not add repetitions merely to search for a positive result |
| SA-GAP-06 — task-specific structured-output ambiguity | all six `research-implicit` arms failed with unexpected or malformed `questions`; no parser error was hidden | preregister task-specific empty/question rules or separate schemas before rerun; do not change this frozen verifier post hoc |
| Exact-term interpretation limit | deterministic required terms measure lexical contract compliance, not semantic equivalence | any blinded semantic audit must be a separate preregistered secondary authority |
| Replay intentionally incomplete | digest trajectory omits system/session/model content | keep content private; use the reviewed scope-complete release for audit, not replay claims |

SA-GAP-01 through SA-GAP-03 are measurement-contract closures, not proof that
skills improve outcomes. SA-GAP-04 through SA-GAP-06 prevent that stronger
interpretation. The zero result remains immutable; the verifier was not tuned
after observing it.

## Attempt lineage

The first frozen run, `skill-attribution-sol-max-paired-20260826t110744z`,
remains infrastructure-invalid because the provider rejected its model-facing
schema before generation. The next valid run,
[`skill-attribution-sol-max-paired-20260826t113400z`](2026-08-26-skill-attribution-sol-max-paired.md),
reported +4/12 but exposed SA-GAP-01 through SA-GAP-03 and had one repetition.
PR [#3220](https://github.com/mangowhoiscloud/geode/pull/3220) closed those
contract gaps before this run was frozen. No predecessor arm was relabelled,
replaced, or added to this denominator.

## Artifact and privacy contract

The native run bundle and learning view passed their repository validators:
72 attempts, 12 examples, 72 rollouts, 72 rewards, four declared run artifacts,
and one analysis record. The source run contained 589 files (2,398,227 bytes).
The reviewed public boundary contains 303 files (1,398,399 bytes); 289 source
files remain withheld.

The public trajectory is scope-complete for all 72 outcomes and intentionally
not replay-complete. Its release manifest binds 75 source digests and 630
events with zero configured secret-scan findings. Raw per-arm native results,
model text, tool payloads, local trajectories, child stdout/stderr, runtime
state, OAuth material, and operator logs remain private.

## Publication

The append-only artifact PR
[mangowhoiscloud/geode-eval-artifacts#32](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/32)
was squash-merged as
[`1efee3d0f4bfda3464b23b298a36f9a97f5fa691`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/1efee3d0f4bfda3464b23b298a36f9a97f5fa691).
The immutable destination is
[`skill-attribution/results-paired/skill-attribution-sol-max-paired-r3-20260826t130119z/`](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/1efee3d0f4bfda3464b23b298a36f9a97f5fa691/skill-attribution/results-paired/skill-attribution-sol-max-paired-r3-20260826t130119z).

All 303 public entries (1,398,399 bytes) were downloaded again from the exact
merge revision and matched their frozen sizes and SHA-256 digests; mismatch
count was zero. The trajectory release manifest SHA-256 is
`f6ee84d7139a3c33905ae48bb420519083890444d52aa0a4f82aee046b7f385a`.
The final publication manifest is
`docs/eval/2026-08-26-skill-attribution-sol-max-paired-r3.publication.json`
(SHA-256
`42c1cd6b8bda434e76f8659dbccef765f49e1382a80e5a1df653f1f9f98205b1`).

## Release readiness

Current judgment: **measurement-valid and artifact-publication ready; the
positive skill-lift hypothesis is not supported, so runtime promotion and
package release are not ready**. No tag, PyPI upload, package-version change,
leaderboard claim, or main promotion is authorized by this diagnostic.
