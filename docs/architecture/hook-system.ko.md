# GEODE Extension Surface

> [English](hook-system.md) | **한국어**

GEODE는 extension 권한을 세 표면으로 분리한다. 사용자 계약은
Hermes처럼 작게 유지하되, GEODE의 세밀한 운영 타임라인은 내부에 보존한다.

| 표면 | canonical API | 권한 | 대상 |
|---|---|---|---|
| 공개 hook | `HookName`, `HookRegistry` | 안정된 13개 checkpoint의 제한된 결정 | 사용자·plugin |
| trusted middleware | `MiddlewareRegistry` | 요청 변형과 실제 실행 wrapping | 신뢰된 in-process extension |
| runtime event | `RuntimeEvent`, `RuntimeEventBus` | 관측·감사·영속화 전용 | 런타임·운영자 |

compaction, approval, sub-agent 실행, verification은 상태 전이를 소유하는
domain service다. checkpoint를 노출하지만 네 번째 extension 표면은 아니다.

설계 기록과 실측 마이그레이션 맵은
[`../plans/2026-07-30-hook-taxonomy-fold.md`](../plans/2026-07-30-hook-taxonomy-fold.md),
영속성 정책은 [`event-persistence.md`](event-persistence.md)에 있다.

## 공개 hook

`HookRegistry`는 아래 `HookName`만 받으며 wildcard 등록을 제공하지 않는다.
handler는 priority 순서로 실행되고 rewrite는 앞 결과를 다음 입력으로
합성한다. block/deny가 나오면 chain을 멈춘다.

| Hook | 경계 | 허용 결정 |
|---|---|---|
| `UserPromptSubmit` | user input admission 전 | continue, rewrite, block |
| `PreToolUse` | `tool_request` 후, policy/approval 전 | continue, rewrite, block, request permission |
| `PermissionRequest` | 실제 사람에게 묻기 직전 | allow, deny, ask |
| `PostToolUse` | 결과 생성 후 model context 반영 전 | continue, add context, block |
| `PreCompact` | runtime-owned compaction 직전 | continue, rewrite, soft defer |
| `PostCompact` | compacted state commit 후 | continue |
| `SessionStart` | durable create/resume 성공 후 | continue |
| `SessionEnd` | durable terminal state 성공 후 | continue |
| `SubagentStart` | child identity·격리 확정 후 | continue |
| `SubagentStop` | terminal child result 확정 후 | continue |
| `PreVerify` | built-in verifier 전 | continue, strengthen |
| `PostVerify` | immutable verifier 결과 후 | accept, revise, escalate |
| `Stop` | 최종 전달 직전 | finalize, bounded continue |

현재 호출은 버전이 고정된 `geode.public-hook.v2` envelope를 쓴다. 기존 v1
schema는 호환성을 위해 그대로 조회할 수 있다.

```python
from core.hooks import HookName, HookRegistry, public_hook_schema

hooks = HookRegistry()
schema = public_hook_schema(HookName.POST_VERIFY)
legacy_schema = public_hook_schema(
    HookName.POST_VERIFY,
    version="geode.public-hook.v1",
)
```

입력은 JSON-safe, secret-redacted, 깊이·크기 제한을 거치며 hook별 JSON
Schema로 최초 입력과 rewrite 후 입력을 모두 검증한다. raw provider request,
인증 정보, personal tool argument, screenshot, base64, 무제한 tool output은
공개 payload에 넣지 않는다.
공개 handler의 기본 제한은 10초다. 동기 handler는 별도 worker thread에서
실행해 blocking extension이 AgenticLoop event loop를 멈추지 못하게 하고,
비동기 handler는 직접 취소한다. timeout된 동기 thread가 자체 작업을 나중에
끝낼 수 있으므로 side effect가 있는 extension은 여전히 idempotent해야 한다.

### Verification과 외부 loop

finalization은 하나의 state machine이다.

```text
candidate -> PreVerify -> built-in verifier -> PostVerify -> Stop -> persist/deliver
                                                |             |
                                                +-- revise ---+
```

`PreVerify`는 검증 요구를 추가만 할 수 있다. `PostVerify`는 immutable한
built-in 결과를 받아 pass 수용·증거 강화, 명시적 지시가 있는 bounded
revision, 외부 판단 escalation을 선택한다.

hook은 built-in 실패를 성공으로 뒤집을 수 없다. revision 횟수는 고정되어
있고 이미 끝난 tool side effect를 재생하지 않은 채 follow-up turn을 시작한다.
따라서 evaluator, CI, human-review 같은 외부 loop가 `PostVerify`를 안전하게
사용하면서도 GEODE verifier의 단조 권위를 보존한다. 외부 `PostVerify`
handler가 결정을 반환하지 않으면 runtime은 같은 단조 기본 정책을 적용한다.
pass는 accept, 재시도 가능한 실패는 revise, 재시도 불가능한 실패는
escalate한다. revision 지시는 dynamic system context에 한 번만 들어가며 user
message나 task decomposition으로 전달되지 않는다. `verification.decided`는
후보 본문을 복제하지 않고 최종 정책과 handler별 결정을 후보 SHA-256 digest,
root turn, verify attempt에 결합한다. escalation은 telemetry
표식이 아니라 delivery gate다. GEODE는 세션을
`external_verification_required`로 pause하고 후보를
`AgenticResult.pending_text`로 외부 소유자에게만 돌려주며 terminal
`session.ended` record를 만들지 않는다. `Stop`은 더 좁다. verification
policy를 통과한 뒤 최종 전달과 한 번의 bounded continuation만 결정한다.

## Trusted middleware

`MiddlewareRegistry` 하나에 네 typed registration method만 둔다.
`MiddlewareKind`, `MiddlewarePoint`, 별도 pipeline 객체는 없다.

```python
registry.register_tool_request(tool_request_middleware)
registry.register_tool_execution(tool_execution_middleware)
registry.register_llm_request(llm_request_middleware)
registry.register_llm_execution(llm_execution_middleware)
```

request middleware는 immutable snapshot을 N→N+1로 변형한다. execution
middleware는 승인된 executor/provider 호출을 감싸는 async onion이다.
`next_call`은 한 번만 호출할 수 있고, 호출하지 않으면 명시적
short-circuit다. downstream exception과 cancellation의 identity는 보존한다.
기본 제한은 request transform 10초, tool execution wrapper 300초, LLM
execution wrapper 900초이며 명시적 0은 제한 해제다. `next_call`이 이미
완료된 뒤 wrapper가 예외를 내면 GEODE는 완료 결과를 보존해 side effect나
provider billing을 재실행하지 않는다.

도구 경로:

```text
tool_request transform
  -> schema validation
  -> PreToolUse
  -> schema revalidation
  -> hard policy
  -> PermissionRequest / approval
  -> tool_execution onion
  -> TOOL_EXEC_STARTED
  -> terminal executor 1회 호출
  -> TOOL_EXEC_ENDED
  -> PostToolUse
```

execution middleware는 이미 승인된 tool name/arguments를 바꿀 수 없다.
personal-data 분류는 request rewrite를 가로질러 단조적으로 유지되므로
rename으로 consent나 retention policy를 낮출 수 없다. short-circuit는
`TOOL_EXEC_STARTED`를 발화하지 않는다.

LLM 경로:

```text
assembled AdapterCallRequest
  -> llm_request transform
  -> llm_execution onion
  -> LLMAdapter.acomplete()
```

main loop, reflection, candidate sampling, API mutation을 포함한다.
cache-sensitive한 prompt/messages/tools 변경은 등록 capability와 명시적인
cache-invalidation reason을 모두 요구한다.

## Runtime event

관측의 canonical API는 `RuntimeEventBus.subscribe()`와 `emit()`이다.
기존 stored value 56개는 그대로 두고, 확장 호출 감사용
`EXTENSION_INVOKED` 하나만 추가해 내부 어휘는 57개다. 이 이벤트는
`surface`, checkpoint, extension, status, duration, correlation 같은 제한된
귀속 정보만 기록하며 request/response 본문은 기록하지 않는다.

마이그레이션 동안 `HookEvent = RuntimeEvent`,
`HookSystem = RuntimeEventBus` runtime identity alias를 유지한다.
legacy feedback/interceptor method도 source compatibility를 위해 남지만
production control path는 더 이상 호출하지 않는다. 새 제어는 공개 hook,
trusted middleware, 또는 상태를 소유한 domain service에 둔다.

내부 `SESSION_STARTED/ENDED`의 과거 행 의미는 old reader를 위해 유지한다.
공개 `SessionStart/End`는 durable session lifetime이며 매 turn 경계를
그대로 projection한 것이 아니다.

## Telemetry와 lifecycle 경계

event bus는 저장소를 모른다. production wiring이
`HookPersistenceSink` 하나를 등록한다.

```text
RuntimeEventBus
  -> HookPersistenceSink
       -> sessions.db:hook_events       canonical 운영 이력
       -> active run events.jsonl       조건부 portable projection
```

- SQLite가 canonical indexed history이며 JSONL projection 존재에 의존하지 않는다.
- JSONL은 active `RunTimeline`이 bind된 동안만 쓴다.
- `EXTENSION_INVOKED`는 audit retention bucket을 쓴다.
- compatibility duplicate는 legacy subscriber에는 전달하지만 두 번 저장하지 않는다.
- raw prompt, personal data, tool body/result, cognitive snapshot, 인증 정보는
  제외하거나 제한된 metadata로 줄인다.
- telemetry sink 실패는 hook, middleware, lifecycle의 정합성을 바꾸지 않는다.

`SessionStart`는 최초/resume checkpoint 성공 후에만 발화한다.
`SessionEnd`는 completed/error terminal state가 durable해진 뒤에만 발화한다.
paused turn은 session을 끝내지 않는다. `PostCompact`도 compacted state
영속화가 성공한 뒤에만 발화한다.
owner는 `amark_session_completed/error`로 닫아 durable state와 public
`SessionEnd` edge를 하나의 await 경계에서 처리한다.

### 라이브 행동 증거

2026-07-31 subscription 기반 행동 E2E는 13개 공개 hook과 네 middleware
join point를 각각의 실제 소유 runtime 경로로 모두 통과했다. LLM 호출 3회,
admission을 통과한 single-invocation tool 호출 1회와 실제 compaction 영속화 1회를 수행했고,
SQLite와 active JSONL projection 양쪽에 동일한 `EXTENSION_INVOKED` 22행을
남겼다. tool start/end 행의 session/turn correlation도 두 저장소에서
일치했다.

검토를 마친 정규화 27-event decision/tool trajectory와 manifest는 불변
[hook/middleware 행동 E2E 산출물](https://github.com/mangowhoiscloud/geode-eval-artifacts/tree/3e5b35f4505a4a2dc76d595b24862e8e73e668ff/trajectories/geode-agenticloop-hook-middleware-behavior-e2e-20260731T001640Z-1326e99cb447)에
발행했다. raw prompt, checkpoint, provider reasoning, database/WAL, usage,
diagnostic은 공개하지 않는 runtime 증거로 유지한다.

## 마이그레이션 맵

| legacy/control 형태 | canonical owner | 호환 |
|---|---|---|
| `HookEvent` | `RuntimeEvent` | alias, stored value 무변경 |
| `HookSystem` | `RuntimeEventBus` | alias, sink/subscriber 무변경 |
| observer `register` / `trigger*` | `subscribe` / `emit*` | legacy method 유지 |
| `USER_INPUT_RECEIVED` interception | `UserPromptSubmit` | 내부 event는 observation |
| `TOOL_EXEC_STARTED` interception | `PreToolUse` + 실제 start event | start는 approval 뒤로 이동 |
| `TOOL_RESULT_TRANSFORM` feedback | `PostToolUse` | legacy event는 non-canonical |
| `CONTEXT_OVERFLOW_ACTION` feedback | compaction policy + Pre/PostCompact | hard invariant는 domain service 소유 |
| approval control event | `PermissionRequest` + approval transition | 기존 audit value 계속 읽음 |
| sub-agent event 3종 | `SubagentStart/Stop` projection | 내부 outcome 유지 |
| verify pass/fail event | `PreVerify`/`PostVerify` + 내부 outcome | stored outcome 유지 |
| executor/provider wrapping 누락 | tool/LLM execution middleware | event alias 없음 |

canonical name은 `HookName`, `HookRegistry`, `MiddlewareRegistry`,
`RuntimeEvent`, `RuntimeEventBus`와 네 role-specific middleware protocol에서
끝난다. service locator나 네 번째 extension plane은 만들지 않는다.

## 등록과 종료

공개 hook과 middleware 등록 이름은 묵시적으로 교체되지 않는다.
process-owned registry pair를 main loop, tool executor, approval workflow,
context manager, sub-agent manager에 주입한다. runtime, serve, worker는
process마다 한 pair를 공유한다.

`RuntimeEventBus.close()`는 새 등록을 막고 subscriber를 비운 뒤 cleanup과
sink를 역순으로 닫는다. SQLite 연결은 각 연산 후 닫히며 close는
idempotent하다.
