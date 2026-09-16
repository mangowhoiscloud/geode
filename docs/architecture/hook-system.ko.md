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

## 계약 소유자와 명명 규격

이름 표기는 [명명 규약](naming-conventions.md#25-constants-tools-and-events),
확장 동작은 이 문서가 소유한다. Python enum member와 wire name은
서로 다른 식별자이며 교환 가능한 alias가 아니다.

| 계약 | 코드 소유자 | 명명 / API | 회귀검사 경계 |
|---|---|---|---|
| 공개 결정 | [public.py](../../core/hooks/public.py) | `HookName.PRE_TOOL_USE` → `PreToolUse`; `HookAction.ADD_CONTEXT` → `add_context` | [Schema·결정·dispatch](../../tests/core/hooks/test_public_hooks.py) |
| 도구 승인·결과 | [executor.py](../../core/agent/tool_executor/executor.py), [approval.py](../../core/agent/approval.py) | `PreToolUse`, `PermissionRequest`, `PostToolUse` | [실제 runtime 연결](../../tests/core/hooks/test_public_hook_wiring.py) |
| 신뢰된 변형·wrapper | [middleware.py](../../core/hooks/middleware.py) | `register_tool_request`, `register_tool_execution`와 LLM 대응 메서드 | [합성·단일 호출](../../tests/core/hooks/test_middleware.py) |
| 관측 | [system.py](../../core/hooks/system.py) | `RuntimeEvent.TOOL_EXEC_STARTED` → `tool_exec_started`; `subscribe` / `emit` | [Subscriber lifecycle](../../tests/core/hooks/test_hook_system_lifecycle.py) |

Schema 통과만으로 runtime 연결, 승인 통제, telemetry 영속화를 입증하지
않는다. 변경된 입력 생산자와 소비자를 함께 검사한다.

### 경계별 회귀검사

| 경계 | 보장할 동작 | 회귀검사 |
|---|---|---|
| 관측 → 실행 | subscriber마다 중첩 데이터까지 복사한다. 관측자가 승인된 tool 인자, 다음 subscriber 또는 저장할 이벤트를 바꿀 수 없다. | [이벤트 격리](../../tests/core/hooks/test_hook_system_lifecycle.py) |
| 모델 전환 → compaction | `ContextWindowManager`의 공통 경로를 사용한다. `PreCompact` defer와 commit 이후 `PostCompact`를 우회하지 않는다. | [모델 전환](../../tests/core/agent/test_model_switch_guard.py) |
| 취소 → 감사 | foreground 자식 취소도 `SubagentStop`을 한 번 알린다. hook/middleware 감사 실패가 원래 취소를 덮어쓰지 않는다. | [자식 연결](../../tests/core/hooks/test_public_hook_wiring.py), [middleware](../../tests/core/hooks/test_middleware.py) |
| 공유 handler → 세션 상태 | 학습 한도·cooldown·tool 횟수·입력 cursor는 세션별로 관리하고 해당 durable `SessionEnd`에서만 정리한다. 과거 turn-end 이벤트는 공유 offload 파일을 삭제하지 않는다. | [학습 수명](../../tests/core/hooks/test_auto_learn.py), [offload 수명](../../tests/core/wiring/test_tool_offload_rewire.py) |
| MCP trace → 본문 | trace는 로컬 파일을 읽거나 write 본문을 수정하지 않는다. schema 인자 alias는 본문 처리와 별개다. | [MCP 호출](../../tests/core/mcp/test_mcp_lifecycle.py) |

offload는 기존 TTL을 유지한다. recall에서 만료 파일을 거부·삭제하고 store는
명시적인 만료 파일 정리 메서드도 제공한다. 주기적인 디스크 청소나 새로운
사용자별 접근 통제를 구현한 것은 아니다.

## 공개 hook

`HookRegistry`는 아래 `HookName`만 받으며 wildcard 등록을 제공하지 않는다.
handler는 priority 순서로 실행되고 rewrite는 앞 결과를 다음 입력으로
합성한다. block/deny가 나오면 chain을 멈춘다.

| Hook | 경계 | 허용 결정 |
|---|---|---|
| `UserPromptSubmit` | user input admission 전 | continue, rewrite, block |
| `PreToolUse` | 요청 변형·admission 검사 후, 최종 policy/approval 전 | continue, rewrite, block, request_permission |
| `PermissionRequest` | headless 실행을 포함한 권한 결정; 사람에게 묻기는 fallback | allow, deny, ask |
| `PostToolUse` | 결과 생성 후 model context 반영 전 | continue, add_context, block |
| `PreCompact` | runtime-owned compaction 직전 | continue, rewrite, defer |
| `PostCompact` | compacted state commit 후 | continue |
| `SessionStart` | durable create/resume 성공 후 | continue |
| `SessionEnd` | durable terminal state 성공 후 | continue |
| `SubagentStart` | child identity·격리 확정 후 | continue |
| `SubagentStop` | terminal child result 확정 후 | continue |
| `PreVerify` | built-in verifier 전 | continue, strengthen |
| `PostVerify` | immutable verifier 결과 후 | accept, revise, escalate |
| `Stop` | 최종 전달 직전 | finalize, continue |

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

`None` 반환은 결정 없음이다. handler 감사 상태는 `ok`이지만 귀속된 결정을
추가하지 않고 domain owner의 기본 처리를 유지한다. 묵시적인 `continue`나
권한 허용이 아니다. 취소는 `error` 상태와 예외 타입명만 reason으로 감사한 뒤
원래 취소를 다시 전파한다. 감사 메타데이터는 제어 결정을 대신하지 않는다.

### Verification과 외부 loop

`GEODE_VERIFY_MODE=reflexion`을 설정하면 LLM이 원래 요청, 길이를 제한한
최근 tool 관측, 후보 응답을 함께 검토한다. `observation`, `lesson`,
`next_check` 피드백은 기존 verification continuation과 checkpoint에
기록한다. 별도 memory store는 만들지 않는다. 판단이 누락되거나 형식이
잘못됐거나 timeout되면 두 LLM 모드 모두 pass가 아닌 escalate로 처리한다.
빈 실행과 운영자 조치 필요 상태는 계속 검사한다. 응답 길이, 키워드 일치,
이미 복구한 tool 오류는 의미 판정을 막지 않는다. Reflexion은 에이전트가 이미
관찰한 이미지도 제한된 범위에서 다시 볼 수 있지만, 새 파일을 읽지는 않는다.
텍스트는 최근 tool 관측 12개를 사용한다. 이미지는 같은 verification chain에서
이미지를 반환한 최근 호출 12개를 별도로 선택한다. 호출당 서로 다른 이미지 두 장,
이미지당 7 MiB, 합계 14 MiB 이내의 인코딩된 데이터만 전달한다. 프롬프트에는
이전 시도와 현재 시도의 관측, 생략한 근거를 구분해 표시한다. 이전에 읽은 자료를
수정 후 새로 실행한 검사로 취급하지 않는다.
관측 근거를 먼저 제시하고 후보의 주장은 마지막에 보여준다. judge에는 성공 예시
대신 중립적인 출력 형식을 주고, 원본과의 일치와 동일한 값을 쓰고 읽은 일관성을
구별하도록 요청한다. 중요한 모호함이 남으면 기존 수정 경로에서 이를 판별할 수
있는 검사를 제안한다. 특정 tool 사용을 강제하거나 judge를 추가하지 않는다.

기존 정책에 따라 verification revision은 최대 두 번이다. judge는 설정된
judge model(없으면 loop model)을 쓰고, 기존 usage 경로에 사용량을 기록한다.
tool은 호출하지 않으며 남은 loop budget 안에서 최대 120초를 사용한다.
수정 단계도 최초 실행의 시계를 공유한다. 시간 제한이 있는 Reflexion은 모델 호출
사이에 남은 시간을 확인하고, 마지막 3분의 1(최대 300초)에 첫 후보를 요청한다.
진행 중인 호출이 이 시점을 넘길 수 있으므로 수정 시간 확보를 보장하지는 않는다.
수정 단계에서는 기존의 최종 종료 구간 전까지 tool을 쓸 수 있다. 세션 예산은
isolated worker에도 전달되며, 전체 종료 시점은 부모 실행의 취소가 통제한다.
agent 정의에서 모델을 생략하면 부모의 기본 모델을 상속한다. task나 agent에
명시한 모델은 그대로 우선한다. 기본값은 기계적 검사만
수행하는 `rule_based`이다. Reflexion은 모델 호출을 추가하며, 검토 결과가 항상
옳다는 보장은 없다.

이 기능은 한 태스크 안에서 피드백으로 수정을 유도하는 Reflexion-inspired
구현이다. 태스크 간 학습이나 weight update는 아니다. 간결한 피드백은
`turn_verify.reason`에 남고, 수정 hint는 다음 continuation에서 한 번만 읽는다.
벤치 점수는 여전히 Harbor의 외부 verifier가 판정한다. 신규 측정은 실행 전에
이 모드를 동결해야 하며, 숨겨진 정답이나 test 내용을 제공하지 않는다.
완료된 Codex 호출은 기존 LLM-call event의 `request_image_receipt`에 요청으로
직렬화한 이미지 수, 인코딩 바이트 수, 이미지와 호출의 digest를 제한된 크기로 남긴다.
이미지 본문과 URL은 이 receipt에 저장하지 않는다. 완료 응답이 없는 호출처럼
receipt가 없으면 0이 아닌 미관측으로 남긴다. completeness는 메타데이터의 범위이지
모델이 이미지를 이해했거나 태스크에 성공했다는 뜻이 아니다.

참고: [Reflexion: Language Agents with Verbal Reinforcement Learning](https://arxiv.org/abs/2303.11366).

finalization은 하나의 state machine이다.

```text
candidate -> PreVerify -> built-in verifier -> PostVerify -> Stop -> persist/deliver
                                                |             |
                                                +-- revise ---+
```

`PreVerify`는 검증 요구를 추가만 할 수 있다. `strengthen`에는 비어 있지 않은
`additional_misses`가 필요하다. instruction만 있는 결정은 검증 강화로
수용하지 않고 `handler_errors`에 남긴다. 잘못된 결정은 기존의 오류 기록 후
계속 진행 정책을 따르며, 그 자체로 finalization을 차단하지 않는다.
`PostVerify`는 immutable한
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
원래 요청 policy 검사
  -> tool_request transform
  -> policy 재검사 + schema validation
  -> PreToolUse
  -> policy 재검사 + schema revalidation
  -> PermissionRequest / approval (필요할 때)
  -> tool_execution onion
  -> TOOL_EXEC_STARTED
  -> terminal executor 1회 호출
  -> TOOL_EXEC_ENDED
  -> PostToolUse
```

execution middleware는 이미 승인된 tool name/arguments를 바꿀 수 없다.
personal-data 분류는 request rewrite를 가로질러 단조적으로 유지되므로
rename으로 consent나 retention policy를 낮출 수 없다. short-circuit는
`TOOL_EXEC_STARTED`를 발화하지 않는다. `PostToolUse.executed`는 terminal
dispatch에 진입했다는 뜻이지 side effect 성공을 뜻하지 않는다. `has_error`와
결과를 별도로 읽어야 하며, post-hook은 이미 완료된 효과를 되돌릴 수 없다.
위 순서는 새 실행이 결과를 반환하는 경로다. 오류 결과는 호환용
`TOOL_EXEC_FAILED`도 알리지만 이중 저장하지 않는다. admission 거부, 완료
receipt 재생, 전파되는 예외·취소에는 `PostToolUse`를 실행하지 않는다.

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
보조 호출은 request middleware 진입 전에 누락된 `llm_call_id`와
`llm_attempt_id`를 부여한다. extension 감사와 실제 호출 이벤트가 같은
식별자를 사용하며, 호출자가 이미 지정한 식별자는 유지한다.

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
소비자가 없던 context-action feedback handler는 제거했다. 과거 이벤트 값은
읽을 수 있지만 활성 제어 subscriber로 사용하지 않는다.

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

## 참고 범위

- [Codex hooks](https://learn.chatgpt.com/docs/hooks): 공개 checkpoint 이름과
  정상 무출력 handler를 참고한다. 동시성이나 보안 경계의 동등성을 뜻하지 않는다.
- [Dioxus agent guide](https://github.com/DioxusLabs/dioxus/blob/ada3b67c73c1c5484dd2e8408cb21c470b200423/AGENTS.md):
  계약 복제 없이 작업에서 소유 문서로 안내한다.
- [Furiosa kernel-authoring skill](https://github.com/furiosa-ai/furiosa-opt/blob/9b9cf0fdc78df00cdc430eae725a5ad9084a735e/skills/furiosa-opt-kernel-authoring/SKILL.md):
  짧은 실행 지침에서 단일 상세 계약으로 연결하고 검증의 의미를 구분한다.
