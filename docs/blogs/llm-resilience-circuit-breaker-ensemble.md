# LLM Resilience 설계 — Circuit Breaker, Failover, Cross-LLM Ensemble

> Date: 2026-03-09 | Author: geode-team | Tags: circuit-breaker, resilience, ensemble, failover, LLM

## 목차

1. 도입: LLM API는 실패한다
2. Circuit Breaker 패턴
3. 4-Stage Failover 전략
4. Prompt Caching으로 비용 절감
5. Cross-LLM Ensemble 검증
6. Token Usage 추적과 Cost Monitoring
7. 마무리

---

## 1. 도입: LLM API는 실패한다

프로덕션 AI Agent에서 LLM API 호출은 가장 취약한 지점입니다. Rate Limit, 네트워크 장애, 서비스 다운타임이 언제든 발생할 수 있습니다. GEODE는 4단계 Failover와 Circuit Breaker(서킷 브레이커)를 조합하여 단일 API 장애가 전체 파이프라인을 중단시키지 않도록 설계했습니다.

## 2. Circuit Breaker 패턴

Circuit Breaker는 연속 실패를 감지하여 추가 호출을 차단하고, 일정 시간 후 복구를 시도하는 패턴입니다.

```python
# geode/llm/client.py
class CircuitBreaker:
    """LLM API 호출을 위한 Circuit Breaker. 3-State 모델."""

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0) -> None:
        self._failures = 0
        self._threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._state: str = "closed"  # closed → open → half-open

    def can_execute(self) -> bool:
        if self._state == "closed":
            return True
        if self._state == "open":
            if time.time() - self._last_failure > self._recovery_timeout:
                self._state = "half-open"
                return True
            return False
        return True  # half-open: 1회 프로브 허용

    def record_success(self) -> None:
        self._failures = 0
        self._state = "closed"

    def record_failure(self) -> None:
        self._failures += 1
        self._last_failure = time.time()
        if self._failures >= self._threshold:
            self._state = "open"
```

> 3-State 전이: **Closed**(정상) → **Open**(차단, 5회 연속 실패) → **Half-Open**(복구 프로브, 60초 경과). Half-Open에서 1회 성공하면 Closed로 복귀합니다. 이 패턴은 API 장애 시 무의미한 재시도를 방지하여 비용과 지연을 절감합니다.

```
┌──────────┐   5회 실패   ┌──────────┐   60초 경과   ┌──────────────┐
│  Closed  │ ──────────→  │   Open   │ ──────────→  │  Half-Open   │
│ (정상)    │              │ (차단)    │              │ (1회 프로브)  │
└──────────┘  ←────────── └──────────┘              └──────────────┘
     ↑          성공                                      │
     └────────────────────────────────────────────────────┘
```

## 3. 4-Stage Failover 전략

```python
# geode/llm/client.py
def _retry_with_backoff(fn: Any, *, model: str, max_retries: int = 3) -> Any:
    """4-Stage Failover: Retry → Fallback → Circuit Break → Recovery."""
    if not _circuit_breaker.can_execute():
        raise RuntimeError("Circuit breaker is open — 호출 차단 중")

    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]

    for current_model in models_to_try:
        for attempt in range(max_retries):
            try:
                result = fn(model=current_model)
                _circuit_breaker.record_success()
                return result
            except _RETRYABLE_ERRORS as exc:
                delay = min(RETRY_BASE_DELAY * (2 ** attempt), RETRY_MAX_DELAY)
                time.sleep(delay)
            except anthropic.BadRequestError as exc:
                if "credit balance" in str(exc).lower():
                    raise RuntimeError("API 크레딧 부족") from exc
                raise

    _circuit_breaker.record_failure()
    raise last_error
```

| Stage | 조건 | 동작 | 지연 |
|---|---|---|---|
| 1. Retry | Transient Error | 동일 모델 exponential backoff | 1s → 2s → 4s |
| 2. Fallback | 3회 실패 | Fallback 모델 전환 | 즉시 |
| 3. Circuit Open | 5회 연속 실패 | 전체 호출 차단 | 60초 |
| 4. Half-Open | 60초 경과 | 1회 프로브로 복구 확인 | 즉시 |

> Retryable Error(Rate Limit, Connection Error, Internal Server Error)와 Non-Retryable Error(크레딧 부족, 컨텍스트 오버플로우)를 분리하여 불필요한 재시도를 방지합니다.

### Claude와 OpenAI 독립 Failover

각 Provider는 독립적인 Circuit Breaker와 Fallback Chain을 운영합니다.

| Provider | Primary | Fallback Chain | Circuit Breaker |
|---|---|---|---|
| Anthropic | claude-opus-4-6 | Sonnet → Haiku | 공유 인스턴스 |
| OpenAI | gpt-5.4 | gpt-5.3 → gpt-4o | 독립 인스턴스 |

```python
# geode/infrastructure/adapters/llm/openai_adapter.py
_openai_circuit_breaker = CircuitBreaker()  # OpenAI 전용

OPENAI_FALLBACK_MODELS = ["gpt-5.4", "gpt-5.3", "gpt-4o"]
```

## 4. Prompt Caching으로 비용 절감

GEODE 파이프라인은 4개 Analyst와 3개 Evaluator가 동일한 시스템 프롬프트를 공유합니다. Anthropic의 Prompt Caching을 활용하면 반복 호출 시 비용을 절감할 수 있습니다.

```python
# geode/llm/client.py
def _system_with_cache(system: str) -> list[TextBlockParam]:
    """시스템 프롬프트에 cache_control 적용.

    4개 Analyst, 3개 Evaluator가 동일 system prompt를 공유하므로
    캐시 히트로 지연/비용 절감.
    """
    return [
        TextBlockParam(
            type="text",
            text=system,
            cache_control={"type": "ephemeral"},
        )
    ]
```

> `cache_control=ephemeral`은 동일 프롬프트의 반복 호출에서 캐시 히트를 유도합니다. 4개 Analyst가 순차 실행될 때 2번째부터 캐시가 적용되어 지연과 비용이 절감됩니다.

## 5. Cross-LLM Ensemble 검증

단일 LLM의 편향을 보완하기 위해 GEODE는 Cross-LLM Ensemble(교차 검증)을 지원합니다.

### Ensemble Routing

```python
# geode/nodes/analysts.py
_SECONDARY_ANALYSTS = {"player_experience", "discovery"}
_PRIMARY_ANALYSTS = {"game_mechanics", "growth_potential"}

def _should_use_secondary(analyst_type: str) -> bool:
    if settings.ensemble_mode != "cross":
        return False
    return analyst_type in _SECONDARY_ANALYSTS
```

> Cross-Ensemble 모드에서 4개 Analyst를 2:2로 분배합니다. Primary(Claude)가 game_mechanics와 growth_potential을, Secondary(GPT)가 player_experience와 discovery를 담당합니다.

### Cross-LLM Agreement Check

```python
# geode/verification/cross_llm.py
def run_cross_llm_check(state: GeodeState) -> dict[str, Any]:
    """교차 검증: 분석 점수 분포의 합의도 측정.

    agreement = 1 - var(scores) / max_possible_variance
    """
    scores = [a.score for a in analyses]
    score_agreement = _calc_agreement(scores, scale_max_var=4.0)
    conf_agreement = _calc_agreement(confidences, scale_max_var=2500.0)
    combined = 0.7 * score_agreement + 0.3 * conf_agreement
```

**Dual Adapter 모드 (Claude + GPT 동시 검증):**

```python
# geode/verification/cross_llm.py
def run_dual_adapter_check(state: GeodeState, *,
                            primary_adapter: LLMClientPort | None = None,
                            secondary_adapter: LLMClientPort | None = None) -> dict[str, Any]:
    # Base agreement (단일 모델 내 합의)
    base_result = run_cross_llm_check(state)

    # Secondary 모델 재검증
    response = secondary_adapter.generate(
        "You are a verification agent. Respond with only a single digit 1-5.",
        f"Verify: IP={ip_name}, Tier={tier}, Score={score:.1f}/100",
        temperature=0.1, max_tokens=10,
    )

    # 블렌딩: 70% base + 30% secondary
    combined = 0.7 * base_result["cross_llm_agreement"] + 0.3 * (secondary_agreement / 5.0)
```

| 합의도 | 판정 | 의미 |
|---|---|---|
| >= 0.80 | Good | 강한 합의 |
| >= 0.67 | Acceptable | 보통 합의 |
| < 0.67 | Low | 높은 분산, 리뷰 필요 |

## 6. Token Usage 추적과 Cost Monitoring

```python
# geode/llm/client.py
@dataclass
class LLMUsage:
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

@dataclass
class LLMUsageAccumulator:
    calls: list[LLMUsage] = field(default_factory=list)

    @property
    def total_cost_usd(self) -> float:
        return sum(u.cost_usd for u in self.calls)

# Thread-safe accumulator (contextvars)
_usage_ctx: contextvars.ContextVar[LLMUsageAccumulator] = contextvars.ContextVar("llm_usage")
```

> 모든 LLM 호출의 토큰 사용량과 비용을 ContextVar에 누적합니다. 세션별로 격리되므로 배치 분석에서 IP별 비용을 독립적으로 추적할 수 있습니다.

| 모델 | Input ($/1M tokens) | Output ($/1M tokens) |
|---|---|---|
| claude-opus-4-6 | $15.00 | $75.00 |
| claude-sonnet-4-5 | $3.00 | $15.00 |
| gpt-5.4 | $2.50 | $15.00 |

## 7. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|---|---|
| Circuit Breaker | 3-State (Closed/Open/Half-Open), 5회 임계, 60초 복구 |
| Failover | 4-Stage (Retry → Fallback → Circuit Break → Recovery) |
| Retry 전략 | Exponential Backoff (1s → 2s → 4s, 최대 30s) |
| Fallback Chain | Claude: Opus → Sonnet, OpenAI: GPT-5.4 → 5.3 → 4o |
| Prompt Caching | `cache_control=ephemeral`, 반복 호출 비용 절감 |
| Ensemble | Cross-LLM 2:2 분배 (Primary+Secondary) |
| Agreement | 0.7*score + 0.3*confidence, 임계 >= 0.67 |
| Cost Tracking | ContextVar 기반, 세션별 독립 누적 |

### 체크리스트

- [ ] Circuit Breaker 3-State 전이 구현
- [ ] Retryable vs Non-Retryable Error 분류
- [ ] Provider별 독립 Fallback Chain 구성
- [ ] Prompt Caching으로 반복 호출 최적화
- [ ] Cross-LLM Ensemble Routing (2:2 분배)
- [ ] Dual Adapter 합의도 검증 (임계 0.67)
- [ ] ContextVar 기반 토큰/비용 추적
