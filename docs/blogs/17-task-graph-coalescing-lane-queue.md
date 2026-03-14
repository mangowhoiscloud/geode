# Task Graph x Coalescing Queue x Lane Queue — 자율 실행 하네스의 제어 평면

> Date: 2026-03-12 | Author: geode-team | Tags: [orchestration, task-graph, concurrency, queue, harness]

## 목차

1. 도입
2. Task Graph — DAG 기반 파이프라인 추적
3. Coalescing Queue — 중복 요청 병합
4. Lane Queue — 계층적 동시성 제어
5. Stuck Detection — 교착 감지
6. 통합 — Hook x Runtime x 제어 평면
7. 설계 원천 — OpenClaw에서 GEODE로
8. 마무리

---

## 1. 도입

LangGraph의 `StateGraph`는 노드와 엣지로 구성된 실행 엔진(Execution Engine)입니다. 컴파일하면 `graph.stream()`으로 상태를 흘려보내고, 노드 함수를 호출하며, 조건부 분기를 처리합니다. 그러나 StateGraph가 답하지 않는 질문이 세 가지 있습니다.

- **진행 상태 추적**: "지금 13개 태스크 중 몇 개가 완료되었는가?" StateGraph는 현재 노드만 알 뿐, 전체 DAG 진행률을 보여주지 않습니다.
- **중복 요청 병합**: REPL에서 사용자가 같은 IP 분석을 연타하면 어떻게 되는가? StateGraph는 요청이 오는 대로 모두 실행합니다.
- **동시성 제어**: 멀티 세션에서 4개 분석이 동시에 돌 때 LLM API Rate Limit은 누가 관리하는가? StateGraph에는 세마포어(Semaphore)가 없습니다.

GEODE는 이 세 가지 공백을 **Task Graph**, **Coalescing Queue**, **Lane Queue**로 채웁니다. 그리고 이 세 모듈을 연결하는 접착제는 **HookSystem의 23개 이벤트**입니다.

```
┌──────────────────────────────────────────────────────────────┐
│                    GEODE 제어 평면                             │
│                                                              │
│  ┌─────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ Task Graph  │  │ Coalescing Queue│  │   Lane Queue    │  │
│  │ (관찰자)     │  │ (병합기)         │  │ (동시성 제어기)   │  │
│  │             │  │                 │  │                 │  │
│  │ 13태스크 DAG│  │ 250ms debounce  │  │ session(1)      │  │
│  │ 상태 추적   │  │ Timer 리셋      │  │ global(4)       │  │
│  └──────┬──────┘  └────────┬────────┘  └────────┬────────┘  │
│         │                  │                     │           │
│         └──────────────────┼─────────────────────┘           │
│                            │                                 │
│                   HookSystem (23 events)                     │
│                   + StuckDetector (7200s)                    │
└──────────────────────────────────────────────────────────────┘
         ↕                   ↕                     ↕
┌──────────────────────────────────────────────────────────────┐
│  LangGraph StateGraph (실행 엔진)                              │
│  router → signals → analyst x4 → evaluator x3 → scoring     │
│  → verification → synthesizer → END                          │
└──────────────────────────────────────────────────────────────┘
```

핵심 원칙은 명확합니다. **StateGraph는 실행만, 제어 평면은 관찰과 조율만**. 이 분리가 없으면 실행 엔진에 부수 관심사가 침투하고, 노드 함수가 동시성 로직까지 품어야 하는 복잡성 폭발로 이어집니다.

---

## 2. Task Graph — DAG 기반 파이프라인 추적

### StateGraph vs TaskGraph: 역할 분리

| 관점 | StateGraph (LangGraph) | TaskGraph (GEODE) |
|------|----------------------|-------------------|
| 역할 | 실행 엔진 | 상태 관찰자 |
| 제어 방향 | 노드를 직접 호출 | Hook 이벤트를 수신만 함 |
| 상태 모델 | 현재 노드 + 전체 State dict | 태스크별 6단계 상태 머신 |
| 동시성 표현 | Send API로 분기 | `get_ready_tasks()`로 병렬 가능 배치 반환 |
| 실패 전파 | 예외 발생 → 그래프 중단 | `propagate_failure()` → 하류 태스크 SKIP |

TaskGraph는 StateGraph를 제어하지 않습니다. NODE_ENTER, NODE_EXIT, NODE_ERROR 이벤트를 수신해서 내부 상태만 갱신합니다. UI 패널이 "현재 13개 중 8개 완료"를 표시할 수 있는 이유가 바로 이 관찰자 패턴입니다.

### Task와 TaskStatus — 6단계 상태 머신

```python
# core/orchestration/task_system.py
class TaskStatus(Enum):
    PENDING = "pending"       # 초기 상태
    READY = "ready"           # 의존성 충족, 실행 대기
    RUNNING = "running"       # 실행 중
    COMPLETED = "completed"   # 정상 완료
    FAILED = "failed"         # 실패
    SKIPPED = "skipped"       # 상류 실패로 건너뜀
```

> 설계 의도: READY와 PENDING을 분리한 이유는 `get_ready_tasks()`에서 의존성이 충족된 태스크만 정확히 반환하기 위함입니다. PENDING은 "아직 의존성 미충족", READY는 "의존성 충족, 실행 가능" 상태입니다.

```python
# core/orchestration/task_system.py
@dataclass
class Task:
    task_id: str
    name: str
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = field(default_factory=list)
    result: Any = None
    error: str | None = None
    started_at: float | None = None
    completed_at: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed_s(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.SKIPPED
        )
```

> `elapsed_s`는 완료 전이면 현재 시각 기준, 완료 후면 실제 소요 시간을 반환합니다. 실시간 진행률 표시에 이 차이가 중요합니다.

### 13태스크 DAG — create_geode_task_graph()

단일 IP 분석의 전체 토폴로지를 태스크 그래프로 표현합니다. `graph.py`의 StateGraph 노드 구조와 1:1로 대응합니다.

```
router
  └─ signals
       ├─ analyst_game_mechanics      ─┐
       ├─ analyst_player_experience    ├─ (4개 병렬)
       ├─ analyst_growth_potential     │
       └─ analyst_discovery           ─┘
            └─ evaluators
                 ├─ scoring   ─┐
                 └─ psm       ─┤ (2개 병렬)
                      │        │
                      ├─ verification (scoring + psm 의존)
                      └─ cross_llm    (scoring만 의존)
                           └─ synthesis
                                └─ report
```

`topological_order()` 메서드는 이 DAG를 병렬 실행 가능한 배치(Batch)로 분해합니다.

```python
# core/orchestration/task_system.py — TaskGraph.topological_order()
def topological_order(self) -> list[list[str]]:
    completed: set[str] = set()
    remaining = list(self._tasks.keys())
    batches: list[list[str]] = []

    while remaining:
        batch = [
            tid for tid in remaining
            if all(dep in completed for dep in self._tasks[tid].dependencies)
        ]
        if not batch:
            log.warning("Unresolvable dependencies detected")
            batches.append(remaining)
            break
        batches.append(batch)
        completed.update(batch)
        remaining = [tid for tid in remaining if tid not in completed]

    return batches
```

> 설계 의도: 사이클이 발견되면 나머지를 강제로 한 배치에 넣습니다. 무한 루프 대신 로그 경고 후 진행. `validate()` 메서드로 사전에 사이클과 미존재 의존성을 검출할 수 있습니다.

### TaskGraphHookBridge — Hook 이벤트를 상태 전이로 변환

TaskGraph는 자체적으로 실행하지 않습니다. HookSystem의 NODE_ENTER/EXIT/ERROR 이벤트를 수신하고, 이를 `mark_running()`, `mark_completed()`, `mark_failed()` 호출로 변환하는 브릿지(Bridge)가 필요합니다.

```python
# core/orchestration/task_bridge.py
class TaskGraphHookBridge:
    def __init__(self, task_graph: TaskGraph, *, ip_prefix: str) -> None:
        self._graph = task_graph
        self._prefix = ip_prefix
        self._evaluator_done_count = 0

    def register(self, hooks: HookSystemPort) -> None:
        hooks.register(HookEvent.NODE_ENTER, self._on_node_enter,
                       name="task_bridge_enter", priority=30)
        hooks.register(HookEvent.NODE_EXIT, self._on_node_exit,
                       name="task_bridge_exit", priority=30)
        hooks.register(HookEvent.NODE_ERROR, self._on_node_error,
                       name="task_bridge_error", priority=30)
```

> priority=30으로 등록합니다. RunLog(priority=50)보다 먼저 실행되어, 로그 기록 시점에 이미 태스크 상태가 갱신되어 있습니다.

**노드-태스크 매핑 규칙**은 4가지로 분류됩니다.

```python
# core/orchestration/task_bridge.py
# 1. 무시 — 태스크 없는 노드
_IGNORED_NODES = frozenset({"gather"})

# 2. 단순 1:1 — 노드 이름 = 태스크 접미사
_SIMPLE_NODES = {"router": "router", "signals": "signals"}

# 3. 1:N — 하나의 노드가 여러 태스크를 완료
_MULTI_TASK_NODES = {
    "scoring":      ["scoring", "psm"],
    "verification": ["verification", "cross_llm"],
    "synthesizer":  ["synthesis", "report"],
}

# 4. 카운팅 — evaluator는 3회 EXIT 후 evaluators 태스크 완료
_EVALUATOR_EXPECTED_COUNT = 3
```

Evaluator 카운팅은 특별한 처리가 필요합니다. Send API로 3개 evaluator가 병렬 실행되므로, NODE_EXIT가 3번 들어와야 `evaluators` 태스크가 완료됩니다. NODE_ERROR가 하나라도 들어오면 즉시 실패 처리 후 `propagate_failure()`로 하류를 SKIP합니다.

```python
# core/orchestration/task_bridge.py — _on_node_exit (evaluator 부분)
if node == "evaluator":
    self._evaluator_done_count += 1
    if self._evaluator_done_count < _EVALUATOR_EXPECTED_COUNT:
        return
    tid = f"{self._prefix}_evaluators"
    task = self._graph.get_task(tid)
    if task and task.status == TaskStatus.RUNNING:
        self._graph.mark_completed(tid)
    return
```

### 실패 전파 — propagate_failure()

한 태스크가 실패하면, 그에 의존하는 모든 하류 태스크를 재귀적으로 SKIP 처리합니다. BFS 방식으로 전파합니다.

```python
# core/orchestration/task_system.py — TaskGraph.propagate_failure()
def propagate_failure(self, task_id: str) -> list[str]:
    skipped: list[str] = []
    to_skip = self._get_dependents(task_id)

    while to_skip:
        current = to_skip.pop(0)
        if current.is_terminal:
            continue
        self.mark_skipped(current.task_id)
        skipped.append(current.task_id)
        to_skip.extend(self._get_dependents(current.task_id))

    return skipped
```

> 예를 들어 `signals` 태스크가 실패하면, 4개 analyst + evaluators + scoring + psm + verification + cross_llm + synthesis + report = 11개 태스크가 한번에 SKIP됩니다. 불필요한 LLM 호출을 방지합니다.

---

## 3. Coalescing Queue — 중복 요청 병합

REPL 환경에서 사용자가 "Berserk 분석해줘"를 빠르게 두 번 입력하면 어떻게 되어야 할까요? 두 번 실행은 낭비입니다. Coalescing Queue(요청 병합 큐)는 **250ms 디바운스 윈도우(Debounce Window)** 내에 들어온 동일 키의 요청을 하나로 병합합니다.

### 동작 원리

```
t=0ms    submit("ip:berserk:analysis")  → Timer 시작 (250ms)
t=120ms  submit("ip:berserk:analysis")  → Timer 리셋 (250ms 재시작)
t=370ms  Timer 만료 → callback 1회 실행
```

핵심은 `threading.Timer`의 리셋입니다.

```python
# core/orchestration/coalescing.py
class CoalescingQueue:
    def __init__(self, window_ms: float = 250.0) -> None:
        self._window_s = window_ms / 1000.0
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    def submit(self, key: str, callback: Any, data: Any = None) -> bool:
        with self._lock:
            existing = self._timers.get(key)
            if existing is not None:
                existing.cancel()          # 기존 타이머 취소
                self._stats.coalesced += 1
                coalesced = True
            else:
                coalesced = False

            timer = threading.Timer(
                self._window_s,
                self._fire,
                args=(key, callback, data),
            )
            timer.daemon = True            # 메인 스레드 종료 시 함께 종료
            self._timers[key] = timer
            timer.start()

        return not coalesced  # True = 신규, False = 병합됨
```

> 설계 의도: `threading.Lock`으로 타이머 교체를 원자적으로 보호합니다. `timer.daemon = True`로 설정하여, REPL 종료 시 대기 중인 타이머가 프로세스를 붙잡지 않습니다. OpenClaw의 `timer.unref()` (Node.js)에 대응하는 Python 관용구입니다.

### 통계 추적

```python
# core/orchestration/coalescing.py
class _CoalescingStats:
    submitted: int = 0   # 총 제출 수
    coalesced: int = 0   # 병합된 수
    executed: int = 0    # 실제 실행 수
    errors: int = 0      # 콜백 에러 수
```

`submitted - coalesced = executed + errors` 관계가 항상 성립합니다. 이 수치는 `GeodeRuntime.get_health()`에서 `coalescing_pending`으로 노출되어, REPL 상태바에서 병합 효율을 실시간 확인할 수 있습니다.

---

## 4. Lane Queue — 계층적 동시성 제어

LLM API에는 Rate Limit이 있습니다. Anthropic Claude Opus 4.6 기준 분당 요청 수 제한이 있고, OpenAI도 마찬가지입니다. 멀티 세션에서 동시에 여러 IP를 분석하면, 동시성을 제어하지 않으면 429 에러가 쏟아집니다.

Lane Queue(레인 큐)는 **이름 있는 레인(Named Lane)**을 세마포어로 구현하여, 계층적 동시성 제어를 제공합니다.

### 2계층 레인 구조

```
Session Lane (max_concurrent=1)
├── session:berserk:analysis   ← 직렬
├── session:cowboy_bebop:analysis ← 직렬
└── session:ghost:analysis     ← 직렬

Global Lane (max_concurrent=4)
└── 전체 세션 합산 4개까지 동시 실행
```

GEODE의 기본 설정은 두 개 레인입니다.

```python
# core/runtime.py — _build_default_lanes()
def _build_default_lanes() -> LaneQueuePort:
    queue = LaneQueue()
    queue.add_lane("session", max_concurrent=1)   # 세션 내 직렬
    queue.add_lane("global", max_concurrent=DEFAULT_GLOBAL_CONCURRENCY)  # 4
    return queue
```

> 설계 의도: 같은 세션(같은 IP)의 요청은 반드시 직렬 처리합니다. 상태 충돌을 원천 차단합니다. 전역적으로는 최대 4개 세션이 동시에 실행될 수 있습니다.

### Lane 클래스 — 세마포어 기반 컨텍스트 매니저

```python
# core/orchestration/lane_queue.py
class Lane:
    def __init__(self, name: str, *, max_concurrent: int = 4,
                 timeout_s: float = 300.0) -> None:
        self.name = name
        self.max_concurrent = max_concurrent
        self.timeout_s = timeout_s
        self._semaphore = threading.Semaphore(max_concurrent)
        self._active: dict[str, float] = {}
        self._lock = threading.Lock()

    @contextmanager
    def acquire(self, key: str) -> Generator[None, None, None]:
        acquired = self._semaphore.acquire(timeout=self.timeout_s)
        if not acquired:
            raise TimeoutError(
                f"Lane '{self.name}' timeout after {self.timeout_s}s"
            )
        with self._lock:
            self._active[key] = time.time()
        try:
            yield
        finally:
            with self._lock:
                self._active.pop(key, None)
            self._semaphore.release()
```

> `_active` 딕셔너리는 현재 실행 중인 작업과 시작 시각을 추적합니다. `get_active()`로 각 작업의 경과 시간을 조회할 수 있어, 대시보드에서 "어떤 분석이 얼마나 오래 걸리고 있는지" 표시할 수 있습니다.

### 다중 레인 획득 — 데드락 방지

여러 레인을 동시에 획득해야 할 때, **순서 획득 / 역순 반환** 원칙으로 데드락(Deadlock)을 방지합니다.

```python
# core/orchestration/lane_queue.py — LaneQueue.acquire_all()
@contextmanager
def acquire_all(self, key: str, lane_names: list[str]
                ) -> Generator[None, None, None]:
    acquired_lanes: list[Lane] = []
    try:
        for name in lane_names:              # 순서대로 획득
            lane = self._lanes[name]
            lane._semaphore.acquire(timeout=lane.timeout_s)
            with lane._lock:
                lane._active[key] = time.time()
            acquired_lanes.append(lane)
        yield
    finally:
        for lane in reversed(acquired_lanes):  # 역순으로 반환
            with lane._lock:
                lane._active.pop(key, None)
            lane._semaphore.release()
```

> 호출 측에서 항상 `["session", "global"]` 순서로 레인을 지정하면, 모든 스레드가 동일 순서로 세마포어를 획득하므로 교차 대기가 발생하지 않습니다. 이는 고전적인 순서 기반 데드락 방지(Lock Ordering) 기법입니다.

---

## 5. Stuck Detection — 교착 감지

파이프라인이 2시간 이상 응답 없이 돌고 있다면, 무언가 잘못된 것입니다. LLM API 타임아웃, 네트워크 단절, 또는 무한 루프. StuckDetector(교착 감지기)는 이 상황을 자동으로 감지하고 해제합니다.

### 설정값

| 항목 | 기본값 | 용도 |
|------|--------|------|
| `timeout_s` | 7200 (2시간) | 이 시간 초과 시 stuck 판정 |
| `check_interval_s` | 60 (1분) | 모니터링 주기 |
| `on_stuck` | 콜백 함수 | stuck 발견 시 호출 |

### 동작 흐름

```
mark_running("berserk:analyst:game_mechanics")
    │
    │  ... 시간 경과 ...
    │
check_stuck()  ← 60초마다 호출
    │
    ├─ elapsed < 7200s → 정상, 무시
    └─ elapsed >= 7200s → stuck 판정
         ├─ running_jobs에서 제거
         ├─ stats.released += 1
         └─ on_stuck(key) 콜백 호출
```

### Hook 연동 — 자동 추적

StuckDetector는 HookSystem에 NODE_ENTER/EXIT/ERROR 핸들러를 등록하여, 수동으로 `mark_running()`/`mark_completed()`를 호출할 필요 없이 자동으로 노드 실행을 추적합니다.

```python
# core/orchestration/stuck_detection.py — register_hooks()
def register_hooks(self, hooks: Any) -> None:
    def _on_enter(_event, data):
        node = data.get("node", "")
        ip = data.get("ip_name", "")
        key = f"{ip}:{node}"
        subtype = data.get("_analyst_type") or data.get("_evaluator_type")
        if subtype:
            key = f"{ip}:{node}:{subtype}"
        self.mark_running(key, metadata={"node": node, "ip_name": ip})

    hooks.register(HookEvent.NODE_ENTER, _on_enter,
                   name="stuck_detector_enter", priority=90)
    # NODE_EXIT, NODE_ERROR도 동일 패턴으로 등록
```

> priority=90으로 등록합니다. TaskBridge(30), RunLog(50) 이후에 실행되어, 교착 감지가 다른 핵심 핸들러를 방해하지 않습니다.

Stuck이 감지되면 `PIPELINE_ERROR` 이벤트를 발화(fire)합니다. 이 이벤트는 RunLog에 기록되고, SnapshotManager가 디버깅용 스냅샷을 캡처하며, TriggerManager가 재분석 트리거를 발동하는 연쇄 반응(Reactive Chain)으로 이어집니다.

```python
# core/orchestration/stuck_detection.py
def _on_stuck_fire_hook(session_key: str) -> None:
    hooks.trigger(
        HookEvent.PIPELINE_ERROR,
        {"source": "stuck_detector", "session_key": session_key},
    )
```

### 백그라운드 모니터링

```python
# core/orchestration/stuck_detection.py
def start_monitor(self) -> None:
    self._monitoring = True
    self._monitor_thread = threading.Thread(
        target=self._monitor_loop,
        daemon=True,
        name="stuck-detector",
    )
    self._monitor_thread.start()

def _monitor_loop(self) -> None:
    while self._monitoring:
        self.check_stuck()
        time.sleep(self._check_interval)  # 60초
```

> `daemon=True`로 메인 프로세스 종료 시 자동 정리됩니다. `stop_monitor()`로 명시적 종료도 가능합니다. 2초 내 join하지 못하면 무시하고 진행합니다.

---

## 6. 통합 — Hook x Runtime x 제어 평면

### GeodeRuntime.create() — 와이어링 흐름

`GeodeRuntime.create("Berserk")`를 호출하면 다음 순서로 제어 평면이 조립됩니다.

```
GeodeRuntime.create("Berserk")
    │
    ├─ 1. _build_hooks()
    │      ├─ HookSystem()           ← 23 이벤트 허브
    │      ├─ RunLog + handler       ← priority=50, 전 이벤트 기록
    │      └─ StuckDetector + handler ← priority=40, PIPELINE_START/END/ERROR
    │
    ├─ 2. CoalescingQueue(250ms)     ← 요청 병합
    │
    ├─ 3. _build_default_lanes()
    │      ├─ session lane(1)        ← 세션 내 직렬
    │      └─ global lane(4)         ← 전역 동시성 4
    │
    ├─ 4. _build_task_graph()
    │      ├─ create_geode_task_graph("Berserk")  ← 13태스크 DAG
    │      └─ TaskGraphHookBridge    ← priority=30, NODE_ENTER/EXIT/ERROR
    │
    └─ 5. 조립 완료 → GeodeRuntime 인스턴스 반환
```

### Priority 기반 핸들러 순서

HookSystem은 priority가 낮을수록 먼저 실행합니다. NODE_ENTER 이벤트가 발화되면 다음 순서로 핸들러가 호출됩니다.

```
NODE_ENTER 발화
    │
    ├─ priority=30: TaskGraphHookBridge._on_node_enter
    │               → Task 상태를 RUNNING으로 전이
    │
    ├─ priority=50: RunLog handler
    │               → JSONL 로그에 이벤트 기록
    │
    └─ priority=90: StuckDetector._on_enter
                    → running_jobs에 시작 시각 기록
```

이 순서가 보장되므로, RunLog가 기록하는 시점에 TaskGraph 상태는 이미 갱신되어 있고, StuckDetector가 추적을 시작하는 시점에 로그는 이미 기록되어 있습니다.

### Health 대시보드 — 전 컴포넌트 통합

`GeodeRuntime.get_health()`는 모든 제어 평면 컴포넌트의 상태를 한 곳에 집약합니다.

```python
# core/runtime.py — get_health() 발췌
health["stuck_tasks"] = len(self.stuck_detector.check_stuck())
health["coalescing_pending"] = self.coalescing.pending_count
health["lanes"] = self.lane_queue.list_lanes()

if self.task_graph is not None:
    health["task_graph"] = {
        "total": self.task_graph.task_count,
        "stats": self.task_graph.stats.to_dict(),
        "is_complete": self.task_graph.is_complete(),
    }
```

### Shutdown — 정리 순서

```python
# core/runtime.py — shutdown()
def shutdown(self) -> None:
    self.coalescing.cancel_all()         # 대기 중인 타이머 취소
    self.config_watcher.stop()           # 파일 감시 중단
    self.stuck_detector.stop_monitor()   # 모니터링 스레드 종료
    if self._task_bridge:
        self._task_bridge.unregister()   # Hook 핸들러 해제
```

> Coalescing의 대기 타이머를 먼저 취소합니다. 타이머가 만료되면서 콜백이 실행되는 경쟁 조건(Race Condition)을 방지하기 위함입니다.

---

## 7. 설계 원천 — OpenClaw에서 GEODE로

GEODE의 제어 평면은 OpenClaw(TypeScript 에이전트 프레임워크)의 패턴을 Python/LangGraph 환경으로 투사(Projection)한 결과입니다. 1:1 번역이 아니라, 각 패턴의 의도를 보존하면서 Python 관용구와 LangGraph 제약에 맞게 재해석했습니다.

### 원본 vs 투사 비교

| 모듈 | OpenClaw (TypeScript) | GEODE (Python) | 변환 |
|------|----------------------|----------------|------|
| **Lane Queue** | 4레인 (Session/Global/Subagent/Hook) | 2레인 (session/global) | LangGraph Send API가 Subagent 레인을 대체. Hook 레인은 HookSystem 내부에서 직렬 실행 |
| **Coalescing** | 250ms + `timer.unref()` | 250ms + `timer.daemon = True` | 수치 동일. Node.js unref → Python daemon thread |
| **Stuck Detection** | `runningAtMs` 2시간 + 해제 | `started_at` 7200s + 해제 | 임계값 동일. ms → s 단위 변환 |
| **Run Log** | JSONL + Pruning (2MB/2000lines) | JSONL + Pruning | 그대로 |
| **Task Graph** | 없음 | 13태스크 DAG + Hook Bridge | GEODE 고유. StateGraph 관찰자로 설계 |
| **Session Key** | `agent:{id}:{context}` | `ip:{name}:{phase}` | 계층 구조 보존, 도메인 키 변환 |
| **Config Reload** | chokidar + 300ms debounce | ConfigWatcher + 300ms debounce | 감시 라이브러리만 변경 |

### 변환 원칙 3가지

**원칙 1: 의도 보존, 구현 재해석**

OpenClaw의 4레인 시스템에서 Subagent Lane(maxConcurrent=8)은 병렬 서브에이전트 실행을 제어합니다. GEODE에서는 LangGraph의 Send API가 이 역할을 구조적으로 수행하므로, 별도 레인이 불필요합니다. Send API는 Private State를 통해 타입 안전한 병렬 분기를 제공하고, Reducer로 자동 합류합니다.

```
OpenClaw: Session Lane → Global Lane → Subagent Lane → 실행
GEODE:    Session Lane → Global Lane → (Send API가 내부 병렬 처리) → 실행
```

**원칙 2: 런타임 특성 존중**

Node.js의 `timer.unref()`는 "이 타이머만으로 이벤트 루프를 유지하지 마라"는 의미입니다. Python에서는 `threading.Timer`에 `daemon=True`를 설정하여 동일한 의미를 달성합니다. 메인 스레드가 종료되면 데몬 스레드도 함께 종료됩니다.

**원칙 3: 없는 것은 만든다**

OpenClaw에는 Task Graph가 없습니다. Gateway가 메시지 라우팅에 집중하는 반면, GEODE는 13단계 파이프라인의 진행 상태를 사용자에게 보여줘야 합니다. Task Graph + Hook Bridge는 이 요구사항을 해결하기 위해 GEODE에서 독자적으로 설계한 모듈입니다.

---

## 8. 마무리

### 핵심 정리

| 모듈 | 역할 | 핵심 수치 | 파일 |
|------|------|----------|------|
| TaskGraph | DAG 상태 추적 | 13태스크, 6상태 | `core/orchestration/task_system.py` |
| TaskGraphHookBridge | Hook → Task 변환 | priority=30 | `core/orchestration/task_bridge.py` |
| CoalescingQueue | 요청 병합 | 250ms window | `core/orchestration/coalescing.py` |
| LaneQueue | 동시성 제어 | session(1), global(4) | `core/orchestration/lane_queue.py` |
| StuckDetector | 교착 감지 | 7200s timeout, 60s interval | `core/orchestration/stuck_detection.py` |
| HookSystem | 이벤트 허브 | 23 events | `core/orchestration/hooks.py` |
| GeodeRuntime | 와이어링 | 전체 조립 | `core/runtime.py` |

### 설계 체크리스트

- StateGraph와 제어 평면이 분리되어 있는가 (실행 vs 관찰)
- TaskGraph가 LangGraph를 제어하지 않고, Hook 이벤트만 수신하는가
- Coalescing 키가 세션 키와 일치하여 동일 IP 요청을 정확히 병합하는가
- Lane 획득 순서가 고정되어 데드락 가능성이 없는가
- Stuck 타임아웃이 파이프라인 최대 소요 시간보다 충분히 큰가
- 실패 전파가 하류 태스크를 SKIP 처리하여 불필요한 LLM 호출을 방지하는가
- priority 순서로 핸들러 실행 순서가 보장되는가 (30 → 50 → 90)
- shutdown()에서 타이머, 스레드, Hook 핸들러가 모두 정리되는가
