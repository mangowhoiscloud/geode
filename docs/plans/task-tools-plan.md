# Task Tool 노출 구현 계획

> task_id: `task-tools` | 브랜치: `feature/task-tools` | 우선순위: P1
> 작성일: 2026-03-26 | 작성자: 세션 35

---

## 목적

AgenticLoop의 Claude가 작업을 분해·추적할 수 있도록, 내부 `TaskGraph` 엔진을
사용자/에이전트 facing `task_*` 도구로 노출한다.

---

## 소크라틱 5문 게이트

| Q | 질문 | 답변 | 판정 |
|---|------|------|------|
| Q1 | 코드에 이미 있는가? | `task_system.py`(TaskGraph 엔진)은 완성. definitions.json + handlers 없음 | 부분 구현 → 나머지만 |
| Q2 | 안 하면 무엇이 깨지는가? | AgenticLoop에서 Claude가 작업을 계획·추적할 수 없음. Sub-Agent 조율 불가 | 실제 장애 → 구현 대상 |
| Q3 | 효과를 어떻게 측정하는가? | handler unit test 5종 + definitions 등록 + `uv run geode` 에서 task tool 호출 확인 | 측정 가능 |
| Q4 | 가장 단순한 구현은? | ContextVar 1개 추가 + handler 함수 5개 + definitions 항목 5개 | 최소 변경 채택 |
| Q5 | 프론티어 3종 동일 패턴인가? | Claude Code(TaskCreate/Update/Get/List/Stop/Output 전체), OpenClaw(task decomposition), Codex CLI(task tracking) | 3종 확인 |

**결론**: 모든 문 통과 → 구현 진행

---

## 프론티어 패턴 분석 (리서치 결과)

### Claude Code Task 도구 설계 (실측)

```json
// ~/.claude/tasks/{session_id}/{id}.json
{
  "id": "41",
  "subject": "블로그 토픽 리스트업 + MD 작성",
  "description": "상세 설명...",
  "activeForm": "작업 중",
  "status": "pending",   // pending | in_progress | completed
  "blocks": [],          // downstream task IDs (역-의존성)
  "blockedBy": []        // upstream task IDs (의존성)
}
```

**핵심 설계 원칙**:
- 생성 시 항상 `pending` 상태로 시작
- 상태 전환은 단방향: pending → in_progress → completed
- `blockedBy`/`blocks` 양방향 의존성 추적
- `metadata` 확장용 임의 키-값

### Geode TaskGraph 상태 (내부)

```
PENDING → READY (자동, 의존성 충족 시)
        → RUNNING (mark_running 호출)
            → COMPLETED (mark_completed)
            → FAILED (mark_failed) → 다운스트림 SKIPPED 전파
```

**외부 노출 전략**: 복잡한 내부 상태를 3개로 단순화
- `pending` → PENDING/READY
- `in_progress` → RUNNING
- `completed` → COMPLETED
- `failed` → FAILED (읽기 전용, 자동 전파)

---

## 아키텍처 결정

### 독립 UserTaskGraph 사용

IP 분석 파이프라인의 `runtime.task_graph`와 **별도**로, 사용자/에이전트 작업 추적용
`UserTaskGraph`를 분리한다.

**이유**:
- IP 분석 파이프라인 TaskGraph는 `create_geode_task_graph(ip_name)` 으로 생성되는
  13-task 고정 구조 (pipeline 전용)
- 사용자 Task는 자유 생성/삭제/상태 변경 필요 → 다른 생명주기

**구현**:
- `session_state.py`에 `_user_task_graph_ctx: ContextVar[TaskGraph | None]` 추가
- 핸들러 첫 호출 시 lazy 초기화
- 기존 `_build_tool_handlers` 시그니처 변경 없음

### 권한 수준

| 도구 | 권한 | 근거 |
|------|------|------|
| `task_list` | STANDARD | 읽기 전용 |
| `task_get` | STANDARD | 읽기 전용 |
| `task_create` | WRITE | 상태 변경 |
| `task_update` | WRITE | 상태 변경 |
| `task_stop` | WRITE | 상태 변경 (FAILED 전파) |

---

## 구현 범위 (5 도구)

### 1. `task_create`
```json
{
  "subject": "string (필수) — 작업 제목, imperative form",
  "description": "string (선택) — 상세 설명",
  "metadata": "object (선택) — {priority, source, tool_name, tool_args}"
}
// 반환: {"status": "ok", "task_id": "t_1", "subject": "..."}
```

### 2. `task_update`
```json
{
  "task_id": "string (필수)",
  "status": "string (선택) — in_progress | completed | failed",
  "subject": "string (선택)",
  "description": "string (선택)",
  "owner": "string (선택) — subagent 할당",
  "metadata": "object (선택) — 병합 (null 값으로 키 삭제)"
}
```

### 3. `task_get`
```json
{
  "task_id": "string (필수)"
}
// 반환: task 상세 (id, subject, status, owner, elapsed_s, metadata)
```

### 4. `task_list`
```json
{
  "status_filter": "string (선택) — pending | in_progress | completed | failed | all"
}
// 반환: task 요약 목록 (id, subject, status, owner)
```

### 5. `task_stop`
```json
{
  "task_id": "string (필수)",
  "reason": "string (선택) — 취소 사유"
}
// mark_failed()로 처리 + 다운스트림 SKIPPED 전파
```

---

## 구현 파일 & 변경 범위

| 파일 | 변경 유형 | 내용 |
|------|----------|------|
| `core/tools/definitions.json` | 추가 | 5개 tool schema 항목 |
| `core/cli/session_state.py` | 추가 | `_user_task_graph_ctx` ContextVar + `_get_user_task_graph()` accessor |
| `core/cli/tool_handlers.py` | 추가 | `_build_task_handlers()` 함수 + `_build_tool_handlers()` 호출 1줄 |
| `tests/test_tool_handlers_task.py` | 신규 | unit tests 5종 (핸들러별 1개) |

**변경 없는 파일**: `task_system.py`, `task_bridge.py`, `runtime.py`, `graph.py`

---

## 구현 단계

### Step 1: session_state.py — ContextVar 추가
- `_user_task_graph_ctx: ContextVar[TaskGraph | None]` 추가
- `_get_user_task_graph()` — lazy 초기화 (첫 호출 시 새 TaskGraph 생성)
- `_reset_user_task_graph()` — 세션 초기화용

### Step 2: definitions.json — 5개 tool schema 추가
- task_create, task_update, task_get, task_list, task_stop
- category: `"task"`, cost_tier 각각 지정

### Step 3: tool_handlers.py — handler group 추가
- `_build_task_handlers()` 함수 작성
  - `_get_user_task_graph()` 경유로 TaskGraph 접근
  - 상태 매핑: `in_progress` → `mark_running()`, `completed` → `mark_completed()`
  - task_id 자동 생성: `f"t_{int(time.time() * 1000) % 100000}"`
- `_build_tool_handlers()` 마지막에 `handlers.update(_build_task_handlers())` 추가

### Step 4: tests 작성
- `test_task_create_handler` — 새 task 생성, task_id 반환
- `test_task_update_status` — pending→in_progress→completed 전환
- `test_task_get_handler` — task 조회, elapsed_s 포함
- `test_task_list_handler` — 전체 목록 + status 필터
- `test_task_stop_handler` — RUNNING task를 FAILED로 처리

---

## 품질 게이트

```bash
uv run ruff check core/ tests/       # 0 errors
uv run mypy core/                     # 0 errors
uv run pytest tests/test_tool_handlers_task.py -v  # 5 pass
uv run pytest tests/ -m "not live" -q              # 3219+ pass
```

---

## 사용 시나리오

```
사용자: "Berserk 분석하고 결과 비교 분석까지 해줘"

Claude (AgenticLoop):
  task_create(subject="Fetch Berserk signals") → t_1
  task_create(subject="Run IP analysis", metadata={"depends_on": ["t_1"]}) → t_2
  task_create(subject="Compare with Ghost in the Shell") → t_3

  task_update(task_id="t_1", status="in_progress")
  ... (analyze_ip 호출) ...
  task_update(task_id="t_1", status="completed")

  task_list() → [{t_1: completed}, {t_2: pending}, {t_3: pending}]
  task_update(task_id="t_2", status="in_progress")
  ...
```
