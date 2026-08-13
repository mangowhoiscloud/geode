---
eval_id: mcpmark-gate0b-tool-cap-gpt54-high-20260814
eval_family: mcpmark
eval_kind: ledger
eval_status: historical
eval_authority: paired-runtime-diagnostic
eval_summary: Prospective five-task k=3 ablation of GEODE's 25K MCP tool-result guard with GPT-5.4/high; unlimited-0 passed 10/15 versus guard-25000 7/15, for a diagnostic-only +0.20 delta.
eval_triggers:
  - MCPMark Gate 0B
  - tool-result guard
  - max tool result tokens
  - GPT-5.4 benchmark
  - paired runtime diagnostic
eval_contracts:
  - docs/eval/schemas/run-spec.schema.json
  - docs/eval/schemas/attempt.schema.json
  - docs/eval/schemas/analysis.schema.json
  - core/observability/schemas/trajectory.schema.json
  - core/observability/schemas/trajectory-release.schema.json
---

# GPT-5.4 MCPMark Gate 0B — 25K tool-result guard ablation

## 판정

동일한 대형 MCP-result task 5개를 GPT-5.4 subscription, effort `high`, 공통
1,200초 action deadline에서 arm별 3회 반복한 prospective paired diagnostic에서
`guard-25000`은 **7/15(46.7%)**, `unlimited-0`은 **10/15(66.7%)**를
기록했다. 사전등록 primary metric은
`(unlimited passes - guard passes) / 15 = 3/15 = +0.20`이므로 가설은
**supported**다.

이 판정은 다섯 task에 한정된 **diagnostic-only** 결과다.
`promotion_authority=none`이며, MCPMark filesystem/standard 30-task 점수나
127-task MCPMark Verified headline, API-key leaderboard 결과, 제품 기본값 변경
근거가 아니다. 같은 task·fixture·model·effort·tool schema·deadline에서
`max_tool_result_tokens`만 바꾼 직접 ablation이라는 범위 안에서만 해석한다.

## Research contract

| Field | Frozen value |
|---|---|
| Research question | 같은 대형 MCP result task에서 25K guard를 제거하면 verifier accuracy와 재독·fresh input·wall이 어떻게 변하는가? |
| Research gap | 이전 30-task 관측은 공통 deadline과 반복된 matched state에서 25K direct MCP-result guard를 분리하지 못했다. |
| Hypothesis | arm별 15 task-repetition에서 `unlimited-0`의 verifier pass가 `guard-25000`보다 많다. |
| Primary metric | `(sum(unlimited-0 passes) - sum(guard-25000 passes)) / 15` |
| Decision rule | unlimited pass가 더 많으면 `supported`, 같으면 `mixed`, 적으면 `not-supported` |
| Secondary | token, wall, MCP call/error, read/re-read, truncation; 원인 설명용이며 primary 판정을 뒤집지 않는다. |
| Invalidation | frozen identity/deadline/cap 결속 불일치, reset·cleanup 실패, native/verifier/trajectory 누락, unrecovered quota·transport escape |
| Authority | `diagnostic`, direct matched ablation, `promotion_authority=none` |

## Frozen identity

| Field | Value |
|---|---|
| Run ID | `mcpmark-gate0b-tool-cap-gpt54-high-20260813t142345z` |
| Execution | 2026-08-13 23:26:32–2026-08-14 02:31:03 KST, 3:04:30 elapsed |
| GEODE | `02f71fae260f050a5ab02af943cfd2244441da7f` |
| Harness | `eval-sys/mcpmark@cd45b7f57923b9b3985467f5139927575f83141c` |
| Verifier compatibility patch | SHA-256 `3f41f13a8edf7b40f411bf0a76412c28fc9629338d9e5051d5633dc064c563e6` |
| Model route | GPT-5.4, subscription, effort `high` |
| Tasks | ordered 5-task subset × 2 arms × 3 repetitions = 30 arms |
| Workload SHA-256 | `b0953abbe11808bd25a03ef97355380ae2a58f0086025cd2557f1cacf32f3a00` |
| Fixture SHA-256 | `c8cfb2815f63ded54a7d79ffed2e0719190bb2dc1e571112a6012f97f95e9f17` |
| Tool schema SHA-256 | `1ad42161dcd16c1d786f859b71a52123fca9daa5c4a4d64864ff240ea150165f` |
| Order | repetition-major serial; task index와 repetition parity로 선행 arm 교대; process·fixture·session 재사용 없음 |
| Deadline | adapter `execute` entry부터 action 종료까지 공통 absolute 1,200초 deadline; verifier는 action 뒤 별도 실행 |
| Arm A | `GEODE_MAX_TOOL_RESULT_TOKENS=25000` |
| Arm B | `GEODE_MAX_TOOL_RESULT_TOKENS=0` |

## Primary result

| Metric | `guard-25000` | `unlimited-0` | Unlimited − guard |
|---|---:|---:|---:|
| Verifier pass | **7 / 15** | **10 / 15** | **+3** |
| Pass rate | **46.7%** | **66.7%** | **+20.0%p** |
| Score-bearing deadline expiration | 2 | 2 | 0 |
| Tool-result truncation | 15 | 0 | −15 |

Paired bucket은 `both-pass=7`, `both-fail=5`, `unlimited-only-pass=3`,
`guard-only-pass=0`이다. 즉 guard가 이기고 unlimited가 실패한 pair는 없었다.
세 discordant pair는 `individual_comments` 1회와
`organize_legacy_papers` 2회다.

| Repetition | `dispute_review` | `individual_comments` | `solution_tracing` | `author_folders` | `organize_legacy_papers` |
|---:|---|---|---|---|---|
| 1 | both pass | both pass | both pass | both fail | unlimited only |
| 2 | both pass | unlimited only | both fail | both fail · both timeout | both fail |
| 3 | both pass | both pass | both pass | both fail · both timeout | unlimited only |

## Task-level stability

| Task | `guard-25000` | `unlimited-0` | Difference |
|---|---:|---:|---:|
| `legal_document/dispute_review` | 3/3 | 3/3 | 0 |
| `legal_document/individual_comments` | 2/3 | 3/3 | +1 |
| `legal_document/solution_tracing` | 2/3 | 2/3 | 0 |
| `papers/author_folders` | 0/3 | 0/3 | 0 |
| `papers/organize_legacy_papers` | 0/3 | 2/3 | +2 |

이 표는 removal 효과가 모든 task에서 균일하지 않았음을 보여준다.
`dispute_review`는 양 arm 모두 안정적으로 통과했고, `author_folders`는 어느
arm에서도 통과하지 못했다. 따라서 +0.20을 “큰 context가 항상 정확도를 높인다”로
일반화하지 않는다.

## Full non-token behavior

아래 값은 score-bearing timeout 네 개를 포함한 **15/15 arm 전체**에서
집계했다. Timeout 동안 남은 action log와 absolute-deadline receipt도 포함한다.

| Metric | `guard-25000` | `unlimited-0` | Change |
|---|---:|---:|---:|
| Action elapsed | 6,076.699s | 4,910.217s | −1,166.482s (−19.2%) |
| Runner envelope | 6,119.096s | 4,951.086s | −1,168.010s (−19.1%) |
| MCP calls | 443 | 255 | −188 (−42.4%) |
| MCP errors | 75 | 27 | −48 (−64.0%) |
| Read references | 532 | 315 | −217 (−40.8%) |
| Unique read references | 321 | 252 | −69 (−21.5%) |
| Repeated read references | 211 | 63 | −148 (−70.1%) |
| Tool-result truncations | 15 | 0 | −15 |
| Deadline expirations | 2 | 2 | 0 |

Unlimited arm은 accuracy뿐 아니라 action wall, tool calls, tool errors, repeated
reads가 함께 감소했다. 특히 guard arm은 15/15에서 정확히 한 번씩 절삭됐고,
unlimited arm은 0/15였다. 다만 이 secondary pattern은 작은 stochastic subset의
설명 증거일 뿐이며 primary 가설이나 제품 정책 권한을 확장하지 않는다.

## Token accounting — exact 13/15 only

`author_folders` repetition 2·3의 양 arm, 총 네 score-bearing timeout은
right-censored trajectory와 유효한 FAIL receipt를 남겼지만 final native usage
completion을 만들지 않았다. 이 네 row의 token은 `0`이 아니라 **missing/null**로
분류한다. 따라서 아래 합계는 arm별 **13/15 exact token-covered attempts**만
비교하며, 15회 평균이나 완전한 token cost로 해석하지 않는다.

| Metric | `guard-25000` | `unlimited-0` | Change |
|---|---:|---:|---:|
| Token-covered attempts | 13 / 15 | 13 / 15 | matched |
| Native input | 6,133,392 | 2,980,965 | −3,152,427 (−51.4%) |
| Cache-read | 2,351,104 | 778,240 | −1,572,864 (−66.9%) |
| Fresh input (`input-cache_read-cache_write`) | 3,782,288 | 2,202,725 | −1,579,563 (−41.8%) |
| Output | 146,710 | 101,113 | −45,597 (−31.1%) |
| Reasoning | 107,425 | 74,764 | −32,661 (−30.4%) |

동일한 13 pair에서 unlimited의 token 총량이 더 작았다는 관측은 call·재독 감소와
일관되지만, subscription usage는 billing 지표가 아니며 네 timeout의 미완성 사용량을
포함하지 않는다.

## Timeout classification and attempt lineage

네 deadline expiration은 양 arm의 `papers/author_folders` repetition 2·3에서
발생했다. 공통 owner가 1,200초 expiry를 증명했고 fixture cleanup과 verifier
receipt가 완결됐으므로 infrastructure-invalid가 아니라 score-bearing FAIL이다.
반대로 scope-incomplete trajectory 네 개는 stable public trajectory로 승격하지
않고 원본 digest만 결속했다.

선택된 `attempt-001-complete`는 62개 contiguous runner event
(`run_started` 1 + `arm_started` 30 + `arm_finished` 30 + `run_completed` 1),
30개 고유 arm, 완전한 reset·identity·verifier join을 가진 valid/mixed attempt다.

이전 run ID `mcpmark-gate0b-tool-cap-gpt54-high-20260813t131422z`의
`attempt-000-timeout-classification-invalid`는 runner가 canonical
`time_budget_expired`를 semantic timeout으로 인정하지 못해 sequence 14에서
중단됐다. 여섯 arm이 실행됐지만 primary denominator를 만들지 않았고
`runner-timeout-outcome-classification`, validity `invalid`, outcome `unknown`,
selected `false`, denominator contribution `0`으로 보존했다. 서로 다른 run ID이므로
current attempt의 parent로 위조하지 않고 `prior-run-lineage.json`으로 연결한다.

## Trajectory and publication

| Quality | Value |
|---|---:|
| Reviewed releases | 6 (3 repetitions × 2 arms) |
| Published scope-complete trajectories | 26 / 30 |
| Withheld scope-incomplete timeout trajectories | 4 / 30 |
| Canonical events in published trajectories | 1,258 |
| Exact tool call/result pairs | 525 / 525 |
| Orphan calls / results | 0 / 0 |
| Missing call IDs / required turn IDs | 0 / 0 |
| Replay-complete trajectories | 0 / 26 |

공개 projection은 selected result bundle 9개, prior invalid lineage bundle 4개,
reviewed trajectory 파일 32개로 총 **45 files / 1,414,288 bytes**다. Raw
messages, execution logs, native meta/results, local paths와 subscription diagnostics
등 **296 files / 113,118,951 bytes**는 `withheld-private`로 SHA-256만 결속했다.
공개 전 source hash, identity/secret scan은 통과했다.

- [Selected run bundle](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/17133f0c8e893b6d765fcef69712ba0867bd573a/mcpmark/results-paired/mcpmark-gate0b-tool-cap-gpt54-high-20260813t142345z)
- [Infrastructure-invalid predecessor](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/17133f0c8e893b6d765fcef69712ba0867bd573a/mcpmark/results-paired/mcpmark-gate0b-tool-cap-gpt54-high-20260813t131422z)
- [Trajectory index](https://github.com/mangowhoiscloud/geode-eval-artifacts/blob/17133f0c8e893b6d765fcef69712ba0867bd573a/mcpmark/results-paired/mcpmark-gate0b-tool-cap-gpt54-high-20260813t142345z/trajectory-index.json)
- [Publication disclosure receipt](2026-08-14-mcpmark-gate0b-tool-cap-gpt54-high.publication.json)

`runner-result.json`이 primary score의 단일 authority다. `analysis.json`은 그
JSON Pointer를 읽어 판정하고, `diagnostic-receipt.json`은 secondary behavior만
소유한다. Human report와 trajectory는 score authority를 복제하지 않는다.

## Implications and next sequence

1. Gate 0B의 frozen question에는 답했다. 이 다섯 대형-result task에서는 25K
   guard 제거가 pass를 3개 늘렸고, full non-token behavior도 더 짧고 단순했다.
2. 제품 기본 cap 변경은 보류한다. 다섯 task·k=3 diagnostic은 안전성, 일반
   workload, memory pressure, full-suite stability를 대표하지 않는다.
3. 기존 sequential plan대로 Gate 0C common-deadline MCPMark FS30 `k=1`을 먼저
   실행한다. Infrastructure-clean이고 quota-safe일 때만 fresh FS30 `k=3` stability로
   확장한다.
4. 다음은 Tau2 base 3-domain no-model preflight다. Native-user headline은 별도
   PAYG 승인을 받은 뒤 smoke → full-1 → four trials 순서로 진행한다.
5. 그 뒤 MCPMark Verified service canary → non-WebArena 106 internal subset → full
   127, 마지막으로 Terminal-Bench 2.1 oracle smoke → 1–3 tasks → 89 tasks를 진행한다.

## Verification

- Run spec SHA-256: `421f695062f7936ef28c991b32077f5402205d41d4bcc4da0be5240d56a1264c`
- Runner plan SHA-256: `65212bf3b57840a2cb4d3a14719e6956b06b0dfc32e32fef4c8c4dccc868eeb0`
- Runner events SHA-256: `c10f09372b4f7da6c0e0a68bdb5ec0a2ebf989f3d4deafa04932911b3e387f71`
- Native result SHA-256: `04f39957cfd7b3a603b54f58d45a6171be9caf156a273314b74bae33e95611ed`
- Diagnostic receipt SHA-256: `b6e1e46425eb2c8f945d68b057bc12fe807fe052764b066ce080a4192f420003`
- Attempts SHA-256: `a2d51de7c499c4eafeddfa64828e3a8f9cbf468cbfc03f5c5fc6a05e54f9bcba`
- Prior-run lineage SHA-256: `41c4e255e451ef90caffa6a70b50d72cfeae59c6fb18bd0f3bb66e5759081c2b`
- Trajectory index SHA-256: `118ceabe739093f62d8ff2c9824cbdee3c729162e71e3df344ee89657e140902`
- Analysis SHA-256: `0c466c572dc769f5a25f5d6a1f5432775e5112de8c444372fdfbc1ada012be68`
- Publication manifest SHA-256: `fc152fa526d5db9b741d981c897b7c1cc4f87905489ea191e0eff02d8103a802`
- Published disclosure receipt SHA-256: `c771dbc527cc9dfe9f7df501f9b1a2fcc422103b0d2482de5b503293dd2f3060`
- Eval contract validation: run spec, selected/current attempts, prior invalid attempts, and analysis passed.
- Runner integrity: 62 events, sequences 0–61, 30/30 arms, no `run_stopped`, no backup residue.
- Trajectory integrity: 6 manifests, 26 admitted trajectories, 1,258 events, 525 exact pairs, zero orphan/missing IDs.
- Publication review: 45 public byte/SHA entries and 296 withheld byte/SHA entries accounted for; source hash and secret/identity scans passed.
