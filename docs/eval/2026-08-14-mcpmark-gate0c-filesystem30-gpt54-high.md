---
eval_id: mcpmark-gate0c-filesystem30-gpt54-high-20260814
eval_family: mcpmark
eval_kind: ledger
eval_status: historical
eval_authority: paired-runtime-diagnostic
eval_summary: Prospective common-deadline k=1 comparison of GEODE and Codex on 30 MCPMark filesystem/standard tasks with GPT-5.4/high; GEODE passed 23/30 versus Codex 21/30, a diagnostic-only +2/30 = +6.67 percentage-point delta.
eval_triggers:
  - MCPMark Gate 0C
  - common action deadline
  - GEODE Codex comparison
  - GPT-5.4 benchmark
  - paired runtime diagnostic
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - core/observability/schemas/trajectory.schema.json
  - core/observability/schemas/trajectory-release.schema.json
eval_latest_valid_release: https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/1160fecfe4447f0a3f4cf30a414f29c61776d012/trajectories/mcpmark-gate0c-gpt54-high-mcpmark-gate0c-filesystem30-gpt54-high-20260813t190922z-geode-20260813T230525Z-9d6773caad04
---

# GPT-5.4 MCPMark Gate 0C — corrective FS30 paired diagnostic

## 판정

동일한 MCPMark `filesystem/standard` 30개 task, semantic fixture, verifier,
GPT-5.4 subscription route, effort `high`, 공통 1,200초 action deadline에서
실행한 prospective paired `k=1` diagnostic에서 GEODE는 **23/30(76.7%)**,
Codex는 **21/30(70.0%)**를 기록했다. 사전등록 primary metric은
`(GEODE passes - Codex passes) / 30 = 2/30 = +0.066667`, 즉
**+6.67%p**다. 동결된 하한 `-0.10`보다 높으므로 가설은 **supported**다.

이 판정은 공통 timed action surface를 가진 한 번의 직접 paired-runtime
diagnostic에 한정된다. `promotion_authority=none`이며 fresh `k=3` 안정성,
MCPMark Verified 127-task headline, API-key leaderboard, 제품 기본값 변경,
GEODE가 일반적으로 더 정확하거나 효율적이라는 인과 주장의 근거가 아니다.
두 arm은 task/state/verifier/model/effort/deadline을 맞췄지만 서로 다른 runtime
scaffold와 tool-result 정책을 유지했다.

## Research contract

| Field | Frozen value |
|---|---|
| Research question | 같은 30개 MCPMark Filesystem task, semantic fixture state, verifier, GPT-5.4/high subscription route, 공통 timed action surface에서 GEODE와 Codex의 verifier accuracy는 어떻게 다른가? |
| Research gap | 이전 FS30 관측은 timeout 시작 경계가 달랐고 fixture receipt가 score-bearing file mtime과 empty directory를 결속하지 않았다. |
| Hypothesis | 30-task workload에서 GEODE verifier accuracy가 Codex보다 10%p 넘게 낮지 않다. |
| Primary metric | `(sum(GEODE passes) - sum(Codex passes)) / 30` |
| Decision rule | signed delta가 `-0.10` 이상이면 `supported`, 더 낮으면 `not-supported` |
| Secondary | arm accuracy, paired bucket, cache-excluded input, output/reasoning, action/envelope wall, MCP calls/errors, read/re-read, termination class |
| Invalidation | frozen deadline/model/route/schema/task/semantic fixture/verifier/reset/GEODE 25K cap 불일치, cleanup 실패, native/verifier/deadline/trajectory 누락, unrecovered quota·transport escape |
| Authority | `diagnostic`, direct paired runtime, `promotion_authority=none` |

## Frozen identity

| Field | Value |
|---|---|
| Run ID | `mcpmark-gate0c-filesystem30-gpt54-high-20260813t190922z` |
| Registration | prospective; frozen 2026-08-13 19:09:22 UTC |
| Execution | 2026-08-14 04:10:39–08:05:25 KST, 3:54:46 elapsed |
| GEODE | `f4b3760488a80dad1186d54458f63bbb08768719` from clean `origin/main` |
| Harness | `eval-sys/mcpmark@cd45b7f57923b9b3985467f5139927575f83141c` plus verifier compatibility patch SHA-256 `3f41f13a8edf7b40f411bf0a76412c28fc9629338d9e5051d5633dc064c563e6` |
| Codex comparator | `codex-cli 0.145.0`; source `openai/codex@dad1db87bb5ad4b92af6b0f58502d12453681f81`; executable SHA-256 `1da3f4e0e96028b8a771814293c3033dafd1971f943f6c7e79b0897fe705f590` |
| Model route | GPT-5.4, subscription, effort `high`, both arms |
| Workload | ordered `filesystem/standard` 30 tasks × 2 arms × `k=1` = 60 arms |
| Workload SHA-256 | `50483308573ce407abaf0700885d56c6df0453557669dddce9edcece83710433` |
| Fixture aggregate SHA-256 | `c8cfb2815f63ded54a7d79ffed2e0719190bb2dc1e571112a6012f97f95e9f17` |
| Semantic fixture SHA-256 | `273477d554250f4f076e69651e29689ed71095ec1b3fe3e054094be82f574fbf` |
| Tool schema SHA-256 | `1ad42161dcd16c1d786f859b71a52123fca9daa5c4a4d64864ff240ea150165f` |
| Order | task별 두 arm 직렬; odd task `GEODE→Codex`, even task `Codex→GEODE`; overlap·resume 없음 |
| Deadline | adapter `execute` entry부터 native runtime return까지 공통 absolute 1,200초; fixture setup과 post-action verifier는 범위 밖 |
| GEODE arm | frozen `GEODE_MAX_TOOL_RESULT_TOKENS=25000`; offload store unbound |
| Codex arm | isolated native Codex CLI runtime |

## Primary result

| Metric | GEODE | Codex | GEODE − Codex |
|---|---:|---:|---:|
| Verifier pass | **23 / 30** | **21 / 30** | **+2** |
| Pass rate | **76.7%** | **70.0%** | **+6.67%p** |
| Score-bearing deadline expiration | 1 | 0 | +1 |
| Exact native-token coverage | 29 / 30 | 30 / 30 | unmatched |

Paired bucket은 `both-pass=17`, `both-fail=3`, `GEODE-only-pass=6`,
`Codex-only-pass=4`다.

| Bucket | Tasks |
|---|---|
| GEODE only (6) | `desktop_template/file_arrangement`, `legal_document/solution_tracing`, `student_database/duplicate_name`, `student_database/gradebased_score`, `threestudio/output_analysis`, `threestudio/requirements_completion` |
| Codex only (4) | `folder_structure/structure_mirror`, `papers/organize_legacy_papers`, `votenet/debugging`, `votenet/requirements_writing` |
| Both fail (3) | `desktop_template/budget_computation`, `file_context/pattern_matching`, `papers/author_folders` |

Discordant pair가 10개이고 `k=1`이므로 +6.67%p를 안정된 arm 우위로 일반화하지
않는다. Fresh `k=3` replication이 남아 있다.

## Full-arm behavior

아래 값은 timeout을 포함한 각 arm의 **30/30 전체 action** 집계다.

| Metric | GEODE | Codex | GEODE − Codex |
|---|---:|---:|---:|
| Action elapsed | 8,463.252s | 5,484.322s | +2,978.930s (+54.3%) |
| Runner envelope | 8,536.382s | 5,548.725s | +2,987.657s (+53.8%) |
| Native execution-log MCP calls | 644 | 678 | −34 (−5.0%) |
| Native execution-log MCP errors | 51 | 17 | +34 (+200.0%) |
| Native execution-log error rate | 7.92% | 2.51% | +5.41%p |
| Read references | 798 | 838 | −40 (−4.8%) |
| Unique read references | 717 | 625 | +92 (+14.7%) |
| Repeated read references | 81 | 213 | −132 (−62.0%) |
| Deadline expirations | 1 | 0 | +1 |

GEODE는 top-level call과 repeated read가 적었지만 action wall과 native-log error가
더 많았다. 이것은 서로 다른 scaffold가 낸 descriptive behavior다. Secondary
metric은 frozen accuracy 판정을 뒤집지 않으며, 한 번의 run으로 속도·오류·재독의
원인을 확정하지 않는다.

### Call-count authority

Native log와 normalized trajectory는 다른 단위를 센다. 둘을 같은 `MCP calls`로
섞지 않는다.

| Surface | GEODE | Codex | Meaning |
|---|---:|---:|---|
| Native execution-log calls / errors | 644 / 51 | 678 / 17 | top-level native log row; GEODE internal recovery attempt 제외 |
| Normalized source-trajectory attempts | 645 | 678 | canonical call/result attempt; GEODE recovery projection 포함 |
| Recovery-projected attempts | 1 | 0 | `votenet/requirements_writing`에서 GEODE internal recovery 한 건 |
| Published release call/result pairs | 603 / 603 | 678 / 678 | scope-complete trajectory만; GEODE timeout의 42 attempts는 withheld |

따라서 GEODE의 `644 → 645`는 누락이나 score 보정이 아니라 한 recovery attempt를
별도 canonical pair로 투영한 결과다. `votenet/requirements_writing`의 native
log는 15 calls지만 normalized trajectory는 16 attempts이며, 최종 verifier
결과는 FAIL이다.

## Token accounting — GEODE 29/30, Codex 30/30

GEODE의 `papers/author_folders` timeout은 final native usage completion을 만들지
않았다. 그 row는 `0`이 아니라 **missing/null**이다.

| Metric | GEODE (29 covered) | Codex (30 covered) |
|---|---:|---:|
| Native input | 6,056,271 | 14,625,891 |
| Cache-read | 2,936,320 | 13,301,504 |
| Fresh input (`input-cache_read-cache_write`) | 3,119,951 | 1,324,387 |
| Output | 313,287 | 256,627 |
| Reasoning | 213,167 | 122,757 |

Coverage가 맞지 않고 scaffold별 cache accounting도 다르므로 이 합계를 arm당 평균,
완전한 token cost, billing, token-efficiency claim으로 사용하지 않는다.

## Timeout and stream diagnostics

GEODE `papers/author_folders`는 adapter-owned deadline에서 1,200.005초 후
`right_censored`로 종료됐고 runner envelope은 1,202.773초였다. Bounded cleanup과
verifier receipt가 완결돼 infrastructure-invalid가 아니라 score-bearing FAIL이다.
Native token usage는 null이고 scope-incomplete trajectory는 공개 release에서
제외했다. 같은 task의 Codex arm은 deadline 없이 정상 종료 후 verifier FAIL이었다.

GEODE private stderr에는 동일한
`responses.stream ... incomplete chunked read` adapter diagnostic이 네 task에서
기록됐다. 네 건 모두 runner 밖으로 unrecovered transport error를 내보내지 않았다.

| Task | Final action / verifier outcome |
|---|---|
| `desktop/timeline_extraction` | normal complete / PASS |
| `desktop_template/file_arrangement` | normal complete / PASS |
| `papers/author_folders` | adapter-owned deadline expiration / FAIL |
| `student_database/gradebased_score` | normal complete / PASS |

이 raw stream diagnostic은 provider/runtime 관찰 증거이며 primary denominator나
공개 trajectory payload로 승격하지 않는다. 별도로 위의
`votenet/requirements_writing` 한 건만 normalized recovery-projected tool attempt를
가진다.

## Attempt lineage

선택된 `attempt-001-complete`는 valid/mixed다. 122개 contiguous runner event
(`run_started` 1 + `arm_started` 60 + `arm_finished` 60 + `run_completed` 1),
60개 고유 arm, sequence 0–121, 완전한 reset·identity·verifier join을 가지며
`run_stopped`는 없다. Infrastructure-invalid predecessor나 denominator 대체 retry는
없다.

## Trajectory and publication

| Quality | GEODE | Codex | Total |
|---|---:|---:|---:|
| Source trajectories | 30 | 30 | 60 |
| Published scope-complete trajectories | 29 | 30 | 59 |
| Withheld scope-incomplete trajectories | 1 | 0 | 1 |
| Published canonical events | 1,438 | 1,653 | 3,091 |
| Published exact call/result pairs | 603 | 678 | 1,281 |
| Orphan calls / results | 0 / 0 | 0 / 0 | 0 / 0 |
| Missing call IDs / required turn IDs | 0 / 0 | 0 / 0 | 0 / 0 |
| Replay-complete trajectories | 0 / 29 | 0 / 30 | 0 / 59 |

Publication projection은 **69 public files / 3,065,229 bytes**와
**510 withheld-private files / 41,174,366 bytes**를 모두 SHA-256으로 결속한다.
Source hashes, local-identity scrub, secret scan은 통과했다. Raw model messages,
tool bodies, local paths, account material, runner logs와 native private artifacts는
공개하지 않는다.

- [Artifact commit](https://github.com/mangowhoiscloud/geode-eval-artifacts/commit/1160fecfe4447f0a3f4cf30a414f29c61776d012)
- [Artifact publication PR #25](https://github.com/mangowhoiscloud/geode-eval-artifacts/pull/25)
- [Selected run bundle](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/1160fecfe4447f0a3f4cf30a414f29c61776d012/mcpmark/results-paired/mcpmark-gate0c-filesystem30-gpt54-high-20260813t190922z)
- [Public trajectory receipt/index](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/1160fecfe4447f0a3f4cf30a414f29c61776d012/mcpmark/results-paired/mcpmark-gate0c-filesystem30-gpt54-high-20260813t190922z/trajectory-index.json)
- [GEODE trajectory release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/1160fecfe4447f0a3f4cf30a414f29c61776d012/trajectories/mcpmark-gate0c-gpt54-high-mcpmark-gate0c-filesystem30-gpt54-high-20260813t190922z-geode-20260813T230525Z-9d6773caad04)
- [Codex trajectory release](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/1160fecfe4447f0a3f4cf30a414f29c61776d012/trajectories/mcpmark-gate0c-gpt54-high-mcpmark-gate0c-filesystem30-gpt54-high-20260813t190922z-codex-20260813T230525Z-feeba0d6f5ef)
- [Local publication disclosure receipt](2026-08-14-mcpmark-gate0c-filesystem30-gpt54-high.publication.json)

`runner-result.json`이 primary score의 단일 authority다. `analysis.json`은 그 JSON
Pointer를 읽어 판정하고, `diagnostic-receipt.json`은 secondary behavior,
`trajectory-index.json`과 release manifests는 행동 projection과 공개 무결성을
소유한다. Artifact PR #25는 2026-08-13T23:46:58Z에 commit
`1160fecfe4447f0a3f4cf30a414f29c61776d012`로 merge되었다. Exact-commit remote
read-back은 2026-08-13T23:49:26Z에 69/69 files, 3,065,229 bytes, missing/size/SHA
mismatch 0으로 통과했고 두 release manifest와 모든 privacy scan class도
검증했다. 로컬 disclosure receipt의 source manifest SHA-256은
`e8a10e53e606b22c2d0b7f31fdd0b74b27c336e4d2f081b90d4318c5abe24324`다. 이
manifest 자체는 69-file public allowlist에 포함하지 않았으므로 원격 manifest
URL을 주장하지 않는다.

## Implications and next sequence

1. Gate 0C `k=1`의 frozen 질문에는 답했다. 공통 action deadline에서 GEODE는
   23/30, Codex는 21/30이었고 `-10%p` non-inferiority-style diagnostic threshold를
   통과했다.
2. 승격은 없다. 한 repetition과 서로 다른 scaffold는 정확도 우위, 일반 효율,
   제품 정책을 승인하지 않는다.
3. 다음 score-bearing 단계는 **fresh FS30 `k=3` stability**다. 완료된 `k=1`을
   사후에 `k=3` 일부로 편입하지 않는다.
4. 현재 machine `WHAM=80%`이므로 `k=3` live launch는 차단한다. Five-hour quota
   headroom이 안전해진 뒤에만 새 run roots로 실행한다.
5. Tau2 278-ID/pin/user/budget **no-model preflight는 지금 진행할 수 있다**.
   이것은 순차 score-bearing gate를 건너뛰지 않으며, Tau2 live smoke/full run은
   Gate 0C stability와 별도 PAYG 승인을 기다린다.

## Verification

- Run spec SHA-256: `e4e9abbdd326f093bb1d513aa2800609f1566b0819929f341623011bb5fa1bb0`
- Runner plan SHA-256: `304ba159b8cbf02ff8943d2e5a890a29d842976757f5399f4cba23c313de19b5`
- Runner events SHA-256: `f13029f29aa249730e59154f9be6853a56eb9a1fbec9b163fae78cb643104099`
- Native result SHA-256: `3c5763e4c13ca7a9b39627b30fd35145aebf83e43e8c791a0556e89fc5f4a017`
- Diagnostic receipt SHA-256: `8d64b53f83440b573f762b203942828b9a12e693b5763b28ec4555a0e9637ca4`
- Attempts SHA-256: `04d8afb9c6228b8698080fd9d9e3d48aa5fd3dc684e7c4ba702a4c9389359110`
- Trajectory index SHA-256: `610d2c59ccc46a5713217e87d55589456fbb9c31a90e1b203ad261ce45c03cdb`
- Analysis SHA-256: `78c1931cb3fff215ebdf8c5665ce8106ac4ed965ce31fdfc40c3f0b4f2eb35e9`
- GEODE release manifest SHA-256: `9d6773caad049cf81f67bc6024f8a9c63688e6793af160a2f70fb50bee5ae969`
- Codex release manifest SHA-256: `feeba0d6f5efc62e63321846517210c92453a94cf20e5080772e03db6e53a4b3`
- Publication manifest SHA-256: `e8a10e53e606b22c2d0b7f31fdd0b74b27c336e4d2f081b90d4318c5abe24324`
- Published disclosure receipt SHA-256: `573da4aae34042460eccb467f683bfd7e2621ae3cb85e4385e5adaad183d33ef`
- Eval contract validation: run spec, selected attempts, and analysis passed.
- Runner integrity: 122 events, sequences 0–121, 60/60 arms, no `run_stopped`.
- Trajectory integrity: 59 admitted trajectories, 3,091 events, 1,281 exact pairs,
  zero orphan/missing IDs; one score-bearing timeout trajectory withheld.
- Publication review: 69 public and 510 withheld-private byte/SHA entries accounted
  for; source hash, secret, and local-identity checks passed. Exact-commit remote
  read-back passed at `1160fecfe4447f0a3f4cf30a414f29c61776d012`: 69/69 files,
  3,065,229 bytes, zero missing/size/SHA mismatches.
