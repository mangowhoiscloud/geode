# Trajectory 재설계안 — 키 정렬 · 어휘 통합 · 배선 · K3 규격

작성 2026-07-29. 모든 수치는 이 날짜의 로컬 저장소 실측이며 분모를 함께 적는다.

**검증 이력.** 초안을 Codex(`codex exec`, gpt-5.6-sol)가 독립 재측정했고 6건이 뒤집혔다. 뒤집힌 항목은 모두 이 문서에서 직접 재확인한 뒤 반영했으며, 표본 일반화가 전수에서 무너진 §6.3이 그중 가장 크다. 표본으로 잰 값은 표본임을 명시하고, 결론에 쓰는 값은 전수로 다시 잰다.

---

## 0. 측정 기준선

### 0.1 저장소 인벤토리

| 저장소 | 규모 | identity 키 | call id | reasoning |
|---|---|---|---|---|
| `sessions.db:messages` | 48,435행 / 8,493 세션 | `session_id`, `seq`, `tool_call_id` | **있음** | 컬럼만, 0% |
| `transcripts/*.jsonl` | 14,515 세션 | `session_id`, `seq` | 없음 | 이벤트 자체 없음 |
| `evidence/*.jsonl` | 10,312 세션 | `session_id`, `seq`, `kind` | 없음 | 없음 |
| `sessions.db:hook_events` | 2,119행 / 9 세션 | `session_key`, `run_id`, `task_id` | 없음 | 없음 |
| `runs/*.jsonl` | 최상위 21 파일 / 21 session_key (`_archive` 포함 927) | `session_key`, `run_id`, `node` | 없음 | 없음 |
| `sessions.db:run_lineage` | **0행** | `run_id`, `parent_run_id`, `root_run_id` | — | — |
| `~/.codex/sessions` | 1,740 파일 (측정 중 증가, §0.4) | `session_id`, `turn_id`, `call_id`, `forked_from_id` | 있음 | §0.4 참조 |

### 0.2 join 실측 — 두 분모를 모두 적는다

| 관계 | 교집합 | 좌측 기준 | transcript 기준 |
|---|---|---|---|
| `messages` ∩ `transcript` | 7,061 | **83.1%** (/8,493) | 48.6% (/14,515) |
| `messages` ∩ `evidence` | 297 | 3.5% (/8,493) | — |
| `hook.session_key` ∩ `transcript` | 8 | **89%** (/9) | 0.06% |
| `runs.session_key` ∩ `transcript` | 19 | **90%** (/21) | 0.13% |
| `runs.session_key` ∩ `messages` | 16 | 76% (/21) | — |

### 0.3 이 문서가 뒤집는 이전 판단

세 건 모두 같은 원인이다. 교집합을 **transcript 14,515라는 남의 분모**로 나눠 낮은 비율을 만든 뒤 "네임스페이스가 다르다"는 서사를 붙였다.

| 이전 진술 | 실제 |
|---|---|
| "hook은 다른 네임스페이스, 0.06%" | `session_key`의 89%(8/9)가 `session_id`와 문자 일치 |
| "`runs`는 구조적으로 분리된 레인, 0.13%" | `session_key`의 90%(19/21)가 일치. 안 붙는 둘은 `subject:gateway:analysis`와 `test` |
| "GEODE는 call id가 없어 순서로 결속해야 한다" | `transcript JSONL`에만 없다. `messages`는 **99.3% id 결속** |

**네임스페이스 문제는 존재하지 않는다.** 다섯 저장소가 이미 같은 `session_id`를 쓰고, 이름만 `session_key`로 갈라져 있다.

### 0.4 Codex 지표의 분모 — 두 모집단을 구분한다

Codex 측 백분율은 무엇을 세느냐에 따라 크게 갈리므로 분모를 명시하지 않으면 인용할 수 없다.

| 지표 | 모집단 | 값 |
|---|---|---|
| `turn_id` 보유 | 최근 150파일 **투영된 메시지** | 31,868/32,141 = 99.2% |
| `turn_id` 보유 | 전 파일 **raw response item** | 200,215/304,122 = 65.8% |
| reasoning summary 판독 | 최근 300파일 **reasoning item** | 4,955/35,999 = 13.8% |
| reasoning summary 판독 | 전 파일 **reasoning item** | 5,141/61,104 = 8.4% |
| `call_id` 보유 | 전 파일 tool item | 87,345/87,345 = **100%** |

투영 메시지 기준이 높은 것은 `turn_id`를 갖는 항목이 메시지 경계를 여는 항목에 몰려 있기 때문이다. 두 수 모두 맞고 재는 대상이 다르다.

`~/.codex/sessions` 파일 수는 1,740에서 1,742로 늘었다. 이 문서를 검증하는 Codex 세션 자신이 파일을 만들었기 때문이며, 관측이 관측 대상을 늘리는 경우다.

---

## 1. 진단 — 두 저장소는 **경쟁하는 정본이 아니라 다른 물건이다**

> **초판 정정 (2026-07-29, 2차).** 이 절은 원래 "정본을 `messages`로 옮긴다"고 제안했다. §6.3의 36건을 파고든 결과 **그 제안은 틀렸다.** `messages`는 이력이 아니라 살아 있는 상태의 거울이며, 옮기면 데이터를 잃는다. 아래는 정정된 진단이다.

### 1.1 `messages`는 append-only가 아니다

`SessionManager.save_messages`는 `(session_id, seq)`로 UPSERT한 뒤 **현재 목록에 없는 `seq`를 모두 DELETE한다**(`core/memory/session_manager.py:883–919`).

```sql
INSERT INTO messages (...) VALUES (...)
ON CONFLICT(session_id, seq) DO UPDATE SET ...
-- 그리고
DELETE FROM messages WHERE session_id = ? AND seq = ?   -- valid_seqs 밖의 모든 seq
```

`seq`는 실행마다 0에서 다시 시작하므로, 새 실행이 같은 `seq` 자리를 덮어쓰고 남는 꼬리를 지운다. **`messages`는 마지막 체크포인트의 메시지 목록이지 대화 이력이 아니다.**

### 1.2 transcript는 실행을 누적한다

한 `session_id`의 transcript 파일에는 `session_start`/`session_end` 쌍이 여러 번 들어간다. 같은 id로 다시 실행하면 같은 파일에 이어 붙는다.

실측 `s-33c24db49548`은 실행 11회, 툴 호출 18건이다. `messages`에는 5건만 남았고 그 5건은 run 5·7·10 소속이며 **run 2(11건)와 run 3(2건)은 덮여 사라졌다.**

### 1.3 그러므로 정본은 transcript다

| | `transcripts/*.jsonl` | `sessions.db:messages` |
|---|---|---|
| 시간 축 | **전 실행 누적 (append-only)** | 마지막 체크포인트만 (mutable mirror) |
| 다중 실행 세션 | 완전 | **소실** |
| 툴 인자 | 300자 절단, 6.93% 파싱 불가 | 전체 JSON |
| 툴 결과 | `summary` 문자열만 | `tool_result` block 전문 |
| 호출-결과 결속 | 순서 추정 (모호 0.03%) | `tool_use_id` 99.3% |
| 병렬 호출 | 행 순서로 추정 | block 배열로 명시 |

**시간 축에서는 transcript가, 턴 내부 해상도에서는 `messages`가 우월하다.** 어느 쪽도 상위집합이 아니며 교체가 아니라 결합이 답이다.

### 1.4 검증

전수 7,061 교집합 세션에서 툴 호출 수 불일치는 36건(0.51%)이고, `session_start` 횟수가 판별한다.

| `session_start` | 세션 | 불일치 | 불일치율 |
|---|---:|---:|---:|
| 1회 | 6,787 | 5 | **0.07%** |
| 2회 이상 | 274 | 31 | **11.31%** |

160배 차이다. 마지막 run만 비교하면 불일치가 201건(2.85%)으로 **늘어나는데**, `messages`가 "마지막 실행"조차 아니라 seq 자리별로 덮인 혼합물이기 때문이다.

### 1.5 참고 — `messages`의 블록 형태

`messages`가 보관하는 provider 원본 블록은 다음과 같다. Assistant 행에 `tool_use`가, 이어지는 `role='user'` 행에 `tool_result`가 들어간다(프로토콜 규약).

```
seq=2 assistant  content=[{"type":"tool_use","id":"call_IMTC…","name":"web_fetch","input":{…}}]
seq=3 user       content=[{"type":"tool_result","tool_use_id":"call_IMTC…","content":"…"}]
                 tool_call_id=call_IMTC…
```

검증: block 배열 17,856개 파싱 **실패 0건**, `tool_use` 5,549 / `tool_result` 5,512, id 결속 5,511. 결과 없는 호출 37건(0.7%)은 중단된 세션이고, 호출 없는 결과는 **0건**이다.

세션 집합도 서로를 포함하지 않는다. `messages`에만 있는 세션이 1,432개, `transcript`에만 있는 세션이 7,454개다.

---

## 2. 키 정렬 — 4단 identity 모델

Codex를 참조 구현으로 삼는다. Codex는 `session_id → turn_id → call_id`에 `forked_from_id` lineage를 더한 4단이며, 실측 채움률이 `turn_id` 99.2%, `call_id` 100%다.

### 2.1 목표 모델

| 층 | 정본 이름 | 현재 GEODE | 조치 |
|---|---|---|---|
| thread | `session_id` | `session_id`(3곳) / `session_key`(2곳) | **이름 통일**. `session_key`를 alias로 강등 |
| **run** | `run_id` | transcript의 `session_start` 경계, `hook_events.run_id` | **읽기 층에서 번호 부여** (구현됨) |
| turn | `turn_id` | 없음 | 신규 발급 필요 |
| call | `call_id` | `messages.tool_call_id`에만 존재 | transcript writer까지 **관통** |
| lineage | `parent_session_id` | `hook_events.task_id`(16행) | **개명**. `run_lineage`는 폐기 |

> **초판 정정.** 초판은 `run_id`를 turn 키로 승격하자고 했다. §1.2가 밝힌 대로 `run_id`는 **실행 경계**이지 턴 경계가 아니다. 한 실행 안에 여러 턴이 있으므로 두 층은 별개이며, turn 키는 여전히 없다.

### 2.2 각 결정의 근거

**`session_key` → `session_id`.** 같은 값을 두 이름으로 부르는 것이 §0.3의 오독을 만든 직접 원인이다. 컬럼을 즉시 개명하면 기존 인덱스와 쿼리가 깨지므로, 읽기 층에서 `session_id`로 노출하고 쓰기 층은 다음 스키마 버전에서 옮긴다.

**`run_id`는 실행 키다.** 입도 실측이 뒷받침한다. `run_id` 하나가 두 `session_key`에 걸치는 경우가 **0건**이라 session 안에 완전히 중첩되며, delegate 세션은 1:1이고 orchestrator 세션은 25개 run을 갖는다. Transcript 쪽 대응물은 `session_start`/`session_end` 경계이고, 읽기 층이 이것을 세어 `run` 번호를 붙인다.

**turn 키는 여전히 없고 새로 발급해야 한다.** `run_id`로 대신하려던 초판의 판단은 실행과 턴을 혼동한 것이다. 발급 지점은 agent loop의 턴 시작이며, Codex의 `turn_id`(99.2% 채움)와 Hermes의 `turn_id`+`api_request_id` 분리가 선례다. 이 작업은 쓰기 층을 건드리므로 `call_id` 관통 이후로 미룬다.

**`task_id` → `parent_session_id`.** 이 컬럼은 죽지 않았다. 16행 전부가 `subject:gateway:analysis`에서 delegate 8개를 가리키는 `subagent_started`/`subagent_failed`이며, Codex의 `parent_thread_id`와 같은 역할이다. 1%라는 채움률이 낮아 보이는 것은 spawn이 드물기 때문이지 기능이 없어서가 아니다. 이름이 `task_id`인 탓에 내가 한 번 "session_key 중복"으로 오독했다.

**`run_lineage` 폐기.** 9개 컬럼(`run_id`, `parent_run_id`, `root_run_id`, …)을 갖고 **0행**이다. `parent_session_id`와 역할이 같으므로 둘 중 하나만 남긴다. 실제로 채워지는 쪽을 남기는 것이 판정 기준이다.

---

## 3. 어휘 통합

### 3.1 `event`와 `action`은 한 어휘의 두 표기다

33개 `(event, action)` 조합 중 `_`를 `.`로 바꾸면 일치하는 것이 **1,809/2,119 = 85%**다. 나머지 15%는 시제·접두사 차이뿐이다.

더 중요한 것은 **`event`에 시제 중복이 있다**는 사실이다. 33종이 26종 `action`으로 접히며, 남는 7종은 같은 사건의 다른 표기다.

| 중복쌍 | 건수 | 공통 `action` |
|---|---|---|
| `llm_call_end` / `llm_call_ended` | 43 / 27 | `llm.call.ended` |
| `llm_call_start` / `llm_call_started` | 43 / 27 | `llm.call.started` |
| `tool_exec_end` / `tool_exec_ended` | 49 / 14 | `tool.exec.ended` |
| `tool_exec_start` / `tool_exec_started` | 49 / 14 | `tool.exec.started` |
| `session_end` / `session_ended` | 20 / 8 | `session.ended` |
| `session_start` / `session_started` | 20 / 8 | `session.started` |
| `turn_complete` / `turn_completed` | 20 / 8 | `turn.completed` |

**이 7쌍은 이미 `core.hooks.system.LEGACY_EVENT_VALUES`에 alias로 등재돼 있다.** 읽기 층은 접고 있는데 쓰기 층이 여전히 둘 다 방출한다. 새 맵을 만들 필요가 없고, 방출 지점만 정본 하나로 모으면 된다.

Alias 맵의 항목은 8개이며 여덟 번째 `llm_call_retry → llm_call_retried`는 현재 데이터에 중복쌍으로 나타나지 않는다(`llm_call_retry` 1건뿐). 관측된 중복은 7쌍이고 등재된 alias는 8개다.

### 3.2 조치 — **이미 되어 있다. 할 일이 없다.**

> **초판 정정.** 초판은 "쓰기 층이 여전히 둘 다 방출한다"며 통합을 제안했다. 확인해 보니 **틀렸다.**

`HookEvent` enum은 값 56개가 전부 고유하고 **과거형만 존재한다.** 짧은 형태(`session_start`, `llm_call_end`)는 enum에 없다. 시간 축으로 보면 전환 시점이 정확히 드러난다.

| `event` | 건수 | 기간 | `schema_version` |
|---|---:|---|---|
| `llm_call_end` | 43 | 07-13 08:30 ~ 07-15 11:26 | v1 |
| `llm_call_ended` | 27 | 07-15 15:51 ~ 07-15 17:48 | **v2** |
| `session_start` | 20 | 07-13 ~ 07-15 11:26 | v1 |
| `session_started` | 8 | 07-15 15:51 ~ | **v2** |
| `tool_exec_end` / `tool_exec_ended` | 49 / 14 | 동일 경계 | v1 / v2 |
| `turn_complete` / `turn_completed` | 20 / 8 | 동일 경계 | v1 / v2 |

**2026-07-15에 v1 → v2 마이그레이션이 이미 일어났고** `LEGACY_EVENT_VALUES`는 그때 만든 alias 맵이 설계대로 동작하는 것이다. 33종은 현재 파편화가 아니라 **두 스키마 버전이 한 테이블에 공존하는 역사**다.

남는 조치는 두 가지뿐이다. 첫째로 v1 행이 retention으로 자연 소멸하면 alias 맵을 지운다. 둘째로 `event`와 `action`이 여전히 같은 정보를 두 표기로 들고 있으므로(`_`↔`.` 치환으로 85% 일치), 저장은 `action` 하나로 줄이고 `event`를 파생시킨다. 이것은 컬럼 하나를 없애는 정리이지 파편화 해소가 아니다.

### 3.3 죽어 보이지만 죽지 않은 컬럼 — 삭제하지 않는다

| 컬럼 | 실측 | 판정 |
|---|---|---|
| `block_reason` | 0% 채움 | **삭제 금지.** interceptor가 실제로 차단한 적이 없을 뿐 |
| `blocked` | 고유값 1개(`0`) | 위와 동일 |
| `handler_error_count` | 고유값 1개(`0`) | 위와 동일 |

세 컬럼 모두 표본이 **9개 세션 2,119행**이다. 이 표본에서 상수라는 것은 기능이 없다는 뜻이 아니라 **해당 경로가 아직 발동하지 않았다**는 뜻이다. 차단 경로를 한 번 유발하는 테스트가 먼저이고, 삭제 판단은 그 다음이다.

---

## 4. 배선

### 4.1 현재 배선의 결손 지점

```
provider 응답
  └─ agentic_response.py:345   call_id 수신
       └─ agentic_response.py:352   ToolUseBlock(id=call_id) 구성
       └─ processor.py:244/309      tool_result에 tool_use_id 실어 반송   ✅ 프로토콜 정상
       └─ session_checkpoint        messages.tool_call_id 기록            ✅ 99.3% 결속
       └─ processor.py:151/156      record_tool_call / record_tool_result ❌ id 안 넘김
```

`_record_tool_activity`는 `tool_use_id`를 **파라미터로 받아**(127행) computer-use payload에는 쓰면서(158행) 두 transcript writer에는 넘기지 않는다.

반송 경로는 244·309행이 일반 결과이고 683·697행은 denial·예외 결과다. 네 곳 모두 `tool_use_id`를 싣는다.

### 4.2 관통 변경

```python
# core/agent/tool_executor/processor.py:151,156
self._transcript.record_tool_call(tool_name, durable_input, call_id=tool_use_id)
self._transcript.record_tool_result(tool_name, status, summary, call_id=tool_use_id)

# core/observability/transcript.py — 두 writer 시그니처에 call_id: str = "" 추가,
# 빈 문자열이면 기존 행 모양을 유지한다(하위 호환).
```

지역변수를 두 줄 아래로 넘기는 변경이다. 새 식별자를 발급하지 않으므로 provider 형식에 무관하다.

### 4.3 마이그레이션을 하지 않는 이유

기존 14,515개 transcript는 그대로 둔다. 읽기 층이 `call_id`가 있으면 그것으로, 없으면 순서로 결속하는 분기를 유지하면 과거 파일과 신규 파일이 같은 코드로 읽힌다. 26,205개 JSONL을 다시 쓰는 위험을 감수할 이유가 없다.

---

## 5. K3 규격

### 5.1 메시지 형태

Kimi K3(arXiv:2607.24653 Appendix F)의 채널 분리와 `tool`·`index` 결속을 따른다. XTML 특수토큰은 채택하지 않는다. 그 형식의 값은 토큰 경계 모호성 제거와 constrained decoding인데, 자체 학습·디코딩을 하지 않는 한 회수되지 않는다.

```jsonc
{"role": "user",   "turn_id": "…", "content": "…"}
{"role": "system", "turn_id": "…", "content": "…"}
{"role": "assistant", "turn_id": "…",
 "think": "",                      // 비어도 유지 — K3는 턴 간 구조 일관성을 위해 채널을 남긴다
 "response": "…",
 "tools": [{"tool": "web_fetch", "index": 0, "call_id": "call_…", "arguments": {…}}]}
{"role": "tool",   "turn_id": "…",
 "results": [{"tool": "web_fetch", "index": 0, "call_id": "call_…",
              "status": "ok", "summary": "…"}]}
```

`index`는 **한 assistant 메시지 안에서** 병렬 호출에 번호를 매기고 결과가 같은 번호를 되풀이한다. `call_id`가 있으면 `index`는 그것으로 확정되고, 없으면 순서로 추정하되 추정임이 데이터에 남는다.

### 5.2 trajectory 객체

```jsonc
{
  "schema": "k3-shaped/2",
  "harness": "geode" | "codex",
  "session_id": "…",
  "parent_session_id": "",          // lineage. Codex는 forked_from_id
  "source": {"primary": "sessions.db:messages", "fallback": "transcripts/…jsonl"},
  "pairing": {"mode": "call_id" | "positional", "exact": 0.993},
  "messages": [ … ],
  "evidence": [ … ],                // kind 기반 판정 기록. 메시지에 끼우지 않는다
  "hooks": [ … ]                    // session_id 조인
}
```

`pairing`을 데이터에 적는 것이 이 규격의 핵심 방어다. 정확 결속과 순서 추정이 같은 필드 모양으로 나오면 소비자가 구분할 방법이 없다.

`evidence`와 `hooks`를 메시지 사이에 끼우지 않는 이유는 두 가지다. 첫째로 `seq`가 writer마다 다른 카운터라 시계로 합치면 **아무도 보장한 적 없는 순서를 지어낸다.** 둘째로 K3의 message list는 정책이 조건화한 것과 생성한 것이며, 컨텍스트에 들어간 적 없는 텔레메트리를 넣으면 재생 가능성이라는 유일한 쓸모가 사라진다. K3도 샌드박스 텔레메트리와 reward를 message list 바깥에 둔다.

### 5.3 읽기 순서 — 골격은 transcript, 해상도는 `messages`

```
session_id
  ├─ transcripts/*.jsonl               → 정본 골격. session_start 로 run 분할
  │    └─ 최신 run 에 한해
  │         sessions.db:messages       → 해상도 보강 (call_id, 무손실 인자, 결과 전문)
  ├─ evidence/<session_id>.jsonl       → sidecar
  └─ hook_events where session_id      → sidecar
```

보강을 **최신 run에만** 거는 것이 이 순서의 핵심이다. §1.1의 UPSERT+DELETE 의미론 때문에 `messages`는 이전 run에 대해 아무것도 주장하지 않으며, 옛 run에 갖다 붙이면 다른 실행의 내용을 그 자리에 심게 된다.

---

## 6. 이행 순서

작은 것부터 두고, 각 단계가 독립적으로 되돌려진다.

| # | 작업 | 범위 | 검증 | 상태 |
|---|---|---|---|---|
| 1 | 읽기 층 `run` 분할 (`session_start` 계수) | 읽기 층 | 274개 다중 run 세션 분할 | **완료** |
| 2 | `call_id` 관통 | `processor.py` 2줄, `transcript.py` 2 시그니처 | 신규 세션 결속 100% | |
| 3 | 최신 run 한정 `messages` 보강 | 읽기 층 | 보강 전후 툴 호출 수 불변 | |
| 4 | `task_id` → `parent_session_id` 노출 | 읽기 층 | 16행 lineage 복원 | |
| 5 | ~~`event` 방출 단일화~~ | — | — | **불필요** (§3.2, 07-15 완료) |
| 6 | `run_lineage` 폐기 | 스키마 | 0행 재확인 후 | |
| 7 | `turn_id` 발급 | 쓰기 층 (agent loop) | 신규 세션 채움률 | 2단계 이후 |

### 6.1 반증 조건

- **3단계** — 보강이 툴 호출 수를 바꾸면 중단한다. `messages`는 해상도만 올려야 하고 사건 집합을 바꾸면 안 된다.
- **5단계** — `event`를 읽는 소비자가 `LEGACY_EVENT_VALUES` 밖의 값을 기대하면 중단한다.
- **7단계** — 턴 경계 정의가 provider마다 갈리면(스트리밍 재개, 도구 재시도) 발급을 미루고 `run` 단위로 만족한다.

### 6.3 1단계 관문 — 실행했고, 관문 자체가 틀렸다

초안은 관문을 "두 소스의 메시지 수 비교"로 잡았다. 실행해 보니 **그 지표가 완결성을 재지 못한다.**

교집합 7,061 세션에서 300개를 무작위 추출하면 `messages`가 더 많은 경우 273건(91%), `transcript`가 더 많은 경우 17건(5.7%), 동일 10건이다. 그런데 역전된 17건을 열면 손실이 아니라 **분절 차이**다.

```
s-dec8665e0af1   transcript 투영 = 8  {user 1, assistant 4, tool 3}
                 messages       = 5  {assistant 2, user 3}
```

투영은 툴 호출마다 assistant 메시지를 새로 여는 반면 `messages`는 한 행의 content 배열에 `tool_use` 여러 개를 담는다. 두 수는 같은 사건의 다른 분절이라 비교 대상이 아니다.

분절과 무관한 지표인 **툴 호출 수**로 같은 300 세션(`random.Random(0)`)을 재면 300건 전부 일치한다. 관문 정의를 메시지 수에서 툴 호출 수로 바꾼다.

**다만 이 표본으로 "두 소스가 같은 사건 집합을 담는다"고 일반화하면 틀린다.** 전수 7,061 세션을 재면 일치 7,025, **불일치 36건(0.51%)**이다. 표본 300개가 36건을 전부 비껴간 것이다.

불일치의 방향이 설계에 직접 영향을 준다. 대부분 `transcript`가 더 많다.

```
s-33c24db49548   transcript=18  messages=5
s-0e16bc9845b1   transcript=7   messages=2
s-0a6994e71aa0   transcript=4   messages=1
s-306eb01ad9dc   transcript=0   messages=1
```

`messages`가 툴 호출을 **누락하는 세션이 존재한다**는 뜻이다.

**36건의 원인은 규명됐고 §1이 그 결과다.** `session_start` 횟수가 판별자이며(1회 0.07% 대 2회 이상 11.31%), 원인은 `save_messages`의 UPSERT+DELETE 의미론이다. 이 규명이 "정본을 `messages`로"라는 초판의 중심 제안을 철회시켰다. 선결 과제로 남겨 둔 것이 실제로 설계를 뒤집었으므로, 관문을 통과시키지 않고 파고든 판단이 옳았다.

`messages`가 세션 후반을 절단한다는 의심도 해소됐다. `seq` 최대는 97이고 98개에 도달한 세션은 8,493개 중 **1개**뿐이며 분포가 자연 감쇠한다(68개 1건, 48개 1건, 32개 8건, 30개 13건). 98은 상한이 아니라 가장 긴 세션의 길이다.

다만 `messages`는 `transcript`의 엄격한 상위집합이 **아니다.** 세션 집합이 서로를 포함하지 않으므로(§1) §5.3의 fallback은 "`messages`가 없을 때"만이 아니라 "해당 세션 구간을 담지 않을 때"까지 덮어야 한다.

### 6.2 하지 않는 것

- 26,205개 기존 JSONL 마이그레이션
- XTML 토큰화 층
- `blocked`·`block_reason`·`handler_error_count` 삭제
- `runs/*.jsonl`을 메시지로 승격 — 21개 session_key 중 19개가 붙지만 내용이 pipeline node 상태이지 대화가 아니다
