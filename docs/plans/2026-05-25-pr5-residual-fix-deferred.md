# 2026-05-25 — PR-5 GAP/Dedup/Slop 잔존 fix (deferred — 다음 sprint 흡수)

> Status: **Deferred** (각 항목을 P2/P3/P4 sprint 의 적절 위치에 흡수)
> Framing: PR-5 Codex MCP review 의 미적용 항목 처리 분배
> 관련: PR-5 #1641 의 Codex MCP threadId `019e5dc9-ad11-7f20-b997-8039188b6c2c`

## 1. Background

PR-5 #1641 의 Codex MCP review (GAP=3 / Dedup=5 / Slop=6) 에서 4 critical fix 는 PR 안에 적용 완료 (commit `5cb1869f`). 나머지 미적용 항목은:

| # | Severity | Issue | 처리 위치 |
|---|---|---|---|
| F1 | GAP HIGH | 26 tests 가 12 acceptance 일부만 cover, 통합 테스트 누락 | **P2 sprint 흡수** (test suite 확장) |
| F2 | GAP MEDIUM | variance filter trigger 시 attribution row orphan (audit subprocess 가 row 작성 후 caller 가 filter 결과 봄) | **P2 sprint 흡수** (Pareto archive 와 attribution lifecycle 같이 redesign) |
| F3 | Dedup MEDIUM | `_SIBLING_SOT_ENV_MAP` (runner.py) + `train.py:818-873` literal SOT 분산 | **별 cleanup PR** (shared constants module) — train.py 가 core 를 import 가능한지 lint-imports contract 점검 후 |
| F4 | Dedup MEDIUM | `write_policy` + `write_sibling_in_memory` serialization 중복 | **별 cleanup PR** (`_serialize_policy_payload` helper) |
| F5 | Dedup LOW | `audit_run_id` mint 분산 (apply_proposal vs apply_group_proposals) | **별 cleanup PR** (helper) |
| F6 | Slop LOW | `_FITNESS_RESULT_SENTINEL` 상수 runner.py + train.py 의 string literal | **deferred** (import cycle 위험) |
| F7 | Slop LOW | `unlink` try/except cleanup | **유지** (의도된 defensive log) |

## 2. F1 — Test coverage 통합 테스트

P2-revised sprint 의 test suite 에 통합 테스트 추가:

| 통합 test | 위치 | 검증 |
|---|---|---|
| `test_apply_group_proposals_audit_sequential` | test_baseline_rl_grounding.py 확장 | N audit 가 sequential 실행 (asyncio audit_lane=1 정합) |
| `test_variance_filter_no_sot_commit` | 동상 | filter trigger 시 canonical SoT 안 변경 |
| `test_top1_canonical_commit` | 동상 | top-1 mutation 의 disk write 정확 |
| `test_apply_sibling_same_group_id` | 동상 | applied + applied_sibling row 의 group_id 동일 |
| `test_train_py_w2_hook_group_id_forward` | test_attribution_wiring.py 확장 | GEODE_SIL_GROUP_ID env → attribution row group_id |
| `test_run_once_group_size_branch` | 동상 | group_size>=2 시 propose_group + apply_group_proposals path |
| `test_entry_temperature_guard` | 동상 | apply_group_proposals 진입 시 temperature guard fire |
| `test_distinct_mutation_best_effort` | 동상 | N=2 parallel call 의 distinct response (stochastic) |

총 8 통합 test, ~200 LOC. P2 sprint 의 acceptance criteria 에 추가.

## 3. F2 — orphan attribution row

variance filter trigger 시 sibling audit subprocess 가 이미 attribution row 작성됨 → ledger 에 "filtered group" 의 attribution row 가 noise 로 남음.

해소 옵션 (P2 sprint 의 archive 설계 시 같이 결정):

| 옵션 | 설명 |
|---|---|
| A | pre-audit attribution suppression — train.py W2 hook 에서 group_id 가 있고 sibling 일 때 attribution skip. caller (apply_group_proposals) 가 post-filter 에 직접 write_attribution 호출 |
| B | post-hoc tagging — variance filter trigger 시 caller 가 attribution row 의 마지막 N 개를 `kind="attribution_filtered"` 로 update (append-only 라 append 만 가능, update X) |
| C | ledger documentation — orphan row 가 noise 로 남는 것을 plan §11 에 명시 + reader (outer_bundle 등) 의 filter API 에 group_id+filter_status join |

추천: **C** (가장 단순) — P2 sprint 의 ledger redesign 시 같이 처리.

## 4. F3-F6 — cleanup PRs

별 cleanup PR 로 묶음 (~80 LOC):

- F3: `core/self_improving_loop/sot_env_constants.py` 신규 — `_SIBLING_SOT_ENV_MAP` + `_STRICT_ENV_MAP` shared SoT
- F4: `core/self_improving_loop/policies.py` 에 `_serialize_policy_payload(kind, sections)` helper 추출
- F5: `core/self_improving_loop/runner.py` 에 `_mint_audit_run_id()` helper 추출 + apply_proposal + apply_group_proposals 호출
- F6: deferred (import cycle 위험)
- F7: 유지

## 5. Sprint 진행 권장

| Sprint | 흡수 항목 |
|---|---|
| P2-revised | F1 (test suite 확장) + F2 (orphan attribution, ledger redesign 시) |
| **Cleanup PR (small, ~80 LOC)** | F3 + F4 + F5 |
| Deferred | F6 + F7 |

본 plan 은 미적용 항목의 **분배 라우팅** 만 명시. 실제 작업은 각 sprint 의 acceptance criteria 에 포함.

## 6. Reference

- PR-5 #1641 Codex MCP threadId `019e5dc9-ad11-7f20-b997-8039188b6c2c`
- PR-5 #1641 merge commit `f993e0bb`
- PR-5 plan: `docs/plans/2026-05-25-baseline-fitness-rl-grounding.md`
- [[feedback-post-implementation-verification]] — verification 후 미적용 항목의 명시 영속화
