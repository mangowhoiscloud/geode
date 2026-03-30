# Race Condition 사냥기 — 멀티스레드 에이전트 시스템에서 발견한 6개의 동시성 버그

> Date: 2026-03-30 | Author: geode-team | Tags: concurrency, race-condition, threading, Python, agent-system

## 목차
1. 배경: 왜 에이전트 시스템에 Race Condition이 생기는가
2. Bug 1: Announce Double-Publish
3. Bug 2: Semaphore Leak
4. Bug 3: TaskGraph 이중 실행
5. Bug 4: acquire_all() 부분 실패
6. Bug 5: Zombie Thread 잔류
7. Bug 6: PIPELINE_END 이벤트 오용
8. 정리: 패턴 카탈로그

---

## 1. 배경: 왜 에이전트 시스템에 Race Condition이 생기는가

단일 LLM 호출은 동시성 문제가 없습니다. 하지만 **sub-agent 병렬 실행**, **scheduler 백그라운드 작업**, **Gateway 폴링**이 동시에 돌아가는 시스템에서는 공유 상태가 곳곳에 생깁니다.

GEODE의 실행 경로는 3개입니다:
- **CLIPoller**: 사용자 입력 처리 (IPC)
- **Gateway**: Slack/Discord 폴링 (daemon thread)
- **Scheduler**: cron 작업 (daemon thread)

이 3개가 동일한 `LaneQueue`, `HookSystem`, `announce_queue`를 공유합니다. v0.35.1에서 6개의 동시성 버그를 수정했습니다.

## 2. Bug 1: Announce Double-Publish

**증상**: sub-agent 결과가 parent AgenticLoop에 2번 주입되어 LLM이 동일 정보를 중복 처리.

**원인**: `_announce_result()`에 lock이 없었습니다. 두 스레드가 동시에 같은 `child_result`를 큐에 push할 수 있었습니다.

```python
# BEFORE (race condition)
def _announce_result(self, parent_key, child_result):
    _announce_queue.setdefault(parent_key, []).append(child_result)
    child_result.announced = True
```

```python
# AFTER — core/agent/sub_agent.py
def _announce_result(self, parent_session_key: str, child_result: SubAgentResult) -> None:
    with _announce_lock:
        if child_result.announced:
            return
        child_result.announced = True
        _announce_queue.setdefault(parent_session_key, []).append(child_result)
        _announce_timestamps[parent_session_key] = time.time()
```

> **Check-and-set 패턴**: `announced` 플래그 확인과 설정이 동일 lock 안에 있어야 합니다. lock 밖에서 `if not announced` → lock 안에서 `announced = True`를 하면 TOCTOU(Time-of-Check-Time-of-Use) race가 발생합니다.

추가로 `_announce_timestamps`에 TTL(300s)을 설정하여, parent가 비정상 종료해도 stale 큐 엔트리가 자동 정리됩니다.

## 3. Bug 2: Semaphore Leak

**증상**: 시간이 지나면 sub-agent 병렬 실행이 점점 줄어들다 멈춤.

**원인**: `_acquire_slot()`에서 semaphore를 획득한 후 실행 중 예외가 발생하면, finally에서 해제되지 않는 경로가 있었습니다.

```python
# BEFORE (leak path)
def _execute_thread(self, config):
    self._acquire_slot(config)      # semaphore acquired
    try:
        result = self._run(config)  # exception here...
    finally:
        self._release_slot(config)  # ...but _release_slot checks _active dict
                                    # which wasn't updated on acquire
```

```python
# AFTER — core/orchestration/isolated_execution.py
def _execute_thread(self, config):
    acquired = False
    try:
        slot_err = self._acquire_slot(config)
        if slot_err:
            return slot_err
        acquired = True
        result = self._run(config)
    finally:
        if acquired:
            self._release_slot(config)
```

> **acquired flag 패턴**: semaphore를 획득했는지 여부를 별도 변수로 추적합니다. `_acquire_slot`이 timeout으로 실패한 경우에는 `acquired=False`이므로 해제하지 않습니다. 이 패턴은 `contextlib.ExitStack`보다 명확합니다.

## 4. Bug 3: TaskGraph 이중 실행

**증상**: 같은 task가 2개 worker에서 동시에 실행됨.

**원인**: `get_ready_tasks()` → `mark_running()` 사이에 다른 스레드가 같은 task를 ready 상태로 가져감.

```python
# AFTER — core/orchestration/task_system.py
def __init__(self) -> None:
    self._tasks: dict[str, Task] = {}
    self._lock = threading.Lock()

def add_task(self, task: Task) -> None:
    with self._lock:
        if task.task_id in self._tasks:
            raise ValueError(f"Task '{task.task_id}' already exists")
        self._tasks[task.task_id] = task

def mark_running(self, task_id: str) -> None:
    with self._lock:
        task = self._require_task(task_id)
        if task.status not in (TaskStatus.PENDING, TaskStatus.READY):
            raise ValueError(f"Cannot start '{task_id}' in '{task.status.value}'")
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
```

> **상태 전이 guard**: `mark_running()`이 lock 안에서 현재 상태를 재확인합니다. `READY → RUNNING` 전이만 허용하므로, 두 번째 스레드가 같은 task를 시작하려 하면 `ValueError`가 발생합니다.

## 5. Bug 4: acquire_all() 부분 실패

**증상**: session lane은 획득했지만 global lane 획득에 실패 → session lane이 해제되지 않아 해당 session key가 영구 잠김.

```python
# AFTER — core/orchestration/lane_queue.py
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

> **역순 해제**: 획득한 순서의 역순으로 해제합니다 (stack unwinding). `acquired` 리스트에는 실제로 획득에 성공한 lane만 들어있으므로, 부분 실패 시에도 정확히 획득한 것만 해제합니다.

## 6. Bug 5: Zombie Thread 잔류

**증상**: timeout된 sub-agent 스레드가 `_active` dict에 남아 `active_count`가 실제보다 높게 보고됨.

**수정**: timeout 시 `_active`와 `_cancel_flags`에서 제거하는 cleanup 로직 추가. 간단하지만 놓치기 쉬운 부분입니다.

## 7. Bug 6: PIPELINE_END 이벤트 오용

**증상**: `[Berserk] tier=?, score=0.00` stub 데이터가 메모리에 기록됨.

**원인**: `isolated_execution.py`의 `_post_to_main()`이 sub-agent 완료 시 `PIPELINE_END`를 fire. 이 이벤트에 등록된 memory write-back 핸들러가 `ip_name`, `tier`, `final_score`가 없는 데이터를 기본값으로 기록.

```python
# BEFORE — core/orchestration/isolated_execution.py
self._hooks.trigger(HookEvent.PIPELINE_END, data)  # data has no ip_name/tier/score

# AFTER
self._hooks.trigger(HookEvent.SUBAGENT_COMPLETED, data)
```

> **이벤트 시맨틱 분리**: `PIPELINE_END`는 "분석 파이프라인 완료"이고 `SUBAGENT_COMPLETED`는 "sub-agent 실행 완료"입니다. 같은 "완료"지만 컨텍스트가 다릅니다. HookSystem의 이벤트를 재사용하면 의도하지 않은 핸들러가 실행됩니다.

## 8. 정리: 패턴 카탈로그

| Bug | 패턴 | 핵심 원칙 |
|-----|------|-----------|
| Double-publish | Lock 안에서 check-and-set | TOCTOU 방지 |
| Semaphore leak | `acquired` flag + finally | 획득 여부 명시적 추적 |
| 이중 실행 | Lock 안에서 상태 전이 guard | 상태 머신 원자성 |
| 부분 실패 | `acquired` 리스트 + 역순 해제 | Stack unwinding |
| Zombie thread | timeout 시 tracking dict cleanup | 리소스 생명주기 일치 |
| 이벤트 오용 | 시맨틱이 다른 이벤트 분리 | Single Responsibility |

공통 원칙은 하나입니다: **"공유 상태 접근은 항상 보호하고, 보호 범위는 최소한으로."**

Lock 범위가 넓으면 deadlock 위험이 커지고, 좁으면 race가 남습니다. GEODE에서는 각 공유 자원(announce_queue, TaskGraph, LaneQueue)마다 독립된 fine-grained lock을 사용합니다.
