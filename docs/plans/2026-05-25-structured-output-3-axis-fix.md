# 2026-05-25 — Structured-output 3-axis fix + checkpointer audit

> Status: **Draft (사용자 승인 대기)**
> Framing: smoke 15/16 의 prose-vs-JSON regression 을 adapter 3 축 (PAYG / subscription / local-cli) 에서 모두 해소.
> 선행 관측: PR-HANDOFF-SCHEMAS 의 hard directive ("FINAL response must be ONLY the JSON object... Start with `{` end with `}`") 는 smoke 16 에서 이미 활성 상태였으나 LLM 이 무시 → **prompt-side directive 만으로는 부족** (empirical refutation).

## 1. Background — 관측된 실패 카탈로그

### 1.1 JSON-formatting 실패 (5 건)

| Smoke | Agent | 응답 형태 | Prompt 상태 |
|-------|-------|----------|-------------|
| 15 | pilot | prose (~500 토큰, 497s) | PR-HANDOFF-SCHEMAS 이전, soft "Return JSON" 지시만 |
| 15 | evolver (iter 1) | JSON 있음 (verdict ok) | 동일 |
| 16 | critic | prose ("**Critique summary:**..." 28s) | hard directive 없음 (critic 만 미적용) |
| 16 | pilot | prose ("I need to actually run..." 497s) | **hard directive 활성 — 무시됨** |
| 16 | meta_reviewer | prose ("Meta-review submitted...") | soft 지시만 |

**핵심:** smoke 16 pilot 의 prompt 는 이미 `"Your FINAL response must be ONLY the JSON object... Start with \`{\` and end with \`}\`"` 를 포함했고, HANDOFF CONTEXT JSON block 도 첨부됨. 그럼에도 LLM 이 prose 만 출력. **즉 prompt-only fix 는 무력하다는 empirical 증거.**

### 1.2 Non-JSON 실패 (1 건)

**smoke 16 evolver — TimeoutError at `core/agent/plan.py:721 decompose_async`** (122초). stderr.log 발췌:

```
File "/opt/homebrew/.../asyncio/streams.py", line 539, in _wait_for_data
    await self._waiter
asyncio.exceptions.CancelledError
...
File "/Users/mango/workspace/geode/core/agent/plan.py", line 721, in decompose_async
    response = await asyncio.wait_for(...)
File "/opt/homebrew/.../asyncio/timeouts.py", line 114, in __aexit__
    raise TimeoutError from exc_val
```

`result.json.summary = "Sub-agent failed: termination_reason=natural"` — orchestrator 의 라벨이 misleading. **실제 원인: AgenticLoop 의 plan-decompose 단계가 wall-time timeout** (claude-cli 가 정상 종료했지만 plan 내부 await 이 시간 초과). JSON 포맷과 무관.

## 2. 영속화 — 이전 제시한 4 옵션 (A/B/C/D)

이전 메시지에서 4 갈래 제안. md 영속화.

### Option A — sub_agent.py 의 `_last_balanced_json_object` fallback 강화

**현 상태:** PR-HANDOFF-SCHEMAS 가 이미 prose 안의 `{...}` 블록 추출 시도 (sub_agent.py).
**확장:** ```json``` fence 안의 JSON 도 우선 시도; 다중 candidate 블록 중 schema-required 필드 가장 많이 매치되는 것 선택; 부분 JSON 의 추가 복원 시도 (예: 마지막 `}` 보강).
**비용:** ~50 LOC. 효과 부분적 — LLM 이 JSON 어디에도 안 적은 경우 무력.

### Option B — Retry-on-parse-failure

**Idea:** 첫 응답이 parse 실패 시 같은 conversation 에 2번째 turn 추가: `"Your previous response was not valid JSON. Reply ONLY with the JSON object matching the schema. No prose, no markdown. Start with { end with }."`
**비용:** ~80 LOC + 추가 LLM call (per failure ~30-60s + 토큰). AgenticLoop 의 turn 관리 침습.
**효과 가설:** higher than (A) — model 이 자기 prose 를 보고 self-correction 가능.

### Option C — Anthropic tool_use 강제 (Anthropic-only)

**Idea:** `tools=[{"name": "submit_result", "input_schema": SCHEMA}]` + `tool_choice={"type": "tool", "name": "submit_result"}`. LLM 은 prose 대신 tool call 로 반드시 응답.
**Scope 제약:** Anthropic SDK 만 적용 가능. 사용자 directive 가 "Anthropic 한정 조치 자제" 였음 → **단독으론 부적합**, 단 3-axis 의 한 축 (PAYG Anthropic) 으로는 적용 가치.
**비용:** ~150 LOC (anthropic_payg.py + anthropic_oauth.py).

### Option D — Post-LLM JSON 변환 layer (별도 sonnet 호출)

**Idea:** 첫 응답이 parse 실패 시 별도 cheap-model (haiku 또는 mini) 에 prose 전체 + schema 전달 → "이 prose 를 schema 형식 JSON 으로 변환" 요청. 변환만 하는 single-purpose LLM 호출.
**비용:** ~100 LOC + 추가 LLM call (저렴). 추가 latency ~5s.
**효과 가설:** 가장 안전한 안전망 — original LLM 의 prose 가 logically 옳다면 변환 LLM 이 추출.

## 3. 3-axis adapter 구조 + 적용 방안

### 3.1 Adapter 인벤토리 (`core/llm/adapters/`)

| Adapter | Auth | Wire | Structured output 현재 |
|---------|------|------|-----------------------|
| `anthropic_payg.py` | API key | Anthropic Messages | **미구현** — `response_schema` plumbing 없음 |
| `anthropic_oauth.py` | OAuth (Claude.ai bucket) | Anthropic Messages | **미구현** |
| `claude_cli.py` | Claude Code session | subprocess | `--json-schema <inline>` (soft hint) |
| `openai_payg.py` | API key | Chat Completions | **미구현** — `response_format` plumbing 없음 |
| `codex_oauth.py` | OAuth (Codex bucket) | OpenAI Responses | **미구현** — `output_schema` plumbing 없음 |
| `codex_cli.py` | Codex CLI session | subprocess | `--output-schema <file>` (soft hint) |

### 3.2 SDK 별 구조화 출력 메커니즘 (ctx7 grounded)

**Anthropic SDK (PAYG + OAuth):**
- 최신 API: `client.messages.parse(messages=..., output_format=PydanticModel)` — Pydantic 자동 hydration. SDK 가 schema 를 force-mode `tools[].input_schema` + `tool_choice` 로 변환.
- ctx7 출처: `/anthropics/anthropic-sdk-python` — `messages.parse()` signature 에 `output_format`, `output_config` 인자.
- 효과: provider-level enforcement (true forced structured output).

**OpenAI SDK (PAYG):**
- `client.chat.completions.create(response_format={"type": "json_schema", "json_schema": {"name": "...", "schema": {...}, "strict": True}})` — strict 모드는 schema 강제 (refusal 또는 schema 외 응답 reject).
- ctx7 출처: `/openai/openai-cookbook` 의 `Leveraging_model_distillation_to_fine-tune_a_model.ipynb`.

**Codex OAuth (OpenAI subscription axis):**
- OpenAI Responses API (`/v1/responses`) — `output_schema` field 지원 (`codex_cli.py` 의 `--output-schema` 가 이 wire 의 CLI 래퍼). PAYG 와 동일.

**Local CLI (Codex + Claude Code):**
- `claude --json-schema <inline-json>` → claude-cli 가 system prompt 로 schema 주입. **enforcement 없음.**
- `codex --output-schema <file>` → 동일. **enforcement 없음.**

### 3.3 적용 plan — 6 셀 매트릭스

| 셀 | adapter | mechanism | 새 작업 | LOC |
|----|---------|-----------|---------|-----|
| **PAYG-Anth** | anthropic_payg.py | `messages.parse(output_format=PydanticModel)` 또는 force `tools[].input_schema` | response_schema → pydantic model 변환 layer | ~120 |
| **PAYG-OpenAI** | openai_payg.py | `response_format={"type":"json_schema", "strict":True, ...}` | response_schema → response_format 변환 | ~80 |
| **Sub-OAuth** | codex_oauth.py | Responses API `output_schema` 필드 (= PAYG-OpenAI 와 동일 wire) | 동일 변환 재사용 | ~30 (shared helper) |
| **CLI-Claude** | claude_cli.py | 이미 soft hint. **Option B retry + Option D fallback** | retry/extract layer (adapter-agnostic) | ~80 |
| **CLI-Codex** | codex_cli.py | 동일 | 동일 (shared retry/extract layer) | (shared) |
| **Anth-OAuth (NEW)** | anthropic_oauth.py | 동일 force tool_use (PAYG-Anth 와 wire 동일) | shared helper 재사용 | ~30 |

**Shared helper:** `core/llm/structured_output.py` (NEW) — `force_structured_output(schema: dict, response: str) -> dict | None` 의 fallback 추출 + retry 의 turn-management. 6 셀 모두 호출.

### 3.4 우선순위

1. **CLI-Claude + CLI-Codex (Option A + B)** — 현재 운영 path, 최대 영향. 별도 SDK 변경 없이 retry + 강화 extract.
2. **PAYG-OpenAI + Sub-OAuth (response_format)** — 한 번에 2 셀. 변환 helper 단일.
3. **PAYG-Anth + Anth-OAuth (messages.parse)** — Anthropic SDK 업데이트 필요. 사용자 directive "Anthropic 한정 조치 자제" 와 일부 충돌하지만, 본 axis 는 SDK-level structured output 의 표준 API. PAYG/OAuth 양쪽에 같은 helper.

**MVP 권장:** (1) + (2) 만 — 가장 임팩트 큰 4 셀 (CLI ×2 + PAYG-OpenAI + Sub-OAuth). Anth-axis 는 후속.

## 4. Non-JSON 실패 처리 (smoke 16 evolver TimeoutError)

별도 트랙 — JSON 작업과 직교.

| 항목 | 현 상태 | 권장 |
|------|---------|------|
| `plan.py:721 decompose_async` timeout | 122s 후 raise TimeoutError | 1) timeout 값 (현재 wait_for 의 timeout) 확인 + 로그. 2) retry-on-timeout 또는 graceful degradation. 3) AgenticLoop 의 plan 단계가 evolver 처럼 long-tool-call sub-agent 에 필요한지 재검토. |
| Orchestrator label 의 오해 ("termination_reason=natural") | sub-agent 의 raw output 이 비어있으면 무조건 natural 로 라벨 | TimeoutError 같은 internal exception 을 별도 reason 으로 surface |

## 5. Checkpointer 점검 (사용자 요청)

### 5.1 현 상태

`plugins/seed_generation/orchestrator.py`:
- `_persist_state()` (l.828) — `state.json` 을 **run 끝에만** 1회 작성 (l.529, `arun()` 의 _PHASE_ORDER 루프 완료 후)
- `_persist_survivors()` (l.630) — `survivors.json` 동일
- `_persist_meta_review()` — meta_review 끝에 1회
- **per-phase 또는 per-candidate checkpoint 없음**

CLI: `audit-seeds config`, `audit-seeds generate` 2개만. **`resume` 명령 없음.** orchestrator.py 의 주석 (l.519, l.834) 는 "S11 CLI `geode audit-seeds resume` will re-hydrate from here" 라고 적었지만 미구현.

### 5.2 의미

- smoke 16 evolver TimeoutError 발생 시 → `arun()` 이 `aborted = True` 로 루프 빠져나오긴 함 → `_persist_state()` 호출됨. 그러나 partial state (critic/pilot/evolver fail 표시) 만 저장.
- **mid-phase crash (예: Pipeline 외 raise)** 시 → state.json 미작성, run_dir 의 candidates/ 등 disk 산출만 남음.
- Per-candidate / per-phase checkpoint 없어 같은 운영 비용으로 재개 불가.

### 5.3 Frontier reference grounding

| Source | 패턴 | 비고 |
|--------|------|------|
| open-coscientist (origin) | LangGraph `ainvoke()` in-memory, 체크포인트 없음 (`generator.py:473`) | crash 시 전부 손실 — GEODE 와 동일 한계 |
| paperclip (Claude Code) | `~/.claude/projects/<hash>/<session>.jsonl` per-event append-only, resume via session_id | event-level granularity, replay = re-stream |
| LangGraph `SqliteSaver` | thread_id + checkpoint_id keying, per-node 단위 | API: `aput()` / `aget()` / `alist()` 의 state CRUD |
| GEODE 현재 | run 끝에 1회 state.json | 인프라 있지만 wire 안 됨 (`pyproject.toml` 에 `langgraph-checkpoint-sqlite>=3.0.0` 명시) |

**수렴 verdict:** per-phase JSON append-only — paperclip 의 event-level 보다는 거칠지만, GEODE 의 phase 단위 atomic 처리에 fit. LangGraph SqliteSaver 의 thread_id ↔ GEODE 의 run_id 1:1 매핑.

### 5.4 수렴 디자인 (S5 sprint)

**파일 추가:**

```
plugins/seed_generation/
├─ checkpointer.py     # NEW — per-phase JSON 작성
└─ resume.py           # NEW — hydration + skip-completed 로직
```

**스키마:**

```python
# checkpointer.py
@dataclass(frozen=True)
class PhaseCheckpoint:
    phase: str                # 'literature_review' | 'generator' | ... | 'meta_reviewer'
    completed_at: float       # Unix epoch
    duration_ms: float
    state_snapshot: dict      # _state_to_json(state) — full PipelineState as JSON
    error: str | None         # phase 가 error 로 끝났으면 사유, 정상이면 None

def write_checkpoint(run_dir: Path, ck: PhaseCheckpoint) -> Path:
    """Write to <run_dir>/checkpoints/<phase>.json. Atomic via tmp+rename."""

def list_completed_phases(run_dir: Path) -> list[str]:
    """Return phase names in order they were completed (mtime sort)."""

# orchestrator.py — PipelineState 에 추가
completed_phases: list[str] = field(default_factory=list)
```

**Orchestrator wiring:**

```python
# arun() 루프 안, await self._arun_phase(phase) 직후
await self._record_checkpoint(phase)

# resume_from_phase 인자 추가 + 루프 시작 시 skip
async def arun(self, *, resume_from_phase: str | None = None) -> PipelineState:
    start_idx = 0
    if resume_from_phase:
        start_idx = _PHASE_ORDER.index(resume_from_phase)
    for phase in _PHASE_ORDER[start_idx:]:
        ...
```

**CLI:**

```python
@audit_seeds_app.command("resume")
def audit_seeds_resume(
    run_id: str = typer.Argument(...),
    from_phase: str | None = typer.Option(None, "--from-phase"),
) -> None:
    """Resume a partial run from its last completed checkpoint.

    Auto-detects the next uncompleted phase from
    ``state/seed-generation/<run_id>/checkpoints/`` unless
    ``--from-phase`` overrides.
    """
```

**Idempotency:**

- Each phase reads `state.candidates`/`reflections`/`pilot_scores` and tolerates already-populated rows.
- Critic/Pilot/Evolver skip work for candidate_ids already in their respective output dict (state already has the result from a prior checkpoint).

**LOC: ~430**
- checkpointer.py: ~80
- resume.py: ~80
- orchestrator.py modifications: ~60
- cli.py resume command: ~50
- Tests (atomic write, list ordering, resume hydration, idempotency × 3 phases): ~160

## 6. time_budget hard cap (사용자 요청)

### 6.1 현 상태

| 위치 | 값 | 단위 | 만료 시 |
|------|----|------|---------|
| `core/agent/sub_agent.py:344 SubAgentManager.__init__ timeout_s` | **120.0** | per-subprocess wall-clock | raise TimeoutError |
| `core/agent/plan.py:657 plan.decompose_async` | **60.0** | per-LLM-call (asyncio.wait_for) | raise TimeoutError → catch + raise sub_agent fail |
| `core/agent/worker.py:54 WorkerRequest.time_budget_s` | 0.0 (default) | (unused) | **enforced 안 됨** |
| `core/orchestration/isolated_execution.py IsolationConfig.timeout_s` | 300.0 default | per-subprocess | wait_for timeout |

smoke 16 evolver: plan.decompose_async 122s 만에 timeout. 120s SubAgentManager + 60s plan.decompose 두 cap 모두 짧음.

### 6.2 Frontier reference grounding

| Source | Cap | Granularity | 만료 |
|--------|-----|-------------|------|
| hermes-agent | iteration budget (50 turns/sub-agent, `IterationBudget` `run_agent.py:520`) | per-LLM-call | graceful refund |
| openclaw | **48시간** default (`agents/timeout.ts:3`) | per-agent-run wall-clock | graceful + optional retry |
| LangGraph | 명시적 wall-time cap 없음 — recursion_limit (default 25 노드) 만 | per-graph traversal | exception |
| GEODE 현재 | 120s SubAgent + 60s plan.decompose | per-subprocess | raise |

**수렴 verdict:** openclaw 의 per-agent-run wall-clock 모델 — iteration counting 보다 tool-using 에 fit. 48시간은 너무 길지만 GEODE 120s 는 짧음. 중간값 **5분 (300s)** 가 IsolationConfig default 와도 일치.

### 6.3 수렴 디자인 (S6 sprint)

**변경:**

1. `core/agent/sub_agent.py:344` — `timeout_s: float = 120.0` → **300.0** (5분).
2. env override: `GEODE_SUBAGENT_TIMEOUT_S` 읽어 `[10, 3600]` clamp.
3. `core/agent/worker.py` — `WorkerRequest.time_budget_s` 를 IsolatedRunner 에 wire-through (현재 dead field). orchestrator/SubAgentManager 가 per-task budget 설정 가능 (예: pilot 300s, critic 120s).
4. `core/agent/plan.py:657` — `decompose_async` wait_for timeout **60s → 90s** (smoke 16 의 122s 는 plan + tool 합쳐서 — plan 단독은 90s 면 충분 추정).

**Tests:**
- `SubAgentManager.timeout_s` default = 300 invariant
- `GEODE_SUBAGENT_TIMEOUT_S` env clamp 동작 (10 / 1800 / 9999 → 3600)
- `WorkerRequest.time_budget_s` 가 0 이 아니면 IsolationConfig 우선
- `plan.decompose_async` 90s default

**LOC: ~120**
- sub_agent.py: ~25 (env override + clamp)
- worker.py: ~15 (wire-through)
- plan.py: ~5 (constant raise)
- Tests: ~75

### 6.4 우선순위

S5 / S6 모두 inter-dependent 한 영역 없음 — 묶거나 분리 자유.

## 6. Sprint 분해 (제안)

| Sprint | scope | LOC | 비용 |
|--------|-------|-----|------|
| **S1 — Structured output S/W (CLI axis)** | Option A 강화 + Option B retry + shared `structured_output.py` helper | ~250 | 0 (코드만) |
| **S2 — PAYG-OpenAI + Sub-OAuth** | response_format / output_schema plumbing | ~120 | 0 |
| **S3 — PAYG-Anth + Anth-OAuth** | messages.parse force | ~150 | 0 |
| **S4 — Non-JSON failure: plan.decompose timeout** | timeout 분석 + retry / degradation | ~80 | 0 |
| **S5 — Checkpointer** | per-phase persist + resume CLI + idempotent phases + tests | ~430 | 0 |

## 7. Socratic Gate

| # | 질문 | 답변 |
|---|------|------|
| Q1 | 이미 존재? | (1) `--json-schema`/`--output-schema` 만 soft hint. (2) `_last_balanced_json_object` fallback 있음. (3) per-phase checkpoint X. retry mechanism X. SDK structured output plumbing X. |
| Q2 | 안 하면? | smoke 17/18 에서 동일 prose regression. 운영 비용 낭비 + 신뢰도 X. 또한 mid-run crash 시 처음부터 다시 — 비용 누적 |
| Q3 | 측정? | smoke 17 vs smoke 16 의 phase-pass 비율, JSON-emit rate per agent, retry trigger 빈도 |
| Q4 | 가장 단순? | S1 (CLI retry + extract 강화) 만 먼저 — 가장 영향 큰 path, SDK 변경 없음 |
| Q5 | frontier 3+? | DSPy / outlines / Instructor / langchain `JsonOutputParser` 모두 retry + parse fallback 패턴 채택. OpenAI SDK + Anthropic SDK 둘 다 force-mode 가 production API. |

## 8. 우선순위 결정 요청

- **Path A** — S1 만 먼저 (CLI retry + extract). 비용 ~250 LOC, smoke 17 으로 효과 측정.
- **Path B** — S1 + S2 묶음 (CLI + OpenAI SDK 양쪽 한 PR). ~370 LOC.
- **Path C** — S1 + S2 + S3 전체 (3-axis 모두). ~520 LOC. SDK 변경 포함이라 Anth subscription path 영향 우려.
- **Path D** — S5 checkpointer 먼저 (run 비용 보호 우선). ~430 LOC. 별도 트랙.

## 9. Status

- [x] Plan SoT 작성 (이 문서)
- [ ] 우선순위 (Path A/B/C/D) 운영자 결정
- [ ] S1 (구현)
- [ ] S2 / S3 후속
- [ ] S4 / S5 deferred 트랙
