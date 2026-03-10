# CI/CD Pipeline, Batch Analysis, Quality Gate — AI Agent의 품질 보증 체계

> Date: 2026-03-09 | Author: geode-team | Tags: CI-CD, batch-analysis, quality-gate, Swiss-Cheese, PSM, verification

## 목차

1. 도입: AI Agent에게 품질 게이트가 필요한 이유
2. 5-Job CI/CD Pipeline
3. Thread-Safe Batch Analysis
4. 5-Layer Swiss Cheese 검증 모델
5. PSM 기반 Scoring Engine
6. Feedback Loop과 Confidence Gate
7. 마무리

---

## 1. 도입: AI Agent에게 품질 게이트가 필요한 이유

LLM 기반 Agent 시스템에서 코드 품질과 출력 품질은 별개의 문제입니다. 코드가 통과해도 LLM 출력이 편향되거나, 점수가 일관성을 잃거나, 근거 없는 분석이 나올 수 있습니다. GEODE는 CI/CD에서 코드 품질을, Swiss Cheese 모델로 출력 품질을 다층으로 검증합니다.

## 2. 5-Job CI/CD Pipeline

```yaml
# .github/workflows/ci.yml
name: CI
on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
```

| Job | Python | 도구 | 역할 |
|---|---|---|---|
| lint | 3.12 | ruff check + format | 스타일/복잡도 검사 |
| typecheck | 3.12 | mypy --strict | 정적 타입 검증 |
| test | 3.12 + 3.13 | pytest --cov | 1541+ 테스트, 75% 커버리지 |
| security | 3.12 | bandit | 보안 취약점 스캔 |
| gate | - | 의존: 상위 4개 | 전체 통과 확인 |

> `cancel-in-progress: true`로 동일 브랜치의 이전 CI 실행을 자동 취소합니다. Gate Job은 4개 Job이 모두 성공해야 통과하며, PR 머지를 차단합니다.

### 주요 설정

```toml
# pyproject.toml
[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "S", "N", "C4", "RUF"]

[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]

[tool.coverage.report]
fail_under = 75

[tool.bandit]
exclude_dirs = ["tests"]
```

## 3. Thread-Safe Batch Analysis

```python
# geode/cli/batch.py
def run_batch(*, top: int = 20, genre: str | None = None,
              concurrency: int = 2, dry_run: bool = True) -> list[dict[str, Any]]:
    """병렬 배치 분석. IP별 독립 GeodeRuntime."""
    selected = select_ips(top=top, genre=genre)

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(run_single_analysis, ip, dry_run=dry_run): ip
            for ip in selected
        }
        for future in as_completed(futures):
            try:
                result = future.result(timeout=120)  # IP당 120초
            except TimeoutError:
                result = {"ip_name": ip, "tier": "ERR", "error": True}
            results.append(result)

    results.sort(key=lambda r: r.get("final_score", 0), reverse=True)
    return results
```

```python
# geode/cli/batch.py
def _run_analysis_standalone(ip_name: str, *, dry_run: bool = True) -> dict[str, Any]:
    """Thread-safe: 각 호출이 독립 GeodeRuntime을 생성합니다."""
    runtime = GeodeRuntime.create(ip_name)  # THREAD-ISOLATED
    graph = runtime.compile_graph()
    try:
        result = graph.invoke(initial_state, config=runtime.thread_config)
    finally:
        runtime.shutdown()
    return {"ip_name": ip_name, "tier": result.get("tier"), "final_score": result.get("final_score")}
```

> 핵심은 Thread Isolation입니다. 각 IP 분석이 독립 GeodeRuntime을 생성하므로 ContextVar, LLM client, Circuit Breaker가 모두 격리됩니다. 120초 타임아웃으로 단일 IP의 지연이 전체 배치를 차단하지 않습니다.

| 설정 | 기본값 | 조정 가능 |
|---|---|---|
| 동시성 | 2 workers | `--concurrency` |
| IP 타임아웃 | 120초 | `_IP_TIMEOUT_S` |
| Dry-run | True | `--dry-run` |
| 정렬 | 점수 내림차순 | 고정 |

## 4. 5-Layer Swiss Cheese 검증 모델

단일 검증 게이트는 특정 유형의 결함을 놓칠 수 있습니다. Swiss Cheese 모델은 5개의 독립 검증 레이어를 적용하여 각 레이어의 약점을 다른 레이어가 보완합니다.

### Layer 1: Guardrails (G1-G4)

```python
# geode/verification/guardrails.py
def run_guardrails(state: GeodeState) -> GuardrailResult:
    checks = [
        ("G1(Schema)", _g1_schema),       # 필수 필드 존재 확인
        ("G2(Range)", _g2_range),         # 수치 범위 검증 (1-5, 0-100)
        ("G3(Ground)", _g3_grounding),    # 증거 근거 확인
        ("G4(Consist)", _g4_consistency), # 점수 일관성 (>2σ 이상치)
    ]
```

| 검사 | 기준 | 실패 조건 |
|---|---|---|
| G1 Schema | analyses, evaluations, tier 존재 | 필수 필드 누락 |
| G2 Range | analyst [1,5], evaluator [0,100] | 범위 초과 |
| G3 Ground | 증거가 signal 데이터에 근거 | 미근거 증거 |
| G4 Consist | 점수 평균 ± 2σ | 이상치 존재 |

### Layer 2: BiasBuster (6 Bias)

```python
# geode/verification/biasbuster.py
class BiasBusterResult(BaseModel):
    confirmation_bias: bool = False
    recency_bias: bool = False
    anchoring_bias: bool = False
    position_bias: bool = False
    verbosity_bias: bool = False
    self_enhancement_bias: bool = False
```

> 통계적 휴리스틱: CV(변동계수) < 0.05이고 Analyst 4명 이상이면 Anchoring Bias 가능성을 플래그합니다. 이는 모든 Analyst가 유사한 점수를 내면 하나의 앵커에 끌려간 것일 수 있다는 신호입니다.

### Layer 3: Cross-LLM Agreement

```python
# geode/verification/cross_llm.py
# agreement = 1 - var(scores) / max_possible_variance
# 임계: >= 0.67 (acceptable)
```

### Layer 4: Rights Risk

```python
# geode/verification/rights_risk.py
class RightsStatus(str, Enum):
    CLEAR = "clear"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"
```

### Layer 5: Ground Truth Calibration

```python
# geode/verification/calibration.py
overall = (
    0.20 * tier_score +     # 티어 일치
    0.20 * cause_score +    # 원인 일치
    0.20 * range_score +    # 점수 범위 내
    0.40 * axes_score       # 14-axis 정확도
)
passed = overall >= 80.0  # 통과 임계
```

> 5개 레이어가 모두 독립적으로 동작하므로 한 레이어의 약점(예: G3가 정성적 증거를 놓침)을 다른 레이어(Cross-LLM Agreement, Calibration)가 보완합니다.

## 5. PSM 기반 Scoring Engine

GEODE의 최종 점수는 6개 가중 구성요소와 신뢰도 배수로 계산됩니다.

```python
# geode/nodes/scoring.py
def _calc_final_score(
    exposure_lift: float,   # 25% — PSM ATT
    quality: float,         # 20% — 8-axis Quality Judge
    recovery: float,        # 18% — Hidden Value (E+F axes)
    growth: float,          # 12% — Trend + Expand + Dev
    momentum: float,        # 20% — Community (J+K+L)
    developer: float,       # 5%  — Developer 실적
    confidence: float,      # Confidence multiplier
) -> float:
    base = (0.25 * exposure_lift + 0.20 * quality + 0.18 * recovery
            + 0.12 * growth + 0.20 * momentum + 0.05 * developer)
    multiplier = 0.7 + (0.3 * confidence / 100)  # [0.7, 1.0]
    return base * multiplier
```

> Confidence multiplier가 [0.7, 1.0] 범위로 최종 점수를 조정합니다. 분석 확신이 낮으면(CV가 높으면) 점수가 최대 30% 감소하여 보수적 평가를 유도합니다.

### PSM (Propensity Score Matching)

```python
# geode/nodes/scoring.py
def _compute_psm(ip_name: str, monolake: dict[str, Any]) -> PSMResult:
    """PSM 시뮬레이션 엔진.

    1. Logistic propensity score 추정
    2. 1:1 NN matching with caliper (0.2 × SD(PS))
    3. SMD balance check (< 0.1)
    4. ATT (Average Treatment Effect)
    5. z-value (Wald test, > 1.645 for 95% 유의)
    6. Rosenbaum Gamma bounds (감도 분석, <= 2.0)
    """
```

| PSM 지표 | 기준 | 의미 |
|---|---|---|
| ATT | - | IP 노출 효과 (%) |
| z-value | > 1.645 | 95% 통계적 유의 |
| Gamma | <= 2.0 | 인과 강건성 확인 |
| SMD | < 0.1 | 공변량 균형 |

### Tier 분류

```python
def _determine_tier(score: float) -> str:
    if score >= 80: return "S"   # Exceptional
    elif score >= 60: return "A" # Strong
    elif score >= 40: return "B" # Moderate
    else: return "C"             # Weak
```

## 6. Feedback Loop과 Confidence Gate

```python
# geode/graph.py
def _configured_should_continue(state: GeodeState) -> str:
    """신뢰도 >= 0.7 → synthesizer, 미달 → gather (재시도)."""
    confidence = state.get("analyst_confidence", 0.0)
    iteration = state.get("iteration", 1)

    if confidence >= 0.7:
        return "synthesizer"
    if iteration >= max_iterations:
        return "synthesizer"  # 강제 진행
    return "gather"  # Feedback loop
```

```
signals → analysts → evaluators → scoring → verification
    ↑                                              │
    └──────── confidence < 0.7 ─────────────────────┘
              (최대 3회 반복)
```

> Confidence Gate는 무한 루프를 방지하면서도 낮은 확신의 분석을 재시도할 기회를 제공합니다. max_iterations(기본 3)에 도달하면 강제로 synthesizer로 진행합니다.

## 7. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|---|---|
| CI/CD | 5-Job (lint, typecheck, test, security, gate) |
| Test | 1541+ tests, 102 modules, 75% 커버리지 |
| Batch | ThreadPoolExecutor, 2 workers, 120s/IP 타임아웃 |
| Swiss Cheese | 5-Layer (Guardrails, BiasBuster, Cross-LLM, Rights, Calibration) |
| Final Score | 6 weighted + confidence multiplier [0.7, 1.0] |
| PSM | ATT + z > 1.645 + Gamma <= 2.0 + SMD < 0.1 |
| Tier | S >= 80, A >= 60, B >= 40, C < 40 |
| Feedback | confidence < 0.7 → gather loop (최대 3회) |

### 체크리스트

- [ ] 5-Job CI Pipeline (cancel-in-progress) 구성
- [ ] mypy strict + Pydantic 플러그인 적용
- [ ] 75% 커버리지 임계 설정
- [ ] Thread-safe Batch (독립 GeodeRuntime)
- [ ] G1-G4 Guardrails 구현
- [ ] 6 Bias 통계적 휴리스틱 감지
- [ ] Cross-LLM Agreement >= 0.67
- [ ] Ground Truth Calibration (4-component, >= 80.0)
- [ ] PSM 시뮬레이션 엔진 (ATT, z, Gamma, SMD)
- [ ] Confidence Gate Feedback Loop (최대 3회)
