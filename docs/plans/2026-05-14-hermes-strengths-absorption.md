# Plan: Hermes 강점 흡수 — Long-term Recall + Platform-aware + 4-phase Compaction + Multi-proc WAL

> [!NOTE]
> Historical comparison: both GEODE and Hermes have changed since this audit.
> Re-audit current code and commit-pinned upstream source before implementation.
> Current architecture-program status is owned by
> [`docs/architecture/extensibility-roadmap.md`](../architecture/extensibility-roadmap.md).
>
> 작성일: 2026-05-14
> 상태: 계획만, 구현 대기

## Problem

GEODE 와 Hermes 의 27축 E2E 대조 결과 (영속화 13축 + 컨택스트 14축), GEODE 가 천장 대비 63% 수준. 핵심 갭은 *"기억과 회상"* 영역:

- 메시지 본문 trim (최근 20개만) → 장기 회상 불가
- FTS / CJK 검색 부재 → 과거 대화 자산화 불가
- LLM 호출 가능한 검색 도구 부재 → 컨택스트 overflow 시 능동 회상 X
- 단일 프로세스 가정 → gateway + serve REPL + worktree 동시 쓰기 미지원
- Platform-aware 시스템 프롬프트 부재 → surface(Slack/CLI/cron)별 차별화 X
- 3-step 휴리스틱 compaction → Hermes 의 4-phase + structured summary 보다 단순

장기 자율 실행 에이전트 방향(스케줄러 + 다중 surface)으로 가려면 위 갭이 결정적.

## Socratic Gate

| # | Question | Answer |
|---|----------|--------|
| Q1 | Does it already exist in code? | 부분적 — `SessionManager` 가 메타 인덱스만, `SessionCheckpoint` 가 JSON 본문. FTS/검색 도구/멀티프로세스 동시성/Platform-aware 는 부재. |
| Q2 | What breaks if we don't do this? | (a) 사용자가 *"지난주 OAuth 이야기 다시 보여줘"* 같은 회상 요청 처리 불가. (b) 컨택스트 overflow 시 LLM 이 능동 회상 못 함. (c) gateway 다중 프로세스 확장 시 WAL contention 발생. (d) Slack/Telegram surface 추가 시 톤/도구 가용성 차별화 어려움. |
| Q3 | How do we measure the effect? | (a) `session_search "OAuth"` E2E 호출이 과거 대화 회수. (b) `--scope all` 로 cross-project 검색. (c) 컨택스트 80% 도달 시 4-phase compactor 가 structured summary 생성. (d) Slack lane 부팅 시 surface=slack 힌트가 system prompt 에 포함. |
| Q4 | What is the simplest implementation? | 4 PR 시퀀스 — messages 테이블 + FTS5 + 검색 도구 + global 인덱스. 본문은 per-project DB, 검색은 글로벌 인덱스 (snapshot 만). |
| Q5 | Is this pattern in 3+ frontier systems? | Hermes(`hermes_state.py`), Claude Code (`~/.claude/projects/*/transcripts.jsonl` + 글로벌 검색), Codex CLI (rollouts 풀텍스트), Cursor (session search). 4/4. |

## Design

### 의존성 그래프

```
Phase 1 (Long-term Recall)  ──►  Phase 4 (Multi-proc WAL)
   │  P2 + P3 + P4 + C4 + C7        P5 + C8 (Phase 1 위에서만 의미)
   │
   ├── Phase 2 (Platform-aware Prompt) — 독립
   │     C12 + C13
   │
   └── Phase 3 (4-phase Compaction) — 독립
         C5 + C6
```

### 토폴로지 결정 — 하이브리드 (per-project 본문 + global 검색 인덱스)

근거: 프로젝트 격리 유지(보안/사적 정보 누수 방지) + cross-project 검색 가능성 양립.

```
~/.geode/
├── projects/
│   └── {encoded-cwd}/
│       ├── sessions/
│       │   ├── sessions.db          ← per-project 본문 SoT (sessions + messages + FTS5 + 트리그램)
│       │   ├── {session_id}/state.json   (메타 핫캐시)
│       │   └── active.json
│       └── journal/costs.jsonl
└── search/
    └── global.db                    ← 글로벌 검색 인덱스 (snapshot 만)
        • projects                   (project_id ↔ encoded-cwd 매핑)
        • message_index              (project_id, session_id, message_id, ts, role)
        • message_index_fts          (FTS5 over content_snapshot)
        • message_index_fts_trigram  (CJK)
```

### Phase 1 — Long-term Recall (4 PR 시퀀스)

#### 1a. `feat(memory): SessionManager messages 테이블 + dual-write`

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/memory/session_manager.py`, `core/runtime_state/session_checkpoint.py` |
| 신규 스키마 | `messages(id, session_id, role, content, tool_call_id, tool_calls, tool_name, timestamp, token_count, finish_reason, reasoning, metadata)` + idx_messages_session, idx_messages_tool_name |
| 쓰기 정책 | dual-write: `SessionCheckpoint.append()` 가 JSON+DB 동시 쓰기. JSON 이 SoT (이 단계까지), DB 는 mirror. 트랜잭션은 분리. DB 실패 시 WARN 로깅 + JSON 유지. |
| 읽기 정책 | `SessionCheckpoint.load()` 는 JSON 우선 (이 PR 까지). |
| 테스트 | dual-write parity, DB 손상 시 graceful degradation |
| 추정 LOC | ~400 |
| 위험 | 중 (스키마 + dual-write 정합성) |

#### 1b. `feat(memory): JSON 20-trim 해제 + DB SoT 전환 (layout v4)`

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/runtime_state/session_checkpoint.py`, `core/wiring/layout_migrator.py` (v3→v4 step 추가) |
| 코드 변경 | `CHECKPOINT_MAX_MESSAGES = 20` 제거. `load()` 가 DB 우선. `messages.json` 은 hot cache 만 (옵션). `tools.json` 은 `messages` 테이블의 tool_calls 컬럼으로 통합 흡수. |
| 마이그레이션 | `_migrate_v3_to_v4()`: 기존 `~/.geode/projects/*/sessions/*/messages.json` 일괄 backfill. 손상 파일은 skip + WARN. 진행률 INFO 로깅 (v3 의 `_log_migration_summary` 패턴). |
| 테스트 | backfill idempotency, 100+ session 부하 backfill, 손상 파일 graceful skip |
| 추정 LOC | ~250 |
| 위험 | 중 (SoT 뒤집기 + 마이그레이션) |

#### 1c. `feat(memory): FTS5 + 트리그램 인덱스`

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/memory/session_manager.py`, 신규 `core/storage/fts_helpers.py` |
| 신규 스키마 | `messages_fts` (unicode61) + `messages_fts_trigram` (trigram) + 각각 3 트리거 (insert/delete/update) |
| 색인 정책 | content + tool_name + tool_calls 통합 색인 (Hermes 패턴) |
| 헬퍼 | `_sanitize_fts5_query()` — 하이픈/도트 인용, 특수문자 제거 (Hermes hermes_state.py:1796 복제) |
| Capability check | SQLite 3.34+ 가 아니면 trigram 인덱스 skip + WARN (graceful degradation) |
| 마이그레이션 | layout v4 의 같은 step 내에서 backfill 동시 수행 (메시지 backfill 직후 색인 backfill) |
| 테스트 | 한글 부분문자열 회상, 하이픈 포함 쿼리, 특수문자 회피 |
| 추정 LOC | ~350 |
| 위험 | 낮음 (트리거 자동 처리, 본문 변경 없음) |

#### 1d. `feat(memory): global.db 검색 인덱스 + session_search 도구`

| 항목 | 내용 |
|---|---|
| 영향 파일 | 신규 `core/memory/search_index.py`, 신규 `core/tools/session_search.py`, `core/tools/definitions.json` 등록, `core/wiring/bootstrap.py` (SearchIndexer 라이프사이클) |
| 신규 스키마 | `global.db` — projects, message_index, message_index_fts (contentless FTS5 over snapshot), message_index_fts_trigram |
| 비동기 인덱서 | `SearchIndexer` thread. bounded queue(1000). queue full 시 동기 fallback (느려지지만 무손실). PASSIVE checkpoint 주기 (50회 쓰기마다). |
| 도구 시그니처 | `session_search(query: str, scope: "current"\|"all"\|"project:<id>", source_filter: str\|None, role_filter: str\|None, since: str\|None, until: str\|None, limit: int=20) -> list[SearchHit]` |
| 결과 형식 | `[{project_id, session_id, message_id, role, snippet, timestamp, score}]` — snippet 은 FTS5 `snippet()` 함수 |
| 시스템 프롬프트 | 컨택스트 80% 임계 부근에서 *"`session_search` 로 과거 회상 가능"* 가이던스 추가 (`core/llm/prompts.py`) |
| 재구축 도구 | `geode reindex` CLI — global.db 비우고 모든 per-project DB 에서 재색인 |
| 테스트 | cross-project 검색, scope 필터링, 비동기 큐 backpressure, rebuild idempotency |
| 추정 LOC | ~500 |
| 위험 | 중 (글로벌 인덱스 + LLM 도구 노출) |

### Phase 2 — Platform-aware System Prompt (1 PR)

| 항목 | 내용 |
|---|---|
| 영향 파일 | 신규 `core/llm/platform_hints.py`, 신규 `core/llm/model_guidance.py`, `core/llm/prompt_assembler.py`, `core/wiring/bootstrap.py` |
| `PLATFORM_HINTS` | dict[surface, str]. keys: `cli`, `serve_repl`, `slack`, `cron`, `worktree`, `mcp_remote`. 각각 응답 스타일/가용 도구/제약. |
| `MODEL_GUIDANCE` | dict[family, str]. keys: `anthropic`, `openai`, `google`, `xai`. tool_use enforcement, reasoning visibility, computer_use 활성화 여부. |
| Bootstrap | entry-point 별 `set_surface_type()` ContextVar 호출. cli=`cli`, gateway=`serve_repl` 또는 `slack`, scheduler=`cron`, etc. |
| 주입 | `PromptAssembler.assemble()` 에 두 fragment 합류 — surface + model lookup 후 system prompt 에 추가 |
| 테스트 | surface 별 다른 system prompt 생성, model 별 다른 guidance |
| 추정 LOC | ~400 |
| 위험 | 낮음 (additive only) |

### Phase 3 — 4-phase Compaction (1 PR)

| 항목 | 내용 |
|---|---|
| 영향 파일 | `core/context/compactor.py` (전체 교체) |
| Phase 1 | Orphan tool result pruning (Hermes context_compressor.py:519-685 패턴) — 200자 이상 + 중복 제거 |
| Phase 2 | Boundary 결정 — protect_first_n=3 + tail token budget(0.20 × threshold) + last user message in tail 강제 |
| Phase 3 | Structured summary 생성 — 12-section 템플릿 (Active Task / Goal / Constraints / Completed Actions / Active State / In Progress / Blocked / Key Decisions / Resolved Questions / Pending Questions / Files / Critical Context). Iterative update (이전 요약 있으면 갱신). Focus topic 옵션. |
| Phase 4 | Message 재조립 — head 복사 + summary 삽입 (role 충돌 해결) + tail 복사 + orphan tool_result stub ("see summary above") |
| Fallback | LLM 호출 실패 시 정적 placeholder (기존 emergency prune 보존) |
| 비용 | LLM 호출 1회 추가/compaction. 모델은 작은 것 (Haiku 또는 Sonnet) 사용. |
| 테스트 | 12-section 템플릿 적용 검증, head/tail 경계 정합, orphan stub 주입 |
| 추정 LOC | ~700 |
| 위험 | 중 (알고리즘 전면 교체) |

### Phase 4 — Multi-proc WAL (1 PR)

| 항목 | 내용 |
|---|---|
| 영향 파일 | 신규 `core/storage/sqlite_helpers.py`, `core/memory/session_manager.py`, `core/memory/search_index.py` |
| 헬퍼 | `_execute_write(fn)` — BEGIN IMMEDIATE + 20-150ms 지터 15회 재시도 + 50회마다 PASSIVE WAL checkpoint. Hermes hermes_state.py:375-446 복제. |
| WAL 폴백 | `apply_wal_with_fallback()` — NFS/SMB 에서 WAL 불가 시 DELETE 모드로 폴백 |
| 적용 | SessionManager 의 모든 write 경로 + SearchIndexer 의 모든 write 경로 헬퍼 경유 |
| 테스트 | 동시 쓰기 contention 시뮬레이션 (10 스레드 × 100 메시지), convoy 없는지 확인 |
| 추정 LOC | ~300 |
| 위험 | 낮음 (헬퍼 추가 + write 경로 wrap) |

## Alternatives Considered

| 대안 | 기각 사유 |
|---|---|
| **글로벌 단일 `~/.geode/state.db` (Hermes 식)** | 프로젝트 격리 손실. GEODE 의 per-project 패러다임을 전면 재작성해야 함. 마이그레이션 비용 큼. |
| **per-project 만, 글로벌 인덱스 없음** | cross-project 검색 불가. 사용자가 *"3주 전 사이드 프로젝트의 그 대화"* 회상 못 함. |
| **본문도 글로벌 DB 에 복제 (snapshot 아님)** | 디스크 2배 사용. 진실 소스가 둘. 동기화 실패 시 진실 충돌. |
| **Phase 1 을 단일 PR 로** | ~1500 LOC. 리뷰 부담. 마이그레이션 위험 집중. 4 PR 분해가 ratchet(P4) 에 부합. |
| **FTS5 대신 임베딩** | 더 똑똑하지만 (a) 외부 의존성 (b) 비용 (c) Hermes 가 안 씀 → 검증된 패턴 우선. 임베딩은 Phase 5+ 후순위. |

## Implementation Checklist

### Phase 1 — Long-term Recall
- [ ] **1a**: SessionManager messages 테이블 + dual-write
- [ ] **1b**: JSON 20-trim 해제 + DB SoT 전환 + layout v4
- [ ] **1c**: FTS5 + 트리그램 인덱스 + sanitize 헬퍼
- [ ] **1d**: global.db + session_search 도구 + 시스템 프롬프트 가이던스

### Phase 2 — Platform-aware Prompt
- [ ] **2**: PLATFORM_HINTS + MODEL_GUIDANCE + bootstrap surface 감지

### Phase 3 — 4-phase Compaction
- [ ] **3**: orphan pruning + boundary + structured summary + reassembly

### Phase 4 — Multi-proc WAL
- [ ] **4**: BEGIN IMMEDIATE + 지터 재시도 + WAL 폴백

### 공통
- [ ] CHANGELOG entry per PR
- [ ] 각 PR 별 quality gates (ruff/mypy/pytest)
- [ ] 각 PR 별 GAP audit
- [ ] 통합 후 27축 재스코어링 — 목표 GEODE 73 → 110+/135

## Verification

```bash
uv run ruff check core/ tests/ plugins/
uv run mypy core/ plugins/
uv run pytest tests/ -m "not live"

# Phase 1 후 — 회상 E2E
uv run geode "지난 세션에서 OAuth 마이그레이션 무엇이라고 했지?"
# session_search 도구 호출 + 결과 회상 + 응답

# Phase 2 후 — surface 별 차별
GEODE_SURFACE=slack uv run geode "안녕"  # Slack 톤
GEODE_SURFACE=cli   uv run geode "안녕"  # CLI 톤

# Phase 3 후 — compaction 품질
# 컨택스트 80% 도달 시 structured summary 12-section 생성 확인 (~/.geode/logs/serve.log)

# Phase 4 후 — 동시성
# 동시 10 프로세스 × 100 메시지 쓰기 → no convoy, no corruption
```

## References

- **Hermes Agent**: `~/workspace/hermes-agent/hermes_state.py` (SessionDB), `agent/context_compressor.py` (4-phase), `agent/prompt_builder.py` (PLATFORM_HINTS), `gateway/session_context.py` (contextvars), `tools/session_search_tool.py` (검색 도구)
- **27축 E2E 비교**: 2026-05-13 GEODE×Hermes 영속화+컨택스트 스코어링 (현재 73/135, Hermes 116/135)
- **GEODE layout migrator**: `core/wiring/layout_migrator.py` v3 (이 plan 의 마이그레이션이 v4 step 으로 들어감)
- **Frontier 대응**: Claude Code transcripts, Codex CLI rollouts, Cursor session search — 4 시스템에서 같은 패턴
