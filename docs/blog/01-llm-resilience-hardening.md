# LLM이 죽어도 파이프라인은 살아야 한다 — LangGraph 파이프라인의 Graceful Degradation 설계

> Date: 2026-03-30 | Author: geode-team | Tags: LangGraph, resilience, graceful-degradation, LLM, pipeline

## 목차
1. 문제 정의
2. GAP 분석: Happy Path와 Total Outage 사이
3. Phase 1 — Degraded Fallback
4. Phase 2 — Verification Enrichment Loop
5. Phase 3 — Cost Control과 Timeout
6. 실전 적용: Scoring Penalty
7. 정리

---

## 1. 문제 정의

LLM 기반 파이프라인은 두 가지 극단에 대한 대비가 잘 되어 있습니다. 정상 경로(Happy Path)는 테스트로 검증하고, 전면 장애(Total Outage)는 fallback chain과 circuit breaker로 처리합니다. 문제는 그 사이입니다.

- Analyst 4명 중 1명만 timeout
- Evaluator가 validation error를 반환
- Verification의 guardrails가 실패했지만 confidence는 충분

이런 **중간 지점의 실패**가 파이프라인을 통째로 crash시키거나, 반대로 조용히 나쁜 결과를 통과시킵니다. GEODE v0.38.0에서는 14개 GAP 항목을 식별하고, 3-Phase로 구현했습니다.

## 2. GAP 분석: Happy Path와 Total Outage 사이

기존 인프라를 먼저 정리합니다. 이미 동작하는 것과 빠진 것을 분리하는 것이 핵심입니다.

| 계층 | 이미 있는 것 | 빠진 것 (GAP) |
|------|-------------|---------------|
| **Shared (LLM)** | Fallback chain, Retry + backoff, Circuit breaker | Jitter 없음, Cross-provider 미연결, 비용 제어 없음 |
| **Agentic Loop** | Model escalation, Context 3-phase 관리 | Cost budget bare except, Checkpoint resume 미통합 |
| **Domain DAG** | Node-level retry (1회), SqliteSaver checkpoint | Retry 소진 시 crash, Verification 실패 무시 |

GAP 항목 14개를 P0(장애 방지) / P1(품질/비용) / P2(다듬기) 3단계로 분류했습니다.

## 3. Phase 1 — Degraded Fallback

가장 치명적인 GAP: retry가 소진되면 `raise`로 파이프라인 전체가 중단됩니다.

**설계 원칙**: crash 대신 degraded 결과를 반환하고, 후속 노드가 이를 인지하게 합니다.

```python
# core/graph.py
_RETRYABLE_NODES = frozenset({"analyst", "evaluator", "scoring", "gather"})
_DEGRADABLE_NODES = frozenset({"analyst", "evaluator", "scoring"})
```

> `_RETRYABLE_NODES`는 retry를 시도할 노드, `_DEGRADABLE_NODES`는 retry 소진 후 degraded 결과를 반환할 노드입니다. `gather`는 retry하지만 degraded 반환은 하지 않습니다 — 상태 취합 노드이므로 부분 결과를 만들어낼 수 없기 때문입니다.

retry 소진 시 분기 로직:

```python
# core/graph.py — _make_hooked_node 내부
except Exception as exc:
    if retries_left > 0:
        retries_left -= 1
        last_exc = exc
        continue
    hook_data["error"] = str(exc)
    hooks.trigger(HookEvent.NODE_ERROR, hook_data)

    # B1: degradable nodes return degraded results instead of crashing
    if node_name in _DEGRADABLE_NODES:
        return _make_degraded_result(node_name, exc, effective_state)

    hooks.trigger(HookEvent.PIPELINE_ERROR, hook_data)
    raise
```

> 핵심은 `PIPELINE_ERROR` 이전에 분기한다는 점입니다. degradable 노드는 PIPELINE_ERROR를 발생시키지 않으므로, downstream 노드가 정상적으로 실행됩니다.

`_make_degraded_result`는 노드 타입별로 안전한 기본값을 반환합니다:

```python
# core/graph.py
def _make_degraded_result(
    node_name: str, exc: Exception, state: Any
) -> dict[str, Any]:
    if node_name == "analyst":
        return {
            "analyses": [AnalysisResult(
                analyst_type=atype,
                score=1.0,
                key_finding="[DEGRADED] Node retry exhausted",
                confidence=0.0,
                is_degraded=True,
            )],
            "errors": [err_msg],
        }
    if node_name == "evaluator":
        return {
            "evaluations": {etype: EvaluatorResult(
                evaluator_type=etype,
                axes=_default_axes.get(etype, _hidden),
                composite_score=0.0,
                is_degraded=True,
            )},
            "errors": [err_msg],
        }
    if node_name == "scoring":
        return {"final_score": 0.0, "tier": "C", "errors": [err_msg]}
```

> `is_degraded=True` 플래그가 핵심입니다. downstream의 scoring 노드가 이 플래그를 읽어 confidence를 낮춥니다. crash가 아닌 "신뢰도가 낮은 결과"로 전파되는 것입니다.

## 4. Phase 2 — Verification Enrichment Loop

기존에는 verification 노드의 guardrails가 실패해도 confidence만 체크했습니다. guardrails 실패와 biasbuster 실패는 별도 조건으로 loopback을 트리거해야 합니다.

```python
# core/graph.py — _configured_should_continue
verification_failed = (
    (guardrails and not guardrails.all_passed)
    or (biasbuster and not biasbuster.overall_pass)
)
if verification_failed and iteration < max_iter:
    return "gather"  # loopback to signals
```

> confidence 체크보다 **앞에** 위치합니다. confidence가 0.9로 충분해도 guardrails가 실패했다면 결과를 신뢰할 수 없기 때문입니다. `max_iter` 안전 밸브는 유지합니다.

LangGraph의 `iteration_history`는 `operator.add` reducer로 무한 증가할 수 있으므로, 커스텀 reducer로 cap을 겁니다:

```python
# core/state.py
_ITERATION_HISTORY_MAX = 10

def _add_and_trim_history(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged = left + right
    return merged[-_ITERATION_HISTORY_MAX:]

class GeodeState(TypedDict):
    iteration_history: Annotated[list[dict[str, Any]], _add_and_trim_history]
```

> LangGraph의 `Annotated[list, operator.add]` 패턴은 편리하지만, feedback loop에서는 무한 증가 위험이 있습니다. 커스텀 reducer로 교체하면 동일한 append 동작 + 상한 제어를 얻을 수 있습니다.

## 5. Phase 3 — Cost Control과 Timeout

**Backoff Jitter**: 결정론적 delay는 thundering herd를 유발합니다. 한 줄 수정이지만 효과는 큽니다.

```python
# core/llm/fallback.py — BEFORE
delay = min(retry_base_delay * (2 ** attempt), retry_max_delay)

# AFTER (full jitter)
delay = random.uniform(0, min(retry_base_delay * (2 ** attempt), retry_max_delay))
```

**Cost Ratio Guard**: haiku에서 opus로 fallback할 때 비용이 5배 뛸 수 있습니다. 사전에 필터링합니다.

```python
# core/llm/fallback.py
if _cfg.llm_max_fallback_cost_ratio > 0:
    primary_price = MODEL_PRICING.get(model)
    for fb_model in models_to_try[1:]:
        fb_price = MODEL_PRICING.get(fb_model)
        ratio = fb_price.input / primary_price.input
        if ratio > _cfg.llm_max_fallback_cost_ratio:
            continue  # skip expensive fallback
        filtered.append(fb_model)
    models_to_try = filtered
```

> `models_to_try` 리스트를 루프 진입 전에 필터링합니다. 루프 중간에 체크하면 `continue`의 스코프 문제가 발생합니다 — 실제로 첫 구현에서 이 버그를 겪었습니다.

**Pipeline Timeout**: LangGraph의 `invoke()`는 기본적으로 timeout이 없습니다. `ThreadPoolExecutor`로 래핑합니다.

```python
# core/graph.py
def invoke_with_timeout(graph, state, config=None, timeout_s=0.0, hooks=None):
    if timeout_s <= 0:
        return graph.invoke(state, config=config)

    def _run():
        return graph.invoke(state, config=config)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run)
        try:
            return future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            if hooks:
                hooks.trigger(HookEvent.PIPELINE_TIMEOUT, {"timeout_s": timeout_s})
            raise PipelineTimeoutError(...) from None
```

## 6. 실전 적용: Scoring Penalty

degraded 결과가 scoring에 도달하면, 단순히 무시하지 않고 confidence에 penalty를 적용합니다.

```python
# core/domains/game_ip/nodes/scoring.py
degraded_analysts = sum(1 for a in analyses if getattr(a, "is_degraded", False))
degraded_evals = sum(1 for e in evaluations.values() if getattr(e, "is_degraded", False))
total_sources = len(analyses) + len(evaluations)
degraded_count = degraded_analysts + degraded_evals
if degraded_count > 0 and total_sources > 0:
    penalty = 1.0 - (degraded_count / total_sources) * 0.5
    confidence = confidence * penalty
```

> 4명 중 2명 degraded → penalty = 1.0 - (2/7) * 0.5 = 0.857 → confidence 14% 감소. crash도 아니고 무시도 아닌, 비례적 감쇄입니다.

## 7. 정리

| 항목 | 변경 | 효과 |
|------|------|------|
| Degraded fallback | retry 소진 → `is_degraded=True` 반환 | 파이프라인 중단 → 계속 |
| Verification loop | guardrails/biasbuster 실패 → gather loopback | 검증 실패 무시 → 재시도 |
| Scoring penalty | degraded 비율 → confidence 감쇄 | 나쁜 결과 통과 → 신뢰도 반영 |
| Backoff jitter | `random.uniform` full jitter | thundering herd 방지 |
| Cost ratio | fallback 전 비용 비율 체크 | 비용 폭주 방지 |
| Pipeline timeout | `ThreadPoolExecutor` + hook | 무한 실행 방지 |
| History trimming | 커스텀 reducer (cap 10) | 메모리 무한 증가 방지 |
| Cross-provider | `_cross_provider_dispatch()` | 단일 프로바이더 의존 제거 |

- 14개 GAP 식별 → 3-Phase 구현 → 34개 테스트 추가
- 기존 3,461 → 3,496 테스트 (전체 통과)
- 설정 2개 추가: `pipeline_timeout_s` (600s), `llm_max_fallback_cost_ratio` (0=무제한)
- Hook 이벤트 2개 추가: `FALLBACK_CROSS_PROVIDER`, `PIPELINE_TIMEOUT` (40 → 42)
