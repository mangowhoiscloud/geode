# PR-COMM-1 — HookEvent → ActivityRow schema + union channel (S2 scope)

> **작성**: 2026-05-24
> **목적**: 74 HookEvent 의 payload 를 paperclip activity_log + openclaw discriminatedUnion 패턴으로 정렬. HookSystem.trigger 호출이 active RunTranscript 에 자동 mirror — unified timeline 의 sub-agent dialogue 외 카테고리도 한 SoT 에서 가시화.
> **검증**: ruff/format/mypy/lint-imports/pytest + Codex MCP review.
> **SoT**: 이 문서. drift 시 코드/문서 동시 갱신.

---

## 0. 문제 진술 + frontier grounding

`docs/plans/2026-05-24-transcript-standardization-and-claude-resume.md` (PR1) 가 SessionTranscript record_user_message/assistant_message/tool_call/tool_result 4 event 만 RunTranscript 에 mirror. 나머지 70 HookEvent (phase / verification / cost / cognitive / auto-trigger 등) 는 여전히 in-proc HookSystem callback 으로 분산. 한 cycle 의 timeline 을 보려면 transcript.jsonl + hook handler 별 sink 를 join 필요.

**frontier 5 시스템 의 event schema 패턴**:

| 시스템 | 패턴 | 위치 | 정확성 |
|---|---|---|---|
| paperclip | `as const` tuple + `PluginEvent<TPayload>` envelope | `packages/shared/src/constants.ts:1029`, `packages/plugins/sdk/src/types.ts:180` | 중 (envelope strong, payload generic) |
| openclaw | **zod `discriminatedUnion` on `type`** | `extensions/voice-call/src/types.ts:90` | **강 (runtime validation 자동)** |
| claude-code-ref | thin enum + `dict[str, Any]` | `src/hooks/lifecycle.ts:30` | 낮음 (5 events만, validation 없음) |
| hermes-agent | callback factory + signature contract | `acp_adapter/events.py` | 낮음 |
| GEODE (pre-PR-COMM-1) | 74 enum + `dict[str, Any]` | `core/hooks/system.py:30` | 낮음 |

**채택**: pydantic discriminatedUnion (openclaw 직접 parity + GEODE 이미 pydantic 2.13.4 + 17 site 사용 중).

---

## 1. 74 events → 11 groups (공통 payload 패턴)

| Group | events 수 | 공통 키 | base class |
|---|---|---|---|
| A. Lifecycle started | 9 | `identifier` | `LifecycleStartedRow` |
| B. Lifecycle completed | 13 | `duration_ms` + `success` | `LifecycleCompletedRow` |
| C. Lifecycle failed | 9 | `duration_ms` + `error_type` + `message` | `LifecycleFailedRow` |
| D. Retry | 1 | `attempt` + `reason` | `LifecycleRetriedRow` |
| E. Cognitive step | 6 | `step_name` + `step_context` | `CognitiveStepRow` |
| F. Auto-trigger | 5 | `trigger_id` + `outcome` | `AutoTriggerRow` |
| G. State change | 5 | `previous` + `current` | `StateChangeRow` |
| H. Cost/budget | 2 | `amount_usd` + `threshold_usd` | `CostBudgetRow` |
| I. Memory mutation | 4 | `entity_id` + `mutation_kind` | `MemoryMutationRow` |
| J. MCP server | 2 | `server_name` + `status` | `McpServerRow` |
| K. Generic single-fire | 18 | `details: dict[str, Any]` | `GenericActivityRow` |

**합계**: 74 ✓ (각 event 가 정확히 1 group).

### 1.1 group → event 명시 매핑 (S2 typing 범위)

**A — Lifecycle started (9, typed in S2)**:
PIPELINE_STARTED / NODE_BOOTSTRAP / NODE_ENTERED / SESSION_STARTED / SUBAGENT_STARTED / LLM_CALL_STARTED / TOOL_EXEC_STARTED / HANDOFF_TRIGGERED / TOOL_RECOVERY_ATTEMPTED

**B — Lifecycle completed (13, typed in S2)**:
PIPELINE_ENDED / NODE_EXITED / SESSION_ENDED / SUBAGENT_COMPLETED / LLM_CALL_ENDED / TOOL_EXEC_ENDED / HANDOFF_COMPLETED / TOOL_RECOVERY_SUCCEEDED / TURN_COMPLETED / TURN_VERIFY_PASSED / ANALYST_COMPLETED / EVALUATOR_COMPLETED / SCORING_COMPLETED

**C — Lifecycle failed (9, typed in S2)**:
PIPELINE_ERROR / PIPELINE_TIMEOUT / NODE_ERROR / SUBAGENT_FAILED / LLM_CALL_FAILED / TOOL_EXEC_FAILED / TOOL_RECOVERY_FAILED / HANDOFF_FAILED / TURN_VERIFY_FAILED

**D — Retry (1, typed in S2)**: LLM_CALL_RETRIED

**S1 base classes (10) + generic (1)** — group E~K 도 base/mixin 정의는 들어가지만 concrete classes 는 후속 PR (점진).

---

## 2. 3-tier class hierarchy

### 2.1 Tier 1 — paperclip-style envelope

```python
# core/observability/activity.py
class ActivityRowBase(BaseModel):
    """paperclip PluginEvent envelope 등가 + GEODE run-level metadata.

    Every HookSystem.trigger() call produces exactly one of the 74
    concrete subclasses (when typed) or GenericActivityRow (fall-through).
    The pipeline transcript at <run_dir>/transcript.jsonl now carries
    a row for every hook event, not just the 4 SessionTranscript mirrors.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    ts: float
    run_id: str
    actor_type: Literal["orchestrator", "agent", "system", "plugin"]
    actor_id: str  # "pipeline" | sub-agent task_id | hook handler name | etc.
    action: str  # discriminator — dotted notation per paperclip
    entity_type: str
    entity_id: str
    task_id: str | None = None  # sub-agent worker task_id when applicable
    level: Literal["info", "warn", "error"] = "info"
```

### 2.2 Tier 2 — 11 base classes (mixins per group)

```python
class LifecycleStartedRow(ActivityRowBase):
    details: LifecycleStartedDetails
class LifecycleStartedDetails(BaseModel):
    identifier: str  # task_id / session_id / call_id / pipeline_id

class LifecycleCompletedRow(ActivityRowBase):
    details: LifecycleCompletedDetails
class LifecycleCompletedDetails(BaseModel):
    duration_ms: float
    success: bool = True

class LifecycleFailedRow(ActivityRowBase):
    details: LifecycleFailedDetails
class LifecycleFailedDetails(BaseModel):
    duration_ms: float | None = None
    error_type: str
    message: str

class LifecycleRetriedRow(ActivityRowBase):
    details: LifecycleRetriedDetails
class LifecycleRetriedDetails(BaseModel):
    attempt: int
    reason: str

# ... E~K group base classes (defined but only used by GenericActivityRow in S2) ...

class GenericActivityRow(ActivityRowBase):
    details: dict[str, Any] = Field(default_factory=dict)
```

### 2.3 Tier 3 — 31 concrete lifecycle classes (S2 scope)

```python
class PipelineStartedRow(LifecycleStartedRow):
    action: Literal["pipeline.started"] = "pipeline.started"
    entity_type: Literal["pipeline"] = "pipeline"

class NodeBootstrapRow(LifecycleStartedRow):
    action: Literal["node.bootstrap"] = "node.bootstrap"
    entity_type: Literal["node"] = "node"

class NodeEnteredRow(LifecycleStartedRow):
    action: Literal["node.entered"] = "node.entered"
    entity_type: Literal["node"] = "node"

class SessionStartedRow(LifecycleStartedRow):
    action: Literal["session.started"] = "session.started"
    entity_type: Literal["session"] = "session"

class SubAgentStartedRow(LifecycleStartedRow):
    action: Literal["subagent.started"] = "subagent.started"
    entity_type: Literal["task"] = "task"

# ... 27 more lifecycle concrete classes (B + C + D groups) ...

ActivityRow = Annotated[
    Union[
        PipelineStartedRow, NodeBootstrapRow, ...,  # 31 concrete
        GenericActivityRow,  # 43 non-lifecycle fall-through
    ],
    Field(discriminator="action"),
]
```

---

## 3. HookEvent → ActivityRow mapping registry

```python
# core/observability/activity_registry.py
HOOK_EVENT_TO_ROW_BUILDER: dict[HookEvent, Callable[[dict[str, Any]], ActivityRowBase]] = {
    HookEvent.PIPELINE_STARTED: _build_pipeline_started,
    HookEvent.PIPELINE_ENDED: _build_pipeline_ended,
    # ... 31 lifecycle ...
    # nothing for K-group events — bridge falls back to GenericActivityRow
}

def map_hook_to_activity(
    event: HookEvent,
    data: dict[str, Any],
    run_id: str,
) -> ActivityRowBase:
    """Convert a HookEvent + data dict into a typed ActivityRow.

    Lifecycle events (31) get concrete subclass with full validation;
    rest fall through to GenericActivityRow. Pre-PR-COMM-1 the data
    payload was never validated — typed lifecycle subclasses surface
    payload bugs at dispatch time."""
    builder = HOOK_EVENT_TO_ROW_BUILDER.get(event)
    if builder is None:
        return GenericActivityRow(
            ts=time.time(),
            run_id=run_id,
            actor_type=_infer_actor_type(event),
            actor_id=str(data.get("session_id", "system")),
            action=f"{_infer_dotted_action(event)}",
            entity_type="system",
            entity_id=event.value,
            details=data,
        )
    return builder(data, run_id=run_id)
```

---

## 4. Union channel wiring

```python
# core/hooks/system.py (HookSystem.trigger 마지막)
def trigger(self, event: HookEvent, data: dict[str, Any] | None = None) -> list[HookResult]:
    results = self._dispatch(event, data or {})
    self._mirror_to_active_transcript(event, data or {})  # ← NEW
    return results

def _mirror_to_active_transcript(self, event: HookEvent, data: dict[str, Any]) -> None:
    """Mirror this hook trigger as an activity row into active RunTranscript."""
    from core.self_improving_loop.run_transcript import current_run_transcript
    from core.observability.activity_registry import map_hook_to_activity

    run_transcript = current_run_transcript()
    if run_transcript is None:
        return
    try:
        row = map_hook_to_activity(event, data, run_id=run_transcript.session_id)
        run_transcript.append(
            event=event.value,
            actor_type=row.actor_type,
            actor_id=row.actor_id,
            action=row.action,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            task_id=row.task_id,
            level=row.level,
            payload=row.details.model_dump() if hasattr(row.details, "model_dump") else row.details,
        )
    except ValidationError:
        log.warning("HookEvent %s payload failed validation; emitting generic row", event)
        # Fall-through: still emit so the row is captured in the timeline.
        ...
```

---

## 5. 검증

### 5.1 Quality gates
- ruff / format / mypy (pydantic.mypy plugin) / lint-imports / pytest

### 5.2 신규 테스트
- `tests/core/observability/test_activity_schema.py`:
  - I1: 11 base classes 정의 + Tier 1 envelope 필드 검증
  - I2: 31 lifecycle concrete 의 action literal 정합 + entity_type literal 정합
  - I3: ActivityRow discriminated union 의 model_validate (PipelineStartedRow 입력 → 정확한 subclass)
  - I4: GenericActivityRow fall-through (typed lifecycle 외 event 가 generic 으로 라우팅)
  - I5: 74 HookEvent 전체가 매핑 cover (HOOK_EVENT_TO_ROW_BUILDER 누락 → generic, 매핑 있으면 concrete)
- `tests/core/hooks/test_activity_mirror.py`:
  - M1: HookSystem.trigger 가 active RunTranscript 에 한 row append
  - M2: 활성 RunTranscript 없으면 no-op
  - M3: payload validation fail 시 generic row 로 fall-through (silent dispatch fail X)

### 5.3 Codex MCP review
- target files: `core/observability/activity.py`, `core/observability/activity_registry.py`, `core/hooks/system.py`, `tests/core/observability/test_activity_schema.py`, `tests/core/hooks/test_activity_mirror.py`
- review focus: 74 events 전체 cover (누락 검출), pydantic discriminator 정합 (action literal 충돌), backwards-compat (기존 hook handler 들 변경 영향 X), `current_run_transcript() == None` 시 silent no-op (REPL / gateway 영향 X).

---

## 6. Anti-deception 체크리스트

- [ ] 11 base classes + 31 lifecycle concrete + 1 generic = 43 ActivityRow classes 가 union 에 모두 등록
- [ ] HOOK_EVENT_TO_ROW_BUILDER 의 키 31 + generic fall-through 43 = 74 (전체 cover)
- [ ] Pydantic ValidationError 가 trigger 자체를 break 하지 않음 (silent no-op + warning log)
- [ ] 기존 SessionTranscript 의 4 mirror (PR-U) 는 그대로 동작
- [ ] backwards-compat: `journal.append(event, payload=...)` 기존 patterns 회귀 없음

---

## 7. Status

| Item | 상태 |
|---|---|
| Spec doc | DONE (이 파일) |
| Tier 1 + Tier 2 (11 base) | PENDING |
| Tier 3 (31 lifecycle concrete) | PENDING |
| Registry (HOOK_EVENT_TO_ROW_BUILDER) | PENDING |
| Union channel wiring | PENDING |
| Tests (I1-I5 + M1-M3) | PENDING |
| Codex MCP review | PENDING |
| CHANGELOG | PENDING |

---

## 8. Follow-up PRs (잔여 PR 영향 — 우선순위 boost 이유)

- PR2 (V) — paperclip `--resume` + sessionId. `agent_runtime_state.sessionId` 등가물 추가. **본 PR 의 activity row 에 `agent_session_id` 필드 추가** 시 PR2 의 session.json 적재 흐름과 자연 연결.
- PR-COMM-2 — `HookSystem.register` wildcard prefix. **본 PR 의 dotted action namespace** (`pipeline.*` / `subagent.*` / `llm.*`) 가 wildcard 의 prefix 가 됨. 본 PR 의 dotted naming 이 PR-COMM-2 의 전제.
- PR-COMM-3 — SQLite `agent_runtime_state` + `run_lineage`. **본 PR 의 ActivityRow 가 직접 row 형식**이라 SQLite 마이그레이션 시 to_sql() 한 줄로 변환 가능.
- PR-COMM-4 — `seq` monotonic + liveness. **본 PR 의 RunTranscript append 가 단일 진입점**이라 seq 추가가 한 곳만 변경.

→ COMM-1 가 다른 4 PR 의 schema/naming 전제. **우선 처리 합리적**.
