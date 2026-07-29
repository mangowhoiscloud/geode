# Hook taxonomy fold — 27 family → 13, 계약을 family 단위로

작성 2026-07-30. 대상 브랜치 `feature/hook-taxonomy-fold`, base `develop`(d0eb411ed).
근거는 전부 이 저장소와 `~/workspace/{hermes-agent,codex}`의 `origin/main` 원문 실측이다.

## 0. 문제

`HookEvent` 56종을 `action`의 첫 세그먼트로 묶으면 **family가 27개이고 그중 16개가 원소 하나뿐**이다.
이름공간의 절반 이상이 분류로 기능하지 않는다. 참조 축과 비교하면 밀도 차이가 드러난다.

| | 이벤트/hook | family | 밀도 |
|---|---:|---:|---|
| Hermes (`hermes_cli/plugins.py` `VALID_HOOKS`) | **23** | 6 문서 계열 | 3.8 |
| Codex (`metrics/names.rs` + `events/session_telemetry.rs`) | **51 metric + 14 event** | ~12 도메인 | 5.4 |
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
