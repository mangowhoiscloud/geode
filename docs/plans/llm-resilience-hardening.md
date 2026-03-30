# LLM Resilience Hardening Plan

## Context

GEODE는 두 개의 LLM 실행 경로를 가진다:
1. **Agentic Loop** — `while(tool_use)` 자율 실행 루프 (범용, 모든 요청)
2. **Domain DAG** — LangGraph StateGraph 파이프라인 (도메인 분석, 8-node)

두 경로 모두 happy path는 탄탄하지만, failure recovery의 중간 지점에 GAP이 있다. 이 플랜은 양측을 분할 분석하여 resilience를 보강한다.

---

## Current State — What Already Works

### Shared Infrastructure (core/llm/)

| Mechanism | Implementation | File |
|-----------|---------------|------|
| Fallback chain (per-provider) | Anthropic 2, OpenAI 3, GLM 3 | `core/llm/fallback.py`, `core/config.py:308-316` |
| Retry + exponential backoff | 3 retries, 2-30s | `core/llm/fallback.py:71-165` |
| Circuit breaker | 5 failures → 60s open → half-open | `core/llm/fallback.py:23-69` |
| Cost tracking | Per-call cost_usd, accumulator | `core/llm/token_tracker.py` |
| Observability hooks | LLM_CALL_START/END, MODEL_SWITCHED | `core/hooks/system.py` |

### Agentic Loop (core/agent/agentic_loop.py)

| Mechanism | Implementation | Lines |
|-----------|---------------|-------|
| Model escalation | 2 consecutive failures → next model → cross-provider | 1174-1213 |
| Context window mgmt | 3-phase: compact→prune→exhaust (80%/95%) | 750-866 |
| Convergence detection | 3 identical errors → escalate → 4 → break | 1265-1305 |
| Tool error backpressure | 3+ consecutive → 1s delay + hint to LLM | 606-668 |
| Cost budget guard | Per-round check, terminate on exceed | 564-587 |
| Time budget guard | Karpathy P3, monotonic clock | 460-466 |
| Session checkpoint | Per-round save (20 msg, 50 tools) | 230-248 |
| Max rounds + wrap-up headroom | Last 2 rounds forced text-only | 462-463, 1097 |

### Domain DAG (core/graph.py)

| Mechanism | Implementation | Lines |
|-----------|---------------|-------|
| Node-level retry | 1 retry, temperature 0.5→0.3 | 146-242 |
| SqliteSaver checkpoint | Full state persisted per-node | 552-632 |
| Partial failure (Send API) | errors reducer, pipeline continues | state.py:269 |
| Feedback loop | confidence < 0.7 → gather → signals (max 5 iter) | 455-509 |
| Analyst partial retry | iteration ≥ 2: skip non-degraded | analysts.py:448-459 |
| Graceful degradation | is_degraded=True + neutral defaults | analysts.py:222, evaluators.py:340 |
| Dynamic graph | Extreme score → skip verification | scoring.py:549-558 |

---

## GAP Analysis — Two-Track

### Track A: Agentic Loop GAPs

| # | GAP | Severity | Root Cause |
|---|-----|----------|-----------|
| A1 | Backoff jitter 없음 — thundering herd risk | P0 | `fallback.py:126` deterministic delay |
| A2 | Cost budget check advisory — exception 삼킴 | P1 | `agentic_loop.py:564` bare except |
| A3 | Checkpoint resume 미통합 — load 경로 불명확 | P1 | CLI layer에서 호출하나 loop 내 resume 로직 없음 |
| A4 | Sub-agent 실패 미전파 — parent 모르고 계속 | P2 | announce queue 비동기, 실패 결과 무시 |

### Track B: Domain DAG GAPs

| # | GAP | Severity | Root Cause |
|---|-----|----------|-----------|
| B1 | Node retry 소진 후 graph-level recovery 없음 | P0 | `graph.py:227` raise 후 파이프라인 중단 |
| B2 | Node errors caller에 미전달 | P0 | `mcp_server.py:69-94` state.errors 미포함 |
| B3 | Per-pipeline timeout 없음 | P1 | compile_graph에 timeout 파라미터 없음 |
| B4 | Degraded 결과 스코어링 미반영 | P1 | scoring.py에서 is_degraded 미체크 |
| B5 | Verification 실패 시 enrichment 미트리거 | P1 | `graph.py:291` 항상 confidence만 체크 |
| B6 | Evaluator partial retry 없음 | P2 | analyst만 skip 로직 있음 |
| B7 | iteration_history 무한 증가 | P2 | state.py:279 trimming 없음 |
| B8 | Gather node not retryable | P2 | _RETRYABLE_NODES에 미포함 |

### Track C: Shared Infrastructure GAPs

| # | GAP | Severity | Root Cause |
|---|-----|----------|-----------|
| C1 | Cross-provider failover 미구현 (router.py level) | P0 | per-provider chain만 존재 |
| C2 | Fallback 비용 제어 없음 | P1 | Haiku→Opus 5x 비용 상승 무제어 |
| C3 | Test coverage 미흡 (failure scenarios) | P2 | 기존 테스트에 resilience 시나리오 부족 |

---

## Implementation Plan — 3 Phases

### Phase 1: P0 — Outage Prevention (4 items)

#### C1. Backoff Jitter (Shared)
- **File**: `core/llm/fallback.py:126`
- **Change**: `delay = min(base * 2^attempt, max)` → `delay = random.uniform(0, min(base * 2^attempt, max))`
- **Effort**: 1 line

#### A1 = C1 (동일 파일, jitter는 Agentic Loop과 DAG 모두에 적용)

#### C1-b. Cross-Provider Failover (Shared — router.py level)
- **File**: `core/llm/router.py` call_llm() 레벨
- **Note**: Agentic Loop은 이미 `_try_model_escalation()`에서 `CROSS_PROVIDER_FALLBACK` 사용. 하지만 DAG의 `call_with_failover()`는 per-provider only.
- **Change**: `retry_with_backoff_generic()`에서 per-provider chain 소진 시, `llm_cross_provider_order` 다음 프로바이더로 재시도
- **Config**: `llm_cross_provider_failover: bool = False` (opt-in)
- **Hook**: `FALLBACK_CROSS_PROVIDER` 이벤트

#### B1. Node Retry 소진 후 Degraded Fallback (DAG)
- **File**: `core/graph.py:227-242`
- **Change**: retry 소진 후 `raise` 대신, degraded 결과 반환 (analyst: score=1.0, evaluator: neutral axes)
- **Pattern**: 기존 analysts.py의 degraded fallback 패턴 재사용
- **Effect**: 파이프라인 중단 → 파이프라인 계속 (degraded 표시)

#### B2. Node Errors Caller 전달 (DAG)
- **File**: `core/mcp_server.py` (또는 tool handler)
- **Change**: `state["errors"]`를 output dict에 포함
- **Format**: `"errors": ["analyst: timeout", "evaluator: validation"]`

### Phase 2: P1 — Quality/Cost (5 items)

#### A2. Cost Budget 강화 (Agentic Loop)
- **File**: `core/agent/agentic_loop.py:564-587`
- **Change**: bare except → specific exception + log.warning. Budget 초과 시 hard termination 보장.

#### B3. Per-Pipeline Timeout (DAG)
- **File**: `core/graph.py` compile_graph() / invoke()
- **Change**: `threading.Timer` 또는 `signal.alarm`으로 invoke() 래핑
- **Config**: `pipeline_timeout_s: float = 600.0`
- **Fallback**: timeout 시 현재 state 스냅샷 반환 (partial result)

#### B4. Degraded 결과 스코어링 페널티 (DAG)
- **File**: `core/domains/game_ip/nodes/scoring.py`
- **Change**: `is_degraded=True` 카운트 → confidence 페널티
- **Formula**: `penalty = 1.0 - (degraded_count / total_count) * 0.5`
- **Effect**: 4명 중 2명 degraded → confidence 75%

#### B5. Verification 실패 → Enrichment Loop (DAG)
- **File**: `core/graph.py:455-502` `_configured_should_continue()`
- **Change**: `guardrails.all_passed=False OR biasbuster.overall_pass=False` → `"gather"` 반환
- **Guard**: max_iterations 안전 밸브 유지

#### C2. Fallback 비용 비율 제한 (Shared)
- **File**: `core/llm/fallback.py`
- **Change**: fallback 전 `next_model_price / current_model_price > ratio` 체크
- **Config**: `llm_max_fallback_cost_ratio: float = 0.0` (0=무제한)

### Phase 3: P2 — Polish (5 items)

#### A3. Checkpoint Resume 통합 (Agentic Loop)
- **File**: `core/agent/agentic_loop.py`
- **Change**: `arun()` 진입 시 `checkpoint.load(session_id)` → messages 복원 → round_idx 이어서
- **Guard**: checkpoint age > 72h면 무시

#### A4. Sub-agent 실패 전파 (Agentic Loop)
- **File**: `core/agent/sub_agent.py`
- **Change**: 실패 결과에 `"error"` 필드 포함 → parent에 tool_result로 전달 → LLM이 인지

#### B6. Evaluator Partial Retry (DAG)
- **File**: `core/domains/game_ip/nodes/evaluators.py` `make_evaluator_sends()`
- **Change**: iteration ≥ 2에서 non-degraded evaluator 스킵 (analyst 패턴 미러)

#### B7. iteration_history Trimming (DAG)
- **File**: `core/graph.py` `_gather_node()`
- **Change**: `iteration_history[-10:]` trimming (최근 10개만 유지)

#### C3. Resilience Test Suite
- **New file**: `tests/test_llm_resilience.py`
- **Agentic Loop tests**: model escalation, convergence break, cost budget
- **DAG tests**: node degraded fallback, partial Send API failure, verification loop
- **Shared tests**: jitter range, cross-provider failover, cost ratio

---

## Configuration Summary (core/config.py)

```python
# Shared
llm_cross_provider_failover: bool = False
llm_cross_provider_order: list[str] = ["anthropic", "openai", "glm"]
llm_max_fallback_cost_ratio: float = 0.0  # 0 = unlimited

# DAG
pipeline_timeout_s: float = 600.0
```

## Hook Events (core/hooks/system.py)

```python
FALLBACK_CROSS_PROVIDER = "fallback_cross_provider"
PIPELINE_TIMEOUT = "pipeline_timeout"
COST_BUDGET_EXCEEDED = "cost_budget_exceeded"  # (기존 agentic loop에서 사용, hook으로 승격)
```

## Execution Order

```
Phase 1 (P0): C1 jitter → C1-b cross-provider → B1 degraded fallback → B2 error propagation
Phase 2 (P1): A2 cost budget → B3 pipeline timeout → B4 degraded scoring → B5 verification loop → C2 cost ratio
Phase 3 (P2): A3 checkpoint resume → A4 sub-agent propagation → B6 evaluator retry → B7 history trim → C3 tests
```

## Verification

```bash
uv run pytest tests/test_llm_resilience.py -v          # New tests
uv run pytest tests/test_model_failover.py -v           # Existing regression
uv run pytest tests/ -m "not live" -q                   # Full suite (3369+)
uv run ruff check core/ tests/ && uv run ruff format --check core/ tests/
uv run mypy core/
uv run bandit -r core/ -c pyproject.toml
```

## Files Modified

| Track | File | Changes |
|-------|------|---------|
| **Shared** | `core/llm/fallback.py` | Jitter, cross-provider, cost ratio |
| **Shared** | `core/llm/router.py` | Cross-provider dispatch |
| **Shared** | `core/config.py` | 4 new settings |
| **Shared** | `core/hooks/system.py` | 3 new events |
| **Agentic** | `core/agent/agentic_loop.py` | Cost budget hardening, checkpoint resume |
| **Agentic** | `core/agent/sub_agent.py` | Failure propagation |
| **DAG** | `core/graph.py` | Degraded fallback, pipeline timeout, verification loop, history trim |
| **DAG** | `core/domains/game_ip/nodes/scoring.py` | Degraded downweighting |
| **DAG** | `core/domains/game_ip/nodes/evaluators.py` | Partial retry |
| **DAG** | `core/mcp_server.py` | Error propagation to caller |
| **Test** | `tests/test_llm_resilience.py` | New — 3 tracks × 3+ tests |
