# SubAgent 병렬 실행 아키텍처 — 의사결정 저널과 패턴 비교

> Date: 2026-03-12 | Author: geode-team | Tags: sub-agent, architecture, decision-journal, openclaw, claude-code, autoresearch, agenthub

## 목차

1. 도입: 왜 이 문서를 쓰는가
2. SubAgent 아키텍처 전체 구조
3. 발전 과정 — 코드가 없던 시점에서 Live E2E까지
4. 의사결정 저널 — 7개 분기점
5. 패턴 비교 — OpenClaw, Claude Code, autoresearch, AgentHub
6. 차용한 것, 차용하지 않은 것
7. 트레이드오프 분석
8. 개선 방향
9. 마무리

---

## 1. 도입: 왜 이 문서를 쓰는가

GEODE의 SubAgent 시스템은 약 1,500줄의 코드로 구현되어 있습니다. 그 코드가 현재의 형태를 갖추기까지 7개의 설계 분기점을 거쳤고, 4개의 외부 프로젝트에서 패턴을 차용하거나 의식적으로 거부했습니다.

이 문서는 **코드가 아닌 결정**을 기록합니다. 왜 `IsolatedRunner`를 스레드로 구현했는지, 왜 `CoalescingQueue`에 250ms 윈도우를 넣었는지, 왜 AgentHub의 메시지 보드를 채택하지 않았는지 — 코드를 읽어서는 알 수 없는 맥락을 남기기 위한 의사결정 저널입니다.

---

## 2. SubAgent 아키텍처 전체 구조

### 2.1 모듈 스택

```
┌─────────────────────────────────────────────────────────┐
│  CLI Layer                                               │
│  ├── ToolExecutor._execute_delegate()  — 진입점          │
│  ├── _build_sub_agent_manager()        — DI 팩토리      │
│  └── make_pipeline_handler()           — 태스크 라우팅   │
├─────────────────────────────────────────────────────────┤
│  SubAgentManager (core/cli/sub_agent.py, 500 LOC)       │
│  ├── SubTask / SubResult / SubagentRunRecord             │
│  ├── delegate() → 병렬 위임 + 결과 대기                  │
│  ├── _execute_subtask() → 격리된 스레드에서 실행          │
│  ├── _resolve_agent() → AgentRegistry 조회               │
│  └── _emit_hook() → SUBAGENT_STARTED/COMPLETED/FAILED   │
├─────────────────────────────────────────────────────────┤
│  Orchestration Primitives                                │
│  ├── IsolatedRunner   — 스레드 격리 실행 (max 5)         │
│  ├── TaskGraph        — DAG 상태 추적 (13 tasks/IP)      │
│  ├── TaskGraphHookBridge — LangGraph → TaskGraph 전환    │
│  ├── CoalescingQueue  — 250ms 디바운싱                   │
│  └── LaneQueue        — 다수준 동시성 (session + global) │
├─────────────────────────────────────────────────────────┤
│  Session Isolation (core/memory/session_key.py)          │
│  ├── build_subagent_session_key() — 5-part 키            │
│  ├── build_subagent_thread_config() — LangGraph config   │
│  └── GeodeRuntime.is_subagent → MemorySaver 분기         │
└─────────────────────────────────────────────────────────┘
```

### 2.2 요청-응답 플로우

```
사용자: "Berserk, Cowboy Bebop 병렬로 분석해줘"

   ↓ NL Router (Claude Opus Tool Use)

delegate_task({tasks: [{task_type: "analyze", args: {ip_name: "Berserk"}}, ...]})

   ↓ ToolExecutor._execute_delegate()

SubTask 생성 → SubAgentManager.delegate()
   ├── [Thread 1] _execute_subtask("Berserk")
   │    ├── child_session_key = "ip:berserk:pipeline:subagent:delegate_xxx_0"
   │    ├── is_subagent = True (thread-local)
   │    ├── GeodeRuntime → MemorySaver (SQLite 회피)
   │    └── LangGraph invoke → {"tier": "S", "score": 81.3}
   │
   └── [Thread 2] _execute_subtask("Cowboy Bebop")
        ├── child_session_key = "ip:cowboy_bebop:pipeline:subagent:delegate_xxx_1"
        └── ... (동일 구조)

   ↓ 결과 수집 + Hook 발행

{results: [...], total: 2, succeeded: 2}
```

### 2.3 데이터 모델

```python
# core/cli/sub_agent.py

@dataclass
class SubTask:
    task_id: str           # "delegate_1710259200_0"
    description: str       # "Berserk 분석"
    task_type: str         # "analyze" | "search" | "compare"
    args: dict[str, Any]   # {"ip_name": "Berserk", "dry_run": True}
    agent: str | None      # AgentRegistry 오버라이드

@dataclass
class SubResult:
    task_id: str
    description: str
    success: bool
    output: dict[str, Any]  # 파이프라인 결과 JSON
    error: str | None
    duration_ms: float

@dataclass
class SubagentRunRecord:
    """OpenClaw Spawn 패턴 — 부모-자식 관계 추적."""
    run_id: str
    task_id: str
    child_session_key: str     # 격리된 세션 키
    parent_session_key: str    # 부모 세션 키
    task_type: str
    outcome: str = "pending"   # "pending" | "ok" | "error"
```

> `SubagentRunRecord`는 OpenClaw의 Spawn+Announce 패턴을 그대로 차용한 것입니다. 부모 에이전트가 자식을 생성(spawn)하고, 자식이 완료 시 결과를 알림(announce)하는 구조를 데이터 모델로 표현합니다. `child_session_key`와 `parent_session_key`의 분리가 G7(SQLite 경합) 해결의 핵심이었습니다.

---

## 3. 발전 과정 — 코드가 없던 시점에서 Live E2E까지

### 3.1 타임라인

```
Phase 0: 인프라 존재, 배선 부재
  └─ SubAgentManager, IsolatedRunner, TaskGraph 구현 완료
  └─ 하지만 delegate_task 호출 시 "SubAgentManager not configured" 에러만 반환

Phase 1: CLI Wiring (G1+G2)  ← cc23154
  └─ _build_sub_agent_manager() 팩토리
  └─ make_pipeline_handler() — analyze/search/compare 라우팅
  └─ ToolExecutor에 sub_agent_manager 전달

Phase 2: Agent Registry + 배치 (G3+G4+G5)  ← dd3e81d
  └─ _resolve_agent() + AgentRegistry 주입
  └─ tasks[] 배열 필드 → 다건 병렬 실행
  └─ on_progress 콜백

Phase 3: Hook 시맨틱 (G6)  ← dd3e81d
  └─ SUBAGENT_STARTED/COMPLETED/FAILED 전용 이벤트 (26개)
  └─ NODE_ENTER/EXIT와 혼동 방지

Phase 4: OpenClaw 세션 격리 (G7)  ← 0f2ae93
  └─ build_subagent_session_key() — 5-part 키
  └─ GeodeRuntime.is_subagent → MemorySaver 분기
  └─ SQLite "database disk image is malformed" 완전 해결

Phase 5: Live E2E 검증 (7 시나리오)
  └─ E1: delegate 단건 NL (18.66s) ✅
  └─ E2: delegate 배치 NL (21.38s) ✅
  └─ E3-E7: wiring, hook, registry, 비회귀, batch ✅
```

### 3.2 GAP 발견과 해결

| GAP | 심각도 | 문제 | 해결 | 커밋 |
|-----|--------|------|------|------|
| **G1** | CRITICAL | `ToolExecutor` 생성 시 `sub_agent_manager` 미전달 | `_build_sub_agent_manager()` 팩토리 | `cc23154` |
| **G2** | CRITICAL | `task_handler`가 `None` — 아무 일도 안 함 | `make_pipeline_handler()` | `cc23154` |
| **G3** | MEDIUM | `_resolve_agent()` 미구현 | `AgentRegistry` 주입 | `dd3e81d` |
| **G4** | MEDIUM | 단건만 지원 — 배치 불가 | `tasks[]` 배열 스키마 | `dd3e81d` |
| **G5** | LOW | 진행 상황 피드백 없음 | `on_progress` 콜백 | `dd3e81d` |
| **G6** | MEDIUM | `NODE_ENTER`로 서브에이전트 이벤트 발행 | 전용 `SUBAGENT_*` 이벤트 | `dd3e81d` |
| **G7** | CRITICAL | 병렬 SQLite 접근 → DB 손상 | 5-part 세션 키 + MemorySaver | `0f2ae93` |

> G1과 G2는 인프라-배선 단절(infrastructure-wiring gap)의 전형적 사례입니다. 1,500줄의 코드가 있었지만, 엔트리포인트에서 그 코드를 호출하는 2줄이 빠져 있었습니다. 이 경험은 "코드가 존재하는 것"과 "코드가 연결된 것"의 차이를 명확히 보여줍니다.

---

## 4. 의사결정 저널 — 7개 분기점

### D1: 왜 스레드인가? (asyncio, ProcessPool 거부)

**결정**: `IsolatedRunner`는 `threading.Thread` 기반

**대안 검토**:

| 대안 | 장점 | 거부 사유 |
|------|------|----------|
| `asyncio` | 네이티브 비동기 | SQLite 체크포인터가 async-unsafe. LangGraph `invoke()`가 동기 API |
| `ProcessPool` | 완전 격리 | 메모리 오버헤드(프로세스당 ~200MB), pickle 직렬화 제약 |
| `concurrent.futures.ThreadPool` | 표준 라이브러리 | 충분했으나, `IsolatedRunner`에 timeout + PostToMain + 세마포어를 직접 넣는 것이 더 투명 |

**결정 근거**:

```python
# core/orchestration/isolated_execution.py
class IsolatedRunner:
    MAX_CONCURRENT = 5  # Semaphore limit

    def _execute(self, fn, args, kwargs, config):
        thread = Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=config.timeout_s)  # 핵심: 타임아웃 강제
```

> `thread.join(timeout)` 한 줄이 이 결정의 핵심입니다. asyncio에서는 `asyncio.wait_for()`로 대체 가능하지만, LangGraph의 `graph.invoke()`가 동기 API이므로 코루틴 래핑이 필요합니다. 그 래핑 코스트 대비 스레드의 단순함이 이겼습니다.

**트레이드오프**: GIL로 인해 CPU-bound 병렬화는 제한됩니다. 하지만 SubAgent의 병목은 LLM API 호출(I/O-bound)이므로 GIL은 실질적 장벽이 아닙니다.

---

### D2: 왜 CoalescingQueue에 250ms인가?

**결정**: 250ms 디바운싱 윈도우

```python
# core/orchestration/coalescing.py
class CoalescingQueue:
    def __init__(self, window_ms: float = 250.0) -> None
```

**대안 검토**:

| 윈도우 | 특성 |
|--------|------|
| 0ms (즉시) | 중복 실행. "분석해" × 3 → 3회 실행 |
| 100ms | 키보드 더블탭은 잡으나, UI 렌더링 지연에는 불충분 |
| **250ms** | **인간 인지 임계: 유의미한 "동시 의도" 범위** |
| 500ms | 의도적 연속 요청까지 병합 위험 |
| 1000ms | 반응성 저하 |

> 250ms는 OpenClaw의 heartbeat-wake 패턴에서 가져온 값입니다. OpenClaw는 하트비트 주기와 웨이크 이벤트 사이의 디바운싱에 유사한 값을 사용합니다. 인간 인지 연구에서 "동시 지각 임계(temporal integration window)"가 약 200-300ms라는 점도 참고했습니다.

---

### D3: 왜 LaneQueue를 session + global 2단으로 설계했는가?

**결정**: 2-lane 구조 (session: max 1, global: max 4)

```python
# core/runtime.py → _build_default_lanes()
queue = LaneQueue()
queue.add_lane("session", max_concurrent=1)   # 세션당 직렬
queue.add_lane("global", max_concurrent=4)    # 전체 4개 제한
```

**OpenClaw 원칙 차용**:

> "기본 실행 모델은 직렬이다. 병렬이 필요하면 명시적으로 요청한다."

**근거**:

```
사용자 A: "Berserk 분석해줘"     → session:A 획득 (1/1)
사용자 A: "Cowboy Bebop도"       → session:A 대기 (직렬 보장)
사용자 B: "Ghost in the Shell"   → session:B 획득 (1/1), global (2/4)
```

- **session lane**: 같은 사용자의 요청은 상태 일관성을 위해 직렬 처리. 한 분석이 진행 중인데 다른 분석이 세션 메모리를 변경하면 레이스 컨디션 발생
- **global lane**: 시스템 전체 LLM API 동시 호출 제한. Anthropic rate limit 보호

> SubAgent의 Send API 병렬 실행과 LaneQueue의 직렬화는 다른 레이어입니다. LaneQueue는 "사용자 요청 레벨"에서 직렬화하고, Send API는 "파이프라인 내부 노드 레벨"에서 병렬화합니다. 이 두 수준을 혼동하지 않는 것이 중요합니다.

---

### D4: 왜 세션 키를 5-part로 확장했는가?

**결정**: `ip:name:phase:subagent:task_id` 5-part 키

**이전 구조** (3-4 part):
```
ip:berserk:analysis
ip:berserk:analysis:quality_judge
```

**문제**: 부모(`ip:berserk:analysis`)와 자식 스레드가 동일 SQLite 체크포인터에 동시 쓰기

```
# G7 에러 재현
Thread-1 (parent): sqlite3.execute("INSERT INTO checkpoints ...")
Thread-2 (child):  sqlite3.execute("INSERT INTO checkpoints ...")
→ sqlite3.DatabaseError: database disk image is malformed
```

**해결**: 자식에 고유 네임스페이스 할당

```python
# core/memory/session_key.py
def build_subagent_session_key(ip_name: str, task_id: str, phase: str = "pipeline") -> str:
    prefix = _normalize(ip_name)
    return f"ip:{prefix}:{phase}:subagent:{task_id}"
    # → "ip:berserk:pipeline:subagent:delegate_1710259200_0"
```

> 이 결정은 OpenClaw의 세션 키 격리 원칙을 직접 적용한 것입니다. OpenClaw에서는 "같은 에이전트도 세션이 다르면 독립된 컨텍스트로 격리"합니다. GEODE에서는 "같은 IP도 서브에이전트가 다르면 독립된 체크포인트로 격리"합니다.

추가로, 자식 서브에이전트는 `MemorySaver`(in-memory)로 fallback합니다:

```python
# core/runtime.py
if self.is_subagent:
    checkpoint_db = None  # → MemorySaver (SQLite 완전 회피)
```

> 서브에이전트는 결과만 부모에게 반환하면 됩니다. 체크포인트 영구 저장이 불필요하므로, SQLite 접근 자체를 제거하는 것이 가장 깨끗한 해결책입니다.

---

### D5: 왜 SUBAGENT 전용 Hook 이벤트를 만들었는가?

**결정**: `SUBAGENT_STARTED`, `SUBAGENT_COMPLETED`, `SUBAGENT_FAILED` 3개 이벤트 추가 (23 → 26)

**이전 문제** (G6):

```python
# 서브에이전트 시작을 NODE_ENTER로 발행했더니...
hooks.trigger(HookEvent.NODE_ENTER, {"node": "delegate_task", ...})

# TaskGraphHookBridge가 이를 파이프라인 노드로 해석
# → "delegate_task" 노드가 TaskGraph에 없어서 에러
# → StuckDetector가 미등록 노드로 감지하여 경고 발행
```

**해결**:

```python
# core/orchestration/hooks.py
class HookEvent(Enum):
    # ... 기존 23개 ...
    SUBAGENT_STARTED = "subagent_started"
    SUBAGENT_COMPLETED = "subagent_completed"
    SUBAGENT_FAILED = "subagent_failed"
```

> 파이프라인 노드 이벤트와 서브에이전트 라이프사이클 이벤트는 의미론적으로 다릅니다. `NODE_ENTER`는 "StateGraph의 한 노드가 실행을 시작했다"이고, `SUBAGENT_STARTED`는 "사용자 요청에 의해 위임된 독립 작업이 시작되었다"입니다. 같은 이벤트 이름을 공유하면 모든 Hook 구독자가 이 구분을 코드에서 해야 합니다.

---

### D6: 왜 Evaluator Counting을 특수 처리하는가?

**결정**: `TaskGraphHookBridge`에서 evaluator `NODE_EXIT`를 3회 카운트한 후 `evaluators` 태스크 완료 처리

```python
# core/orchestration/task_bridge.py
_EVALUATOR_EXPECTED_COUNT = 3

def _on_node_exit(self, event, data):
    node = data.get("node", "")
    if node == "evaluator":
        self._evaluator_done_count += 1
        if self._evaluator_done_count >= _EVALUATOR_EXPECTED_COUNT:
            self._graph.mark_completed(f"{self._prefix}_evaluators")
```

**근거**: LangGraph의 토폴로지에서 evaluator는 3개 인스턴스가 순차/병렬로 실행됩니다. 각 인스턴스가 `NODE_EXIT` 이벤트를 발행하므로, 3회 모두 완료되어야 "evaluators 단계 완료"입니다.

| LangGraph 관점 | TaskGraph 관점 |
|----------------|----------------|
| evaluator 인스턴스 1 EXIT | 카운트 1/3 |
| evaluator 인스턴스 2 EXIT | 카운트 2/3 |
| evaluator 인스턴스 3 EXIT | 카운트 3/3 → `evaluators` COMPLETED |

> 이 카운팅은 현재 하드코딩(3)되어 있습니다. evaluator 수가 동적으로 변하는 경우(예: 전문가 패널 확장)를 대비하려면 TaskGraph 메타데이터에 `expected_count`를 포함해야 합니다. 이것은 알려진 기술 부채입니다.

---

### D7: 왜 "Smart Platform"을 선택했는가?

**결정**: 결정론적 오케스트레이션 (TaskGraph + Hook + LaneQueue)

이 결정은 GEODE의 도메인 특성에서 비롯됩니다:

```
IP 평가 파이프라인:
  router → signals → analyst×4 → evaluator×3 → scoring → verification → synthesizer

이 순서는 고정입니다.
signals 전에 analyst가 실행되면 외부 데이터 없이 분석하게 됩니다.
evaluator 전에 scoring이 실행되면 평가 없이 점수를 매기게 됩니다.
```

**반례 (AgentHub가 적합한 경우)**:

```
ML 자동 실험 (autoresearch):
  "어떤 변경이든 val_bpb를 개선하면 된다"
  → 순서 무관. 에이전트가 자율적으로 탐색하는 것이 유리.
```

---

## 5. 패턴 비교 — OpenClaw, Claude Code, autoresearch, AgentHub

### 5.1 아키텍처 원형(Archetype) 비교

```
                    제어 수준
              결정론적 ◄────────► 자율적
                │                    │
  OpenClaw ─────┤                    │
  GEODE ────────┤                    │
                │                    ├───── Claude Code
                │                    ├───── autoresearch
                │                    └───── AgentHub
                │                    │
              단일 주체 ◄────────► 다중 주체
```

### 5.2 OpenClaw — Gateway 중심 제어

OpenClaw(TypeScript, ~48 소스 파일)는 Gateway(제어 평면) + Agent Runtime(실행 평면) 이중 체계입니다.

**핵심 패턴 6가지**:

| 패턴 | OpenClaw | GEODE 적용 여부 |
|------|----------|-----------------|
| Session Key 계층 | `agent:{id}:{context}` | **적용** → `ip:{name}:{phase}[:subagent:{id}]` |
| Lane Queue | session/global/subagent 차선 | **적용** → session(1) + global(4) |
| Spawn + Announce | 자식 생성 → 결과 알림 | **적용** → `SubagentRunRecord` |
| Binding Router | 결정적 메시지→에이전트 매핑 | **부분 적용** → slash command 직접 dispatch |
| Policy Chain | 도구 접근 4단계 필터링 | **적용** → `PolicyChain` (dry_run, full_pipeline) |
| Hot Reload | 재시작 없이 설정 반영 | **적용** → `ConfigWatcher` + `refresh_tools()` |

### 5.3 Claude Code — while(tool_use) Agentic Loop

Claude Code의 실행 모델은 단순합니다:

```
User → LLM(tools) → while stop_reason == "tool_use":
    execute_tool() → feed result → LLM continues
→ end_turn → Done
```

**GEODE 적용**:

```python
# core/cli/agentic_loop.py
class AgenticLoop:
    """Claude Code-style agentic execution loop.

    while stop_reason == "tool_use":
        execute tools → feed results back → continue
    """
```

| Claude Code 패턴 | GEODE 적용 |
|-------------------|-----------|
| while(tool_use) 루프 | **적용** → `AgenticLoop.run()` |
| Tool 렌더링 (▸/✓/✗) | **적용** → `agentic_ui.py` |
| Token 표시 (✢) | **적용** → `render_tokens()` |
| Multi-intent | **적용** → "분석하고 비교해줘" 가능 |
| Self-correction | **적용** → tool 실패 시 LLM이 재시도 판단 |

**GEODE의 하이브리드**: slash command는 OpenClaw Binding으로, 자연어는 Claude Code loop로 처리합니다.

```python
# core/cli/__init__.py — _interactive_loop()
if user_input.startswith("/"):
    # OpenClaw Binding — 결정론적 직접 dispatch
    dispatch(cmd, args)
else:
    # Claude Code — LLM 자율 판단
    result = agentic.run(user_input)
```

> 이 하이브리드가 GEODE의 가장 독특한 설계입니다. `/analyze Berserk`는 NL Router를 거치지 않고 직접 실행하므로 LLM 비용이 0입니다. `"베르세르크 분석해줘"`는 의도 해석이 필요하므로 AgenticLoop에 진입합니다. 사용자가 명시적일 때는 결정론, 모호할 때는 자율 — 이 분기가 비용과 유연성의 균형점입니다.

### 5.4 autoresearch (Karpathy) — 제약이 곧 설계

autoresearch는 파일 3개, ~630줄 코드로 이루어진 자율 ML 실험 시스템입니다.

**핵심 메커니즘 — Ratchet(래칫)**:

```bash
1. train.py 수정 (가설 기반)
2. git commit -m "실험 설명"
3. uv run train.py > run.log 2>&1
4. grep "^val_bpb:" run.log
5. val_bpb < previous_best → 커밋 유지 (새 baseline)
   val_bpb >= previous_best → git reset HEAD~1 (폐기)
```

**실전 결과**: ~700건 실험 중 ~20건 채택(2.9%) → GPT-2 대비 11% 성능 향상

| autoresearch 원칙 | GEODE 대응 |
|---|---|
| 단일 파일(train.py)만 수정 | 각 노드는 자신의 output keys만 반환 (노드 계약) |
| 5분 wall-clock 제한 | Confidence Gate ≥ 0.7 + max 5 iter 루프백 |
| val_bpb 단일 메트릭 | PSM 6가중 복합 스코어 + Tier |
| `grep`으로 정보 압축 | Send API Clean Context (앵커링 방지) |
| program.md 지시서 | CLAUDE.md + Skill 시스템 |
| Git as Experiment Tracker | RunLog (JSONL) + LangSmith |

> autoresearch의 가장 강력한 통찰은 **정보 압축이 자율 실행의 지속 가능성을 결정한다**는 것입니다. 시간당 12실험 × 8시간 = ~96실험. 각 실험의 컨텍스트 유입 = grep 결과 2줄 + 커밋 1줄 = ~3줄. 총 ~288줄. 현대 LLM의 128K+ 윈도우에서 충분히 수용 가능합니다. GEODE의 Send API Clean Context(분석가에게 다른 분석가의 결과를 보여주지 않음)는 이 원칙의 응용입니다.

### 5.5 AgentHub (Karpathy) — 바보 플랫폼(Dumb Platform)

AgentHub는 GitHub를 대체하려는 것이 아니라, **에이전트 간 협업 인프라**를 제안합니다.

**핵심 철학**: 플랫폼은 "메시지를 저장하고 전달할 뿐"이고, "누가 무엇을 할지"는 에이전트가 프롬프트를 읽고 자율적으로 결정합니다.

```
기술 스택: Go + SQLite + bare git repo + HTTP/JSON
스키마: 5개 테이블 (agents, commits, channels, posts, rate_limits)
저장소: 브랜치 없는 커밋 DAG — 에이전트가 임의의 커밋 위에 쌓음
보안: Bearer token + 50MB bundle limit + 100 push/hr rate limit
```

**커밋 DAG (브랜치 없음)**:

```
A: root (Agent-1)
├── B: optimizer tweak (Agent-1)
│   ├── C: lr schedule (Agent-2)
│   └── E: batch size (Agent-4)
└── D: arch change (Agent-3)
    └── F: attention variant (Agent-3)
```

> AgentHub에서 가장 급진적인 결정은 **조율 로직을 플랫폼에서 프롬프트로 위임**한 것입니다. 전통적 분산 시스템에서는 플랫폼이 리더 선출, 작업 할당, 충돌 해결을 담당합니다. AgentHub는 이 모든 것을 program.md에 자연어로 기술하고, 에이전트가 메시지 보드를 읽으며 스스로 조율합니다.

---

## 6. 차용한 것, 차용하지 않은 것

### 6.1 차용한 패턴

| 출처 | 패턴 | GEODE 구현 | 차용 이유 |
|------|------|-----------|----------|
| OpenClaw | Session Key 계층 | `session_key.py` 5-part | SQLite 격리 필수 |
| OpenClaw | Lane Queue | `lane_queue.py` 2-lane | 세션 일관성 + rate limit 보호 |
| OpenClaw | Spawn+Announce | `SubagentRunRecord` | 부모-자식 추적 필수 |
| OpenClaw | Policy Chain | `PolicyChain` | dry-run 모드 도구 제한 |
| OpenClaw | Coalescing | `CoalescingQueue` 250ms | 중복 LLM 호출 방지 |
| Claude Code | while(tool_use) | `AgenticLoop` | 다중 의도 + 자기수정 |
| Claude Code | ▸/✓/✗/✢ UI | `agentic_ui.py` | 사용자 피드백 가독성 |
| autoresearch | 정보 압축 | Send API Clean Context | 앵커링 방지 |
| autoresearch | 단조성 보장 | Confidence Gate ≥ 0.7 | 품질 하한 유지 |

### 6.2 차용하지 않은 패턴

| 출처 | 패턴 | 거부 이유 |
|------|------|----------|
| AgentHub | 브랜치 없는 커밋 DAG | IP 평가는 선형 파이프라인. DAG 탐색이 불필요 |
| AgentHub | 메시지 보드 조율 | 결정론적 파이프라인에서 프롬프트 기반 조율은 예측 불가능성 증가 |
| AgentHub | Dumb Platform | Smart Platform이 파이프라인 도메인에 적합 |
| autoresearch | git reset 폐기 | IP 평가 결과는 모두 보존해야 함 (비교 분석용). 실패도 기록 |
| autoresearch | 단일 메트릭 판정 | 14축 다면적 평가에 단일 메트릭은 부적합 |
| OpenClaw | Gateway 분리 배포 | 단일 프로세스 CLI. 마이크로서비스 수준의 분리는 과잉 |
| OpenClaw | 3-lane (subagent 전용) | 2-lane으로 충분. SubAgent는 global lane 내에서 실행 |

### 6.3 의식적 차이점

**OpenClaw vs GEODE — 동시성 기본값**:

```
OpenClaw: "기본 직렬, 병렬은 명시적 요청"
   └─ Session lane: max 1
   └─ Subagent lane: max 8 (별도)

GEODE:    "기본 직렬, 병렬은 Send API 범위 내에서 자동"
   └─ Session lane: max 1
   └─ Global lane: max 4 (SubAgent 포함)
   └─ IsolatedRunner: max 5 (내부 세마포어)
```

> GEODE에는 subagent 전용 lane이 없습니다. `IsolatedRunner.MAX_CONCURRENT = 5`가 그 역할을 합니다. 두 수준의 동시성 제어(LaneQueue + IsolatedRunner 세마포어)가 존재하며, 더 엄격한 쪽이 적용됩니다.

**autoresearch vs GEODE — 실패 기록**:

```
autoresearch: git reset HEAD~1 → 실패한 실험 완전 소실
GEODE:        RunLog + LangSmith → 실패한 분석도 영구 기록
```

> 이 차이는 도메인에서 비롯됩니다. ML 실험에서 실패한 하이퍼파라미터 조합은 재현 가치가 낮습니다. 하지만 IP 평가에서 "왜 이 IP가 낮은 점수를 받았는지"는 중요한 비즈니스 인사이트입니다.

---

## 7. 트레이드오프 분석

### 7.1 제어 수준 스펙트럼

```
                     비용          예측성        유연성
결정론적 (OpenClaw)   낮음 ───────── 높음 ───────── 낮음
하이브리드 (GEODE)    중간 ───────── 중간 ───────── 중간
자율적 (Claude Code)  높음 ───────── 낮음 ───────── 높음
```

GEODE의 하이브리드 위치:

| 시나리오 | 사용 패턴 | 비용 | 예측성 |
|---------|----------|------|--------|
| `/analyze Berserk` | Slash → 직접 dispatch | $0 (LLM 0회) | 100% |
| `"베르세르크 분석해줘"` | NL → AgenticLoop | ~$0.01 (1 라운드) | 95%+ |
| `"분석하고 비교해서 리포트"` | NL → AgenticLoop (3+ 라운드) | ~$0.05 | 80%+ |

### 7.2 격리 수준 스펙트럼

```
                     격리도        오버헤드      복잡도
프로세스 (ProcessPool) 완전 ──────── 높음(200MB) ── 높음
스레드 (GEODE)         부분 ──────── 낮음(8MB) ─── 중간
코루틴 (asyncio)       없음 ──────── 극소 ──────── 높음(async 전파)
```

GEODE가 스레드를 선택한 이유: I/O-bound 워크로드에서 프로세스 격리는 과잉, asyncio는 LangGraph API 비호환.

### 7.3 Smart vs Dumb Platform

| 관점 | Smart (GEODE) | Dumb (AgentHub) |
|------|---------------|-----------------|
| 파이프라인 보장 | 노드 순서 강제 | 에이전트 재량 |
| 디버깅 | Hook 이벤트 + TaskGraph 상태 | 메시지 보드 로그만 |
| 확장성 | 코드 변경 필요 | 프롬프트 수정만 |
| 비용 예측 | 가능 (고정 토폴로지) | 불가능 (에이전트 자율) |
| 창발적 행동 | 불가능 | 가능 (의도치 않은 것도) |

> GEODE 도메인에서 "창발적 행동"은 리스크입니다. IP 가치 평가에서 에이전트가 자율적으로 새로운 평가 축을 만들거나, 예상치 못한 순서로 노드를 실행하는 것은 검증되지 않은 결과를 만들 수 있습니다. Smart Platform은 이 리스크를 코드로 제어합니다.

---

## 8. 개선 방향

### 8.1 단기 (현재 아키텍처 내)

| 항목 | 현재 | 개선안 | 참조 패턴 |
|------|------|--------|----------|
| Evaluator counting | 하드코딩 `3` | TaskGraph 메타데이터 `expected_count` | - |
| SubAgent 타임아웃 | 고정 120s | 태스크 유형별 적응적 타임아웃 | OpenClaw lane timeout |
| 결과 캐싱 | 없음 | 동일 IP + 동일 파라미터 → 캐시 히트 | CoalescingQueue 확장 |
| 진행 표시 | `on_progress` 콜백 | 실시간 스트리밍 (SSE/WebSocket) | Claude Code 스트리밍 |

### 8.2 중기 (아키텍처 확장)

**AgentHub 메시지 보드 부분 도입**:

현재 Analyst×4는 Clean Context로 실행되어 서로의 결과를 모릅니다. AgentHub 스타일의 메시지 보드가 있다면:

```python
# 가상: Analyst 간 비정형 메시지 교환
class AnalystBoard:
    def post(self, analyst_type: str, content: str) -> None:
        """분석 힌트 공유. 조율 로직 없음."""

    def read(self, limit: int = 5) -> list[str]:
        """다른 분석가의 메시지 조회."""
```

> 주의: Clean Context 원칙과 충돌합니다. 다른 분석가의 결과를 보면 앵커링 바이어스가 발생할 수 있습니다. "결과" 대신 "관찰"만 공유하는 제한이 필요합니다. 예: "이 IP는 Steam 리뷰가 매우 긍정적" (관찰) vs "이 IP는 A 등급" (결론).

**autoresearch Ratchet 적용 — A/B 분석 품질 추적**:

```python
# 가상: 분석 품질 단조 개선 추적
class AnalysisRatchet:
    def record(self, ip_name: str, score: float, config: dict) -> None:
        """분석 결과 기록."""

    def should_keep(self, ip_name: str, new_score: float) -> bool:
        """이전 best 대비 개선 여부."""
        return new_score > self.best_score(ip_name)
```

### 8.3 장기 (패러다임 전환)

**async 전환**: LangGraph가 native async를 지원하면 `IsolatedRunner` → `asyncio.TaskGroup` 전환이 가능합니다. 스레드 오버헤드 제거 + 더 세밀한 동시성 제어.

**분산 SubAgent**: 현재는 단일 프로세스 내 스레드. 대규모 배치(100+ IP) 분석 시 여러 워커 프로세스로 분산 필요. AgentHub의 HTTP + git bundle 프로토콜이 참고 가능.

---

## 9. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|------|---------|
| 총 SubAgent 코드 | ~1,500 LOC (6개 모듈) |
| 의사결정 분기점 | 7개 (D1-D7) |
| 해결된 GAP | 7개 (G1-G7) |
| 참조 패턴 | 4개 (OpenClaw, Claude Code, autoresearch, AgentHub) |
| 차용 패턴 | 9개 |
| 거부 패턴 | 7개 |
| Live E2E 시나리오 | 7개 (전원 통과) |
| 병렬 성능 향상 | 3 IP 기준 2.8배 |

### 패턴 차용 요약

```
OpenClaw ────── Session Key, Lane Queue, Spawn+Announce,
                Policy Chain, Coalescing, Hot Reload
                (거부: Gateway 분리, 3-lane)

Claude Code ─── while(tool_use), ▸/✓/✗/✢ UI,
                Multi-intent, Self-correction
                (거부: 없음 — 전면 적용)

autoresearch ── 정보 압축 (Clean Context),
                단조성 보장 (Confidence Gate)
                (거부: git reset 폐기, 단일 메트릭)

AgentHub ────── (거부: 메시지 보드, Dumb Platform, DAG)
                (향후 검토: L6 Extensibility에서 부분 적용)
```

### 결론

> "제약이 곧 설계" — autoresearch의 630줄 제약, AgentHub의 5-table 스키마, OpenClaw의 "기본 직렬" 원칙. 이 프로젝트들의 공통점은 무제한 유연성 대신 의도된 제약으로 시스템의 예측 가능성을 확보한다는 점입니다.

GEODE의 SubAgent 시스템은 이 철학을 따릅니다. `IsolatedRunner.MAX_CONCURRENT = 5`는 무한 병렬이 아닌 의도된 제약입니다. `LaneQueue` session lane의 `max_concurrent = 1`은 성능 손해를 감수하고 상태 일관성을 선택한 것입니다. `MemorySaver` fallback은 체크포인트 영속성을 포기하고 SQLite 안전성을 확보한 것입니다.

이 문서가 기록하는 것은 코드가 아니라 **왜 그 코드가 그 모양인지**입니다.
