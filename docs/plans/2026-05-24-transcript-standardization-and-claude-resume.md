# Transcript 표준화 + claude-cli `--resume` 정렬 — 2-PR sprint plan

> **작성**: 2026-05-24
> **목적**: GEODE 의 observability + adapter 계층을 paperclip 의 frontier 패턴에 정렬.
> **2 PR** — PR1 (Q.5 + U): 식별자 정렬 + paperclip-style timeline. PR2 (V): adapter `--resume` + per-agent sessionId.
> **검증**: 각 PR 마다 ruff/format/mypy/lint-imports/pytest + Codex MCP cross-LLM review.
> **SoT**: 이 문서. 구현 중 모든 변경은 이 문서의 "스펙" 섹션과 1:1 매핑. drift 발견 시 코드/문서 동시 갱신.

---

## 0. 문제 진술

`2026-05-24` seed-generation 스모크 + post-PR Q audit 에서 발견한 두 GAP:

**GAP-A (식별자 단절)**: PR Q (`#1583`) 가 sub-agent 산출물을 `sub_agents/<task_id>/` 안에 묶는다고 했지만 실제로는 `dialogue.jsonl` 만 별도 `sub_agents/s-<uuid>/` 로 빠짐. AgenticLoop 가 자체 `f"s-{uuid.uuid4().hex[:12]}"` 생성, `WorkerRequest.task_id` 를 안 받음. operator 가 `task_id` 만 알면 `dialogue.jsonl` 못 찾음.

**GAP-B (`--resume` 부재)**: paperclip 은 `claude --print --resume <sessionId>` 로 per-agent session continuity → prompt cache hit → 매 호출 5-10K 토큰 절약. GEODE 의 `ClaudeCliAdapter` 는 매 호출 fresh session, system prompt 풀 재전송. 단일 OAuth 의 5-hour quota 가 더 빨리 고갈.

두 GAP 모두 paperclip 의 frontier 패턴과 비교했을 때 명확함. 본 sprint 가 정렬.

---

## 1. paperclip 대조표 (정렬 anchor)

### 1.1 paperclip 의 식별자 흐름

```
agents (PK: agent.id)
  ↓
agent_runtime_state (1-to-1 with agents)
  ├── agentId          (PK)
  ├── adapterType
  ├── sessionId        ← claude --resume 의 인자
  ├── lastRunId
  └── ...
  ↓
heartbeat_runs (N rows per agent)
  ├── agentId
  ├── sessionIdBefore  ← run 진입 직전 agent_runtime_state.sessionId
  ├── sessionIdAfter   ← run 종료 후 claude 가 emit 한 새 session_id
  └── ...
  ↓
activity_log (N rows per heartbeat_run)
  ├── runId            (FK → heartbeat_runs)
  ├── actorType        "agent" | "user" | "system" | "plugin"
  ├── actorId
  ├── action           "issue.comment.created" (dotted)
  ├── entityType       "issue"
  ├── entityId         ─────────┐
  ├── agentId          (FK)     │
  ├── details          (jsonb)  │
  └── ...                       │
                                │ FK 한 줄로 본문 join
                                ▼
                          issue_comments
                            ├── issueId   (= activity_log.entityId)
                            ├── body
                            └── ...
```

**핵심 invariant**:
1. `agent.id` 가 모든 layer 의 anchor (3-tier 모두 한 식별자)
2. `runtime.sessionId` 가 adapter contract 의 first-class state (--resume 의 인자)
3. `activity_log.entityId == issue_comments.issueId` (timeline → 본문 navigation 결정적)

### 1.2 GEODE 의 대응 매핑

| paperclip | GEODE 대응 (post-sprint) |
|---|---|
| `agent.id` | sub-agent `task_id` (e.g. `"gen-gen1-001-bd2e3854"`) |
| `runtime.sessionId` | claude-cli stream-json 의 `system.init.session_id` (persisted in `sub_agents/<task_id>/session.json`) |
| `heartbeat_runs.id` | seed-generation `run_id` (e.g. `"gen1-redundant_tool_invocation"`) |
| `heartbeat_runs.sessionIdBefore/After` | `session.json` 의 turn 별 갱신 |
| `activity_log` row | `transcript.jsonl` 의 한 줄 (paperclip-style schema) |
| `activity_log.entityId` | `details.task_id` (= sub-agent worker task_id) |
| `issue_comments.body` | `sub_agents/<task_id>/dialogue.jsonl` (Anthropic-style turn-by-turn) |

---

## 2. PR1 — 식별자 정렬 + paperclip-style timeline mirror

**브랜치**: `feature/transcript-unified-timeline`
**현재 상태**: worktree 할당 완료, 본 문서 적재 중.

### 2.1 변경 스펙 (5 file change)

#### F1. `core/agent/loop/agent_loop.py` — AgenticLoop session_id 인자
```python
def __init__(
    self,
    ...,
    session_id: str = "",  # ← NEW (PR-Q.5)
    ...,
) -> None:
    ...
    # PR-Q.5: caller (worker.py) 가 WorkerRequest.task_id 를 명시 전달.
    # 비어있으면 자체 ephemeral uuid (legacy, REPL/gateway 경로).
    if session_id:
        self._session_id = session_id
    else:
        self._session_id = f"s-{_uuid.uuid4().hex[:12]}"
    self._transcript = SessionTranscript(self._session_id)
```

#### F2. `core/agent/worker.py` — task_id 를 AgenticLoop 에 전달
```python
loop = AgenticLoop(
    conversation,
    executor,
    session_id=request.task_id,  # ← NEW (PR-Q.5)
    ...,
)
```

#### F3. `core/self_improving_loop/run_transcript.py` — paperclip-style schema 확장
```python
class RunTranscript:
    def append(
        self,
        event: str,
        *,
        level: str = "info",
        payload: dict[str, Any] | None = None,
        ts: float | None = None,
        # PR-U: paperclip activity_log parity (모두 optional, backwards-compat).
        actor_type: str = "orchestrator",  # "orchestrator" | "agent" | "system"
        actor_id: str = "pipeline",        # e.g. "pipeline" | "generator" | "critic"
        action: str | None = None,         # dotted notation; auto-infer = f"pipeline.{event}"
        entity_type: str | None = None,    # "phase" | "task" | "candidate" | "pipeline"
        entity_id: str | None = None,
        task_id: str | None = None,        # sub-agent worker task_id (when actor_type=="agent")
    ) -> None:
        ...
```

- `event` + `payload` 는 기존 caller (cli.py 의 `journal.append("phase_started", payload={...})`) 호환.
- 자동 추론: `action` 미지정 시 `f"pipeline.{event}"`, `actor_type=="orchestrator"` 기본.

#### F4. `core/observability/transcript.py` — SessionTranscript mirror
```python
class SessionTranscript:
    def record_user_message(self, text: str) -> None:
        truncated = _truncate(text, MAX_TEXT_CHARS)
        self._append({"event": "user_message", "text": truncated})
        self._mirror_to_run_transcript(
            action="agent.user_message",
            entity_type="task",
            entity_id=self._session_id,
            details={"text": truncated},
        )

    def record_assistant_message(self, text: str) -> None: ...  # 같은 패턴
    def record_tool_call(self, tool, tool_input) -> None: ...   # 같은 패턴
    def record_tool_result(self, tool, status, summary) -> None: ...

    def _mirror_to_run_transcript(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: str,
        details: dict[str, Any],
    ) -> None:
        """Mirror this SessionTranscript event into the active RunTranscript
        as a paperclip activity_log row. No-op when no RunTranscript is bound
        (REPL / gateway / tests). The full body stays in dialogue.jsonl;
        details carry the truncated preview + task_id for navigation."""
        from core.self_improving_loop.run_transcript import current_run_transcript

        run_transcript = current_run_transcript()
        if run_transcript is None:
            return
        # actor_type="agent" for SessionTranscript-originated events.
        # actor_id == session_id == task_id (post-PR-Q.5 identifier alignment).
        run_transcript.append(
            event=action.split(".", 1)[1] if "." in action else action,
            actor_type="agent",
            actor_id=self._session_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            task_id=self._session_id,
            payload=details,
        )
```

#### F5. `plugins/seed_generation/cli.py` — orchestrator journal.append 사이트 enrich (optional, scope-creep 가능)

```python
journal.append(
    "phase_started",
    actor_type="orchestrator",
    actor_id="pipeline",
    action="pipeline.phase_started",
    entity_type="phase",
    entity_id=role_name,
    payload={"role": role_name},
)
```

→ 기존 caller 가 명시 안 해도 backwards-compat 으로 동작 (RunTranscript 가 자동 추론). 본 PR 의 minimum scope 는 F1–F4 만, F5 는 nice-to-have.

### 2.2 식별자 invariant (테스트로 pin)

| Invariant | 검증 위치 |
|---|---|
| **I1 (단일 anchor)**: `WorkerRequest.task_id == IsolationConfig.session_id == AgenticLoop.session_id == SessionTranscript._session_id` | `tests/core/agent/loop/test_agent_loop_session_id.py` — AgenticLoop(session_id="...") 가 그 값 사용 + SessionTranscript file_path 가 그 식별자 디렉터리 |
| **I2 (단일 디렉터리)**: result.json + stderr.log + dialogue.jsonl 이 모두 `<run_dir>/sub_agents/<task_id>/` 안 | `tests/core/observability/test_sub_agent_dir_unity.py` — 세 writer 가 같은 폴더 적재 검증 |
| **I3 (navigation)**: pipeline transcript 의 `details.task_id` 가 디스크의 `sub_agents/<task_id>/dialogue.jsonl` 와 결정적 매핑 | `tests/core/observability/test_unified_timeline.py` — mirror 된 row 의 task_id 로 dialogue 파일 회수 가능 |
| **I4 (backwards-compat)**: 기존 `journal.append("phase_started", payload={...})` caller 가 변경 없이 동작 | 기존 `tests/core/self_improving_loop/test_run_transcript.py` 회귀 없음 |

### 2.3 폴더트리 (전/후)

**Before (post-PR Q, 깨진 상태)**:
```
state/seed-generation/gen1-X/
├── transcript.jsonl
└── sub_agents/
    ├── gen-gen1-001-bd2e3854/
    │   ├── result.json
    │   └── stderr.log         (dialogue 없음 ❌)
    └── s-7a06da37641d/        ← 별개 식별자
        └── dialogue.jsonl
```

**After (PR1 merge)**:
```
state/seed-generation/gen1-X/
├── transcript.jsonl           ← paperclip-style timeline (orchestrator + agent events)
└── sub_agents/
    ├── gen-gen1-001-bd2e3854/    ← 단일 task_id anchor
    │   ├── result.json     ✅
    │   ├── stderr.log      ✅
    │   └── dialogue.jsonl  ✅ (이제 같은 폴더)
    └── critic-gen1-001-bd2e3854/
        ├── result.json
        ├── stderr.log
        └── dialogue.jsonl
```

### 2.4 transcript.jsonl row 샘플 (전/후)

**Before (phase events 만)**:
```jsonl
{"ts":1779596971.12, "session_id":"gen1-X", "gen_tag":"gen1", "component":"seed-generation", "level":"info", "event":"phase_started", "payload":{"role":"generator"}}
{"ts":1779597344.27, "session_id":"gen1-X", ...,                                                                "event":"phase_finished", "payload":{"role":"generator","duration_ms":373149}}
```

**After (phase + agent events 통합, paperclip-style)**:
```jsonl
{"ts":1779596971.12, "session_id":"gen1-X", "actor_type":"orchestrator", "actor_id":"pipeline",  "action":"pipeline.phase_started",   "entity_type":"phase", "entity_id":"generator",        "event":"phase_started",   "payload":{"role":"generator"}}
{"ts":1779596975.40, "session_id":"gen1-X", "actor_type":"agent",        "actor_id":"gen-gen1-001-bd2e3854", "action":"agent.user_message", "entity_type":"task",  "entity_id":"gen-gen1-001-bd2e3854", "task_id":"gen-gen1-001-bd2e3854", "event":"user_message",    "payload":{"text":"Generate ONE Petri seed scenario for redundant_tool_invocation. ...(500자)"}}
{"ts":1779597089.21, "session_id":"gen1-X", "actor_type":"agent",        "actor_id":"gen-gen1-001-bd2e3854", "action":"agent.assistant_message", "entity_type":"task", "entity_id":"gen-gen1-001-bd2e3854", "task_id":"gen-gen1-001-bd2e3854", "event":"assistant_message","payload":{"text":"# Overlapping log windows...(500자)"}}
{"ts":1779597344.27, "session_id":"gen1-X", "actor_type":"orchestrator", "actor_id":"pipeline",  "action":"pipeline.phase_finished",  "entity_type":"phase", "entity_id":"generator",        "event":"phase_finished",  "payload":{"role":"generator","duration_ms":373149}}
```

### 2.5 검증 절차

1. ruff check / ruff format --check / mypy / lint-imports (CI gate parity).
2. 신규 테스트: `test_agent_loop_session_id.py` (I1), `test_sub_agent_dir_unity.py` (I2), `test_unified_timeline.py` (I3).
3. 기존 회귀: `tests/core/observability/` + `tests/core/agent/` + `tests/core/self_improving_loop/` 모두 통과.
4. Codex MCP 검증: 본 문서 + diff 를 review, F1–F4 omission 여부 / I1–I4 invariant test coverage / backwards-compat 보존 확인.

---

## 3. PR2 — `--resume` + per-agent sessionId

**브랜치**: `feature/claude-cli-resume` (PR1 머지 후 별도 worktree 할당).
**전제**: PR1 머지 = task_id 가 단일 anchor 확정 → `sub_agents/<task_id>/session.json` 위치 안정.

### 3.1 변경 스펙 (4 file change)

#### V.1 — `core/llm/adapters/base.py` — contract 확장
```python
@dataclass
class AdapterCallRequest:
    ...existing fields...
    # PR-V (paperclip parity) — per-agent persistent claude-cli session.
    # Non-empty value triggers `--resume <session_id>` which makes
    # claude-cli reuse the cached system prompt + prior conversation
    # context. Empty = fresh session (legacy behaviour).
    resume_session_id: str = ""

@dataclass
class AdapterCallResult:
    ...existing fields...
    # PR-V — sessionId emitted by claude-cli's `system.init` event.
    # Caller persists this + threads back as the next turn's
    # `resume_session_id`. Mirrors paperclip's
    # heartbeat_runs.sessionIdBefore/After capture.
    session_id: str = ""
```

#### V.2 — `plugins/petri_audit/claude_cli_provider.py` — argv builder + session_id parser
```python
def build_claude_cli_argv(
    *,
    binary: str,
    model_name: str,
    max_turns: int = 1,
    resume_session_id: str | None = None,  # ← NEW
    mcp_config_path: str | None = None,
    allowed_tools: list[str] | None = None,
    disable_builtin_tools: bool = False,
    extra_args: Iterable[str] | None = None,
) -> list[str]:
    argv = [binary, "--print", "-", "--output-format", "stream-json", "--verbose"]
    if resume_session_id:
        argv += ["--resume", resume_session_id]  # ← paperclip parity (execute.ts:680)
    argv += ["--model", model_name, "--max-turns", str(max_turns)]
    ...

def extract_session_id_from_events(events: list[StreamJsonEvent]) -> str:
    """Pull session_id from the `system.init` event. Mirrors paperclip
    parse.ts:30 — `system.init` is the first event claude-cli emits,
    carrying the freshly-allocated session_id for this turn."""
    for event in events:
        if event.type == "system":
            init_subtype = event.payload.get("subtype", "")
            if init_subtype == "init":
                sid = event.payload.get("session_id", "")
                if isinstance(sid, str) and sid:
                    return sid
    return ""
```

#### V.3 — `core/llm/adapters/claude_cli.py` — wire + persist
```python
async def acomplete(self, req: AdapterCallRequest) -> AdapterCallResult:
    ...
    argv = build_claude_cli_argv(
        binary=binary,
        model_name=req.model,
        max_turns=1,
        resume_session_id=req.resume_session_id or None,  # ← NEW
    )
    ...
    emitted_session_id = extract_session_id_from_events(stream_events)
    return AdapterCallResult(
        text=assistant_text,
        usage=UsageSummary(),
        stop_reason=stop_reason,
        session_id=emitted_session_id,  # ← NEW
    )
```

#### V.4 — `core/agent/loop/agent_loop.py` — session.json 적재 + read-back

새 helper `_resolve_session_continuity(task_id, run_dir) -> str | None`:
- `<run_dir>/sub_agents/<task_id>/session.json` 읽음 → `claude_cli_session_id` 회수 → `req.resume_session_id` 로 set
- 호출 후 `result.session_id` 받으면 `session.json` 업데이트

```python
# In AgenticLoop._call_llm (or a new helper called from there)
session_continuity_path = resolve_sub_agent_path(self._session_id, "session.json")
prior_session_id = _read_prior_session_id(session_continuity_path) if session_continuity_path else None

req = build_adapter_request(
    ...,
    resume_session_id=prior_session_id or "",  # ← NEW
)
result = await self._new_adapter.acomplete(req)
if session_continuity_path and result.session_id:
    _persist_session_id(session_continuity_path, result.session_id, turn_count=...)
```

### 3.2 폴더트리 (PR2 후)
```
state/seed-generation/gen1-X/sub_agents/<task_id>/
├── result.json
├── stderr.log
├── dialogue.jsonl
└── session.json              ← NEW (paperclip agent_runtime_state 등가)
    {
      "claude_cli_session_id": "abc123...",
      "turn_count": 3,
      "last_updated_ts": 1779597089.21,
      "model": "claude-opus-4-7"
    }
```

### 3.3 효과 측정

| 지표 | Before (PR2 전) | After (PR2 후, 예상) |
|---|---|---|
| 같은 sub-agent 의 2nd turn input tokens | system prompt 풀 (5-10K) | cached (≤ 500 토큰 marker) |
| 5-hour quota 소진 속도 | baseline | 5-10x 완화 (system prompt cache hit) |
| cross-cycle continuity | 매 cycle 새 session | 같은 task_id 면 prior session 이어받음 |

### 3.4 검증 절차

1. 신규 테스트: `test_resume_session_id_threading.py` (V.1 contract field), `test_argv_resume_flag.py` (V.2 argv 정확성), `test_session_id_extraction.py` (V.2 parser), `test_adapter_resume_round_trip.py` (V.3 adapter), `test_session_json_persistence.py` (V.4 read/write).
2. 기존 회귀: `tests/core/llm/adapters/test_claude_cli_adapter.py` + `tests/plugins/petri_audit/test_claude_cli_transient_classifier.py` + `tests/plugins/petri_audit/test_claude_cli_provider.py` 모두 통과.
3. Codex MCP 검증: paperclip `execute.ts:678-770` + `parse.ts:30` 의 정확한 패턴 정렬 여부 + adapter contract 의 backwards-compat (기존 caller 가 `resume_session_id=""` 일 때 기존 동작 보존).

---

## 4. Sprint workflow + Codex 검증 체크리스트

각 PR 마다:

1. **Plan grounding**: 본 문서 의 해당 PR 섹션 다시 읽고 차이/모호점 식별. 발견 시 본 문서 먼저 갱신.
2. **Implement**: 스펙의 file change 항목과 1:1 매핑. 새 helper / 파일이 생기면 즉시 본 문서에 추가 (drift 방지).
3. **Self-test**: 로컬 ruff / format / mypy / lint-imports / pytest 모두 통과.
4. **Invariant pin**: I1–I4 (PR1) 또는 V.1–V.4 의 정확한 보존 테스트 작성.
5. **Codex MCP review** (`codex-mcp-verify` skill):
   - Plan diff cross-check: 본 문서 ↔ git diff. omission / 추가 변경 / stub 여부.
   - Frontier parity: paperclip 의 정확한 코드 위치 (execute.ts / activity_log.ts / parse.ts) 와 GEODE 의 구현이 식별자/contract 수준에서 일치.
   - Backwards-compat: 기존 caller 의 동작 보존 (`run_transcript.append("phase_started", payload={...})` 무변경).
   - Anti-deception: 본 문서의 verb/adjective (예: "paperclip-style", "single anchor", "navigation 결정적") 가 코드에서 grep-provable.
6. **PR push**: HEREDOC body 가 본 문서의 해당 섹션을 인용. CI 5/5 green 후 머지.
7. **Doc-sync**: PR 머지 후 본 문서의 "Status" 섹션 갱신 (PR# / 머지 ts / 차이가 있었으면 차이 적재).

### 4.1 Codex MCP 의 정확한 invocation pattern

```
mcp__codex__review(
    target_files=[
        "core/agent/loop/agent_loop.py",
        "core/agent/worker.py",
        "core/self_improving_loop/run_transcript.py",
        "core/observability/transcript.py",
    ],
    base_ref="develop",
    review_focus=(
        "본 PR 가 docs/plans/2026-05-24-transcript-standardization-and-claude-resume.md "
        "의 PR1 (Q.5 + U) 섹션 의 F1-F4 + I1-I4 invariant 와 정확히 정렬되었는지 검증. "
        "paperclip parse.ts:30 / activity_log.ts 패턴과의 일치도. backwards-compat 보존."
    ),
)
```

### 4.2 Anti-deception 체크리스트

- [ ] 본 문서의 모든 file change 항목이 git diff 에 존재
- [ ] 새 invariant test (I1–I4 또는 V.1–V.4) 가 진짜 검증 하는지 (`pass` 만 아님)
- [ ] backwards-compat 보존: 기존 `tests/core/self_improving_loop/test_run_transcript.py` 회귀 없음
- [ ] CHANGELOG 의 verb/adjective 가 코드 grep 으로 증명 가능
- [ ] `git check-ignore` 로 모든 새 파일 path 가 tracked

---

## 5. Status (live, PR 진척에 따라 갱신)

| PR | 브랜치 | 상태 | CI | PR# | 머지 ts |
|---|---|---|---|---|---|
| PR1 (Q.5 + U) | `feature/transcript-unified-timeline` | IN PROGRESS (이 worktree) | — | — | — |
| PR2 (V) | `feature/claude-cli-resume` | PLANNED (PR1 머지 후 worktree 할당) | — | — | — |

---

## 6. 참고 (frontier code grounding)

- `~/workspace/paperclip/packages/db/src/schema/activity_log.ts` — 12-field schema
- `~/workspace/paperclip/packages/db/src/schema/agent_runtime_state.ts` — sessionId persistence
- `~/workspace/paperclip/packages/db/src/schema/heartbeat_runs.ts` — sessionIdBefore/After
- `~/workspace/paperclip/packages/adapters/claude-local/src/server/execute.ts:678-770` — buildClaudeArgs + runAttempt (--resume + retry-on-unknown-session)
- `~/workspace/paperclip/packages/adapters/claude-local/src/server/parse.ts:17-55` — parseClaudeStreamJson (session_id extraction)
- `~/workspace/paperclip/server/src/services/heartbeat.ts:2555` — getRuntimeState
- `~/workspace/paperclip/server/src/services/heartbeat.ts:3490` — sessionIdBefore/After threading

GEODE 현재 핵심 파일:

- `core/agent/loop/agent_loop.py:225` — SessionTranscript 자체 uuid 생성 (식별자 단절 root cause)
- `core/agent/worker.py:340-360` — AgenticLoop call site (session_id 인자 누락)
- `core/llm/adapters/base.py:93` — AdapterCallRequest dataclass (resume 필드 없음)
- `core/llm/adapters/claude_cli.py:50-150` — ClaudeCliAdapter.acomplete (sessionId 무관)
- `plugins/petri_audit/claude_cli_provider.py:200-260` — build_claude_cli_argv (--resume 인자 없음)
- `core/observability/run_dir.py` — PR Q 의 ContextVar SoT (PR1 + PR2 의 path resolver 의존)
- `core/observability/transcript.py:163-200` — SessionTranscript.record_* (mirror 미구현)
- `core/self_improving_loop/run_transcript.py:103-126` — RunTranscript.append (schema 확장 필요)
