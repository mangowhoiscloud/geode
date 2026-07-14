# 세션 상태 머신

> 세션 수명주기 오토마타의 정본 서술: 상태 공간, 코드에 실존하는 전이
> 그래프, v0.99.329에서 도입한 강제 장치, 그리고 수용된 갭. inner 루프의
> 종결 오토마타(`TerminationReason` 폐쇄 알파벳, v0.99.328)는 별도
> 머신으로 `core/agent/loop/models.py`에 문서화되어 있다. 이 페이지는
> OUTER 머신 — 영속되는 세션 체크포인트 — 를 다룬다.

## 머신 인스턴스

머신 인스턴스 1개 = 세션 체크포인트 1개 = `session_id` 1개
(`~/.geode/projects/{id}/sessions/<session_id>/`). 나머지 키는 전부
이 인스턴스에 매달린다:

| 키 | 인스턴스와의 관계 |
|---|---|
| `AgenticLoop._session_id` | 라이브 루프의 인스턴스 바인딩; 생성 시 또는 `restore_from_checkpoint`가 설정 |
| 게이트웨이 `session_key` (채널/스레드) | 안정 인스턴스 id로 결정론 매핑(`s-gw-<sha256[:12]>`, v0.99.329) — 메시징 스레드 하나가 턴을 가로질러 머신 인스턴스 하나 |
| `claude_cli_session_id` | 어댑터 쪽 resume 토큰. 인스턴스에 저장될 뿐(SQLite `agent_runtime_state`) 인스턴스 키가 아님 |
| Transcript / evidence ledger | 같은 `session_id`로 키된 write-only 싱크 |
| 스케줄러 레인 키(`sched:<job>`) | 동시성 제어 전용; 발화된 잡마다 새 인스턴스 |

## 상태 공간

`SessionStatus` (`core/memory/session_checkpoint.py`):

| 상태 | 의미 | 터미널 |
|---|---|---|
| ACTIVE | 머신이 턴을 더 받을 수 있음 | 아니오 |
| PAUSED | 운영자 입력(pending ask) 대기로 파킹됨 | 아니오 |
| COMPLETED | 깨끗하게 종료; cleanup 대상 | 예 (reopen 엣지로만 재진입) |
| ERROR | 원샷 실행 사망(타임아웃/미처리 예외) | 예 (reopen 엣지로만 재진입) |

## 전이 그래프 (v0.99.329부터 강제)

```
             save() 매 턴
            +-----v------+
 (부재) ----> A C T I V E <-------------------+
            +--+---+---+-+                    |
               |   |   |                      | resume 턴
   ask 파킹    |   |   | 타임아웃/예외        | (save)
 (스케줄러,    |   |   +---------> ERROR      |
  continuation)|   |                 .        |
               v   |                 . reopen |
           PAUSED  | 정상 종결       .        |
               |   +----------> COMPLETED     |
               |                     .        |
               +---------------------.--------+
                답변 → continuation (PAUSED → ACTIVE)
                                     .
                       reopen(session_id) — 명시 엣지:
                       터미널 인스턴스의 id 지정 resume
```

합법 전이 테이블(`_LEGAL_TRANSITIONS`): ACTIVE → {ACTIVE, PAUSED,
COMPLETED, ERROR}; PAUSED → {ACTIVE, PAUSED, COMPLETED, ERROR}(재파킹
멱등); COMPLETED → {}; ERROR → {}. 터미널 두 상태는 명시 `reopen()` 엣지(id 지정 resume
표면)로만 재진입한다. 그 외의 터미널 상태 쓰기는 경고와 함께 거부된다 —
그래프를 우회한 작성자를 드러내는 fail-loud 신호. 단 `save()`는 터미널
인스턴스에 대해 데이터를 버리는 대신 경고를 남기고 암묵 reopen을
수행한다: 재개된 대화를 잃는 쪽이 시끄러운 엣지보다 나쁘고, 경고와
그것을 핀하는 테스트가 이 엣지를 계속 보이게 만든다.

## 전이 소유자

| 엣지 | 소유자 |
|---|---|
| 부재 → ACTIVE, ACTIVE → ACTIVE | `_lifecycle.save_checkpoint` (매 턴, 전 표면) |
| ACTIVE → PAUSED | 스케줄러 드레인(pending-ask 파킹); 게이트웨이 ask continuation(재질문) |
| ACTIVE → COMPLETED | REPL 클린 종료; 스케줄러 원샷 종결; ask continuation 종결; 게이트웨이 컨텍스트 소진 |
| ACTIVE → ERROR | 스케줄러 드레인 타임아웃/미처리 예외 |
| PAUSED → ACTIVE | ask 답변 → continuation의 매 턴 save |
| COMPLETED/ERROR → ACTIVE | `reopen()` 전용 (IPC id 지정 resume) |

## 머신 상태의 내용물

체크포인트는 완전한 머신 스냅샷이다(v0.99.328 계약): 대화 메시지
(SQLite SoT), `cognitive_state`, 모델/프로바이더, 그리고 대화가 담지
못하는 가드 카운터 `loop_guards`(overthinking 스트릭, LLM 실패 카운터,
diversity 트래커, `ConvergenceDetector`, low-confidence replan arm).
단일 resume 수술은 `AgenticLoop.restore_from_checkpoint(state)`이고,
`apply_guard_state`는 교체 시맨틱이라 레거시 체크포인트가 재사용 루프의
카운터를 상속하지 않고 리셋한다.

## 읽기 경로 (결정론 우선순위)

`SessionCheckpoint.load()`는 순서대로 읽는다: `state.json`(메타데이터,
status는 `SessionStatus`로 정규화 — 미지 문자열은 경고와 함께 ERROR로
강제), SQLite `messages`(대화 SoT), 그리고 DB가 권위 있게 답하지 못할
때에만(이행 전 세션) `messages.json` 핫캐시. 이 폴백은 Phase 1b 이행
부채다: 목표 종착지는 DB 단독 + JSON 캐시의 export 도구 강등이며 후속
과제로 추적한다 — 폴백 자체는 결정론적(같은 입력, 같은 소스)이지만
여전히 이중 SoT 읽기다.

## 주변 상태 (수용, 문서화)

ContextVar(코어 전체 26개)는 횡단 참조(cognitive state, 세션 id,
알림 어댑터, 게이트웨이, 스케줄러)를 주입한다. 이들은 머신 상태가
아니다: `arun()`이 매 턴 세션 스코프 항목을 루프의 복원된 필드에서
재바인딩하므로, `restore_from_checkpoint`가 올바르면 주변 뷰는
수렴한다. 배선 규칙(set/get parity, bootstrap 등록)은 CLAUDE.md의
Wiring Verification 표에 있다. 주변 표면 축소는 오토마타 범위에서
의도적으로 제외한다: 재바인딩 계약이 유지되는 한, 주입 지점 26곳을
재배선하는 위험이 가치를 초과한다.

## 관측성

모든 상태 변화 — 합법 전이, 상태를 바꾸는 save(부재 → ACTIVE, resume의
PAUSED → ACTIVE), `reopen`, 암묵 reopen — 와 모든 거부(REFUSED) 시도가
전이 원장(정상 상태의 매 턴 ACTIVE → ACTIVE save는 의도적으로 제외 —
라운드당 한 행은 신호가 아니라 소음) `<sessions>/transitions.jsonl`에 구조화된 행 하나로
append된다(`{ts, session_id, edge, from, to}`). "이 세션이 어떻게 이
상태에 도달했는가"를 사후에 답할 수 있다. 원장은 append-only이고
best-effort(원장 실패가 전이를 막지 않음)이며
`SessionCheckpoint._record_transition`이 소유한다. 불법 시도는 추가로
WARNING 로그를 남긴다. 이 이벤트들의 hook system 통합은 hook system
재설계 사이클로 의도적으로 미룬다 — 원장이 그 재설계가 소비할 수 있는
안정 기질이다.

## 알려진 갭

- 서로 무관한 동시성 키를 가진 두 작성자(IPC 클라이언트와 게이트웨이,
  같은 id를 resume한 IPC 클라이언트 둘)는 여전히 한 인스턴스 아래에서
  전체 `save()` 히스토리를 교차시킬 수 있다 — status read-check-write는
  flock으로 직렬화했지만, 대화 수준의 last-writer-wins는 레인 키가
  체크포인트 id로 통일될 때까지 남는다(후속 과제).

- 게이트웨이 멀티턴 인스턴스는 턴 사이에 설계상 ACTIVE로 남는다
  (다음 메시지 여부를 게이트웨이가 알 수 없음). 게이트웨이가 소유하는
  터미널 엣지: 컨텍스트 소진 → COMPLETED, ask 파킹 → PAUSED.
- Phase 1b 이행 완료 전까지 `messages.json` 폴백 읽기가 남는다.
- 인터랙티브 REPL은 클린 종료의 `mark_session_completed`에 의존한다;
  강제 종료된 REPL은 ACTIVE로 남는다(재개 가능 — 의도된 동작).
