# Hook taxonomy fold — 27 family → 13, 계약을 family 단위로

작성 2026-07-30. 대상 브랜치 `feature/hook-taxonomy-fold`, base `develop`(d0eb411ed).
근거는 전부 이 저장소와 `~/workspace/{hermes-agent,openclaw,codex}`의 `origin/main` 원문 실측이다.

## 0. 문제

`HookEvent` 56종을 `action`의 첫 세그먼트로 묶으면 **family가 27개이고 그중 16개가 원소 하나뿐**이다.
이름공간의 절반 이상이 분류로 기능하지 않는다. 참조 축과 비교하면 밀도 차이가 드러난다.

| | 이벤트/hook | family | 밀도 |
|---|---:|---:|---|
| Hermes (`hermes_cli/plugins.py` `VALID_HOOKS`) | **23** | 6 문서 계열 | 3.8 |
| Codex (`metrics/names.rs` + `events/session_telemetry.rs`) | **50 metric + 14 event** | ~12 도메인 | 5.3 |
| **GEODE 현재** | 56 | **27** | **2.1** |
| GEODE 목표 | 56 | 13 | 4.3 |

## 1. GAP Audit

| # | 항목 | 이미 있는가 | 판정 |
|---|---|---|---|
| 1 | family alias 맵 | 없음 (`grep FAMILY\|_ACTION_ALIAS` 0건) | **구현** |
| 2 | payload 필수키 계약 | `REQUIRED_PAYLOAD_KEYS` **4/56 (7%)** | **확대** |
| 3 | payload 스키마 버전 | 상수 없음. `schema_version`은 `hook_events` 컬럼에만 | **구현** |
| 4 | `mirror_transcript` 기본값 | 있음 — `EventPersistenceSpec()` 기본 `True`, 52/56 적용 | **기각** (§2.4) |
| 5 | 구독자 0 게이팅 | 있음 — `_validate_payload`가 계약 없으면 즉시 반환(52/56) | **보류** (§2.5) |

가지치기 대상은 없다. 정적 분석에서 56종 전부에 프로덕션 발화지가 있고(참조 0회 0종),
실데이터 `hook_events` 2,179행에서 **generic 폴백 0%, `entity_id` 빈 값 0%**다. 죽은 이벤트도
깨진 타입 매핑도 존재하지 않는다.

> 조사 중 `map_hook_to_activity`에 빈 payload를 넣어 `fix the emit-site key` 경고가 다수 나왔으나
> **그것은 프로브 산물이지 결함이 아니다.** 같은 오염으로 첫 family 분류에서 `approval_transition`이
> `approval`로 잡혔고, 정적 spec에서는 `tool.approval.transition`이다. 아래 분류는 정적 spec 기준이다.

## 2. Socratic Gate

### 2.1 family 접기 — 채택

- **Q1 이미 있나** — 없다.
- **Q2 안 하면** — 16개 싱글턴 family가 남아 `action` 접두사 필터가 대부분의 이벤트에서 무의미하다.
  3번 계약 확대 비용이 56종 개별 정의로 고정된다.
- **Q3 어떻게 재나** — 접기 후 family 수와 싱글턴 수. 목표 13/0.
- **Q4 최소 구현** — 이벤트를 추가·삭제하지 않는다. `action` 문자열의 첫 세그먼트만 바꾸고
  옛 값은 alias로 읽는다. 07-15의 v1→v2 전환(`LEGACY_EVENT_VALUES`)이 선례다.
- **Q5 frontier 3곳** — Hermes 6 family, Codex ~12 도메인, OpenClaw span 계층 3단. 모두 계층을 쓴다.

### 2.2 payload 계약 family 단위 확대 — 채택

- **Q1** — 부분. 4/56.
- **Q2** — 계약 없는 52종은 emit-site가 키를 빠뜨려도 조용히 통과한다. 검증 장치는 있는데
  검증할 규칙이 없다.
- **Q3** — 계약이 덮는 이벤트 비율. 7% → family 13개 정의로 전 이벤트.
- **Q4** — **family 단위로 정의한다.** 56개를 하나씩 적으면 유지되지 않는다. 접기가 이 항목을
  싸게 만드는 것이 두 항목을 이 순서로 두는 이유다.
- **Q5** — Hermes는 hook마다 kwargs 계약을 인라인 주석으로 명시하고, Codex는 `metrics/tags.rs` +
  `validation.rs`로 태그 스키마를 분리 검증한다.

### 2.3 `telemetry_schema_version` payload 주입 — 채택

- **Q1** — 없다.
- **Q2** — payload만 받는 소비자(플러그인·export)가 자기가 읽는 계약 버전을 모른다. 컬럼의
  `schema_version`은 SQL 소비자만 본다.
- **Q3** — 발화된 payload에 키가 있는지.
- **Q4** — 발화 직전 `setdefault` 한 줄. Hermes `plugins.py:1931`과 같은 위치·같은 방식.
- **Q5** — Hermes가 `hermes.observer.v1`로 한다. Codex는 OTel semconv가 대신한다.

### 2.4 `mirror_transcript` 기본값 뒤집기 — **기각**

- **Q2에 답할 수 없다.** 56종 중 52종이 `mirror_transcript=True`지만, transcript 전수
  **1,009,468행 중 HookEvent 이름과 일치하는 행은 12행(0.0012%)**이다. 이중 기록은 정책상 켜져
  있을 뿐 실제로 아무것도 쓰고 있지 않다.
- 지금 뒤집으면 측정된 비용 없이 동작만 바꾼다. Socratic Q2가 "답 없으면 제거"이므로 제거한다.
- 다시 열 조건: hook 영속화가 실제로 활성화되어 transcript 행이 유의미하게 늘 때.

### 2.5 구독자 0 게이팅 — **보류**

- **전제가 틀렸다.** `_validate_payload`는 `REQUIRED_PAYLOAD_KEYS.get(event)`가 비면 즉시 반환한다
  (`core/hooks/dispatch.py:65-67`). 현재 52/56이 그 경로라 비용이 사실상 없다.
- 다만 **2번이 이 비용을 만든다.** 전 이벤트에 계약이 생기면 조기 반환이 사라진다.
- 2번 착지 후 dispatch 지연을 재고 판단한다. Hermes의 `has_hook()`은 그대로 옮겨지지 않는데,
  `HookPersistenceSink`가 항상 등록돼(`core/wiring/bootstrap.py:158`) 구독자 수가 0이 되지 않기
  때문이다. 게이팅 대상은 구독자가 아니라 비싼 payload 구성이어야 한다.

## 3. 접기 설계

| family | 수 | 접어 넣는 싱글턴 |
|---|---:|---|
| `tool` | 10 | — |
| `llm` | 8 | `adapter_dispatch_attempt` · `prompt_assembled` · `model_switched` · `reasoning_metrics` |
| `turn` | 7 | `user_input_received` · `execution_cancelled` · `result_feedback` · `post_analysis` |
| `cognitive` | 6 | — |
| `mutation` | 4 | — |
| `session` | 4 | `shutdown_started` · `handoff_triggered` |
| `subagent` | 3 | — |
| `policy` (신설) | 3 | `rule_changed` · `config_reloaded` · `program_md_unreadable` |
| `improve` (신설) | 3 | `trigger_fired` · `self_improving_auto_trigger` · `baseline_promoted` |
| `context` · `cost` · `mcp` · `memory` | 각 2 | — |

**27 → 13, 싱글턴 16 → 0.** 이벤트 수는 56 그대로다.

### 버린 대안

`HookEvent` 이름 자체를 `tool_exec_started` → `tool.exec.started`로 바꾸는 안을 먼저 검토했다.
enum 값이 곧 family가 되어 alias 맵이 필요 없어지는 점이 매력적이었으나, `hook_events` 2,179행과
`LEGACY_EVENT_VALUES` 8쌍이 이미 enum 값에 결속돼 있어 3세대 alias가 쌓인다. `action`만 바꾸면
enum은 불변이고 alias는 한 층으로 끝난다.

## 4. 검증

| 단계 | 방법 | 기준 |
|---|---|---|
| 접기 | family 계산 스크립트 재실행 | family 13, 싱글턴 0, 이벤트 56 |
| alias | 옛 `action` 값 → 새 family 해소 | `hook_events` 2,179행 전부 해소 |
| 계약 | `REQUIRED_PAYLOAD_KEYS` 커버리지 | 56/56 |
| 버전 | 발화 payload 키 검사 | `telemetry_schema_version` 존재 |
| 회귀 | `scripts/preflight.sh` 전체 | all gates passed |
| 교차 | Codex MCP DEDUP/SLOP/GAP | 확정 결함 0 |

## 5. 하지 않는 것

- 이벤트 추가·삭제 (전 56종이 라이브)
- `HookEvent` enum 값 변경 (§3 버린 대안)
- `mirror_transcript` 기본값 변경 (§2.4)
- 구독자 0 게이팅 (§2.5, 2번 이후 재평가)

## 6. Codex 감사 반영 (2026-07-30)

`codex exec`(gpt-5.6-sol) DEDUP/SLOP/GAP 감사가 PASS 4 / FAIL 7을 냈고, 기계로 확인되는 것을
전부 재측정한 뒤 반영했다.

| 지적 | 재확인 | 조치 |
|---|---|---|
| **`action_family()` 프로덕션 사용처 0** | 사실. grep 결과 catalog 밖 호출 0건 | `HookEventStore.read(family_filter=...)` 배선. 실데이터 전 행에서 family별 건수 일치 확인 |
| Hermes "~15 hook / 6 family" | 사실. `VALID_HOOKS`는 **23개**. 6은 문서의 계열 수 | 코드 기준 23으로 교정하고 출처를 구분해 표기 |
| Codex "~66 신호" | 근사. metric 상수 **51** + event 이름 **14** | 두 수를 분리해 표기 |
| `hook_events` 2,179행 | 라이브 DB라 계속 증가 (감사 시 2,109, 재측정 시 2,199) | 고정 수치를 빼고 "전 행" 표현으로 교체 |
| 완화 8곳 중 3곳 불필요 | 사실. 해당 경로엔 `schema_version`이 주입되지 않는다 | 정확 단언으로 복원. 복원 후에도 실패 0건 |
| 계획 56/56 대 구현 18/56 | 사실. §2.2가 "전 이벤트"로 읽혔다 | 아래로 정정 |

**계약 커버리지를 56/56으로 적은 것은 과장이었다.** 실제로는 수기 4종과 pydantic 14종의 합집합인
**18/56**이다. family 단위 공통 필수키를 실데이터로 찾아보면 `mcp`의 `server_name`과 `cognitive`의
5개를 빼면 100% 등장하는 키가 없어, family 계약은 성립하지 않는다. 나머지 38종의 계약은 새로
작성해야 하며 이 PR의 범위 밖이다.

---

## 7. 2026-07-31 후속 계획 — Hermes-shaped hook planes

### 7.1 문서 범위

§0~§6은 PR #2832의 taxonomy fold 결정 기록이다. 아래 §7 이후는 그 다음 리팩토링의 실행 계획이다.
두 작업은 분리한다.

- PR #2832: 56개 runtime signal의 저장 문자열을 유지한 채 action family와 payload 계약을 정리한다.
- 후속 리팩토링: 공개 hook, trusted middleware, 내부 runtime event, stateful domain service를 분리한다.

§2의 Socratic/minimum-implementation gate는 원래 PR의 역사로만 남긴다. 사용자 지시에 따라 이번
후속 리팩토링의 범위나 구조를 축소하는 근거로 사용하지 않는다.

### 7.2 최신 reference snapshot

2026-07-31에 세 저장소를 fast-forward한 뒤 다음 commit을 기준으로 다시 읽었다.

| runtime | `origin/main` | 실측 표면 |
|---|---|---|
| Hermes Agent | `36e41c09ed02bd783c1186564bf08cca5c8e821d` | public plugin hook 23, middleware point 4 |
| OpenClaw | `90a22b4f50226b13735e77dde81a92340ae724cf` | `PluginHookName` 44 (deprecated 2 포함) |
| Codex | `578c1b2230288104041e880a86d0f7f3a5ca6e47` | command hook 11 + 별도 typed extension contributor plane |

#### Hermes

Hermes의 정체성은 hook 개수가 아니라 다음 구조에 있다.

1. CLI, gateway, TUI, desktop이 같은 conversation loop를 공유한다.
2. system prompt와 과거 context는 conversation 동안 byte-stable하게 유지하고, compaction만 예외로
   둔다.
3. core를 narrow waist로 두고 기능을 plugin, skill, provider, domain service로 확장한다.
4. 논리적 lifecycle hook과 물리적 request/execution middleware를 구별한다.

현재 Hermes 표면은 다음과 같다.

| 역할 | Hermes 구현 | GEODE가 취할 것 |
|---|---|---|
| plugin lifecycle | `VALID_HOOKS` 23개 | 전부 복제하지 않고 안정적인 공개 hook만 선별 |
| request transform | `tool_request`, `llm_request`가 실제 tool/LLM 경로에 배선됨 | true-sequential typed transform |
| execution wrapping | `tool_execution`, `llm_execution`이 실제 executor/provider를 감쌈 | async `next_call`, exactly-once |
| compaction | `ContextEngine` | stateful service가 소유하고 공개 hook은 경계를 감쌈 |
| subagent control | `SubagentLifecycleService` | live object 대신 immutable contract |
| approval | 단일 approval subsystem | hard deny 아래에서 permission decision을 합성 |
| verify/stop | evidence 기반 verify-on-stop + public `pre_verify` | verifier 결과와 외부 결정을 분리 |
| observability | content-free monitoring queue → optional OTLP, 로컬 저장 없음 | 내부 RuntimeEvent와 exporter를 분리 |

Hermes에서 그대로 복사하지 않을 것도 확인됐다.

- `on_session_end` plugin hook은 실제로 매 `run_conversation()` 종료에 발화하지만
  `ContextEngine.on_session_end`는 durable session 종료를 뜻한다. GEODE에서는 turn/session을 처음부터
  분리한다.
- hook allowlist 안에 observer, transformer, decision hook이 혼재한다. GEODE는 반환 계약과 권한을
  hook별로 고정한다.
- request middleware는 현재 모든 callback에 같은 입력 snapshot을 전달한 뒤 결과를 적용한다.
  GEODE에서는 앞 transform의 출력이 다음 transform의 입력이 되는 true-sequential 합성을 보장한다.
- unknown hook/middleware 이름을 경고만 하고 저장하는 forward-compat 동작은 typo와 비인가 표면을
  숨긴다. GEODE public registry는 알 수 없는 이름을 거부한다.
- 최신 소스에서 `register_middleware(...)`의 비테스트 plugin 소비자는 0개다. 네 join point의 실행
  구조는 채택하되 Hermes의 사용 실적을 과장하지 않는다.
- execution middleware의 `next_call`은 single-use이고 downstream exception identity를 복원하지만
  동기 함수다. GEODE provider/tool 경로는 async이므로 awaitable chain을 정본으로 둔다.
- `pre_verify`는 code edit 후 종료하려는 시점에 bounded synthetic follow-up을 주는 stop gate다.
  built-in verify-on-stop은 변경 경로와 verification evidence를 먼저 검사한다. 즉 Hermes도 verification
  policy와 plugin continuation을 분리했지만, verifier 결과를 외부에 내보내는 `PostVerify` 계약은 없다.
- `on_session_finalize`와 `on_session_reset`이 추가됐어도 `on_session_end`는 여전히 매
  `run_conversation()` 종료에 발화한다. 이름보다 실제 발화 지점으로 durable lifecycle을 판정한다.

#### Codex와 OpenClaw

Codex의 공개 command hook은 요청한 기본 목록과 정확히 일치하는 11개다.

```text
PreToolUse, PermissionRequest, PostToolUse,
PreCompact, PostCompact,
SessionStart, SessionEnd, UserPromptSubmit,
SubagentStart, SubagentStop, Stop
```

Codex는 이 공개 표면과 별개로 in-process extension API를 둔다. immutable registry에
`ThreadLifecycleContributor`, `TurnLifecycleContributor`, `ToolLifecycleContributor`, context/tool/input
contributor를 등록하고, public hook처럼 raw JSON을 범용 노출하지 않는다. 특히 tool lifecycle은
input/output 변경 권한 없이 `Completed/Blocked/Failed/Aborted`를 관측한다. GEODE의 exposure level은
이처럼 안정 ABI와 trusted typed seam을 별도 plane으로 둔다.

Codex `Stop`은 finalization을 block하고 continuation prompt를 돌려 같은 turn을 이어갈 수 있다.
handler exit code 2의 stderr도 같은 continuation으로 해석하며 여러 handler의 block을 합성한다.
Codex에는 `PreVerify`/`PostVerify`가 없으므로 verification 결과 자체는 공개하지 않는다.

OpenClaw는 44개 plugin hook을 한 이름공간에 두지만 runner 안에서는 modifying, claiming, void hook을
구분하고 priority, timeout, failure policy를 따로 적용한다. 이 중 `before_agent_finalize`는
`continue/revise/finalize`와 retry `instruction/idempotencyKey/maxAttempts`를 반환한다. 여러 revise는
합치되 finalize가 우선하고, run+instruction별 retry budget을 적용하며, 잠재적 side effect 뒤에는
rewind revision을 거부한다. 이는 `PostVerify` 외부 루프에 필요한 bounded retry와 idempotency의
직접 선례다.

OpenClaw의 `session_end` reason은 `new/reset/idle/daily/compaction/deleted/shutdown/restart/unknown`으로
durable transition을 구분하고, compaction hook은 30초 fail-open timeout을 둔다. 반면 44개 전체를
GEODE 공개 ABI로 복제하지 않는다. 제품·gateway·channel lifecycle은 domain event나 bundled extension
표면에 남긴다.

## 8. 목표 구조

### 8.1 네 평면

| 평면 | 책임 | 데이터 노출 | 제어 가능 |
|---|---|---|---|
| `PublicHook` | 사용자·plugin용 안정 ABI | redacted, JSON-safe | hook 계약별로 제한 |
| `MiddlewarePipeline` | 실제 요청 변형·실행 wrapping | trusted raw/effective request | 예 |
| `RuntimeEvent` | 운영, audit, persistence, trajectory | 내부 상세 payload | 아니오 |
| domain service | compaction, approval, subagent 등 상태ful 기능 | 전용 typed contract | 서비스가 소유 |

현재 `HookSystem` 하나가 `trigger`, `trigger_with_result`, `trigger_interceptor`를 모두 제공하는 구조는
호환 facade로만 남기고 책임을 다음과 같이 이동한다.

- `RuntimeEventBus`: observe + sink만 제공한다.
- `PublicHookRegistry`: hook별 typed input/output을 제공한다.
- `MiddlewarePipeline`: request transform과 execution chain을 제공한다.
- `ExtensionRuntime`: 위 세 컴포넌트를 wiring하는 composition root다.

### 8.2 공개 hook 13개

| Public hook | 시점 | 허용 반환 |
|---|---|---|
| `UserPromptSubmit` | user input admission 전 | rewrite / block |
| `PreToolUse` | `tool_request` transform 후, policy/approval 전 | rewrite / block / request permission |
| `PermissionRequest` | 실제 human permission prompt 직전 | allow / deny / ask |
| `PostToolUse` | tool 결과 생성 후 model context 반영 전 | observe / redacted context 추가 / bounded block |
| `PreCompact` | runtime-owned compaction 직전 | context·focus 보강 / soft defer |
| `PostCompact` | durable compaction commit 후 | observe |
| `SessionStart` | durable session 생성·resume 확정 후 | observe |
| `SessionEnd` | reset, expiry, explicit close, process shutdown | observe |
| `SubagentStart` | child identity와 격리 context 확정 후 | observe |
| `SubagentStop` | terminal child result 확정 후 | observe |
| `PreVerify` | final candidate 생성 후 verifier 실행 전 | verification requirement 추가 |
| `PostVerify` | built-in verifier 결과 후, stop 결정 전 | accept / revise / escalate |
| `Stop` | verify policy를 통과한 최종 종료 직전 | finalize / bounded continue |

Hermes의 `pre_llm_call` / `post_llm_call`은 이 단계에서 공개 hook으로 추가하지 않는다.
공개 context injection은 `UserPromptSubmit`, raw request 변경은 trusted `llm_request`, 관측은
`RuntimeEvent`가 담당한다. 셋으로 해결되지 않는 구체적인 외부 소비자가 생길 때 공개 model
lifecycle hook을 별도 GAP으로 등록한다.

13개는 서로 독립된 13개 dispatcher를 뜻하지 않는다. `PreVerify` → verifier → `PostVerify` → `Stop`은
하나의 internal finalization state machine에 있는 세 public checkpoint다. `PostVerify`는 검증 결과
해석, `Stop`은 최종 전달 직전 continuation만 소유해 권한이 겹치지 않는다.

### 8.3 RuntimeEvent

현재 `HookEvent` 56종은 내부 `RuntimeEvent`로 이동한다. 저장된 enum value와 SQLite row는 바꾸지
않는다.

- `HookEvent = RuntimeEvent` 호환 alias를 한 migration window 유지한다.
- `LLM_CALL_STARTED/ENDED`, `TOOL_EXEC_STARTED/ENDED`, approval transition, cognitive, cost, mutation,
  persistence signal은 공개 hook allowlist에 들어가지 않는다.
- `TOOL_EXEC_STARTED`는 permission이 끝나고 실제 executor를 호출하기 직전에만 발화한다.
- `TurnStarted` / `TurnCompleted`를 내부 경계로 사용하고 public `SessionStart/End`와 혼용하지 않는다.
- public hook dispatch 결과도 별도 RuntimeEvent로 기록해 어느 extension이 결과를 바꿨는지 추적한다.

### 8.4 Middleware 명명과 계약

`MiddlewareKind`는 사용하지 않는다. 네 값은 종류가 아니라 실행 그래프의 join point이므로 내부
registry key가 필요할 때만 `MiddlewarePoint`라고 부른다. 외부 등록 API는 역할 타입을 직접 받는다.

```python
register_tool_request(transform: ToolRequestTransform)
register_tool_execution(middleware: ToolExecutionMiddleware)
register_llm_request(transform: LlmRequestTransform)
register_llm_execution(middleware: LlmExecutionMiddleware)
```

계약:

- request transform은 immutable input을 받고 새 request/args를 반환한다.
- transform N의 출력이 N+1의 입력이다.
- original과 effective payload, extension name, reason을 `MiddlewareTrace`에 남긴다.
- execution middleware는 async `next_call(effective_payload)`을 정확히 한 번 호출할 수 있다.
- `next_call`을 호출하지 않으면 명시적인 short-circuit result를 반환해야 한다.
- downstream exception은 원형을 보존한다.
- execution middleware는 policy/approval을 감싸지 않고 승인된 실제 executor/provider 호출만 감싼다.
- middleware 자체의 timeout/error 정책은 registration capability에 고정하고 RuntimeEvent로 남긴다.
- public hook에는 raw provider request, secret, base64, unrestricted tool output을 노출하지 않는다.

## 9. `PostVerify` 외부 루프 계약

### 9.1 위치

```text
final candidate
→ PreVerify
→ built-in verifier
→ PostVerify
→ accept / revise / escalate
→ Stop
→ final persistence and delivery
```

현재처럼 finalizer가 결과를 준비한 뒤 verify telemetry를 붙이는 순서로는 외부 loop가 검증 결과를
받아 같은 turn을 계속할 수 없다. verify를 final persistence 앞으로 이동하고 `PostVerifyDecision`을
실제 loop 재진입에 연결한다.

### 9.2 이점

- 외부 orchestration loop가 동일한 `VerifyResult`를 읽고 retry, replan, escalation, handoff를 결정한다.
- 프로젝트별 품질·보안·CI 정책을 core verifier에 넣지 않고 합성한다.
- 외부 verifier, CI, human review가 만든 evidence reference를 동일한 종료 경계에 첨부한다.
- Petri, benchmark, self-improving loop가 별도 종료 판정기를 만들지 않고 같은 계약을 사용한다.
- local verifier 결과와 external policy decision을 따로 보존해 사후 진단과 학습 trajectory가 정직해진다.

### 9.3 반환 계약

```python
class PostVerifyAction(StrEnum):
    ACCEPT = "accept"
    REVISE = "revise"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class PostVerifyDecision:
    action: PostVerifyAction
    reason: str = ""
    instruction: str = ""
    additional_misses: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
```

합성 규칙은 단조적이어야 한다.

- built-in pass는 `REVISE` 또는 `ESCALATE`로 강화할 수 있다.
- 일반 public hook은 built-in fail을 pass로 뒤집을 수 없다.
- 기존 `rubric_misses`를 삭제할 수 없고 `additional_misses`만 추가한다.
- `ACCEPT`는 built-in result가 pass일 때만 유효하다.
- hook error/timeout은 원래 `VerifyResult`를 유지하고 실패 RuntimeEvent를 남긴다.
- `REVISE`는 기존 turn continuation budget과 `(run_id, idempotency_key)` attempt budget을 함께 사용해
  무한 verify loop를 막는다.
- revision은 새 follow-up을 append하며 이미 성공한 side effect를 rewind/replay하지 않는다. 구현이
  replay 없는 continuation을 보장할 수 없으면 `REVISE`를 `ESCALATE`로 낮춘다.
- 후보 원문과 raw tool output은 기본 payload에서 제외한다. 필요한 extension만 manifest capability로
  별도 허용한다.

외부 전달 envelope는 최소한 다음 correlation을 갖는다.

```text
schema_version
session_id / turn_id / run_id
verify_attempt
VerifyResult
termination_reason
changed_paths
tool_call_count
evidence_refs
candidate_summary
```

in-process plugin과 외부 host bridge가 같은 JSON-safe envelope를 사용한다. 별도 webhook/network
transport는 이 리팩토링에서 만들지 않는다. 기존 plugin/IPC 경계가 envelope를 전달할 수 있게만 한다.

## 10. canonical 실행 순서

### 10.1 Tool

```text
model tool call
→ tool_request transforms
→ schema validation
→ PreToolUse
→ modified-args revalidation
→ hard deny / scope / safety policy
→ PermissionRequest when needed
→ RuntimeEvent.TOOL_EXEC_STARTED
→ tool_execution middleware onion
→ next_call(final args): exactly-once executor dispatch
→ middleware unwind
→ RuntimeEvent.TOOL_EXEC_ENDED
→ PostToolUse
```

요구 불변식:

- parallel, sequential, recovered, deferred-tool, MCP, subagent tool path가 모두 같은 terminal을 통과한다.
- approval은 middleware가 바꾼 최종 args를 대상으로 한다.
- hard deny는 `PermissionRequest(ALLOW)`로 우회할 수 없다.
- blocked/cancelled/error도 start 없는 terminal outcome으로 관측 가능하지만, 실제 실행하지 않은 호출에
  `TOOL_EXEC_STARTED`를 발화하지 않는다.

### 10.2 LLM

```text
prompt/context assembly
→ immutable AdapterCallRequest
→ llm_request transforms
→ RuntimeEvent.LLM_REQUEST_PREPARED
→ llm_execution middleware onion
→ RuntimeEvent.LLM_CALL_STARTED
→ adapter.acomplete / provider execution
→ RuntimeEvent.LLM_CALL_ENDED or ERROR
→ middleware unwind
→ normalized AgenticResponse
```

`llm_request`는 system prompt cache invariant를 깨는 변경을 검사한다. 과거 message prefix, toolset,
system prompt를 mid-session에 바꾸는 middleware는 명시적인 capability와 cache-invalidation trace 없이는
거부한다.

### 10.3 Compaction

- runtime-owned overflow, model-switch, aggressive recovery, manual compact를 공통 service entrypoint로 모은다.
- runtime-owned 경로는 `PreCompact`와 `PostCompact`의 정확한 pair를 보장한다.
- hard context ceiling에서는 public hook이 compaction을 영구 차단할 수 없다.
- provider-native compaction이 사전 경계를 제공하지 않으면 가짜 `PreCompact`를 만들지 않는다.
  관측된 완료는 internal provider-compaction RuntimeEvent로 기록한다.
- durable commit이 실패한 경우 `PostCompact(success=True)`를 발화하지 않는다.

### 10.4 Session과 turn

- `SessionStart/End`: durable lifetime.
- `TurnStarted/Completed`: 각 `arun()` / user message.
- 현재 `SESSION_ENDED`를 소비하는 metrics/persistence handler를 먼저 `TurnCompleted`로 이동한 후 public
  Session 의미를 교정한다.
- reset은 `SessionEnd(reason="reset")` 후 새 `SessionStart`다.
- process shutdown, gateway expiry, explicit close도 reason을 구분한다.

### 10.5 Telemetry와 lifecycle 저장 경계

2026-07-31 read-only audit 결과, 저장 책임의 코드 경계는 부분적으로 성숙했지만 lifecycle 의미와
공개 표면의 경계는 아직 분리되지 않았다.

잘 된 부분:

- `HookSystem`은 저장소를 모르고, `core.observability.HookPersistenceSink`가 dispatch를 typed activity로
  투영해 SQLite와 활성 `RunTranscript`에 보낸다.
- 기본 bootstrap과 subprocess worker가 같은 bounded SQLite sink를 사용한다.
- 현재 56종 중 compatibility signal 4종은 canonical event와 이중 계수하지 않도록 SQLite와
  transcript 양쪽에서 제외하고, 나머지 52종은 retention class에 따라 저장한다.
- SQLite payload는 secret redaction, 금지 키 제거, 깊이·길이·크기 제한을 거친다. 보존 기간은
  high-volume 7일, standard 30일, audit 180일이고 project DB당 최대 100,000행이다.
- Hermes도 monitoring emitter를 hook/plugin lifecycle과 분리했다. 단 Hermes monitoring은 bounded
  in-memory queue에서 optional OTLP subscriber로만 나가며 로컬에 영속화하지 않는다. GEODE는
  self-hosted replay/audit 요구가 있으므로 이를 그대로 복제하지 않고 SQLite operational store와
  exporter를 분리한다.
- Codex 역시 command hook 실행 결과와 typed extension contributor, metrics/event sink를 서로 다른
  계약으로 둔다. 공개 hook 개수가 적다는 사실은 telemetry가 적다는 뜻이 아니라 exposure가 좁다는
  뜻이다.

분리되지 않은 부분:

- `HookEvent` 하나가 public callback, control interceptor, internal telemetry, lifecycle fact를 모두
  표현한다. package root에서 enum 전체를 공개하고 `register_prefix("*", ...)`도 허용하므로 exposure
  level이 없다.
- activity schema는 `session.started` / `session.ended`와 `turn.completed`를 다른 entity로 모델링하지만,
  `AgenticLoop.arun()` 시작과 종료가 세 이벤트를 같은 turn 경계에 발화한다.
- `SessionTranscript`는 dialogue와 lifecycle을 한 JSONL에 함께 쓴다. 따라서 이 파일은 재생 가능한
  audit stream이지 durable session 상태의 정본으로 사용할 수 없다.
- hook의 JSONL mirror는 일반 session transcript가 아니라 활성 self-improving `RunTranscript`에만
  조건부로 기록된다. 활성 run binding이 없으면 SQLite만 남는다.
- event row가 존재한다는 사실은 lifecycle pair가 닫혔다는 보장이 아니다. uniqueness, terminal-state,
  crash reconciliation을 소유하는 state machine이 별도로 없다.

실측 snapshot은 다음과 같다. 숫자는 2026-07-31 조회 시점 값이며 라이브 저장소이므로 증가할 수 있다.
본문·payload·session id는 읽지 않고 파일/행/event cardinality만 집계했다.

| 저장소 | 실측 | 현재 의미 |
|---|---:|---|
| `~/.geode/transcripts/**/*.jsonl` | 14,982 files / 1,009,588 rows / 408 MB | 일반 session dialogue + lifecycle audit |
| 위 JSONL의 주요 event | `session_start` 195,122 = `user_message` 195,122; `session_end` 193,717; `assistant_message` 193,705 | `SessionStart/End`가 durable session이 아니라 turn마다 기록된다는 증거 |
| self-improving `transcript.jsonl` | 1,782 files / 14,090 rows / 10 MB | run-level lifecycle/activity timeline |
| self-improving `sessions.jsonl` | 3 files / 6,311 rows / 2.6 MB | 일반 session store가 아니라 run-level aggregate index |
| `~/.geode/usage/*.jsonl` | 5 files / 140,490 rows / 14 MB | calendar-day usage/cost ledger |
| workspace `sessions.db` | 260 MB; sessions 8,511 / messages 48,435 / agent runtime 1,318 / hook events 2,219 | project-local query/index/state + bounded operational events |
| 현재 worktree `sessions.db` | 344 KB; sessions 4 / messages 4 / hook events 240 | 격리된 worktree runtime store |

workspace SQLite의 lifecycle 세 이벤트는 각 8행으로 동행했다. 반면 worktree DB에는
`session_started` 16행만 있고 `session_ended` / `turn_completed`는 없었다. 테스트, 중단, 진행 중인
실행을 상태 없이 event append만 한 결과를 구분할 수 없다는 뜻이다. 또한 1,782개 run transcript의
현재 corpus에서는 `geode.observer.v1` hook mirror row가 0개였다. 코드 경로는 존재하지만 실제
JSONL telemetry 근거로 간주해서는 안 된다.

후속 구조의 저장 계약:

| 사실 | 정본 | projection / export |
|---|---|---|
| durable session 상태 | SQLite `sessions` + 명시적 lifecycle transition/state | `SessionStart/End` RuntimeEvent |
| turn 상태 | `turn_id`를 가진 RuntimeEvent pair 또는 전용 turn row | session/run transcript |
| internal runtime telemetry | SQLite `hook_events` | 활성 `RunTranscript` JSONL, optional |
| public hook·middleware 결정 | 결과를 RuntimeEvent로 변환한 SQLite row | redacted operator export |
| 대화 재생·감사 | checkpoint/message store | `SessionTranscript` JSONL |
| 일별 비용·사용량 | 기존 usage ledger grain 유지 | `~/.geode/usage/*.jsonl` |

불변식:

- `SessionStart`는 durable create/resume 확정 시 session generation당 한 번, `SessionEnd`는 terminal
  transition당 한 번만 쓴다.
- user message마다 `TurnStarted`; 정상·오류·취소를 포함해 정확히 하나의 terminal turn event를 쓴다.
- SQLite lifecycle state commit이 성공한 뒤 corresponding public hook과 RuntimeEvent를 발화한다.
- JSONL write 실패나 활성 run binding 부재가 lifecycle correctness를 바꾸지 않는다.
- crash 후 열린 session/turn은 다음 bootstrap이 명시적인 `recovered` / `abandoned` transition으로
  reconcile한다.
- 일반 `SessionTranscript`에 모든 RuntimeEvent를 복제하지 않는다. full dialogue와 bounded operational
  telemetry의 보존·민감도 계약을 계속 분리한다.
- `PostVerify`와 `Stop` 결정은 `turn_id`, `verify_attempt`, `session_generation`으로 correlation하고,
  durable `SessionEnd`로 오인하지 않는다.

## 11. 구현·머지 순서

아래 H0~H7은 설계 분해이지 지금 바로 만들 수 있는 branch 목록이 아니다.
`docs/architecture/extensibility-roadmap.md`가 실행 SOT이며, GAP package의 readiness/claim 순서를
먼저 만족해야 한다. 기능 PR마다 `[Unreleased]`를 갱신한다.

### 11.1 현재 roadmap gate

2026-07-31 `origin/develop`(`d0eb411ed99d33d614ab4085e3104aa0ef42c808`)의 canonical ledger를
재확인한 결과:

- 유일한 active claim은 R1.1/BND-001이며 hook 리팩토링 claim은 없다.
- public/internal protocol 분리는 `PROTO-001`이고 `LOOP-002`, `DI-002`에 의존한다. 세 GAP 모두 현재
  `OPEN`이다.
- durable lifecycle 저장은 `STORE-001`/`STORE-002`이며 각각 `DI-002 + PROTO-001`, `STORE-001`에
  의존한다.
- discovery/trust/exposure는 `BND-004`, `TRUST-001`, `TRUST-002`가 소유한다.
- 네 middleware join point와 `PreVerify/PostVerify` finalization gate는 기존 GAP exit condition에
  명시적으로 등록되지 않았다. 구현 전에 별도 roadmap-only GAP-registration PR로 stable ID,
  measurable exit condition, dependency와 closure package를 추가해야 한다.

등록안은 한 closure package R6.4와 세 GAP으로 고정한다. canonical ledger에 merge되기 전까지 아래
ID는 계획안이지 status authority가 아니다.

| proposed GAP | outcome | dependency |
|---|---|---|
| `HOOK-001` | Codex 11 + `PreVerify/PostVerify`의 versioned public ABI, 56 internal event 비노출 | `PROTO-001`, `STORE-001`, `TRUST-002` |
| `HOOK-002` | `tool_request/tool_execution/llm_request/llm_execution` 네 typed join point와 전 경로 choke point | `CAP-002`, `LOOP-003`, `LLM-003`, `HOOK-001` |
| `HOOK-003` | 단일 finalization state machine의 PreVerify → verifier → PostVerify → Stop과 bounded external continuation | `LOOP-003`, `HOOK-001` |

따라서 이 문서를 고치는 현재 PR에서 production code를 시작하지 않는다. 실행 순서는 다음으로
고정한다.

1. PR #2832에는 taxonomy fold와 이 measured design record만 둔다.
2. current `origin/develop`에서 middleware/verify GAP-registration ledger PR을 별도로 연다.
3. 기존 선행 package가 `DONE` 또는 `IN_DEVELOP`에 도달한 뒤 해당 package 전체를 `READY`로
   reconciliation한다.
4. claim PR을 merge한 뒤에만 명시된 implementation branch/worktree를 만든다.
5. H0~H7을 claimed GAP와 1:1로 다시 매핑하고 code/test/change log를 시작한다.

이 gate는 최소 구현을 강요하는 Socratic anchor가 아니라 여러 architecture session이 같은 kernel
경계를 동시에 바꾸지 못하게 하는 ownership protocol이다.

### 11.2 구현 stage

| 순서 | 작업 | 완료 기준 |
|---:|---|---|
| H0 | 계약 고정 | public 13 hook input/output, authority, redaction, correlation schema 테스트 |
| H1 | 평면 분리 | `RuntimeEventBus`, `PublicHookRegistry`, `MiddlewarePipeline`; 기존 호출 호환 |
| H2 | tool choke point | 모든 tool path 단일 terminal, tool middleware pair, exactly-once/TOCTOU 테스트 |
| H3 | LLM choke point | immutable request transform, async execution chain, retry/error/cache 테스트 |
| H4 | lifecycle | durable Session과 Turn 분리, SQLite state transition, crash reconciliation, SubagentStart/Stop immutable payload |
| H5 | compaction | 모든 runtime-owned 경로 공통 boundary, Pre/PostCompact commit parity |
| H6 | verify/stop | PreVerify → verifier → PostVerify → Stop → persist, bounded continuation |
| H7 | exposure/trust | manifest-first, hash trust, capability gate, unknown name reject, 구 API deprecation |

H1에서 현재 `HookSystem`을 즉시 삭제하지 않는다. 기존 56-event subscriber와 persistence sink가
`RuntimeEventBus`로 이동한 뒤 compatibility facade의 호출자 수가 0이 된 시점에 제거한다.

## 12. 검증 계획

| 영역 | 필수 검증 |
|---|---|
| public ABI | 13 hook allowlist, JSON round-trip, schema version, redaction snapshot |
| request transform | N→N+1 순차 합성, original/effective 불변, invalid output reject |
| execution middleware | onion order, exactly-once `next_call`, short-circuit, cancellation, exception identity |
| tool | final args 승인, hard-deny 우선, parallel/sequential/MCP/recovery 동일 terminal |
| LLM | adapter request replacement, retry마다 correlation 유지, cache prefix 불변 |
| verify | pass 강화, fail→pass 거부, bounded continue, timeout fallback, external evidence |
| lifecycle | session/turn cardinality, reset/expiry/shutdown reason, crash reconciliation, subagent terminal parity |
| compaction | pre/post pair, no-op/abort/commit 구분, provider-native honesty |
| persistence | 기존 stored event 문자열과 전 행 조회 호환, SQLite 정본/JSONL projection 경계, mirror 부재 시 correctness |
| 전체 | targeted pytest → ruff/mypy/import lint → `scripts/preflight.sh` |

live provider 호출은 별도 사용자 승인 없이는 실행하지 않는다.

## 13. 명시적 비목표

- Hermes의 23 hook을 모두 공개 ABI로 복제하지 않는다.
- 현재 56 RuntimeEvent를 삭제하거나 stored enum value를 바꾸지 않는다.
- public hook handler에게 기본적으로 raw LLM request나 secret-bearing payload를 주지 않는다.
- `PostVerify`가 built-in failure를 지우거나 임의 pass를 선언하게 하지 않는다.
- compaction, approval, subagent state machine을 generic callback 집합으로 재구현하지 않는다.
- 구체적인 consumer 없이 다섯 번째 middleware point나 외부 network transport를 추가하지 않는다.
