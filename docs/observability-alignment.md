# Observability 정렬 — GEODE ↔ Hermes ↔ Codex

재점검 2026-07-29. 세 축을 **로컬 소스 원문**으로 다시 읽고 정렬 대상을 정한다.

## 0. 근거의 출처와 최신성

이전 조사(`docs/observability-survey.md`)는 Hermes를 "공개 문서만 가능"으로 적었다. **틀렸다.** 세 저장소가 모두 로컬에 있다.

| 대상 | 로컬 경로 | 체크아웃 시점 | 조치 |
|---|---|---|---|
| Hermes | `~/workspace/hermes-agent` | v0.13.0 / 2026-05-12 | **11,024 커밋 뒤처짐** → `git fetch` 후 `origin/main`(cbecd72e9) 원문을 읽음 |
| Codex | `~/workspace/codex` | 2026-06-30 | **769 커밋 뒤처짐** → fetch 후 `origin/main`(fe01054a) |
| GEODE | `~/workspace/geode` | v1.0.7 | 작업 트리 |

스테일 체크아웃을 그대로 읽으면 두 달 전 설계를 현재로 오인한다. 아래 인용은 전부 `git show origin/main:<path>` 결과다.

---

## 1. 계약 대조

### 1.1 이벤트 어휘 — GEODE가 가장 많다

| | 개수 | 구성 |
|---|---:|---|
| GEODE `HookEvent` | **56** | tool 9 · cognitive 6 · llm 4 · mutation 4 · subagent 3 · turn 3 · memory/context/session/mcp/cost 각 2 |
| Hermes observer hooks | ~15 | session 4 · turn-scoped LLM 2 · request-scoped API 3 · tool 3 · approval 2 · subagent 2 |
| Codex OTel events | 16 | `codex.{api_request, sse_event, tool_decision, tool_result, user_prompt, conversation_starts, turn_ttft, startup_phase, sandbox_outcome, auth_recovery, websocket_connect, websocket_request, …}` |

GEODE는 `cognitive_*` 6종과 `mutation_*` 4종처럼 나머지 둘에 대응물이 없는 축을 갖는다. **어휘 부족이 문제가 아니다.**

### 1.2 상관 식별자 — GEODE가 가장 적다

Hermes는 payload마다 다음을 싣는다(`docs/observability/README.md` § Correlation IDs).

```
session_id → task_id → turn_id → api_request_id (+api_call_count) → tool_call_id
lineage: parent_session_id / child_session_id
         parent_subagent_id / child_subagent_id
         parent_turn_id
```

GEODE `hook_events` payload 2,149건을 전수로 세면 이렇다.

| 필드 | 건수 | 비중 |
|---|---:|---:|
| `turn_id` | **0** | 0% |
| `tool_call_id` | **0** | 0% |
| `api_request_id` | **0** | 0% |
| `run_id` | **0** | 0% |
| `session_id` | 302 | 14% |

식별자는 payload가 아니라 테이블 컬럼(`session_key`, `run_id`, `task_id`)에 있어 SQL join은 되지만, **turn과 call 층 자체가 없다.**

**이것이 격차의 본체다.** Hermes는 hook 15개로 trajectory를 재구성하고 GEODE는 56개로 못 하는데, 이유는 이벤트 수가 아니라 각 이벤트가 무엇에 결속되는지다.

### 1.3 영속 의미론 — 여기서 설계가 갈린다

세 축이 "라이브 컨텍스트"와 "이력"을 어떻게 분리하는가.

| | 라이브 컨텍스트 | 이력 | 분리 수단 |
|---|---|---|---|
| **Hermes** | `messages WHERE active=1` | 같은 테이블 전체 | **`active`/`compacted` 2비트 플래그** |
| **Codex** | rollout 재생 + `compacted` 레코드 | rollout JSONL 영구 | `compacted.replacement_history` |
| **GEODE** | `sessions.db:messages` | `transcripts/*.jsonl` | **저장소 두 개** |

Hermes의 압축 경로가 자기 설계를 직접 설명한다(`hermes_state.py:7420-7431`).

```python
# Soft-archive the live turns: active=0 hides them from the live
# context load, compacted=1 marks them as "summarized away" (vs
# rewind/undo's active=0+compacted=0, which means "user took it
# back"). search_messages includes compacted=1 rows by default so
# the pre-compaction transcript stays discoverable; live-context
# loads (active=1 only) still exclude them.
conn.execute(
    "UPDATE messages SET active = 0, compacted = 1 "
    "WHERE session_id = ? AND active = 1", (session_id,))
```

2비트가 세 상태를 구분한다.

| `active` | `compacted` | 뜻 |
|---|---|---|
| 1 | 0 | 라이브 컨텍스트 |
| 0 | 1 | 요약되어 치워짐 — 검색에는 남음 |
| 0 | 0 | 사용자가 되돌림(rewind/undo) |

GEODE는 같은 자리에서 **행을 지운다**(`session_manager.py:912-919`). `save_messages`가 `(session_id, seq)` UPSERT 뒤 현재 목록 밖의 `seq`를 DELETE하므로, 재실행 세션의 이전 내용이 복구 불가능하게 사라진다. 이력을 잃지 않으려고 `transcripts/`를 따로 두는 구조가 여기서 나왔다.

**Hermes 방식이면 저장소 하나로 족하다.** `id AUTOINCREMENT` + `active` 플래그이지 `(session_id, seq)` 자연키가 아니라는 점이 핵심이다. seq 자연키는 실행마다 0에서 재시작하므로 덮어쓰기를 구조적으로 강제한다.

### 1.4 `messages` 컬럼 대조

| 축 | Hermes | GEODE |
|---|---|---|
| 키 | `id INTEGER PRIMARY KEY AUTOINCREMENT` | `(session_id, seq)` |
| 라이프사이클 | `active`, `compacted`, `observed` | 없음 |
| reasoning | `reasoning`, `reasoning_content`, `reasoning_details`, `codex_reasoning_items`, `codex_message_items` (**5종**) | `reasoning` (컬럼만, **0% 기록**) |
| tool | `tool_call_id`, `tool_calls`, `tool_name`, `effect_disposition` | `tool_call_id`, `tool_calls`, `tool_name` |
| 계측 | `token_count`, `finish_reason` | 둘 다 컬럼만, **0% 기록** |
| 표시 | `api_content`, `display_kind`, `display_metadata`, `platform_message_id` | 없음 |
| 전문검색 | FTS5 3종(기본·trigram·CJK) | `messages_fts` |

GEODE의 `reasoning`·`token_count`·`finish_reason`은 스키마에 있으나 한 건도 쓰이지 않는다. **컬럼을 더 만들 일이 아니라 이미 있는 컬럼에 쓰기를 붙이는 일이다.**

### 1.5 실패 의미론

| | 계약 |
|---|---|
| Hermes | **fail-open** — 콜백 예외를 잡아 경고만 남기고 루프를 계속한다. `telemetry_schema_version = "hermes.observer.v1"`을 모든 payload에 주입해 버전 협상을 한다 |
| Hermes 성능 | 비싼 payload 구성을 `has_hook(...)` 뒤에 둬서, 구독자가 없으면 sanitize 비용을 아예 치르지 않는다 |
| GEODE | `hook_persistence`가 dispatch를 기록하되 `EvidenceLedger`는 best-effort. schema_version은 테이블 컬럼(v1/v2)이지 payload 필드가 아니다 |

---

## 2. 정렬안

### 2.1 채택 — 우선순위 순

**A. `active`/`compacted` 2비트로 저장소 통합** (Hermes)

GEODE의 transcript/`messages` 이중화를 없앤다. `messages`를 `id AUTOINCREMENT` 키에 `active`·`compacted` 플래그로 바꾸면 한 테이블이 라이브 컨텍스트와 이력을 겸한다. 사용자가 지적한 "중복된 저장 지양"의 직접 해답이며, 앞선 조사가 밝힌 다중 run 소실(11.31%, 31/274)의 근본 원인을 제거한다.

버린 대안은 `transcripts/`를 정본으로 고정하고 `messages`를 캐시로 격하하는 것이다. 마이그레이션이 없어 매력적이지만 JSONL은 전문검색·부분 갱신·인덱스가 없어 Hermes/OpenClaw가 이미 떠난 자리로 되돌아간다.

**B. turn 층 발급** (Hermes `turn_id`, Codex `turn_id`)

GEODE에 없는 유일한 계층이다. Hermes는 `turn_id`를 "한 user turn 안의 API 시도와 tool call이 공유하는 식별자"로 정의하고, 그 아래 `api_request_id`를 **불투명 값**으로 따로 둔다(문서가 파싱 금지를 명시). GEODE의 `run_id`는 실행 경계이지 턴이 아니므로 대체할 수 없다.

**C. hook payload에 식별자 주입** (Hermes)

56개 event가 있어도 결속이 없으면 재구성이 안 된다. 최소한 `session_id`·`run_id`·`turn_id`·`tool_call_id`를 payload에 싣는다. 컬럼에 이미 있는 것을 payload에도 넣는 중복처럼 보이지만, payload만 받는 소비자(플러그인·export)가 컬럼을 볼 수 없다는 것이 Hermes가 이 설계를 택한 이유다.

**D. `reasoning`·`token_count`·`finish_reason` 쓰기 배선**

스키마 변경 0, writer만 붙이면 된다. Hermes는 reasoning을 5종으로 나눠 보관하고, Codex는 `codex.usage.*` metric으로 토큰을 낸다.

**E. `has_hook` 게이팅** (Hermes)

구독자가 없을 때 sanitize 비용을 치르지 않는 성능 계약. GEODE의 `ActivityRow` 기구가 1,846줄로 2,119행을 만드는 현 상태에 직접 적용된다.

### 2.2 비채택

| 항목 | 출처 | 이유 |
|---|---|---|
| OTLP 내장 exporter | Codex | GEODE는 traceloop 래퍼가 이미 있고 기본 비활성이 옳다. Codex가 설정 없이 Statsig로 지표를 보내는 것(9.9일 574건)은 따를 설계가 아니다 |
| 운영 로그 SQLite 싱크 | Codex `logs_2.sqlite` | 257MB에 9.9일치, 78.6% TRACE, 67.7% SSE 잡음. 상위 저장소도 이슈 4건으로 다루는 중이다 |
| XTML 토큰화 | K3 | 자체 학습·디코딩이 없으면 값이 회수되지 않는다 |
| `agent/trajectory.py` ShareGPT export | Hermes | 학습용 trajectory 수집은 GEODE의 현재 목표가 아니다 |

### 2.3 반증 조건

- **A** — `active` 플래그 도입 후에도 `search_messages` 성능이 유지되는지 본다. 아카이브 행이 누적되면 라이브 로드가 느려질 수 있고, 그때는 Hermes처럼 부분 인덱스가 필요하다.
- **B** — 턴 경계가 provider마다 갈리면(스트리밍 재개, 도구 재시도) 발급을 미루고 `run` 단위로 만족한다.
- **C** — payload 크기가 `max_payload_bytes`(8KB) 상한에 부딪히면 식별자만 남기고 나머지를 줄인다.

---

## 3. 이 문서가 정정하는 것

| 이전 진술 | 실제 |
|---|---|
| "Hermes는 이 머신에 없어 공개 문서가 유일한 근거" (2회) | `~/workspace/hermes-agent`에 체크아웃 존재. `which hermes`와 `~/.hermes` 부재는 **런타임 미설치**이지 소스 부재가 아니다 |
| "Hermes `messages`는 append-only" | 정확히는 **append + soft-archive**. `UPDATE ... SET active=0` 경로가 5곳 있고 hard DELETE는 세션 단위 정리뿐이다 |
| "GEODE는 event 어휘가 파편화" | 56개 값이 전부 고유하고 v1→v2 전환이 07-15에 끝났다. 격차는 어휘가 아니라 **식별자**다 |

`~/workspace`에는 `codex`·`openclaw`·`claude-code-ref`·`autoresearch`·`crumb`·`paperclip` 체크아웃도 있다. frontier 대조는 웹 검색 이전에 이쪽을 먼저 읽는다.
