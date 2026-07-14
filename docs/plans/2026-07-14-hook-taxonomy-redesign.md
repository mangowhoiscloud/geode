# Hook System 재설계 — 택소노미 통합·명명 규약·디스패치 단일화·emit 계약

> 상태: 구현 중 (2026-07-14, feature/hook-taxonomy-redesign). 파편화 감사
> (v0.99.329 기준, 세션 내 Explore 감사)의 판정을 근거로 한 재설계 결정
> 기록. 구현 완료 후 docs/architecture/hook-system.md에 정본 반영.

## 감사 판정 (근거)

- HookEvent 65종 중 전용 핸들러 보유 42종. 나머지 23종은 범용
  HookPersistenceSink(SQL+transcript)만 통과 — enum이 로그 레벨 역할.
- 완전 사망 2종: TOOL_APPROVAL_GRANTED/DENIED — catalog 호환 규칙이 SQL
  저장까지 제외, 핸들러 0. approval.py의 발화 사이트 전부 no-op 레일.
- PROGRAM_MD_UNREADABLE은 trigger_with_result로 피드백을 기대하지만
  등록된 핸들러가 어디에도 없음 — 피드백 경로가 구조적으로 불발.
- 명명: 7종이 NAME(과거분사) ≠ VALUE(명령형) (SESSION_STARTED="session_start" 등),
  수명주기 슬롯당 동사 5~6종 경쟁, self-improving 도메인은 두 접두 규약 혼재.
- 페이로드: emit은 전부 무타입 dict; 타입 스키마(activity.py 70 Row+30
  Details, 1,086 LoC)는 리더(persistence) 측에만 존재. 같은 이벤트를
  발화 사이트마다 다른 키로 emit — 검증된 침묵 배선 단절 3건:
  ① SUBAGENT_COMPLETED: isolated_execution.py·orchestrator.py 발화가
  bootstrap 핸들러 요구 키(task_id/component/status) 미포함 → early-return
  ② LLM_CALL_ENDED: router/calls/text.py 발화가 session_id/usage 미포함 →
  핸들러 early-return(bootstrap.py:285-287 자기 문서화)
  ③ SUBAGENT_STARTED: orchestrator 발화에 audit 로거 요구 키 부재.
- 디스패치: 공용 fire_hook(dispatch.py)이 있는데 `_fire_hook` 재구현이
  11곳으로 역행(try/except 자체 재구현 5곳, executor.py:134는 데드).
- 레일 중복: 같은 순간이 hook_events+transcript(싱크가 이중 기록)+
  EvidenceLedger+orchestrator 자체 이벤트로 3~5회 기록.

## 결정 (이 PR 스코프)

| # | 결정 | 근거 |
|---|------|------|
| D1 | TOOL_APPROVAL_GRANTED/DENIED enum 삭제 + approval.py 발화 사이트 제거 | 핸들러 0 + 저장 0 = 완전 no-op 레일. APPROVAL_TRANSITION이 정본 |
| D2 | SELF_IMPROVING_AUTO_TRIGGER_* 6종 → SELF_IMPROVING_AUTO_TRIGGER 1종 + payload `stage` 필드(fired/lock_busy/interval_blocked/runner_error/parse_error/max_generation_reached) | 전부 싱크 전용 텔레메트리 — 판별자는 페이로드가 담당 |
| D3 | RULE_CREATED/UPDATED/DELETED 3종 → RULE_CHANGED 1종 + payload `action` 필드 | 싱크 전용, 동일 도메인 |
| D4 | PROGRAM_MD_UNREADABLE의 trigger_with_result 의존 제거 — 일반 notify 발화로 강등(불발 피드백 경로 삭제). trigger_with_result(_async)의 다른 사용자가 없으면 메서드도 삭제(디스패치 표면 6→4) | 등록 핸들러 0인 피드백 계약은 죽은 계약 |
| D5 | NAME↔VALUE 정합: tense-split 7종의 VALUE를 NAME 소문자로 변경(session_start→session_started 등) + 저장 데이터 리더(activity_registry/catalog)에 구값→신값 alias 맵 + alias 맵이 정확히 7종만 커버함을 핀하는 테스트 + "신규 이벤트는 NAME==lower(VALUE), 과거분사" 규약 가드 테스트 | 하나의 enum 안 두 규약 제거. 스토리지 호환은 read-side alias로 |
| D6 | 디스패치 단일화: dispatch.py를 유일 구현으로(sync/async/interceptor 커버), 재구현 5곳을 위임으로 교체, executor.py:134 데드 삭제 | "four copies 제거" 선언의 원상 복구 |
| D7 | emit 계약: dispatch.fire_hook에 페이로드 키 검증(이벤트별 요구 키 카탈로그 대조, 누락 시 WARNING — fail-loud, 차단 아님) + 침묵 단절 3건의 발화 페이로드 수선 | 계약을 emit 측으로; 기존 침묵 실패를 가시화 |
| D8 | docs/architecture/hook-system.md에 규약(명명·emit 계약·등록 표면)과 이벤트 카탈로그 갱신 | 정본 문서 동기화 |

축약 결과: 65 → 56종 (사망 2 + auto_trigger 5 + rule 2 축약, D2/D3의
신설 2종 포함 계산: 65-2-6-3+1+1=56).

## 명시적 보류 (후속 사이클)

- 레일 중복 제거(hook→SQL+transcript 이중 기록, approval 3중 기록,
  orchestrator 이중 행): 소비자(허브·사이트·분석) 영향 조사가 선행 —
  별도 사이클.
- COGNITIVE_* 6종의 기존 이벤트 섀도잉 해소: register_prefix 소비자가
  실사용 중(인지 스냅샷) — 통합은 cognitive 파이프라인 재설계와 함께.
- TOOL_EXEC_FAILED/LLM_CALL_FAILED/TOOL_RESULT_TRANSFORM 호환 중복 정리:
  전용 핸들러 보유 — 핸들러 이관 설계 필요.
- 이벤트↔activity Row 이중 어휘(70 Row 클래스)의 단일화.

## 위험/호환

- 저장된 hook_events 행의 event 문자열: D2/D3/D5는 새 이벤트 문자열을
  쓰기 시작 — 리더는 alias 맵으로 구행 호환. 허브/사이트가 이벤트
  문자열을 직접 grep하는 곳 전수 확인 필요.
- `.geode/hooks/` 파일시스템 훅(discovery.py)이 구 이벤트명을 참조하면
  로드 시 KeyError — discovery에 alias 적용.
- worker(서브프로세스) 경로: build_worker_hooks 최소 번들은 영향 없음.

## 세션 핸드오프 — 재개 절차 (컨텍스트 요약/신규 세션용)

구현 에이전트가 이 워크트리(feature/hook-taxonomy-redesign)에서 D1~D8을
구현 중이거나 완료해 두었다. 재개 시 순서:

1. `git -C .claude/worktrees/hook-taxonomy-redesign status --short`로 에이전트
   산출물 확인 → 설계 문서 D1~D8 대비 완결성 검수(스텁·누락·original residue).
2. 풀 게이트(bare, 파이프 금지): ruff check/format(core tests plugins scripts),
   mypy core/ plugins/, lint-imports, slop ratchet, 영향권 pytest
   (hooks·agent·memory·cli·server·llm·self_improving + tests/integration +
   tests/plugins/crucible — fable5/crucible 소스스캔 함정).
3. **함정**: D6이 core/agent/tool_executor/processor.py를 건드림 →
   plugins/crucible/producers/context_graph.json의 contentSha256 재증명 필요
   (sha256 재계산; agent-fsm-formalization 메모리 참조).
4. CHANGELOG [0.99.330] + 버전 5곳 스탬프(스탬프 직전 origin/develop 재확인 —
   동시세션 선점 시 재범프) + node site/scripts/sync-stats.mjs +
   scripts/check_llms_version.py --fix + Tests 메트릭은 [audit] extra 설치 후 실측.
5. 커밋(한국어 + Co-Authored-By: Claude Fable 5) → push → PR(develop 베이스,
   HEREDOC Summary/Why/Changes/Verification). 체크 0개면 gh pr close/reopen.
6. Codex MCP 사후 점검: model gpt-5.6-sol, effort xhigh, read-only, 관점=누수·
   중복(dedup)·slop+실결함. 발견 반영 후 재게이트.
7. gpt subscription 라이브 E2E: .audit/smoke-archives/2026-07-14-live-e2e-harness-reference.py
   패턴 재사용(bootstrap_builtins→setup_contextvars(load_env=True)→
   AgenticLoop(model="gpt-5.6-sol", provider="openai", source="subscription")).
   hook 재설계 검증 포인트: 축약 이벤트(RULE_CHANGED action, AUTO_TRIGGER stage)
   발화가 sessions.db hook_events에 기록되는지 + D5 신규 VALUE로 저장되는지 +
   required-keys WARNING이 정상 경로에서 안 뜨는지.
8. 머지 플로우: squash→develop, main→develop 프리싱크, develop→main 승격
   (--merge), 실결과 게이트(test $(gh pr checks N | grep -cE 'fail|pending') -eq 0),
   post-merge cleanup(remote/worktree/local 3종), 칸반 Done(임시 워크트리
   detached+push HEAD:main, && 단일 체인, 파이프 금지, 사전 df 확인).
9. 리빌드는 여전히 보류(공유 체크아웃 main 미착륙 커밋 2011e659a — 운영자 결정 대기).
