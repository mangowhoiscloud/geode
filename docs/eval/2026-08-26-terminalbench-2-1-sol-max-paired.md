---
eval_id: terminalbench21-sol-max-paired-main-20260826t092455z
eval_family: terminal-bench-2
eval_kind: ledger
eval_status: historical
eval_authority: paired-runtime-diagnostic
eval_summary: Prospective three-task Terminal-Bench 2.1 comparison of GEODE and native Codex with gpt-5.6-sol/max on the OpenAI subscription route; both arms passed 3/3, with no invalid attempts.
eval_triggers:
  - Terminal-Bench 2.1
  - gpt-5.6-sol
  - GEODE Codex comparison
  - Harbor
  - paired runtime diagnostic
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - docs/eval/schemas/publication.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Terminal-Bench 2.1 — Sol/max GEODE vs native Codex diagnostic

## 판정

동일한 canonical Terminal-Bench 2.1 task 3개, task digest, Docker 환경,
verifier, gpt-5.6-sol, reasoning max, OpenAI subscription route,
task별 900초 제한, concurrency 1, repetition 1에서 GEODE와 native
Codex는 모두 **3/3 (100%)**를 기록했다. 유효 attempt는 6개, 무효 attempt와
retry는 각각 0개다. 성공 수 차이는 0이므로 “한 task 이내”라는 동결
가설은 supported다.

이 결과는 같은 model의 두 harness를 직접 대조한 3-task diagnostic이다.
89-task 전체 정확도, 안정성, 속도 우위, 비용 우위, 공식 leaderboard 순위를
주장하지 않는다.

## Research contract

| Field | Frozen value |
|---|---|
| Question | 같은 3개 Terminal-Bench 2.1 task와 외부 protocol에서 GEODE와 native Codex의 verifier 결과는 어떻게 다른가? |
| Gap | 기존 GEODE Harbor adapter에는 same-model 2.1 paired measurement와 공개 artifact bundle이 없었다. |
| Hypothesis | GEODE 성공 수가 native Codex와 한 task 이내다. |
| Primary metric | arm별 canonical verifier passes / 3 |
| Decision | 절대 성공 수 차이가 1 이하이면 supported |
| Invalidation | dataset/task digest, timeout/resource, auth, container, verifier authority가 어긋나면 infrastructure-invalid |
| Analysis | 첫 valid attempt만 선택; semantic reward 0은 유지; infrastructure-invalid만 최대 1회 retry |
| Authority | direct paired-runtime diagnostic; suite headline/official submission authority 없음 |

## Frozen identity

| Field | Value |
|---|---|
| Run ID | terminalbench21-sol-max-paired-main-20260826t092455z |
| Preregistration | prospective, final freeze 2026-08-26T09:29:40Z |
| Original preregistered SHA-256 | a9e32fb4a7db31acf101a0cd600faf3a7fa11288fb2ebd67a94d81c3838beff6 |
| Canonical sidecar SHA-256 | 86ebef5c71f9b50458436c1ca5af59f4d5a99b82add1ea12c210ade93f529f8a |
| GEODE execution revision | 11fc370af279ade50308bf1af14e5464b0dca209 (origin/develop) |
| Harbor | 0.22.0 |
| Dataset | terminal-bench/terminal-bench-2-1@6 |
| Dataset digest | sha256:7d7bdc1cbedad549fc1140404bd4dc45e5fd0ea7c4186773687d177ad3a0699a |
| Model | gpt-5.6-sol, max, OpenAI subscription |
| GEODE arm | evals.platforms.harbor:GeodeHarborAgent, internal max_tokens=32768 per call |
| Comparator | Harbor native Codex 0.145.0 |
| Environment | macOS 15.3.1 arm64; Docker Desktop 4.53.0 / Engine 29.0.1; official linux/amd64 images under emulation |
| Timeout | canonical task agent/verifier limit 900s, multiplier 1.0, override 없음 |
| Concurrency | 1 |
| Repetition | 1 |
| Seed | Harbor 0.22.0 CLI에 seed option 없음 |

## Frozen tasks

| Task | Canonical digest | GEODE | Codex |
|---|---|---:|---:|
| regex-log | sha256:802c16cfd132e6c457529cb864be5a757c1b23b6cadc57f2d01983cb0110292a | 1 | 1 |
| openssl-selfsigned-cert | sha256:d4afa2bd2a9ba1420db8d6cfde42ffdb4873ae2d955c35014e8da94444c83302 | 1 | 1 |
| cancel-async-tasks | sha256:a3d048d351136e48070696cda8bb79660dfd74db1fea3b6da88559f0332699c1 | 1 | 1 |
| **Total** | — | **3/3** | **3/3** |

## Resource observations

| Metric | GEODE | Native Codex |
|---|---:|---:|
| Harbor job wall | 427s | 968s |
| Input tokens | 57,985 | 330,510 |
| Cached input tokens | 0 | 290,048 |
| Output tokens | 13,512 | 14,794 |
| Harbor estimated cost field | $0.616949 | $0.5737472 |

이 값은 descriptive다. Native Codex의 container 내부 CLI 설치, 서로 다른
prompt/tool/runtime, cache accounting, token policy가 포함된다. subscription
route의 cost_usd는 가격표 기반 관측값이며 실제 청구 증거가 아니다.

## Attempt lineage

| Arm | Attempts | Valid | Invalid | Retry | Selected |
|---|---:|---:|---:|---:|---:|
| GEODE | 3 | 3 | 0 | 0 | 3 |
| Native Codex | 3 | 3 | 0 | 0 | 3 |
| **Total** | **6** | **6** | **0** | **0** | **6** |

별도 smoke는 GEODE 1/1, native Codex 1/1; 그 전에 no-model oracle
1/1을 확인했다. Oracle은 final freeze 이전 preflight이므로 prospective
attempt denominator에는 넣지 않았다.

## Comparability

| Comparator | Grade | Reason |
|---|---|---|
| GEODE vs native Codex in this run | **direct diagnostic** | same tasks/digests/verifier/model/route/effort/external timeout/concurrency; harness internals are the treatment |
| Official full-suite submission | **not comparable** | this run is 3 × k=1; official contract is 89 × k>=5, static checks, ATIF for rewarded trials, and maintainer reward-hacking review |
| Public leaderboard rows | **not comparable as rank** | different full workload, repetitions, infrastructure, dates, and reviewed submission authority |

The [official leaderboard](https://www.tbench.ai/leaderboard/terminal-bench/2.1)
and [submission contract](https://github.com/harbor-framework/terminal-bench-2-1/blob/7131e4375048a0e408a8fb404b5f499d726b695b/leaderboard/SUBMIT.md)
are contextual references only. Community submissions are currently closed.

## Artifact contract

The public bundle contains:

- corrected canonical run spec plus the byte-identical original preregistration;
- typed attempt lineage;
- native result summary and canonical Harbor task results;
- verifier reward receipts and outcome receipt;
- schema-valid digest-only geode.trajectory@1;
- analysis and publication manifest.

Detailed provider reasoning, native system/session text, Codex JSONL sessions, and
raw GEODE runtime stores are withheld. The public trajectory is scope-complete
for the six attempt outcomes but intentionally not replay-complete.

The original preregistration used repository-relative artifact directories copied
from the run-spec template. Bundle validation requires run-directory-relative
files. The original bytes and hash remain immutable; only the post-run artifact
locators were corrected. eval-run-spec.template.json is fixed in the same PR.

## Publication

The append-only artifact PR
[mangowhoiscloud/geode-eval-artifacts#30](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/30)
was squash-merged as
[`c2a2d14b9053b7a80ec3c30d36b9afe7433407e9`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/c2a2d14b9053b7a80ec3c30d36b9afe7433407e9).
The immutable destination is
[`terminalbench/results-paired/terminalbench21-sol-max-paired-main-20260826t092455z/`](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/c2a2d14b9053b7a80ec3c30d36b9afe7433407e9/terminalbench/results-paired/terminalbench21-sol-max-paired-main-20260826t092455z).

All 36 manifest entries (105,417 bytes) were downloaded again from the exact
merge revision and matched their frozen sizes and SHA-256 digests; mismatch
count was zero. The final publication manifest is
`docs/eval/2026-08-26-terminalbench-2-1-sol-max-paired.publication.json`
(SHA-256 `7269975973ddc4119a2243adfb195839c7899bd2f288902a9c2626174438f344`).

## Limitations and release readiness

- 3/89 tasks and k=1 do not estimate suite accuracy or variance.
- linux/amd64 task images ran under arm64 host emulation.
- arm order was GEODE then Codex and not randomized.
- Harbor exposes no seed option.
- GEODE emits its native digest trajectory, not official Harbor ATIF.
- no official reward-hacking judge reviewed these trials.

판정은 **artifact-publication ready, release headline not ready**다. Package
release, tag, PyPI publication, public benchmark headline은 이 작업 범위에 없다.
