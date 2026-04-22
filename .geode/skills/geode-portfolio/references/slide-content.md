# GEODE Submit Slides Content Reference

> Source: `submit/task2_GEODE.pdf` (3 slides)
> SOT: `ppt-workspace/task2/docs/architecture-v6.md`

## Slide 1: PSM 인과 추정과 다차원 가치 평가 기준 (WHY)

### PSM 6-Step Pipeline
1. INPUT: IP + 14 Covariates
2. PS 추정: Logistic Regression → PS(X) = P(T=1|X)
3. Matching: Nearest Neighbor, Caliper = 0.2 × SD(PS)
4. Balance: SMD Check → SMD < 0.1 (all covariates)
5. ATT: Abadie-Imbens SE, Var Ratio [0.5, 2.0], Z > 1.645 (p<0.05)
6. HG_Score: 0-100

### HG_Score Formula
```
HG_Score = E[Y₁ - Y₀ | T=1, PS(X)]
T=1: 마케팅 노출 상위 50%
Y: DAU×0.3 + Revenue×0.4 + Retention(D1/D7/D30)×0.3
Residual(잔차)와 실질 격차를 동시에 포착하는 PSM 모듈경계
```

### 14 Covariates
- IP 속성 (5): genre, ip_age, media_origin, developer_tier, franchise_history
- 품질 (5): core_gameplay, content_depth, narrative, review, social
- 시장 (4): launch_timing, market_segment, price_tier, competitor_density

### Sensitivity Analysis (Rosenbaum Bounds)
- PASS: Γ ≤ 2.0 → "미관측 교란 변수가 있더라도 결과가 유효한가?"
- WARN: 2.0 < Γ ≤ 3.0
- FAIL: Γ > 3.0

### Quality Evaluator (8축) — Quality_Score = (축 합산 - 8) / 32 × 100
A. Core Mechanics | B. IP Integration | C. Engagement | B.1 Trailer | C.1 Conversion | C.2 Experience | M. Polish | N. Fun

### Hidden Evaluator (3축) — (D+E+F-3)/12 × 100
D. Discovery Gap | E. Execution Gap | F. Expansion

### Momentum Evaluator (3축) — (J+K+L-3)/12 × 100
J. Growth Velocity | K. Social Resonance | L. Platform

### Route 2: 미게임화 IP (9축)
Fit: G Genre | H IP Power | I Timing
Feasibility: O Technical | P Innovation
Momentum: Q Awareness | R Fan | S Content

### Decision Tree (코드 기반, LLM 미사용)
```
IF timing_issue & D≥3 → timing_mismatch
IF D≥3 & E≥3 → conversion_failure
IF D≥3 & E<3 → undermarketed
IF D≤2 & E≥3 → monetization_misfit
IF D≤2 & E≤2 & F≥3 → niche_gem
ELSE → discovery_failure (복합 요인)
```

### DECISION : ACTION MAPPING
| Cause | Action |
|-------|--------|
| undermarketed | → 마케팅 강화 |
| conversion_failure | → 마케팅+과금 개선 |
| monetization_misfit | → 과금 재설계 |
| niche_gem | → 플랫폼 확장 |
| timing_mismatch | → 리런치 타이밍 최적화 |
| discovery_failure | → 종합 전략 |

### FINAL SCORE: 6가지 가중 합산
```
.25 HG(PSM) + .20 Quality + .18 Recovery + .12 Growth + .20 Community + .05 Dev
× CM (0.7 + 0.3 × Confidence/100)

S ≥ 80 | A ≥ 60 | B ≥ 40 | C < 40
```

---

## Slide 2: GEODE 저평가 IP 발굴 에이전트 시스템 (HOW)

### Agent Layer Architecture (6 layers)
- L5: EXTENSIBILITY — Custom Agents, Plugins, Reports
- L4.5: AUTOMATION — Pre-defined Automation, Trigger Manager, Snapshot Manager (peekaboo)
- L4: ORCHESTRATION — Plan Mode, Task System, Hooks
- L3: AGENTIC CORE — Agent Loop, Analysts, Evaluators
- L2: MEMORY — Org > Project > Session
- L1: FOUNDATION — MonoLake, LLM, APIs, Skills

### Agent Loop (Core)
```
START → GATHER(데이터 수집) → ACTION(분석+종합) → Verify(confidence≥0.7?)
  ↑ NO ─────────────────────────────────────────────────┘
  YES → FINALIZE(결과 반환)
Loop Back (max_iterations=3)
```

### GATHER Phase
1. Memory Context 조회
2. Snowflake Cortex Agent(SQL) 수집
3. 외부 Signal 4종 수집
4. 데이터 신뢰도 체크

### ACTION+SYNTHESIZE Phase
- Phase 1: Analysts ×4 (병렬) — Clean Context 원칙
- Phase 2: Evaluators ×3
- Phase 3: PSM Engine
- Phase 4: Synthesizer — Decision Tree 기반 원인 분류

### Orchestration Layer
- PLANNER: 사용자 요청 → 6가지 Route 결정 (Model: Gemini 3.0 Flash)
- TASK SYSTEM: Task Decomposition, Dependency Graph, 상태 변환/추적
- HOOK SYSTEM: Session Start/End, Error, OnError/OnComplete

### Tool System — 17 Tools × 5 Categories
| Category | Tools |
|----------|-------|
| DATA | query_monolake, cortex_analyst, cortex_search |
| SIGNAL | youtube_search, reddit_sentiment, twitch_stats, steam_info, google_trends |
| ANALYSIS | run_analyst, run_evaluator, psm_calculate |
| MEMORY | memory_search, memory_get, memory_save |
| OUTPUT | generate_report, export_json, send_notification |

---

## Slide 3: Multi-Agent 시스템 재귀 개선 루프 (WHAT)

### Core Question
"LLM이 평가한 결과를 믿어도 되는가?"

### LLM-as-Judge의 리스크
- 확증편향: 기존 인식 강화 → BiasBuster(Verify) 결과 무결성 검증
- 최근성편향: 최신 정보 과대평가 → Clean Context 적용
- 앵커링: 지표에 과도한 편향 → 평가자별 글로벌평 가중치
- 결과 무시: 라이선스 미검토 → Rights Check 의무화

### Feedback Loop 5-Phase Architecture (RLHF + RLAIF)

| Phase | Content |
|-------|---------|
| 1. PREDICTION (T+0) | Agent Loop → Final_Score → Tier → Snapshot 저장 |
| 2. OUTCOME TRACKING (T+30/90/180d) | Scheduled Automation → 실제 성과 수집 → Delta 계산 |
| 3. CORRELATION ANALYSIS (Quarterly) | Spearman ρ, Kendall τ, Precision@K 산출 |
| 4. MODEL IMPROVEMENT (Bi-annual) | A. Rubric / B. Weight / C. Prompt tuning |
| 5. RLAIF INTEGRATION (Advanced) | AI Feedback으로 Human Feedback 보완 |

### KPI Targets
| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| ρ ≥ 0.50 | Spearman Correlation | Final_Score vs Revenue Delta |
| τ ≥ 0.45 | Kendall Tau | 순위 일관성 (τ ≈ 0.9×ρ) |
| P@10≥0.6 | Precision at 10 | 상위 10개 중 6+ 정확 |
| α ≥ 0.80 | Krippendorff's Alpha | Human-LLM 신뢰도 |

### Expert Panel Hierarchy (NDC25 기반)
- Tier 3 Verified: ρ≥0.50, 30+개 예측, 핵심 검증
- Tier 2 Provisional: 실적 누적 중, 리뷰 참여
- Tier 1 Candidate: 기초 인증 참가

### CUSUM Calibration Drift 탐지
```
S_n = Σ (μ − x_i) / σ
누적합이 임계값 초과 시 Drift 경고
```
- NONE: CUSUM ≤ 2.5 (정상)
- WARNING: 2.5 < CUSUM ≤ 4.0
- CRITICAL: CUSUM > 4.0 (즉시 조치)

### Guardrail (G1-G4)
- G1: Schema — JSON 스키마 검증 (구조)
- G2: Range — 점수 범위 검증 (1-5)
- G3: Ground — 근거 데이터 검증 (사실)
- G4: Consistency — 일관성 검증 (논리)

### Model Versioning & Registry (MLflow/W&B)
```python
version_id: "v6.0.1"
parent: "v5.5.0"
rubric_hash: SHA256
weight_hash: SHA256
prompt_hash: SHA256
```
Promotion Pipeline: DEV → STAGING → PROD

### Pairwise Ranking (RLHF 핵심 가치)
IP A vs IP B → Elo Rating → Reward Signal
