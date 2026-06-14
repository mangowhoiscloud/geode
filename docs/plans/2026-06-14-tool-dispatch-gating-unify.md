# Tool dispatch + safety-gating unification

> **작성**: 2026-06-14
> **운영자 지시**: "computer-use 외에도 다른 툴에서 비슷한 현상 가능 → 상위 레벨로 제약을 묶어 리팩토링. 패치식 수정 금지(재발). 레거시 정리." cleanup PR(Socratic Q4 최소변경 미적용, [[feedback_cleanup_no_minimal_change]]).

## 0. 근본 원인 (검증됨)

`core/agent/tool_executor/executor.py::aexecute` 디스패치가 **3갈래로 분기**, 그 중 DANGEROUS가 실행을 short-circuit:
1. `if tool_name in DANGEROUS_TOOLS: return await self._execute_dangerous_async(...)` (172행) — 그런데 `_execute_dangerous_async`(428행)는 **`run_bash`만 구현**, 나머지(`computer`)는 `{"error":"Dangerous tool not implemented"}` → 등록된 `handle_computer` 핸들러에 **영영 도달 못 함**. computer-use가 PR-COMPUTER-USE-A(v0.99.208) 후에도 dispatch에서 막혀 비기능.
2. `apply_safety_gates_async` (175행) — write/expensive/MCP 게이트.
3. `delegate_task` 특수 분기 + handler/MCP 디스패치.

→ 안전 게이팅이 분산(_execute_dangerous + apply_safety_gates + dangerous early-return)되고, DANGEROUS 툴은 **gate가 아니라 실행 메서드로** 라우팅돼 handler를 가린다. 신규 DANGEROUS/특수 툴마다 같은 갭 재발.

## 1. 설계 — 단일 파이프라인 (classify → gate → dispatch)

`aexecute`를 3단 균일 파이프라인으로:

1. **cancellation 체크** (유지).
2. **GATE** (`_gate_async`, 단일 진입): 안전등급별 승인. rejection이면 early-return, 아니면 통과.
   - DANGEROUS: `run_bash` → bash 승인(`is_bash_auto_approved`/`request_bash_approval_async`, skip-aware); `computer` → 세션-1회 승인(MCP 패턴 미러, skip/hitl auto). **승인만, 실행 X.**
   - WRITE/EXPENSIVE/MCP → 기존 `apply_safety_gates_async`.
3. **DISPATCH** (`_dispatch_async`, 균일): `delegate_task` → `_aexecute_delegate`; `run_bash` → `_run_bash_exec_async`(validate+subprocess, **승인 분리됨**); 그 외 → `_handlers[tool]`(computer 포함, 이제 도달) → MCP fallback → unknown. deadline+spinner 공통.

핵심: DANGEROUS가 더는 실행 메서드로 short-circuit하지 않음 → gate 통과 후 **모든 툴이 동일 dispatch**를 거쳐 handler에 도달. computer-use는 부수효과로 동작.

## 2. 변경

| 파일 | 변경 |
|---|---|
| `core/agent/tool_executor/executor.py` | `aexecute` = classify→gate→dispatch. `_gate_async`(통합) + `_gate_dangerous_async`(bash/computer 승인). `_dispatch_async`(균일) + `_run_bash_exec_async`(validate+subprocess, 승인 제거). **`_execute_dangerous_async` 제거**(folded). `_execute_bash_async` → `_run_bash_exec_async`로 승인 분리. |
| `core/agent/approval.py` | computer 세션-승인 헬퍼(`is_computer_approved`/`mark_computer_approved` or 통합), skip-aware. 미사용 sync 경로(`apply_safety_gates`/`confirm_write`/`confirm_cost` sync + executor `_confirm_*`)는 callsite 감사 후 정리([[feedback_audit_before_migrate]]). |
| 테스트 | computer가 handle_computer에 도달(가장 중요), run_bash 승인분리 후에도 validate/deny/timeout 유지, gate 통합 동치, 미구현 DANGEROUS는 honest error(짝 없는 dispatch silent skip 금지). |

## 3. 검증
- 단위: dispatch 도달(computer→handler), bash 승인분리 동치(auto/deny/validate-block), gate 통합(write/expensive/mcp 동치), skip-permissions 연동(이전 PR), delegate 경로 유지, unknown/ MCP fallback 유지.
- 게이트: ruff/format/mypy(457)/lint-imports/pytest + Codex(gpt-5.5).
- 레거시 제거는 callsite 감사(re-export/test/write-only가 grep 환상) 후.

## 4. computer 승인 모델
continuous-control이라 per-action HITL 비현실. `computer_use_enabled` opt-in = consent. gate: skip/hitl≤1 auto, 아니면 세션-1회 승인(MCP `is_mcp_approved` 미러) 후 remember. (운영자가 더 강한 게이트 원하면 후속.)

## 4b. 관련 — `./state` 재배치 (별도 PR, 운영자 결정 2026-06-14)
운영자: `./state`(repo-루트, self-improving loop 상태)를 **tracked SoT vs 런타임 분리**. git-tracked 정책/베이스라인 SoT(mutations.jsonl·baseline_archive.jsonl·baseline_epochs.json·policies/*.json)는 의미있는 tracked 위치로, gitignored 런타임(seed_generation/<run_id>/·handoff/)은 ~/.geode 또는 state/runtime으로. blast radius=`core/paths.py` 상수 다수 + `GEODE_STATE_ROOT` 계약 + tests/fixtures + tracked 데이터. **executor dispatch와 도메인이 달라 별도 PR**로 진행(이 PR 이후).

## 5. Status — ✅ DONE (v0.99.211)
| 항목 | 상태 |
|---|---|
| aexecute classify→gate→dispatch | ✅ `_gate_async` 단일 게이트 → 균일 dispatch |
| _gate_dangerous (bash 검증+승인 분리 + computer) | ✅ |
| run_bash exec 분리 (`_run_bash_exec_async`, 승인 제거) | ✅ |
| _execute_dangerous_async 제거 (dispatch legacy) | ✅ + executor `_confirm_write`/`_confirm_cost` dead-wrapper 제거 |
| computer→handler 도달 (computer-use 부활 완결) | ✅ 핵심 |
| computer 세션-1회 승인 (`confirm_computer_async`, skip/hitl aware) | ✅ |
| 테스트 | ✅ `test_tool_dispatch_unify.py` (computer 도달/bash 분리/honest-error/세션승인/gate 통합) |
| **sync approval API 제거** | **별도 PR로 분리** — B6 병렬승인 인시던트 테스트(`test_parallel_approval` source-inspection 불변식 + 스레드 레이스) + test_hitl_level 재작성 유발, 안전크리티컬이라 dispatch와 섞지 않음. dead-in-production이나 테스트가 동작 핀(tested-dead [[feedback_audit_before_migrate]]) → async 마이그레이션 동반한 전용 PR. |
