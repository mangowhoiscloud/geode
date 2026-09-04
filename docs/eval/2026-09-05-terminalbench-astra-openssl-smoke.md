---
eval_id: terminalbench21-astra-high-openssl-smoke-20260904t202725z
eval_family: terminal-bench-2
eval_kind: ledger
eval_status: historical
eval_authority: routing-and-behavior-diagnostic
eval_summary: Preregistered one-task Terminal-Bench 2.1 smoke showing that GEODE reached GPT-6 Astra/high through the current OpenAI subscription route and earned canonical verifier reward 1 without retry or fallback.
eval_triggers:
  - Terminal-Bench 2.1
  - GPT-6 Astra
  - OpenAI subscription
  - Harbor
  - E2E smoke
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - docs/eval/schemas/publication.schema.json
  - core/observability/schemas/trajectory.schema.json
---

# Terminal-Bench 2.1. GPT-6 Astra subscription E2E smoke

## 판정

현재 OpenAI 구독 계정에서 GEODE가 `gpt-6-astra`와 reasoning `high`를
호출해 canonical Terminal-Bench 2.1 `openssl-selfsigned-cert` 작업을
완료했다. Harbor verifier reward는 **1/1**, 개별 검사는 **6/6**이었고,
retry와 fallback은 없었다.

이 결과의 권한은 account-scoped E2E smoke에 한정된다. 한 작업, 한 반복으로
Terminal-Bench 2.1 전체 정확도, 분산, 순위, 다른 harness 대비 우위 또는 모든
계정의 Astra 접근 가능성을 주장하지 않는다.

## Frozen contract

| Field | Value |
|---|---|
| Run ID | `terminalbench21-astra-high-openssl-smoke-20260904t202725z` |
| Preregistration | prospective, frozen at 2026-09-04T20:27:25Z |
| GEODE | 1.0.27 at `132dc61f90b0fe097cf16b01efa564e88d9d8dc9` |
| Model route | `gpt-6-astra`, `high`, OpenAI subscription |
| Harness | Harbor 0.22.0 |
| Dataset | `terminal-bench/terminal-bench-2-1@6` |
| Task | `terminal-bench/openssl-selfsigned-cert` |
| Task digest | `sha256:d4afa2bd2a9ba1420db8d6cfde42ffdb4873ae2d955c35014e8da94444c83302` |
| Timeout | canonical 2,400s, multiplier 1.0 |
| Concurrency / repetition | 1 / 1 |
| Decision rule | Sole valid trial must finish without infrastructure error and receive reward 1 |
| Promotion authority | none |

## Observed result

| Measurement | Observation | Authority |
|---|---:|---|
| Canonical task reward | **1/1** | Harbor aggregate result and task verifier |
| Verifier checks | **6/6 passed** | CTRF receipt |
| Harbor errors / retries | **0 / 0** | Harbor aggregate result |
| GEODE rounds | **3** | GEODE trajectory outcome |
| Tool calls | **2 calls / 2 results / 0 orphans** | recomputed trajectory integrity |
| Termination | `natural` | GEODE trajectory outcome |
| Tokens | 10,442 input / 1,948 output / 0 cached | Harbor aggregate result |
| Trial wall time | 102.489s | Harbor trial result, retained privately because it contains a local path |

Harbor의 `cost_usd=$0.20182`는 price table 기반 추정치다. ChatGPT 구독의
실제 청구 내역으로 해석하지 않는다.

## Published evidence

Artifact PR [#40](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/40)은
[`a32abcbf78ab6100ea1e85540a2ace9436dc6f76`](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/a32abcbf78ab6100ea1e85540a2ace9436dc6f76)으로
squash merge됐다. 불변 bundle은
[`terminalbench/results-smoke/terminalbench21-astra-high-openssl-smoke-20260904t202725z/`](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/a32abcbf78ab6100ea1e85540a2ace9436dc6f76/terminalbench/results-smoke/terminalbench21-astra-high-openssl-smoke-20260904t202725z)에
있다.

공개된 9개 파일, 30,857바이트를 merge SHA에서 다시 내려받아 로컬 원본과
byte-for-byte로 대조했다. 불일치는 0개였다. bundle에는 다음이 포함된다.

- frozen run spec, typed attempt lineage, analysis;
- Harbor aggregate result, canonical verifier CTRF와 reward;
- privacy review를 통과한 `geode.trajectory@1` release와 manifest.

원본 prompt, reasoning, OAuth 자료, tool payload, ATIF, recording, 로컬 경로,
미검토 task output은 공개하지 않았다. 공개 trajectory는 12개 event와 정확히
짝지어진 tool call/result 2쌍을 담는다. 범위는 완전하지만 9개 payload body를
digest로 대체했으므로 replay는 불완전하다.

Publication manifest는
[`2026-09-05-terminalbench-astra-openssl-smoke.publication.json`](2026-09-05-terminalbench-astra-openssl-smoke.publication.json)에
있으며 SHA-256은
`feb0289dd64e5a277852d4c69fbc1ad6ca26e2db60c9f5b22d7977110470478a`다.

## 남는 한계

- 1/89 task, k=1이다. suite 성능이나 변동성을 추정하지 않는다.
- canonical linux/amd64 image를 arm64 macOS의 Docker Desktop에서 실행했다.
- comparator가 없으므로 runtime 간 비교 권한이 없다.
- official 제출 요건인 89 tasks × k>=5, static analysis, reward-hacking review를
  충족하지 않았다.
- 이 계정에서 성공했다는 증거이며, OpenAI의 전체 계정 rollout 완료 증거가
  아니다.

판정은 **artifact-publication complete, package-release not required**다.
GEODE 코드와 wheel version은 바뀌지 않았으며, 공개 문서와 Pages만 이 불변
증거를 가리킨다.
