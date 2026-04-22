# GEODE Hook System — 이벤트 기반 라이프사이클 제어

> [English](hook-system.en.md) | **한국어**

> **모듈**: `core/hooks/` (cross-cutting concern, L0~L5 전 레이어에서 접근)
> **진입점**: `from core.hooks import HookSystem, HookEvent`
> **이벤트**: 58개 | **등록 핸들러**: 38+ | **플러그인**: YAML + class-based

---

## Hook 성숙도 모델

Hook System은 단순한 이벤트 로깅을 넘어 **관측 → 반응 → 판단 → 자율**의 4단계로 진화한다.

```
┌─────────────────────────────────────────────────────────────────┐
│  L4 AUTONOMY   패턴에서 규칙을 자율 학습                          │
│                                                                 │
│  ○ hook-tool-approval    HITL 승인 이력 → 자동 승인 룰 학습       │
│  ○ hook-model-switched   전환 사유 기록 → 자동 전환 정책 (L1 ✓)  │
│  ○ hook-filesystem-plugin  .geode/hooks/ 자동 발견 + 등록        │
├─────────────────────────────────────────────────────────────────┤
│  L3 DECIDE     Hook이 행동 방향을 결정                            │
│                                                                 │
│  ✓ hook-context-action   CONTEXT_OVERFLOW_ACTION → 압축 전략 위임│
│  ✓ hook-tool-exec-start  TOOL_EXEC_START interceptor (차단/수정) │
│  ✓ hook-tool-exec-end    TOOL_EXEC_END feedback (결과 변환)      │
│  ✓ hook-tool-transform   TOOL_RESULT_TRANSFORM (결과 변환 분리)  │
│  ○ hook-session-start    SESSION_START → 동적 프롬프트 보강       │
├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┤
│                          ▲ CURRENT FRONTIER                     │
│  L2 REACT      이벤트에 자동 반응                                │
│                                                                 │
│  ✓ turn_auto_memory        P85  TURN_COMPLETE → 인사이트 저장    │
│  ✓ drift_auto_snapshot     P80  DRIFT → 상태 캡처               │
│  ✓ pipeline_end_snapshot   P80  PIPELINE_END → 스냅샷            │
│  ✓ drift_pipeline_trigger  P70  DRIFT → 재분석 파이프라인         │
├─────────────────────────────────────────────────────────────────┤
│  L1 OBSERVE    기록만, 상태 변경 없음                             │
│                                                                 │
│  ✓ TaskGraphBridge    P30  NODE_ENTER/EXIT/ERROR                │
│  ✓ StuckDetector      P40  PIPELINE_START/END/ERROR             │
│  ✓ RunLog             P50  ALL 58 events → JSONL                │
│  ✓ JournalHook        P60  END/ERROR/SUBAGENT → journal         │
│  ✓ NotificationHook   P75  END/ERROR → Slack/외부 알림           │
│  ✓ TableLoggers ×5    P90  Automation events → 구조화 로깅       │
│  ✓ hook-llm-lifecycle  P55 LLM_CALL latency/cost 집계            │
└─────────────────────────────────────────────────────────────────┘

✓ = 구현 완료    ○ = 칸반 Backlog    ▲ = 현재 프론티어
```

> **다이어그램**: [`docs/diagrams/hook-maturity-model.mmd`](../diagrams/hook-maturity-model.mmd)

### 핵심 인사이트

새 hook 항목을 추가한다는 것은 **기존 이벤트에 더 높은 성숙도의 핸들러를 붙이는 것**이다.
이벤트 자체는 변하지 않고, 핸들러 체인이 깊어진다.

---

## 리플 패턴 — 하나의 이벤트가 여러 레벨을 동시에 관통

같은 이벤트가 L1(관측) + L2(반응) 핸들러를 동시에 트리거한다.
Priority 순서로 실행되므로 관측이 먼저, 반응이 나중.

```
PIPELINE_END ─┬─ P50 RunLog          ─── L1 OBSERVE  (기록)
              ├─ P60 JournalHook     ─── L1 OBSERVE  (runs.jsonl)
              ├─ P80 SnapshotCapture ─── L2 REACT    (자동 스냅샷)
              └─ P85 MemoryWriteBack ─── L2 REACT    (MEMORY.md)

DRIFT_DETECTED ─┬─ P70 DriftTrigger  ─── L2 REACT   (재분석 트리거)
                ├─ P80 DriftSnapshot  ─── L2 REACT   (디버깅 캡처)
                └─ P90 DriftLogger   ─── L1 OBSERVE  (구조화 로그)

TURN_COMPLETE ─┬─ P50 RunLog         ─── L1 OBSERVE  (이벤트 기록)
               └─ P85 TurnAutoMemory ─── L2 REACT    (인사이트 저장)

CONTEXT_CRITICAL ─── P50 RunLog         ─── L1 OBSERVE  (이벤트 기록)

CONTEXT_OVERFLOW_ACTION ── P50 ContextAction ── L3 DECIDE (압축 전략 위임)

TOOL_EXEC_START ─┬─ P90 AuditLogger     ─── L1 OBSERVE  (시작 기록)
                 └─ Pxx Interceptor      ─── L3 DECIDE   (차단/입력 수정)

TOOL_EXEC_END ─┬─ P90 AuditLogger       ─── L1 OBSERVE  (완료 기록)
               └─ Pxx Feedback           ─── L3 DECIDE   (결과 변환)
```

> **다이어그램**: [`docs/diagrams/hook-ripple-chains.mmd`](../diagrams/hook-ripple-chains.mmd)

---

## 아키텍처

```mermaid
graph TB
    subgraph "이벤트 소스"
        SG["StateGraph 실행<br/>(_make_hooked_node)"]
        AL["AgenticLoop<br/>(TURN_COMPLETE)"]
        PA["PromptAssembler<br/>(PROMPT_ASSEMBLED)"]
        L45["L4.5 Automation<br/>(DRIFT/OUTCOME/MODEL/<br/>SNAPSHOT/TRIGGER)"]
        SA["SubAgent<br/>(SUBAGENT_*)"]
        GW["Gateway<br/>(GATEWAY_*)"]
    end

    subgraph "HookSystem (core/hooks/)"
        HS["HookSystem<br/>register() / trigger()"]
        RH["_RegisteredHook[]<br/>priority-sorted chain"]
    end

    subgraph "핸들러 체인 (우선순위 순)"
        P30["P30: TaskGraphBridge"]
        P40["P40: StuckDetector"]
        P50["P50: RunLog (ALL)"]
        P60["P60: JournalHook"]
        P70["P70: TriggerManager"]
        P80["P80: SnapshotManager"]
        P85["P85: MemoryWriteBack / TurnAutoMemory"]
        P90["P90: TableLoggers ×5"]
    end

    SG --> HS
    AL --> HS
    PA --> HS
    L45 --> HS
    SA --> HS
    GW --> HS
    HS --> P30 --> P40 --> P50 --> P60 --> P70 --> P80 --> P85 --> P90
```

---

## HookEvent 열거형 (56개)

| 카테고리 | 이벤트 | 소스 | 핸들러 | 트리거 모드 | 성숙도 |
|---|---|---|---|---|---|
| **Pipeline** | `PIPELINE_START` | `graph.py` | StuckDetector, RunLog, Metrics | `trigger()` | L1 |
| | `PIPELINE_END` | `graph.py` | RunLog, Journal, Snapshot, Memory, Outcomes, Notification | `trigger()` | L1+L2 |
| | `PIPELINE_ERROR` | `graph.py` | StuckDetector, Journal, RunLog, Notification | `trigger()` | L1 |
| | `PIPELINE_TIMEOUT` | `graph.py` | RunLog, AuditLogger | `trigger()` | L1 |
| **Node** | `NODE_BOOTSTRAP` | `bootstrap.py` | RunLog | `trigger()` | L1 |
| | `NODE_ENTER` | `graph.py` | TaskBridge, StuckDetector, Metrics, RunLog | `trigger()` | L1 |
| | `NODE_EXIT` | `graph.py` | TaskBridge, StuckDetector, Metrics, RunLog | `trigger()` | L1 |
| | `NODE_ERROR` | `graph.py` | TaskBridge, StuckDetector, RunLog | `trigger()` | L1 |
| **Analysis** | `ANALYST_COMPLETE` | `graph.py` | RunLog, Metrics | `trigger()` | L1 |
| | `EVALUATOR_COMPLETE` | `graph.py` | RunLog, Metrics | `trigger()` | L1 |
| | `SCORING_COMPLETE` | `graph.py` | RunLog, ScoringDriftScan | `trigger()` | L1+L2 |
| **Verification** | `VERIFICATION_PASS` | `graph.py` | RunLog | `trigger()` | L1 |
| | `VERIFICATION_FAIL` | `graph.py` | RunLog | `trigger()` | L1 |
| **Automation** | `DRIFT_DETECTED` | CUSUMDetector, FeedbackLoop | Trigger, Snapshot, Logger, Notification | `trigger()` | L1+L2 |
| | `OUTCOME_COLLECTED` | OutcomeTracker, FeedbackLoop | FeedbackCycle, Logger | `trigger()` | L1+L2 |
| | `MODEL_PROMOTED` | ModelRegistry | Logger | `trigger()` | L1 |
| | `SNAPSHOT_CAPTURED` | SnapshotManager | Logger | `trigger()` | L1 |
| | `TRIGGER_FIRED` | TriggerManager, Scheduler | Logger | `trigger()` | L1 |
| | `POST_ANALYSIS` | Triggers | RunLog | `trigger()` | L1 |
| **Memory** | `MEMORY_SAVED` | MemorySaveTool | RunLog | `trigger()` | L1 |
| | `RULE_CREATED` | RuleCreateTool | RunLog | `trigger()` | L1 |
| | `RULE_UPDATED` | RuleUpdateTool | RunLog | `trigger()` | L1 |
| | `RULE_DELETED` | RuleDeleteTool | RunLog | `trigger()` | L1 |
| **Prompt** | `PROMPT_ASSEMBLED` | PromptAssembler | RunLog | `trigger()` | L1 |
| **SubAgent** | `SUBAGENT_STARTED` | SubAgentManager | RunLog | `trigger()` | L1 |
| | `SUBAGENT_COMPLETED` | SubAgentManager, IsolatedExec | Journal, RunLog | `trigger()` | L1 |
| | `SUBAGENT_FAILED` | SubAgentManager | RunLog, Notification | `trigger()` | L1 |
| **Tool Exec** | `TOOL_EXEC_START` | ToolCallProcessor | AuditLogger | `trigger_interceptor()` | **L3** |
| | `TOOL_EXEC_END` | ToolCallProcessor | AuditLogger | `trigger_with_result()` | **L3** |
| | `TOOL_RESULT_OFFLOADED` | ToolCallProcessor | RunLog | `trigger()` | L1 |
| **Tool Recovery** | `TOOL_RECOVERY_ATTEMPTED` | ToolCallProcessor | RunLog | `trigger()` | L1 |
| | `TOOL_RECOVERY_SUCCEEDED` | ToolCallProcessor | Metrics, RunLog | `trigger()` | L1 |
| | `TOOL_RECOVERY_FAILED` | ToolCallProcessor | RunLog | `trigger()` | L1 |
| **Tool Approval** | `TOOL_APPROVAL_REQUESTED` | ApprovalWorkflow | AuditLogger | `trigger()` | L1 |
| | `TOOL_APPROVAL_GRANTED` | ApprovalWorkflow | ApprovalTracker | `trigger()` | L1 |
| | `TOOL_APPROVAL_DENIED` | ApprovalWorkflow | ApprovalTracker | `trigger()` | L1 |
| **Turn** | `TURN_COMPLETE` | AgenticLoop | RunLog, AutoMemory, AutoLearn, LLMExtract | `trigger()` | L1+L2 |
| **Context** | `CONTEXT_CRITICAL` | ContextWindowManager | AuditLogger, RunLog | `trigger()` | L1 |
| | `CONTEXT_OVERFLOW_ACTION` | ContextWindowManager | ContextActionHandler | `trigger_with_result()` | **L3** |
| **Session** | `SESSION_START` | AgenticLoop | SessionLifecycle, RunLog | `trigger()` | L1 |
| | `SESSION_END` | AgenticLoop | SessionLifecycle, ToolOffloadCleanup, RunLog | `trigger()` | L1 |
| **Model** | `MODEL_SWITCHED` | AgenticLoop | ModelSwitchLogger | `trigger()` | L1 |
| **LLM Call** | `LLM_CALL_START` | LLM Router | AuditLogger, RunLog | `trigger()` | L1 |
| | `LLM_CALL_END` | LLM Router | LLMSlowLogger, RunLog | `trigger()` | L1 |
| | `LLM_CALL_FAILED` | AgenticLoop | AuditLogger, RunLog | `trigger()` | L1 |
| | `LLM_CALL_RETRY` | AgenticLoop | AuditLogger, RunLog | `trigger()` | L1 |
| **Cost** | `COST_WARNING` | AgenticLoop | AuditLogger, RunLog | `trigger()` | L1 |
| | `COST_LIMIT_EXCEEDED` | AgenticLoop | AuditLogger, RunLog | `trigger()` | L1 |
| **User Input** | `USER_INPUT_RECEIVED` | AgenticLoop | AuditLogger | `trigger_interceptor()` | **L3** |
| **Cross-Provider** | `FALLBACK_CROSS_PROVIDER` | AgenticLoop | AuditLogger, RunLog | `trigger()` | L1 |
| **Serve** | `SHUTDOWN_STARTED` | CLI | AuditLogger, RunLog | `trigger()` | L1 |
| | `CONFIG_RELOADED` | Bootstrap | AuditLogger, RunLog | `trigger()` | L1 |
| **MCP** | `MCP_SERVER_CONNECTED` | MCP Manager | AuditLogger, RunLog | `trigger()` | L1 |
| | `MCP_SERVER_FAILED` | MCP Manager | AuditLogger, RunLog | `trigger()` | L1 |
| **Execution** | `EXECUTION_CANCELLED` | IsolatedExecution | AuditLogger, RunLog | `trigger()` | L1 |
| **Reasoning** | `REASONING_METRICS` | AgenticLoop | AuditLogger, RunLog | `trigger()` | L1 |

---

## 이벤트 발생 순서

`_make_hooked_node()` 래퍼 내부:

```
1. NODE_BOOTSTRAP        (bootstrap_mgr 존재 시)
2. PromptAssembler 주입   (state["_prompt_assembler"])
3. NODE_ENTER
4. PIPELINE_START         (router 노드일 때만)
5. node_fn(state) 실행
6-a. NODE_EXIT            (성공)
6-b. {ANALYST|EVALUATOR|SCORING}_COMPLETE  (해당 노드)
6-c. VERIFICATION_PASS/FAIL  (verification 노드)
6-d. PIPELINE_END         (synthesizer)
--- 또는 ---
6-e. NODE_ERROR + PIPELINE_ERROR  (예외 — 둘 다 trigger)
```

AgenticLoop 턴 경계:

```
1. USER_INPUT_RECEIVED    (interceptor — 차단 가능)
2. SESSION_START           (session_id, model, provider)
3. LLM_CALL_START → LLM_CALL_END (또는 LLM_CALL_FAILED → LLM_CALL_RETRY)
4. TOOL_EXEC_START        (interceptor — 차단/입력 수정 가능)
5. tool 실행
6. TOOL_EXEC_END          (feedback — 결과 변환 가능)
7. (tool 연속 실패 시) TOOL_RECOVERY_ATTEMPTED → SUCCEEDED | FAILED
8. TURN_COMPLETE          (text, user_input, tool_calls, rounds)
9. SESSION_END            (session_id, total_cost)
```

---

## 등록 핸들러 전체 목록

| P | 핸들러명 | 구독 이벤트 | 등록 위치 | 성숙도 |
|---|---|---|---|---|
| **30** | `task_bridge_*` (3) | `NODE_ENTER/EXIT/ERROR` | `TaskGraphHookBridge` | L1 |
| **40** | `stuck_tracker` | `PIPELINE_START/END/ERROR` | `bootstrap.build_hooks()` | L1 |
| **45** | `metrics_*` (5) | `NODE_*/PIPELINE_*/ANALYSIS` | `SessionMetrics` | L1 |
| **50** | `run_log_writer` | **전체 56개** | `bootstrap.build_hooks()` | L1 |
| **50** | `context_action_handler` | `CONTEXT_OVERFLOW_ACTION` | `bootstrap._reg_context_action()` | **L3** |
| **55** | `llm_slow_logger` | `LLM_CALL_END` | `bootstrap.build_hooks()` | L1 |
| **60** | `journal_pipeline_end` | `PIPELINE_END` | `bootstrap.build_hooks()` | L1 |
| **60** | `journal_pipeline_error` | `PIPELINE_ERROR` | `bootstrap.build_hooks()` | L1 |
| **60** | `journal_subagent` | `SUBAGENT_COMPLETED` | `bootstrap.build_hooks()` | L1 |
| **60** | `scoring_drift_scan` | `SCORING_COMPLETE` | `automation.wire_hooks()` | L2 |
| **60** | `outcome_feedback_cycle` | `OUTCOME_COLLECTED` | `automation.wire_hooks()` | L2 |
| **65** | `approval_tracker` (2) | `TOOL_APPROVAL_GRANTED/DENIED` | `bootstrap.build_hooks()` | L1 |
| **70** | `drift_pipeline_trigger` | `DRIFT_DETECTED` | `automation.wire_hooks()` | L2 |
| **70** | `pipeline_end_outcomes` | `PIPELINE_END` | `automation.wire_hooks()` | L2 |
| **75** | `notification_*` (4) | `PIPELINE_END/ERROR, DRIFT, SUBAGENT_FAILED` | `notification_hook plugin` | L1 |
| **80** | `drift_auto_snapshot` | `DRIFT_DETECTED` | `automation.wire_hooks()` | L2 |
| **80** | `pipeline_end_snapshot` | `PIPELINE_END` | `automation.wire_hooks()` | L2 |
| **82** | `turn_llm_extract` | `TURN_COMPLETE` | `llm_extract_learning` | L2 |
| **84** | `turn_auto_learn` | `TURN_COMPLETE` | `auto_learn` | L2 |
| **85** | `turn_auto_memory` | `TURN_COMPLETE` | `bootstrap.build_hooks()` | L2 |
| **90** | `session_lifecycle` (2) | `SESSION_START/END` | `bootstrap.build_hooks()` | L1 |
| **90** | `model_switch_logger` | `MODEL_SWITCHED` | `bootstrap.build_hooks()` | L1 |
| **90** | `audit_loggers` (15+) | 15+ events (C9 table) | `bootstrap.build_hooks()` | L1 |
| **90** | `drift_logger` | `DRIFT_DETECTED` | `automation.wire_hooks()` | L1 |
| **90** | `snapshot_logger` | `SNAPSHOT_CAPTURED` | `automation.wire_hooks()` | L1 |
| **90** | `trigger_logger` | `TRIGGER_FIRED` | `automation.wire_hooks()` | L1 |
| **90** | `outcome_logger` | `OUTCOME_COLLECTED` | `automation.wire_hooks()` | L1 |
| **90** | `model_promotion_logger` | `MODEL_PROMOTED` | `automation.wire_hooks()` | L1 |
| **90** | `stuck_detector_*` (3) | `NODE_ENTER/EXIT/ERROR` | `stuck_detection` | L1 |
| **95** | `tool_offload_cleanup` | `SESSION_END` | `bootstrap.build_hooks()` | L1 |

---

## 플러그인 확장

`core/hooks/discovery.py`를 통해 외부 플러그인 추가 가능:

### Class-based Plugin

```python
# .geode/hooks/my_hook/hook.py
from core.hooks.system import HookEvent
from core.hooks.discovery import HookPlugin, HookPluginMetadata

class MyHook:
    @property
    def metadata(self) -> HookPluginMetadata:
        return HookPluginMetadata(
            name="my_hook",
            events=[HookEvent.PIPELINE_END],
            priority=75,
        )

    def handle(self, event: HookEvent, data: dict) -> None:
        # Custom logic
        pass
```

### YAML-based Plugin

```yaml
# .geode/hooks/my_hook/hook.yaml
name: my_hook
events: [pipeline_end, pipeline_error]
priority: 75
handler: my_hook.handler  # Python module path
```

---

## 트리거 모드 (3종)

| 모드 | 메서드 | 반환값 | 용도 | 사용 이벤트 |
|------|--------|--------|------|------------|
| **L1 Observe** | `trigger()` | `list[HookResult]` (성공/실패만) | Fire-and-forget 관찰 | 대부분 (50개) |
| **L3 Feedback** | `trigger_with_result()` | `list[HookResult]` (data 포함) | 핸들러가 전략/값 반환 | `CONTEXT_OVERFLOW_ACTION`, `TOOL_EXEC_END` |
| **L3 Interceptor** | `trigger_interceptor()` | `InterceptResult` (block/modify) | 실행 차단 또는 데이터 수정 | `USER_INPUT_RECEIVED`, `TOOL_EXEC_START` |

### Interceptor 프로토콜 (Claude Code PreToolUse 패턴)

```python
# 핸들러가 반환할 수 있는 값:
{"block": True, "reason": "..."}           # 실행 차단
{"modify": {"tool_input": {새 입력}}}       # 입력 수정
None                                        # 통과 (관찰만)
```

### Feedback 프로토콜 (Claude Code PostToolUse 패턴)

```python
# 핸들러가 반환할 수 있는 값:
{"updated_result": {변환된 결과}}            # 결과 교체
{"additional_context": "추가 맥락"}          # 결과에 context 주입
None                                        # 통과 (관찰만)
```

---

## 설계 원칙

1. **비차단 실행**: 한 핸들러의 예외가 다른 핸들러를 중단하지 않음 (interceptor 예외도 비차단)
2. **우선순위 정렬**: 낮은 수 = 높은 우선순위 (30 → 95)
3. **메타데이터 전용 방출**: `PROMPT_ASSEMBLED`는 해시와 통계만 전달 (보안)
4. **`HookResult` 반환**: 모든 핸들러의 성공/실패 결과 인트로스펙션 가능
5. **Cross-cutting**: `core/hooks/`는 독립 모듈 — 어느 레이어에서든 import 가능
6. **성숙도 진화**: 같은 이벤트에 L1(관측) → L2(반응) → L3(판단) → L4(자율) 핸들러를 점진 추가
7. **플러그인 확장**: 코어 수정 없이 `.geode/hooks/` 디렉토리로 외부 확장
8. **3종 트리거**: observe(기록) / feedback(값 반환) / interceptor(차단+수정) 용도에 맞게 선택

---

## 커버리지 매트릭스

> **다이어그램**: [`docs/diagrams/hook-coverage-matrix.mmd`](../diagrams/hook-coverage-matrix.mmd)

| 이벤트 그룹 | L1 OBSERVE | L2 REACT | L3 DECIDE | L4 AUTONOMY |
|---|:---:|:---:|:---:|:---:|
| Pipeline (4) | ✓ StuckDetector, RunLog, Metrics | ✓ Snapshot, Outcomes, Notification | — | — |
| Node (4) | ✓ TaskBridge, StuckDetector, Metrics | — | — | — |
| Analysis (3) | ✓ RunLog, Metrics | ✓ ScoringDriftScan | — | — |
| Verification (2) | ✓ RunLog | — | — | — |
| Automation (6) | ✓ 5 Loggers | ✓ Trigger, Snapshot, FeedbackCycle | — | — |
| Memory (4) | ✓ RunLog | — | — | — |
| Prompt (1) | ✓ RunLog | — | — | — |
| SubAgent (3) | ✓ Journal, RunLog, Notification | — | — | — |
| Tool Exec (3) | ✓ AuditLogger | — | ✓ Interceptor, Feedback | — |
| Tool Recovery (3) | ✓ RunLog, Metrics | — | — | — |
| Tool Approval (3) | ✓ ApprovalTracker, AuditLogger | — | — | — |
| Turn (1) | ✓ RunLog | ✓ AutoMemory, AutoLearn, LLMExtract | — | — |
| Context (2) | ✓ AuditLogger | — | ✓ ContextActionHandler | — |
| Session (2) | ✓ SessionLifecycle, RunLog | — | — | — |
| Model (1) | ✓ ModelSwitchLogger | — | — | — |
| LLM Call (4) | ✓ LLMSlowLogger, AuditLogger | — | — | — |
| Cost (2) | ✓ AuditLogger | — | — | — |
| User Input (1) | ✓ AuditLogger | — | ✓ Interceptor | — |
| Cross-Provider (1) | ✓ AuditLogger | — | — | — |
| Serve (2) | ✓ AuditLogger | — | — | — |
| MCP (2) | ✓ AuditLogger | — | — | — |
| Execution (1) | ✓ AuditLogger | — | — | — |
| Reasoning (1) | ✓ AuditLogger | — | — | — |
