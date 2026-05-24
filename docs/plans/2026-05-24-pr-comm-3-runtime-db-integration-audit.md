# PR-COMM-3 (pre-impl) — runtime.db vs sessions.db integration audit

> **작성**: 2026-05-24
> **상태**: PR-COMM-3 implementation 전 통합 가능성 검토 (operator 결정 대기).
> **이유**: DB/table 교체 비용이 높음 — 초기 스키마 결정이 굳어지면 변경 어려움. 신규 `runtime.db` 만들기 전에 기존 `sessions.db` 와 역할 / anchor / 통합 가능성 검토 우선.
> **결정 필요**: §4 의 3 옵션 중 운영자가 선택.

---

## 1. 기존 SQLite 인프라 (GAP audit)

### 1.1 `sessions.db` — AgenticLoop interactive session 의 SoT

**위치**: `~/.geode/projects/{slug}/sessions/sessions.db` (per-project) + `~/.geode/projects/global/sessions/global.db` (cross-project 검색).

**writer**: `core/memory/session_manager.py` (`SessionManager`) + `core/memory/session_checkpoint.py` (`SessionCheckpoint`).

**용도**:
- AgenticLoop REPL session 의 resume (`/resume <id>`) — `session_state.py` 가 query
- Cross-session 검색 (`session_search` tool) — `core/tools/session_search.py`
- Handoff watcher 의 `handoff_state='pending'` poll — `core/agent/handoff.py`
- Hermes absorption Phase 1a — `messages` table (SessionCheckpoint JSON 의 SQLite mirror)
- Phase 1c (계획) — FTS5 contentless index for full-text search

**테이블 (현재 schema)**:

```sql
-- 22-column session metadata + handoff/verify state
CREATE TABLE sessions (
    session_id                  TEXT PRIMARY KEY,           -- "s-<8hex>" 또는 task_id (PR-Q.5 후)
    created_at                  REAL NOT NULL,
    updated_at                  REAL NOT NULL,
    status                      TEXT NOT NULL DEFAULT 'active',
    model                       TEXT NOT NULL DEFAULT '',
    provider                    TEXT NOT NULL DEFAULT 'anthropic',
    user_input                  TEXT NOT NULL DEFAULT '',
    round_count                 INTEGER NOT NULL DEFAULT 0,
    message_count               INTEGER NOT NULL DEFAULT 0,
    -- PR-CL-BUDGET (handoff)
    handoff_state               TEXT NOT NULL DEFAULT '',
    handoff_platform            TEXT NOT NULL DEFAULT '',
    handoff_error               TEXT NOT NULL DEFAULT '',
    handoff_triggered_at        REAL NOT NULL DEFAULT 0.0,
    -- PR-CL-A3 (verify telemetry)
    verify_pass_count           INTEGER NOT NULL DEFAULT 0,
    verify_fail_count           INTEGER NOT NULL DEFAULT 0,
    last_verify_passed          INTEGER NOT NULL DEFAULT 1,
    last_verify_mode            TEXT NOT NULL DEFAULT '',
    last_verify_effective_mode  TEXT NOT NULL DEFAULT '',
    last_verify_rubric_misses   TEXT NOT NULL DEFAULT '',
    last_verify_should_retry    INTEGER NOT NULL DEFAULT 0
);

-- Phase 1a Hermes absorption (message log mirror)
CREATE TABLE messages (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT,
    tool_call_id  TEXT,
    tool_calls    TEXT,
    tool_name     TEXT,
    timestamp     REAL NOT NULL,
    token_count   INTEGER,
    finish_reason TEXT,
    reasoning     TEXT,
    metadata      TEXT,
    UNIQUE(session_id, seq)
);
```

### 1.2 PR-COMM-3 의 원래 `runtime.db` 안 (3-codebase audit GAP 2+3)

paperclip `agent_runtime_state` + `heartbeat_runs.retryOfRunId` 등가물:

```sql
-- per-agent cumulative + sessionId
CREATE TABLE agent_runtime_state (
    agent_id              TEXT PRIMARY KEY,        -- = task_id (PR-Q.5 anchor)
    adapter_type          TEXT NOT NULL,
    session_id            TEXT,                    -- claude-cli session_id (PR-V's session.json)
    state_json            TEXT,                    -- free-form per-agent state
    last_run_id           TEXT,
    last_run_status       TEXT,
    total_input_tokens    INTEGER NOT NULL DEFAULT 0,
    total_output_tokens   INTEGER NOT NULL DEFAULT 0,
    total_cached_tokens   INTEGER NOT NULL DEFAULT 0,
    total_cost_cents      INTEGER NOT NULL DEFAULT 0,
    last_error            TEXT,
    created_at            REAL NOT NULL,
    updated_at            REAL NOT NULL
);

-- cross-cycle retry chain (paperclip heartbeat_runs.retryOfRunId)
CREATE TABLE run_lineage (
    run_id            TEXT PRIMARY KEY,            -- = seed-gen run_id (e.g. "gen2-redundant_X")
    parent_run_id     TEXT,                        -- previous cycle this is a retry of
    started_at        REAL NOT NULL,
    finished_at       REAL,
    status            TEXT NOT NULL,
    target_dim        TEXT
);
```

---

## 2. 역할 비교 — overlap / orthogonal axis

| 차원 | sessions.db | runtime.db (proposed) |
|---|---|---|
| **anchor** | `session_id` (= `s-<8hex>` for REPL / `task_id` for sub-agent post-PR-Q.5) | `agent_id` (= `task_id`) |
| **단위** | 1 row per `AgenticLoop` 실행 (REPL + sub-agent 모두) | 1 row per *agent role* (cumulative across many sub-agent runs) |
| **lifetime** | per-session (TTL ~72h via SessionCheckpoint cleanup) | persistent (cumulative across cycles) |
| **scope** | per-project (sessions.db) + cross-project (global.db) | per-user (single ~/.geode/runtime.db) — currently |
| **writer 빈도** | 매 session start/end | 매 SUBAGENT_COMPLETED hook |
| **읽기 패턴** | resume / search / handoff watcher | quota dashboard / cross-cycle continuity |
| **anchor 중복?** | PR-Q.5 후 `session_id == task_id` for sub-agents → **anchor 동일** | |

**핵심 발견**: PR-Q.5 의 단일-anchor invariant 로 sub-agent 의 경우 `sessions.session_id == agent_runtime_state.agent_id == task_id`. **두 DB 가 같은 row 키를 다른 차원으로 보고 있음** — 통합 가능성 있음.

**역할 명확 분리되는 점**:
- sessions.db 의 `round_count` / `message_count` / `last_verify_*` 는 **현재 active session 의 instantaneous state**
- runtime.db 의 `total_input_tokens` / `total_cost_cents` / `last_run_id` 는 **agent role 의 cumulative history**

→ 두 axis 가 다른 시간 dimension (snapshot vs accumulator) 이라 **column-level overlap 은 적음**.

---

## 3. Hermes absorption Phase context

`docs/plans/2026-05-14-hermes-strengths-absorption.md` 가 sessions.db 의 multi-phase 확장 plan:
- Phase 1a (merged) — messages table mirror
- Phase 1b (merged) — DB SoT flip (JSON → DB authoritative)
- Phase 1c (pending) — FTS5 contentless index for full-text search
- Phase 1d (pending) — global.db cross-project search

→ sessions.db 가 이미 활발히 진화 중. PR-COMM-3 가 별도 runtime.db 만들면 **Hermes Phase 1 의 cumulative metric (`total_input_tokens` 등) 추가 시 다시 통합 문제 발생**.

---

## 4. 통합 옵션 — 3 가지 (operator decision)

### Option A — `sessions.db` 안에 통합 (단일 DB)
```
~/.geode/projects/{slug}/sessions/sessions.db
├── sessions                 (existing — 22 columns, per-session snapshot)
├── messages                 (existing — Hermes 1a)
├── agent_runtime_state      (NEW — paperclip parity, FK session_id → sessions.session_id)
└── run_lineage              (NEW — paperclip retryOfRunId equivalent)
```
- **장점**: 단일 DB, 단일 connection, 단일 backup. session_id anchor 가 두 axis 자연 연결. Hermes Phase 1 의 추후 cumulative 확장도 같은 DB 안에서.
- **단점**: sessions.db 가 더 비대해짐. per-project 위치라 cross-cycle / cross-project 같은 agent_id 의 cumulative metric 누적이 분산됨. global.db 의 별도 처리 필요.
- **운영 영향**: schema migration 1 회 (sessions.db 에 2 새 테이블 추가).

### Option B — `runtime.db` 별도 (proposed)
```
~/.geode/runtime.db              (NEW, user-level cross-project)
├── agent_runtime_state
└── run_lineage

~/.geode/projects/{slug}/sessions/sessions.db   (unchanged)
├── sessions
└── messages
```
- **장점**: per-project (sessions) vs user-level (runtime) 의 scope 자연 분리. Hermes Phase 1 의 sessions.db 진화 영향 없음. runtime.db 가 cross-project agent cumulative 의 single SoT.
- **단점**: 두 DB 가 같은 anchor (`task_id`) 를 다른 row 로 들고 있어서 cross-DB join 필요. backup 2개. 연결 2개.
- **운영 영향**: 신규 DB 파일 + 신규 migration runner.

### Option C — `runtime.db` 가 cross-project umbrella, `sessions.db` 가 per-project subset
```
~/.geode/runtime.db              (NEW, master)
├── agents              (cross-project per-agent identity)
├── agent_runtime_state (cumulative)
├── run_lineage         (cross-cycle)
├── runs                (1 row per heartbeat_runs equivalent — bridges to sessions.db)
└── (optional) views over sessions.db per-project sessions tables

~/.geode/projects/{slug}/sessions/sessions.db   (unchanged, per-project)
```
- **장점**: paperclip 의 4-layer UUID chain (companies → agents → heartbeat_runs → activity_log) 와 직접 1:1 정렬. 가장 frontier-aligned.
- **단점**: 가장 무거운 마이그레이션. 신규 `runs` 테이블이 sessions.db 의 sessions row 와 join 필요 (attach DB pattern). 초기 비용 큼.

---

## 5. 추천 — Option A (단일 DB) + 점진적 evolve

**근거**:
1. **anchor 통합**: PR-Q.5 가 이미 `task_id` = `session_id` 단일 anchor 확정 — sessions.db 의 session_id PK 가 그대로 agent_runtime_state 의 FK 가 됨.
2. **Hermes Phase 1 align**: sessions.db 가 active development 중. 동일 DB 안에 cumulative axis 추가하면 future Phase 와 자연 합류 (Phase 2 = agent-level cumulative 라고 정의 가능).
3. **운영 부담 최소**: 마이그레이션 1회, backup 1 파일, 연결 1개. 운영자가 `sqlite3 sessions.db` 한 명령으로 모든 state 검사.
4. **cross-project 처리**: global.db 도 같은 schema 로 attach. runtime cumulative 가 cross-project 일 필요 있으면 `global.db.agent_runtime_state` aggregator query.

**리스크**:
- sessions.db 비대화 — agent_runtime_state 는 per-agent 1 row 만 (수십~수백 행), run_lineage 는 cycle 당 1 행 (cumulative 수천 행 / year) — 부담 작음.
- Phase 1c FTS5 attach 후 schema migration 충돌 — agent_runtime_state 는 contentless index 와 무관 (text search 대상 아님).

**비추천 옵션**:
- Option C (separate runtime.db with 4-layer paperclip parity) — over-engineering. GEODE 는 single-user, companies 레이어 없음. paperclip 의 4-layer 가 multi-tenant 산물.

---

## 6. PR-COMM-3 의 implementation 변경 (Option A 채택 시)

| 파일 | 변경 |
|---|---|
| `core/memory/session_manager.py` | `_CREATE_AGENT_RUNTIME_STATE_TABLE_SQL` + `_CREATE_RUN_LINEAGE_TABLE_SQL` 추가. `_initialize_db` 가 4 테이블 모두 create. |
| `core/observability/agent_runtime.py` (NEW) | `record_subagent_completed(task_id, tokens, cost, error)` writer + `get_agent_state(task_id)` reader. |
| `core/wiring/bootstrap.py` | SUBAGENT_COMPLETED hook handler 등록 (`record_subagent_completed` 호출). |
| `core/agent/loop/agent_loop.py:_persist_session_id` | PR-V 의 file-based session.json 을 SQLite `agent_runtime_state.session_id` 로 migrate. session.json 1-release grace 후 삭제. |
| Migration | sessions.db 의 PRAGMA table_info 가 agent_runtime_state / run_lineage 부재 감지 시 자동 create (기존 layout_migrator 패턴). |
| 테스트 | `tests/core/memory/test_agent_runtime_integration.py` (NEW) — Option A 의 통합 invariant pin. |

---

## 7. 결정

| 옵션 | scope | LOC | 마이그레이션 위험 | 채택? |
|---|---|---|---|---|
| **A (sessions.db 안 통합)** | 위 §6 | ~150 | 낮음 (기존 migrator 재사용) | **✅ 선택** |
| B (runtime.db 별도) | 원안 | ~180 | 중간 | 거부 |
| C (runtime.db master, 4-layer paperclip parity) | over-engineered | ~400+ | 높음 | 거부 (multi-tenant 산물) |

**확정**: Option A — sessions.db 안에 `agent_runtime_state` + `run_lineage` 추가.

## 8. General agentic loop 적용성 검토

PR-COMM-3 schema 가 seed-generation 전용인지 일반 AgenticLoop 도 cover 하는지 grounding (`2026-05-24` 추가 검토):

**AgenticLoop 호출 경로 3 entry**:
- `core/cli/bootstrap.py:206` — REPL / CLI
- `core/server/supervised/services.py:189` — gateway / serve (Slack/Discord/Telegram)
- `core/agent/worker.py:326` — sub-agent subprocess (seed-gen path)

**hook fire pattern**:
- 모든 3 path 가 SESSION_STARTED/ENDED fire (`core/agent/loop/_lifecycle.py:282`, `agent_loop.py:652`) — payload `{model, provider, session_id, termination_reason, rounds, error}` 통일
- sub-agent dispatch layer (`core/agent/sub_agent.py:345,404,407`) 만 SUBAGENT_STARTED/COMPLETED/FAILED 추가 fire

**결론**:
- `agent_runtime_state` — **3 path 모두 적용 가능** (writer 만 SESSION_ENDED + SUBAGENT_COMPLETED 양쪽에 등록)
- `run_lineage` — **seed-gen-only 의미** (parent_run_id / target_dim / gen_tag 가 cross-cycle retry 개념, 일반 session 은 chain 없음). 일반 path 는 0 row — 정상.

## 9. Schema 보강 — 2 차원 origin/component 분리

`agent_runtime_state` 에 2 컬럼 추가 — process 차원 (`agent_kind`) + GEODE subsystem 차원 (`component`):

```sql
CREATE TABLE IF NOT EXISTS agent_runtime_state (
    -- Identity
    agent_id                  TEXT PRIMARY KEY,
    agent_kind                TEXT NOT NULL DEFAULT 'subagent',   -- process origin: 'subagent' | 'repl' | 'gateway' | 'scheduler'
    component                 TEXT NOT NULL DEFAULT 'agentic_loop', -- GEODE subsystem (reuses RunTranscript.component SoT)

    -- Adapter + resumable session (paperclip parity)
    adapter_type              TEXT NOT NULL,                     -- 'claude-cli' | 'claude-payg' | 'openai-payg' | 'codex' | 'glm-payg'
    claude_cli_session_id     TEXT NOT NULL DEFAULT '',          -- empty when no resumable session

    -- Cross-cycle continuity (seed-gen only — empty for repl/gateway)
    last_run_id               TEXT NOT NULL DEFAULT '',          -- FK → run_lineage.run_id
    last_run_status           TEXT NOT NULL DEFAULT '',

    -- Cumulative quota / cost
    total_input_tokens        INTEGER NOT NULL DEFAULT 0,
    total_output_tokens       INTEGER NOT NULL DEFAULT 0,
    total_cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_cents          INTEGER NOT NULL DEFAULT 0,        -- round(usd * 100)

    -- Diagnostics
    last_error                TEXT NOT NULL DEFAULT '',

    -- Lifecycle
    created_at                REAL NOT NULL,
    updated_at                REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_kind
    ON agent_runtime_state (agent_kind, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_component
    ON agent_runtime_state (component, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_updated
    ON agent_runtime_state (updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_session
    ON agent_runtime_state (claude_cli_session_id)
    WHERE claude_cli_session_id != '';
```

### 9.1 `component` 용어 결정 근거

후보 6 검토 — `workflow_type` / `domain` / `surface` / `harness` / `runner` / `extension` — 모두 의미 좁거나 frontier 컨텍스트 와 충돌. **`component` 가 정답**:

- 이미 `RunTranscript.component` 의 SoT (drift 회피)
- 기존 사용 catalog 가 사용자 의도와 매치: `"seed-generation"` (cli.py:349), `"agentic_loop"` (agent_loop.py:1105), `"autoresearch"` (autoresearch/train.py:650)
- "workflow" 의 deterministic state-graph 함의 회피 — `"agentic_loop"` 도 한 component (loop runtime 자체가 GEODE subsystem)

### 9.2 `agent_kind` vs `component` 분리 의미

| 컬럼 | 차원 | 값 catalog | 사용 |
|---|---|---|---|
| `agent_kind` | **process origin** | `subagent` / `repl` / `gateway` / `scheduler` | "어디서 spawn 됐나" — quota throttling 시 origin 별 분리 |
| `component` | **GEODE subsystem** | `seed-generation` / `self-improving-loop` / `petri-audit` / `autoresearch` / `agentic_loop` / `serve` / `scheduler` | "무엇을 하고 있나" — domain 별 cumulative 분리 |

### 9.3 예시 row

| agent_id | agent_kind | component | adapter_type | 의미 |
|---|---|---|---|---|
| `gen-gen1-001-bd2e3854` | subagent | seed-generation | claude-cli | seed-gen 의 generator sub-agent |
| `critic-gen1-001-bd2e3854` | subagent | seed-generation | claude-cli | seed-gen 의 critic sub-agent |
| `s-7a06da37641d` | repl | agentic_loop | claude-cli | REPL 의 일반 AgenticLoop |
| `s-9275436cc397` | gateway | serve | claude-cli | Slack message handler |
| `mut-gen2-X-abc` | subagent | self-improving-loop | claude-cli | autoresearch generation mutator |
| `audit-jud-X` | subagent | petri-audit | claude-cli | Petri judge run |

### 9.4 Writer 흐름 — 양쪽 hook 등록

| hook | scope | writer call |
|---|---|---|
| `SESSION_ENDED` | 모든 AgenticLoop (REPL + gateway + sub-agent) | `record_agent_session_end({session_id, model, provider, ...})` — `component` 값은 `current_run_transcript().component` (fallback `"agentic_loop"`), `agent_kind` 는 호출 컨텍스트에서 추론 |
| `SUBAGENT_COMPLETED` | sub-agent dispatch layer only | `record_subagent_completed({task_id, ...})` — sub-agent 의 `last_run_id` linkage + cumulative |
| `LLM_CALL_ENDED` | 모든 LLM call | `accumulate_tokens_and_cost({session_id, input_tokens, output_tokens, cached_input_tokens, cost_usd})` — `agent_runtime_state.total_*_tokens` 누적 |

## 10. PR-COMM-3 의 implementation 변경 (Option A + §9 schema 채택)

| 파일 | 변경 |
|---|---|
| `core/memory/session_manager.py` | `_CREATE_AGENT_RUNTIME_STATE_TABLE_SQL` + `_CREATE_RUN_LINEAGE_TABLE_SQL` + 4 index 추가. `_initialize_db` 가 4 테이블 모두 create. 기존 handoff/verify column migration 패턴 재사용 (idempotent on 기존 DB). |
| `core/observability/agent_runtime.py` (NEW) | `AgentRuntimeState` + `RunLineage` dataclass. `record_agent_session_end()` / `record_subagent_completed()` / `accumulate_tokens_and_cost()` writer + `get_agent_runtime_state()` / `get_retry_chain()` / `get_root_run()` reader. |
| `core/wiring/bootstrap.py` | 3 hook handler 등록 — SESSION_ENDED + SUBAGENT_COMPLETED + LLM_CALL_ENDED (`accumulate_tokens_and_cost`). |
| `core/agent/loop/agent_loop.py:_persist_session_id` | PR-V 의 file-based `session.json` 을 SQLite `agent_runtime_state.claude_cli_session_id` 로 migrate. session.json 1-release grace 후 삭제. |
| `tests/core/memory/test_agent_runtime_integration.py` (NEW) | I1 schema 정합 / I2 양쪽 hook writer / I3 component/agent_kind 정확성 / I4 cumulative 누적 / I5 cross-cycle run_lineage chain / I6 PR-V session.json 마이그레이션 호환성. |

## 11. Status

| Item | 상태 |
|---|---|
| Spec doc (이 파일) | DONE |
| GAP audit (§1 sessions.db schema) | DONE |
| Hermes Phase context (§3) | DONE |
| 통합 옵션 3개 (§4) | DONE |
| 추천 + 근거 (§5) | DONE — Option A |
| Operator 결정 (§7) | **DONE — Option A 확정** |
| General AgenticLoop 적용성 (§8) | DONE — agent_runtime_state 모든 path, run_lineage seed-gen-only |
| Schema 보강 — component + agent_kind (§9) | DONE |
| Implementation (§10) | PENDING — 작업 착수 |
