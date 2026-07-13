# GEODE Hook System

> [English](hook-system.md) | **한국어**

`core/hooks/`는 GEODE 런타임의 저장소 독립적인 이벤트 버스다. 65개
`HookEvent` 호환 표면, 우선순위 핸들러, interceptor/feedback, 그리고
post-dispatch sink를 제공한다. 영속성 정책은
[`event-persistence.md`](event-persistence.md)에 별도로 정의한다.

## 핵심 계약

1. 핸들러는 낮은 priority부터 순차 실행한다.
2. 한 핸들러의 예외는 이후 핸들러를 중단하지 않는다.
3. observer/feedback 핸들러는 각각 top-level payload 복사본을 받는다.
4. interceptor의 `modify`만 다음 핸들러의 입력에 명시적으로 반영된다.
5. 한 trigger 호출은 완료 후 sink마다 정확히 한 `HookDispatch`를 보낸다.
6. 이름 충돌은 묵시적으로 덮어쓰지 않는다. 의도적 교체는
   `replace=True`가 필요하다.
7. `HookSystem.close()`는 등록·전역 바인딩·sink를 결정적으로 해제하며
   여러 번 호출해도 안전하다. SQLite 연결은 각 저장 연산이 반환되기
   전에 닫힌다.

## 디스패치 구조

```text
event source
  -> exact + prefix handler resolve
  -> priority sort / name dedup
  -> handler chain
  -> HookDispatch(final data, results, block state, timing)
  -> post-dispatch sinks (once each)
       -> HookPersistenceSink
            -> sessions.db:hook_events
            -> active run transcript (선별 mirror)
```

`HookSystem` 자체는 `core.observability`를 import하지 않는다. 생산
부트스트랩이 `HookPersistenceSink`를 등록하므로 단위 테스트나 임베디드
사용자는 원하는 sink를 선택할 수 있다.

## 트리거 모드

| 의미 | 동기 API | 비동기 API | 반환 |
|---|---|---|---|
| Observe | `trigger()` | `trigger_async()` | `list[HookResult]` |
| Feedback | `trigger_with_result()` | `trigger_with_result_async()` | handler 반환 dict를 담은 결과 |
| Interceptor | `trigger_interceptor()` | `trigger_interceptor_async()` | `InterceptResult` |

Interceptor 반환 규약:

```python
{"block": True, "reason": "policy"}
{"modify": {"tool_input": {"path": "safe.txt"}}}
None
```

도구 결과 변경은 `TOOL_RESULT_TRANSFORM` 한 단계가 소유한다.
`transformed_result`, 이전 호환 키인 `updated_result`,
`additional_context`를 처리한 뒤 최종 `TOOL_EXEC_ENDED`가 발생한다.
`TOOL_EXEC_FAILED`는 외부 핸들러 호환 신호이며 영속성에서는
`TOOL_EXEC_ENDED(has_error=True)`와 중복 저장하지 않는다.

## 등록과 해제

```python
subscription = hooks.register(
    HookEvent.SESSION_ENDED,
    on_session_end,
    name="session_index",
    priority=60,
)

subscription.cancel()  # idempotent
```

- `register_prefix("SUBAGENT", ...)`는 `SUBAGENT_*`를 구독한다.
- `register_prefix("*", ...)`는 모든 이벤트를 구독한다.
- 같은 이름이 겹치는 exact/prefix 범위에서 서로 다른 핸들러를 가리키면
  `DuplicateHookRegistrationError`가 발생한다.
- tool matcher 정규식은 등록 시 compile된다. 잘못된 정규식은 fail-open이
  아니라 즉시 `ValueError`다.
- matcher가 있는 핸들러는 `tool_name`이 없는 payload에 실행되지 않는다.

## Timeout

동기 Python 함수를 안전하게 강제 중단할 방법은 없다. 따라서
`timeout_s > 0`인 동기 interceptor는 실행하지 않고
`HookTimeoutUnsupportedError`를 `HookResult` 실패로 기록한다. 이전
ThreadPoolExecutor 방식처럼 timeout 이후에도 버려진 thread가 살아남지 않는다.

비동기 핸들러는 `asyncio.wait_for`로 취소되며
`HookExecutionTimeoutError`로 분류된다.

## 생산 영속성

`build_hooks()`는 wildcard 기록 핸들러 대신 post-dispatch sink 하나를
등록한다.

- 쿼리·필터·보존 정책이 필요한 운영 이벤트: `sessions.db:hook_events`
- 활성 autoresearch 실행의 portable timeline: `transcript.jsonl`
- 호환 중복 이벤트: 핸들러에는 전달, SQL/transcript에는 미기록
- raw `user_input`, prompt, tool input/result, cognitive snapshot, 인증 헤더:
  미기록
- payload: 깊이/문자열/collection/전체 bytes 제한 및 secret redaction
- retention: high-volume 7일, standard 30일, audit 180일, 전체 100,000행

최근 실행 컨텍스트도 더 이상 `runs/*.jsonl`을 scan하지 않고
`hook_events`의 `SESSION_ENDED`를 조회한다.

## 도구 라이프사이클

모든 허용된 도구 시도는 다음 pair를 완결한다.

```text
TOOL_EXEC_STARTED (interceptor)
  -> blocked | execute | adaptive recovery
  -> TOOL_RESULT_TRANSFORM (feedback, transient)
  -> TOOL_EXEC_ENDED (canonical terminal)
  -> TOOL_EXEC_FAILED (error compatibility signal only)
```

차단, 복구, executor 예외도 terminal event를 건너뛰지 않는다. 최종
`has_error`는 transformation과 clarification guard가 끝난 뒤 계산한다.

## 플러그인

외부 플러그인은 `.geode/hooks/<name>/hook.py` 또는 `hook.yaml`에서만
자동 발견한다. `core/hooks/plugins/`의 built-in은 부트스트랩에서 명시적으로
한 번 등록한다. 이 구분으로 notification 같은 built-in이 explicit wiring과
filesystem discovery 양쪽에서 두 번 등록되는 문제를 막는다.

동적 모듈 로더는 임시 `sys.modules` 항목을 load 후 복원해 반복 reload 시
module 객체를 누수하지 않는다.

## 수명주기

`HookSystem.close()`는 다음 순서로 동작한다.

1. 새 등록을 차단하고 handler/prefix 참조를 제거한다.
2. 역순 cleanup callback으로 router/MCP/tool ContextVar와 보조 SQLite
   store를 해제한다. owner cleanup은 약한 참조를 사용해 자기 참조
   cycle을 만들지 않는다.
3. 역순 sink close로 `HookEventStore`를 비활성화한다. DB/WAL/SHM
   descriptor는 이미 각 저장 연산이 끝날 때 닫힌 상태다.

Runtime, serve, worker, 일회성 memory-lifecycle command는 각자 소유한
HookSystem을 종료해야 한다.
