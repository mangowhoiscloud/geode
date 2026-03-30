# SessionLane: OpenClaw에서 배운 Per-Key Serialization — 4-Lane에서 Per-Session 직렬화로

> Date: 2026-03-30 | Author: geode-team | Tags: concurrency, session-management, OpenClaw, LaneQueue, semaphore

## 목차
1. 문제: 4-Lane 시스템의 한계
2. OpenClaw의 Session Key 패턴
3. SessionLane 설계
4. acquire_all(): 통합 진입점
5. Idle Cleanup
6. 정리

---

## 1. 문제: 4-Lane 시스템의 한계

v0.36 이전 GEODE는 4개의 Named Lane으로 동시성을 제어했습니다:

```
session_lane  (max=1)   — REPL 세션
global_lane   (max=8)   — 전체 병렬 실행
gateway_lane  (max=4)   — Slack/Discord
scheduler_lane(max=2)   — Cron 작업
```

문제는 **session_lane이 전체 시스템에 1개**라는 점입니다. 사용자 A의 IPC 세션이 실행 중이면 사용자 B의 세션은 대기합니다. 실제로는 서로 다른 세션이므로 병렬 실행이 가능해야 합니다.

gateway_lane과 scheduler_lane도 마찬가지입니다. "Slack 메시지 4개까지 동시 처리"라는 제약은 있지만, 같은 채널의 메시지가 순서를 지켜야 하는지에 대한 보장이 없었습니다.

## 2. OpenClaw의 Session Key 패턴

OpenClaw(오픈소스 에이전트 프레임워크)는 이 문제를 Session Key 기반 직렬화로 해결합니다:

- **같은 session key** → 직렬 실행 (한 세션 내 요청은 순서대로)
- **다른 session key** → 병렬 실행 (독립 세션은 동시에)

GEODE에서 session key는 자연스럽게 존재합니다:
- IPC: `ipc:{pid}` (클라이언트 프로세스 ID)
- Gateway: `slack:{channel_id}` (채널 단위 직렬)
- Scheduler: `sched:{job_id}` (작업 단위 직렬)

## 3. SessionLane 설계

```
┌─ SessionLane (per-key Semaphore(1)) ──────────────────┐
│  ipc:1234 ──── Sem(1) ──── [executing]                │
│  ipc:5678 ──── Sem(1) ──── [executing]    ← 병렬     │
│  slack:C01 ─── Sem(1) ──── [waiting]                  │
│  slack:C01 ─── Sem(1) ──── [blocked]      ← 직렬     │
│  max_sessions = 256                                   │
└───────────────────────────────────────────────────────┘
          │
          ▼
┌─ Lane("global", max=8) ──────────────────────────────┐
│  전체 시스템 병렬 실행 상한                              │
└───────────────────────────────────────────────────────┘
```

핵심 구현:

```python
# core/orchestration/lane_queue.py

@dataclass
class _SessionEntry:
    semaphore: threading.Semaphore  # Semaphore(1) — per-key serial
    held: bool = False
    last_used: float = 0.0

class SessionLane:
    def __init__(self, max_sessions: int = 256, idle_timeout_s: float = 300.0):
        self._sessions: dict[str, _SessionEntry] = {}
        self._lock = threading.Lock()
        self.max_sessions = max_sessions
        self.idle_timeout_s = idle_timeout_s
```

> `Semaphore(1)`은 `Lock`과 동일한 효과이지만, `acquire(timeout=N)` 지원과 `LaneQueue` API 일관성을 위해 Semaphore를 사용합니다.

`_raw_acquire`는 세션이 없으면 생성하고, `max_sessions` 초과 시 idle 세션을 정리합니다:

```python
def _raw_acquire(self, key: str) -> bool:
    with self._lock:
        entry = self._sessions.get(key)
        if entry is None:
            if len(self._sessions) >= self.max_sessions:
                self._evict_idle_locked()
                if len(self._sessions) >= self.max_sessions:
                    return False  # still full after eviction
            entry = _SessionEntry(semaphore=threading.Semaphore(1))
            self._sessions[key] = entry
    acquired = entry.semaphore.acquire(timeout=self._acquire_timeout)
    if acquired:
        with self._lock:
            entry.held = True
            entry.last_used = time.time()
    return acquired
```

> lock 범위가 **세션 조회/생성**에만 한정됩니다. semaphore acquire는 lock 밖에서 수행합니다. lock 안에서 blocking acquire를 하면 다른 세션 키의 생성까지 차단되기 때문입니다.

## 4. acquire_all(): 통합 진입점

모든 실행 경로(CLI, Gateway, Scheduler)가 동일한 진입점을 사용합니다:

```python
# core/orchestration/lane_queue.py
@contextmanager
def acquire_all(self, key: str, lane_names: list[str]):
    acquired: list[Lane | SessionLane] = []
    try:
        for name in lane_names:
            lane = self._resolve_lane(name)
            if not lane._raw_acquire(key):
                raise TimeoutError(f"Lane '{name}' timeout for '{key}'")
            acquired.append(lane)
        yield
    finally:
        for item in reversed(acquired):
            item._raw_release(key)
```

호출 측:

```python
# CLI, Gateway, Scheduler 모두 동일
async with lane_queue.acquire_all(session_key, ["session", "global"]):
    session = create_session(mode)
    await session.execute(prompt)
```

> `["session", "global"]` 순서가 중요합니다. session lane을 먼저 획득하여 같은 세션의 동시 요청을 차단하고, 그 다음 global lane으로 전체 병렬도를 제한합니다. 역순으로 하면 global 슬롯을 점유한 채 session 대기하는 비효율이 발생합니다.

## 5. Idle Cleanup

세션이 300초간 사용되지 않으면 자동 정리됩니다:

```python
def cleanup_idle(self) -> int:
    with self._lock:
        return self._evict_idle_locked()

def _evict_idle_locked(self) -> int:
    now = time.time()
    to_remove = [
        k for k, e in self._sessions.items()
        if not e.held and (now - e.last_used) > self.idle_timeout_s
    ]
    for k in to_remove:
        del self._sessions[k]
    return len(to_remove)
```

> `e.held` 체크가 핵심입니다. 실행 중인 세션은 idle 시간과 무관하게 보존됩니다. 정리 대상은 "semaphore가 해제된 상태에서 300초 이상 미사용"인 세션입니다.

## 6. 정리

| 항목 | 4-Lane (v0.36) | SessionLane (v0.37) |
|------|----------------|---------------------|
| 세션 간 관계 | 전체 직렬 (session_lane max=1) | 같은 key만 직렬, 다른 key 병렬 |
| 최대 병렬 세션 | 1 | 256 (max_sessions) |
| Gateway/Scheduler | 전용 lane (hardcoded max) | session key 기반 동적 |
| 진입점 | lane별 개별 acquire | `acquire_all(key, ["session", "global"])` |
| Idle 관리 | 없음 | 300s auto-eviction |
| 코드 라인 | 4개 Semaphore 선언 | SessionLane 180줄 + Lane 120줄 |

**삭제한 것**: `CoalescingQueue` (148줄, 0 trigger), standalone REPL `_interactive_loop` (~487줄), gateway/scheduler 전용 lane.

**설계 교훈**: "고정 슬롯 수"로 동시성을 제어하면 단순하지만, 독립적인 요청까지 직렬화됩니다. "요청의 identity(세션 키)"를 기준으로 직렬/병렬을 분리하면 더 자연스러운 동시성 모델이 됩니다.
