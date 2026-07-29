# Observability 실태 조사 — GEODE · Codex · Hermes · OpenClaw

작성 2026-07-29. GEODE와 Codex는 **이 머신의 실측**이고, Hermes·OpenClaw는 **공개 저장소·문서**다.

> **정정 (2026-07-29).** Hermes·Codex·OpenClaw의 소스 체크아웃이 `~/workspace/`에 있다. `which hermes` 부재는 런타임 미설치이지 소스 부재가 아니었다. 로컬 원문으로 다시 읽은 결과는 `docs/observability-alignment.md`에 있고, 아래 §3 Hermes 절의 결론 일부를 정정한다.
근거 층위를 열마다 표시하며, 백분율에는 분모를 붙인다. 모든 DB는 `mode=ro`로 열었고 쓰지 않았다.

---

## 1. GEODE — 무엇이 있는가

### 1.1 `core/observability/` 모듈 14개 (5,369줄)

| 모듈 | 줄 | 역할 | 쓰는 곳 |
|---|---:|---|---|
| `activity.py` | 1,030 | `ActivityRow` 봉투 + 이벤트별 payload 스키마 | → `hook_events` 컬럼 |
| `activity_registry.py` | 816 | HookEvent → ActivityRow 매핑 (`_TYPED_ROW_SPECS`) | → 위와 동일 |
| `transcript.py` | 597 | 세션 JSONL 이벤트 스트림 (Tier 1) | `~/.geode/transcripts/` |
| `event_store.py` | 566 | HookSystem 운영 이벤트, bounded SQLite | `sessions.db:hook_events` |
| `agent_runtime_state.py` | 530 | agent별 누적 런타임 상태 | `sessions.db:agent_runtime_state` |
| `trajectory.py` | 522 | K3형 message list 투영 (읽기 전용, 신규) | — |
| `session_metrics.py` | 518 | 세션 집계 지표 (Tier 2). 13곳 분산 상태를 통합 | 메모리 + 체크포인트 |
| `hook_persistence.py` | 211 | dispatch 영속화 + transcript 미러링 | 위 둘을 잇는 배선 |
| `otel_export.py` | 154 | OpenLLMetry(`traceloop-sdk`) 래퍼 | OTLP (기본 꺼짐) |
| `logging_config.py` | 127 | 진입점별 로깅 설정 통일 | stderr / 파일 |
| `run_dir.py` | 115 | per-cycle 출력 디렉터리 ContextVar SoT | 경로만 |
| `run_log.py` | 101 | 스케줄러 job 이력, bounded JSONL | `~/.geode/runs/` |
| `redaction.py` | 38 | secret 정규식 마스킹 | 다른 writer가 호출 |
| `__init__.py` | 44 | 재수출 | — |

`ActivityRow` 계열 **1,846줄이 `hook_events` 2,119행을 만든다.** 스키마 기구가 그 산출량에 비해 크다.

### 1.2 패키지 밖 관측 표면

| 구성 요소 | 위치 | 소유 모듈 |
|---|---|---|
| EvidenceLedger | `~/.geode/evidence/` | `core/agent/evidence_ledger.py` |
| 메시지 SOT | `sessions.db:messages` | `core/memory/session_manager.py` |
| 세션 체크포인트 | `sessions.db:sessions` + JSON hot cache | `core/memory/session_checkpoint.py` |
| Cognitive 상태·이벤트 | `sessions.db:cognitive_*` | `core/memory/cognitive_state_store.py` |
| Context artifact | `sessions.db:context_artifacts` | `core/tools/session_search.py` |
| 프로젝트 저널 | `~/.geode/journal/` | `core/memory/project_journal.py` |
| 토큰·비용 | `~/.geode/usage/` | `core/llm/token_tracker.py` |

### 1.3 디스크 실측

| 저장소 | 파일 | 크기 | 계층 |
|---|---:|---:|---|
| `transcripts/` | 14,966 (+ `index.json` 40) | 408 M | 대화 |
| `evidence/` | 10,312 | 341 M | 판정 |
| `petri/` | 566 | 132 M | 감사 |
| `diagnostics/` | 6,835 | 77 M | 운영 |
| `runs/` | 927 | 61 M | 파이프라인 |
| `vault/` | 5,866 | 23 M | 산출물 |
| `journal/` | 4,694 | 20 M | 서사 |
| `usage/` | 5 | 14 M | 비용 |
| `autoresearch/` | 1,758 | 14 M | 실험 |

`sessions.db` 테이블: `messages` 48,435 · `sessions` 8,511 · `cognitive_events` 2,722 · `hook_events` 2,119 · `agent_runtime_state` 1,318 · `cognitive_states` 301 · `context_artifacts` 65 · **`run_lineage` 0**.

### 1.4 보존

| 저장소 | 정책 |
|---|---|
| transcript | 30일 + 파일당 5 MB tail 절단 |
| hook_events | retention class 3종(`audit`/`standard`/`high_volume`)별 일수, 256 write마다 prune |
| run_log | 2 MB 초과 시 최신 N줄만 |
| evidence | **정책 없음 — 무한 증가** |

---

## 2. Codex CLI 0.145.0 — 세 평면이 `thread_id`만 공유한다

로컬 `CODEX_HOME` 23개 하위 디렉터리, 약 3.2 GB.

### 2.1 Trajectory 평면 — `sessions/**/rollout-*.jsonl`

**1,742 파일 / 598,479줄 / 파싱 실패 0건.** 모든 줄이 `{timestamp, type, payload}`다.

| 레코드 종류 | 건수 | 비중 | 담는 것 |
|---|---:|---:|---|
| `response_item` | 304,387 | 50.9% | 모델이 보는 대화 항목 |
| `event_msg` | 280,111 | 46.8% | UI·런타임 이벤트, 토큰 회계 포함 |
| `turn_context` | 6,388 | 1.07% | 턴별 설정 스냅샷 |
| `session_meta` | 3,837 | 0.64% | 세션 정체성 + git 출처 |
| `world_state` | 1,828 | 0.31% | 주입된 환경·지시 상태 |
| `compacted` | 1,295 | 0.22% | 컨텍스트 압축 경계 |
| `inter_agent_communication_metadata` | 633 | 0.11% | 에이전트 간 턴 트리거 |

`response_item` 하위(분모 304,397): `message` 66,884 · `function_call` 63,909 · `function_call_output` 63,901 · `reasoning` 61,201 · `custom_tool_call_output` 23,477 · `custom_tool_call` 23,397 · `web_search_call` 759.

**`token_count`가 시스템 전체에서 가장 조밀한 텔레메트리다** — `event_msg` 하위 126,190건으로 전체 rollout 줄의 21.1%다. Payload에 `input/cached_input/cache_write_input/output/reasoning_output/total_tokens`와 `rate_limits`(사용률, 창 길이, 리셋 시각, 크레딧 잔액, 플랜 종류)가 들어 있어 **exporter 없이 로컬 파일만으로 턴별 비용·캐시 적중·쿼터를 복원할 수 있다.**

`session_meta`가 3,837건으로 파일 수의 2.2배인 것은 fork와 sub-agent 스레드가 자기 meta 줄을 덧붙이기 때문이다. 키에 `parent_thread_id` 211건, `forked_from_id` 79건이 있다.

### 2.2 운영 평면 — `logs_2.sqlite` (257 M + WAL 56 M)

`tracing_subscriber::Layer`가 배치 insert하는 싱크다.

| 측정 | 값 (분모 144,461행) |
|---|---|
| 기간 | 2026-07-20 → 07-29, **약 9.9일 롤링** |
| TRACE | 113,602 (78.6%) |
| DEBUG / INFO | 16,413 / 14,131 |
| WARN / ERROR | 273 / 42 (0.19% / 0.029%) |
| 최다 target | `codex_api::sse::responses` 97,823 (**67.7%**) |

설치는 2026-02부터인데 로그는 07-20부터다. **분석용이 아니라 `/feedback` 번들용**이며, 구조화 필드가 아니라 렌더된 텍스트를 저장한다. 상위 저장소의 이슈 #26374·#28224·#29532가 같은 폭증을 다루고, 0.145.0 릴리스가 로그량 수정 4건을 담았다.

### 2.3 상태 평면

| DB | 테이블 | 행 | 뜻 |
|---|---|---:|---|
| `state_5.sqlite` | `threads` | **1,742** | rollout 파일과 1:1 |
| | `thread_spawn_edges` | 209 | `parent → child` 스폰 그래프 |
| `goals_1.sqlite` | `thread_goals` | 2 | `token_budget`, `tokens_used` 보유 |
| `memories_1.sqlite` | `stage1_outputs`, `jobs` | **0 / 0** | 파이프라인 존재, 미사용 |

`threads`가 세션당 가장 풍부한 기록이다. `tokens_used`, `cli_version`, `model`, `reasoning_effort`, `sandbox_policy`, `approval_mode`, `git_sha`, `git_branch`, `cwd`, `agent_role`를 담는다.

### 2.4 Export 평면 — 기본으로 나간다

OpenTelemetry 0.31.0을 링크한다. 문서상 `otel.exporter` 기본은 `none`이지만 **`otel.metrics_exporter` 기본은 `statsig`**이고 엔드포인트 `https://ab.chatgpt.com/otlp/v1/metrics`가 바이너리에 하드코딩돼 있다.

로컬 `config.toml`에 `[otel]` 항목이 **없는데도** 9.9일간 `HttpMetricsClient.ExportSucceeded` **574건, 실패 0건**이 기록됐다. Trace·log exporter는 발동하지 않았다. **지표는 설정 없이 나가고 트레이스는 안 나간다.**

자체 collector로 돌리려면 `[otel] metrics_exporter = "otlp-http"` + `endpoint`, 끄려면 `"none"`이다.

> 미검증 — Statsig로 나간 payload의 내용은 네트워크 캡처를 하지 않아 확인하지 못했다. 문서는 `log_user_prompt` 기본 `false`에 프롬프트가 마스킹된다고 하지만 이는 문서 주장이지 실측이 아니다.

---

## 3. Hermes — 공개 저장소 기준

[NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent), MIT, Python.

**JSONL을 버리고 SQLite로 이주했다.** `hermes_state.py` 모듈 docstring이 "FTS5 전문검색을 갖춘 영속 세션 저장소를 제공하며 **per-session JSONL 파일 방식을 대체한다**"고 명시한다. 저장소는 `$HERMES_HOME/state.db`(기본 `~/.hermes`), WAL 저널이며 NFS·SMB·FUSE에서 `journal_mode=DELETE`로 후퇴하는 경로가 문서화돼 있다.

상관 ID 계층이 조사 대상 넷 중 가장 깊다. `hermes.observer.v1` 계약이 **`session_id → task_id → turn_id → api_request_id → tool_call_id`**에 더해 `parent_session_id`/`child_session_id`, `parent_subagent_id`/`child_subagent_id`, `parent_turn_id`를 규정한다.

Reasoning은 `messages` 테이블에 **전용 컬럼 4개**(`reasoning`, `reasoning_content`, `reasoning_details`, `codex_reasoning_items`)로 보존된다.

**내장 OTLP exporter가 없다.** 대신 백엔드 중립 observer hook 계약을 두고 Langfuse·NeMo Relay 플러그인을 번들한다. 학습용 trajectory는 `state.db`와 분리해 ShareGPT 형식 `trajectory_samples.jsonl`로 따로 쌓는다.

---

## 4. OpenClaw — 공개 저장소 기준

[openclaw/openclaw](https://github.com/openclaw/openclaw), MIT, TypeScript.

역시 **JSONL → SQLite 이주**를 마쳤다(`openclaw doctor`의 "SQLite flip", 다운그레이드 경로 문서화). 저장소는 agent별 `~/.openclaw/agents/<agentId>/agent/openclaw-agent.sqlite`이고, transcript가 **append-only 트리 이벤트(`id` + `parentId`)**다. 삭제 세션은 `*.jsonl.deleted.<ts>.zst`로 보관한 뒤 행을 지운다.

넷 중 **OTel 문서화가 가장 두껍다.** `diagnostics-otel` 플러그인이 OTLP/HTTP protobuf 전용이고 trace·metric·log를 개별 토글하며, span 계층 `openclaw.harness.run ⊃ openclaw.run ⊃ openclaw.model.call`과 지표 이름(`openclaw.tokens`, `openclaw.cost.usd`, `openclaw.model_call.time_to_first_byte_ms` 등)을 공개 카탈로그로 제공한다.

Tool 결속에 **복구 로직**이 있다. `sanitizeToolUseResultPairing`이 tool_use↔tool_result 짝을 고치고, rate-limit 실패로 부분 저장된 인자 없는 호출 블록을 버린다.

---

## 5. 비교

| 축 | GEODE | Codex 0.145.0 | Hermes | OpenClaw |
|---|---|---|---|---|
| 근거 | 로컬 실측 | 로컬 실측 | 공개 문서 | 공개 문서 |
| Trajectory 정본 | **JSONL과 SQLite 이중** | JSONL (영구) | SQLite (JSONL 폐기) | SQLite (JSONL 폐기) |
| 대화 저장 | `transcripts/` 14,966 + `messages` 48,435행 | `rollout-*.jsonl` 598,479줄 | `state.db:messages` | append-only 이벤트 트리 |
| call id | `messages`만 보유 (99.3% 결속), JSONL은 없음 | **100%** (87,345/87,345) | `tool_call_id` 컬럼 | 있음 + 짝 복구 로직 |
| turn id | **없음** (`run_id`가 후보) | `turn_id` | `turn_id` + `api_request_id` | 이벤트 트리 `parentId` |
| lineage | `hook_events.task_id` 16행, `run_lineage` **0행** | `thread_spawn_edges` 209행 | `parent_session_id` 등 6종 | `fork: true` + `parentSessionKey` |
| reasoning | **미기록** (컬럼만, 0%) | `reasoning` 61,201건 (13.8% 판독) | 전용 컬럼 4개 | 저장 + hygiene 규칙 |
| 전문검색 | `messages_fts` 있음 | 없음 | **FTS5 3종** (기본·trigram·CJK) | 없음 |
| 토큰·비용 | `usage/` 5파일 14 M | **`token_count` 126,190건**, rate limit 포함 | 세션·모델별 컬럼 | 지표 카탈로그 공개 |
| OTel | traceloop 래퍼, **기본 꺼짐**, config 항목 없음 | metric은 **기본으로 Statsig 전송** (574건), trace는 `none` | **내장 없음**, hook 계약 + 플러그인 | OTLP/HTTP, span 계층 공개 |
| 운영 로그 | `diagnostics/` 6,835파일 | `logs_2.sqlite` 9.9일 롤링, 78.6% TRACE | `~/.hermes/logs/` 6종 + `hermes logs` CLI | JSONL 일별 롤링 |
| 압축 경계 기록 | 없음 | `compacted` 1,295건 (`replacement_history` 포함) | 압축 시 child session 생성 | compaction 요약을 트리에 |
| 환경 스냅샷 | 없음 | `world_state` 1,828 + `turn_context` 6,388 | — | — |
| 보존 | transcript 30일, evidence **무제한** | rollout 영구, 로그 10일 | — | `maxDiskBytes` + zst 보관 |

---

## 6. 읽히는 것

**JSONL → SQLite 이주는 이미 합의다.** Hermes와 OpenClaw가 독립적으로 같은 이동을 했고 각자 이유를 명시했다(전문검색, append-only 이벤트 트리). GEODE는 두 저장소를 **동시에 갖고 있으면서 정본을 JSONL로 두어** 손실이 큰 쪽을 읽고 있다. `docs/trajectory-redesign.md`가 제안한 정본 교체는 이 수렴과 같은 방향이다.

**GEODE의 결손은 세 가지다.** turn 키가 없고, reasoning을 컬럼만 두고 안 쓰며, lineage 테이블(`run_lineage`)이 0행이다. 셋 다 나머지 셋은 갖고 있다.

**Codex의 `token_count` 밀도가 참고할 만하다.** 전체 줄의 21.1%를 토큰·쿼터 회계에 쓰고 exporter 없이 로컬만으로 비용을 복원한다. GEODE는 `usage/`에 5파일 14 M를 두지만 trajectory와 결속돼 있지 않다.

**Codex의 `world_state`·`turn_context`는 GEODE에 대응물이 없다.** 턴마다 sandbox 정책·승인 모드·모델·effort를 스냅샷으로 남기면 "왜 이 턴이 저렇게 동작했나"가 사후에 답해진다.

**운영 로그와 trajectory를 섞지 않는 것은 Codex가 더 엄격하다.** 세 평면이 `thread_id`만 공유하고 서로 침범하지 않는다. GEODE는 `hook_persistence`가 transcript로 미러링해 두 평면이 섞인다.

**Statsig 기본 전송은 사용자가 알아야 할 사실이다.** 이 머신에서 설정 없이 9.9일간 574건이 나갔다. 끄려면 `~/.codex/config.toml`에 `[otel] metrics_exporter = "none"`이다.
