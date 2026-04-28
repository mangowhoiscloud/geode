# Deep Research: Think Deep, Not Just Long (arXiv 2602.13517)

> Google + U. of Virginia, February 2026
> "Deep-Thinking Ratio (DTR)" — LLM 추론 노력을 토큰 길이가 아닌 레이어 깊이로 측정

---

## 1. Paper Overview

| Item | Detail |
|------|--------|
| **Title** | Think Deep, Not Just Long: Measuring LLM Reasoning Effort via Deep-Thinking Tokens |
| **Authors** | Wei-Lin Chen, Liqian Peng, Tian Tan, Chao Zhao, Blake JianHang Chen, Ziqian Lin, Alec Go (Google), Yu Meng (U. of Virginia) |
| **Published** | 2026-02-12, arXiv:2602.13517 |
| **Core Claim** | 추론 성능은 토큰 길이(how long)가 아니라 내부 계산 깊이(how deep)에 의해 결정된다 |

## 2. Core Concepts

### 2.1 Deep-Thinking Token

Transformer의 중간 레이어 hidden state를 unembedding matrix로 vocabulary에 투영했을 때, **최종 레이어까지 예측 분포가 계속 수정되는 토큰**을 "deep-thinking token"으로 분류.

- 거리 측정: **Jensen-Shannon Divergence (JSD)** between intermediate layer distribution `p_{t,l}` and final layer distribution `p_{t,L}`
- 안정화 강제: `D_bar_{t,l} = min_{j<=l} D_{t,j}` (monotonic non-increasing)
- Deep-thinking 판정: settling depth가 late-settling regime (깊은 레이어)에 해당하면 deep-thinking

### 2.2 Deep-Thinking Ratio (DTR)

```
DTR(S) = (1/T) * sum( 1[c_t in L_deep-thinking] )
```

시퀀스 S의 전체 토큰 중 deep-thinking token의 비율. 핵심 하이퍼파라미터:

| Param | Value | Meaning |
|-------|-------|---------|
| `g` (settling threshold) | 0.5 | JSD가 이 값 이하로 수렴해야 "settled" |
| `rho` (depth fraction) | 0.85 | 전체 레이어의 85% 이상에서만 수렴 = deep-thinking |

### 2.3 Think@n Strategy

1. n개의 candidate response 생성
2. **50 토큰 prefix만으로** DTR 계산 (early prediction)
3. DTR 상위 eta%만 선별 → majority voting
4. 결과: 정확도 유지/향상 + **inference 토큰 비용 ~50% 절감**

## 3. Experimental Results

### 3.1 Correlation Analysis (DTR vs Baselines)

| Metric | Avg Pearson r | 특성 |
|--------|--------------|------|
| Token Count | **-0.594** | 길수록 오히려 정확도 하락 (역상관) |
| Log Probability | 0.527 | 모델 간 불일치 |
| Negative Entropy | 0.571 | 중간 수준, 변동 큼 |
| Self-Certainty | 0.605 | 최선의 confidence baseline |
| **DTR (proposed)** | **0.683** | 가장 강하고 안정적인 양의 상관 |

핵심 발견: **토큰 수와 정확도는 음의 상관** (r=-0.594). 기존 "길게 생각하면 좋다"는 가정을 정면 반박.

### 3.2 Think@n Performance

| Model | Benchmark | Cons@n Acc | Cons@n Tokens | Think@n Acc | Think@n Tokens | Savings |
|-------|-----------|-----------|---------------|-------------|----------------|---------|
| OSS-120B-medium | AIME 2025 | 92.7% | 307.6k | **94.7%** | 155.4k | **-49%** |
| Qwen3-30B | AIME 2025 | 86.7% | 1073.1k | **90.0%** | 537.5k | **-50%** |

전 벤치마크에서 Think@n이 self-consistency 대비 동일/상회 정확도 + ~50% 토큰 절감.

### 3.3 Benchmarks Used

- **AIME 2024/2025**: American Invitational Mathematics Examination
- **HMMT 2025**: Harvard-MIT Mathematics Tournament
- **GPQA-Diamond**: Graduate-level science Q&A

### 3.4 Models Evaluated

- GPT-OSS (20B / 120B) — Google 내부 모델
- DeepSeek-R1-70B
- Qwen3-30B-Thinking

## 4. Why JSD? (Distance Metric Ablation)

| Metric | 결과 |
|--------|------|
| KL Divergence | 비대칭, 수치 불안정 (AIME 25에서 부호 반전) |
| Cosine Similarity | 약한 상관 (r=0.633 AIME, r=0.172 HMMT) |
| **JSD** | 대칭, 유계 [0,1], 최적 |

## 5. Theoretical Foundation — 선행 연구 계보

DTR은 아래 연구들의 연장선에 있다:

### 5.1 Logit Lens → Tuned Lens (레이어별 예측 관찰)

| Paper | Year | Contribution |
|-------|------|-------------|
| **nostalgebraist, "Logit Lens"** | 2020 | Transformer 중간 레이어에 unembedding 직접 적용하여 예측 엿보기. GPT-2에서 유효하나 대형 모델에서 불안정 |
| **Belrose et al., "Tuned Lens"** (arXiv 2303.08112) | 2023 | 레이어별 affine probe 훈련 → KL divergence 최소화. 20B 모델까지 안정적. "coarse guess → iterative refinement" 프레임워크 확립 |
| **DTR (본 논문)** | 2026 | Tuned Lens의 관찰을 **정량적 메트릭으로 조작화** → inference routing에 활용 |

### 5.2 DoLa (레이어 대비 디코딩)

| Paper | Year | Contribution |
|-------|------|-------------|
| **Chuang et al., "DoLa"** (arXiv 2309.03883, ICLR 2024) | 2023 | 후반 레이어 vs 전반 레이어의 logit 차이로 디코딩 → factuality 향상 (TruthfulQA +12-17%) |
| **DTR과의 관계** | — | DoLa는 레이어 간 차이를 **디코딩 전략**에 사용, DTR은 **추론 노력 측정**에 사용. 동일한 "레이어별 분포 변화" 신호를 다른 목적으로 활용 |

### 5.3 Overthinking / Inverse Scaling 연구

DTR이 해결하려는 문제의 배경:

| Paper | arXiv | Year | Key Finding |
|-------|-------|------|-------------|
| **"Don't Overthink It"** | 2505.17813 | 2025 | 짧은 reasoning chain이 긴 것보다 **최대 34.5% 더 정확** |
| **"When More is Less"** | 2502.07266 | 2025 | CoT 길이와 정확도는 **역 U자 커브** — 최적점 이후 성능 하락. 능력 높은 모델일수록 짧은 CoT 선호 |
| **"Between Underthinking and Overthinking"** | 2505.00127 | 2025 | LLM은 쉬운 문제에서 overthink, 어려운 문제에서 underthink — 양방향 비효율 |
| **"Evolution of Thought" (RCPD)** | 2508.17627 | 2025 | Reasoning Completion Point 이후의 computation은 무의미. RCPD로 토큰 **44% 절감** |
| **Inverse Scaling in TTC** (Anthropic 등) | — | 2025 | 긴 추론이 **적극적으로 성능을 해침** — 5가지 메커니즘 식별 |

## 6. 관련 연구 — Efficient Reasoning 생태계

DTR과 같은 문제(추론 효율화)를 다른 각도에서 접근한 논문들:

### 6.1 Token Budget / Compute Allocation

| Paper | arXiv / Venue | Key Idea |
|-------|---------------|----------|
| **"Token-Budget-Aware LLM Reasoning"** | ACL Findings 2025 | 문제 난이도별 토큰 예산 할당 → 토큰 67% 절감, 비용 59% 절감, 정확도 80.22% 유지 |
| **"Plan and Budget"** | OpenReview 2025 | 복잡 질의를 sub-question으로 분해 + 난이도별 토큰 예산 → 정확도 70% 향상, 토큰 39% 절감 |
| **"Increasing the Thinking Budget is Not All You Need"** | arXiv 2512.19585 | 단순히 thinking budget 증가 < self-consistency + reflection 조합. Summary 전략이 최고 성능 |

### 6.2 Thinking Token Suppression

| Paper | arXiv | Key Idea |
|-------|-------|----------|
| **"Wait, We Don't Need to Wait!"** (NoWait) | 2506.08343 (EMNLP 2025) | "Wait", "Hmm" 등 self-reflection 토큰 억제 → CoT 길이 **27-51% 감소**, 성능 유지. Plug-and-play |

### 6.3 Adaptive Test-Time Compute

| Paper | arXiv / Venue | Key Idea |
|-------|---------------|----------|
| **"Scaling LLM Test-Time Compute Optimally"** | ICLR 2025 | Inference compute scaling이 parameter scaling보다 효율적인 조건 도출 |
| **"The Art of Scaling Test-Time Compute"** | arXiv 2512.02008 | 30B+ 토큰 생성 실험으로 TTS 전략 체계적 비교 |
| **"Reasoning on a Budget" (Survey)** | arXiv 2507.02076 | Adaptive & controllable test-time compute 서베이 |
| **"Optimal Self-Consistency"** | arXiv 2511.12309 | Self-consistency의 power-law scaling 분석 + Blend-ASC 알고리즘 |

### 6.4 Reasoning Distillation (구조적 전이)

| Paper | arXiv | Key Idea |
|-------|-------|----------|
| **"Reasoning Scaffolding"** | 2509.23619 | 추론을 semantic signal (Contrast, Addition 등)로 추상화 → 구조적 scaffold로 distillation |
| **"D-COT" (Disciplined CoT)** | 2602.21786 | 규율화된 CoT distillation |
| **"Skip-Thinking"** | 2505.18642 | Chunk 단위 CoT distillation → 소형 모델 추론 가속 |

## 7. DTR의 위치: 패러다임 맵

```
                     외부 스캐폴드                내부 메커니즘
                     (prompting)                  (model internals)
                          |                            |
    ┌─────────────────────┼────────────────────────────┼───────────────────┐
    │                     │                            │                   │
길이 │  CoT Prompting      │  Self-Consistency          │  Thinking Tokens  │
기반 │  SELF-DISCOVER      │  (majority voting)         │  (Gemini 2.5)     │
    │                     │                            │                   │
    ├─────────────────────┼────────────────────────────┼───────────────────┤
    │                     │                            │                   │
효율 │  Plan-and-Budget    │  Token-Budget-Aware        │  NoWait           │
기반 │  Reasoning Scaffold │  Optimal Self-Consistency  │  RCPD             │
    │                     │                            │                   │
    ├─────────────────────┼────────────────────────────┼───────────────────┤
    │                     │                            │                   │
깊이 │                     │  Think@n                   │  ★ DTR ★          │
기반 │                     │  (DTR + voting)            │  DoLa             │
    │                     │                            │  Tuned Lens       │
    └─────────────────────┴────────────────────────────┴───────────────────┘
```

**DTR의 차별점**: 유일하게 **모델 내부의 레이어별 계산 깊이**를 직접 관찰하여 추론 품질을 측정. Training-free, 50 토큰 prefix로 예측 가능.

## 8. Limitations & Open Questions

| 한계 | 설명 |
|------|------|
| **모델 간 비교 불가** | DTR 절대값은 모델 아키텍처에 종속 — 모델 A DTR 0.3 vs 모델 B DTR 0.5 직접 비교 불가 |
| **도메인 한정** | 수학/과학 벤치마크에서만 검증. 코딩, 상식추론, 다국어 등 미검증 |
| **하이퍼파라미터 민감도** | g=0.5, rho=0.85는 경험적 최적 — 새 모델/태스크에서 재튜닝 필요 가능 |
| **Reasoning Level 역설** | GPT-OSS에서 높은 reasoning level → 낮은 DTR but 높은 정확도. 계산이 깊이에서 길이로 재분배되는 현상. DTR이 항상 "높을수록 좋다"는 아님 |
| **Closed-model 적용 불가** | 중간 레이어 접근 필요 → API-only 모델 (GPT-4, Claude 등)에서 사용 불가 |

## 9. Implications for Agent/Scaffold Design

DTR 연구가 에이전트 시스템 설계에 주는 시사점:

1. **길이 =/= 품질**: 에이전트의 reasoning trace가 길다고 좋은 것이 아님. 스캐폴드가 "더 길게 생각하라"고 유도하면 오히려 성능 하락 가능
2. **Early Stopping 근거**: 50 토큰 prefix로 reasoning 품질 예측 가능 → 에이전트가 초기에 불량 trajectory를 버리는 전략 근거
3. **Compute Routing**: 모든 문제에 동일한 compute 할당 대신, 문제 난이도에 따라 적응적 할당이 효율적
4. **내부 신호 활용**: Open-weight 모델 사용 시 DTR을 실시간 라우팅 신호로 활용 가능

## 10. References

### Primary Paper
- [Think Deep, Not Just Long (arXiv 2602.13517)](https://arxiv.org/abs/2602.13517)

### Foundational Works (Layer-wise Analysis)
- [Tuned Lens — Belrose et al. (arXiv 2303.08112)](https://arxiv.org/abs/2303.08112)
- [DoLa — Chuang et al. (arXiv 2309.03883)](https://arxiv.org/abs/2309.03883)

### Overthinking / Inverse Scaling
- [Don't Overthink It (arXiv 2505.17813)](https://arxiv.org/abs/2505.17813)
- [When More is Less (arXiv 2502.07266)](https://arxiv.org/abs/2502.07266)
- [Between Underthinking and Overthinking (arXiv 2505.00127)](https://arxiv.org/abs/2505.00127)
- [Evolution of Thought / RCPD (arXiv 2508.17627)](https://arxiv.org/abs/2508.17627)

### Efficient Reasoning
- [Token-Budget-Aware LLM Reasoning (ACL Findings 2025)](https://aclanthology.org/2025.findings-acl.1274.pdf)
- [Increasing the Thinking Budget is Not All You Need (arXiv 2512.19585)](https://arxiv.org/abs/2512.19585)
- [Wait, We Don't Need to Wait! / NoWait (arXiv 2506.08343)](https://arxiv.org/abs/2506.08343)
- [Plan and Budget (OpenReview 2025)](https://openreview.net/forum?id=ctspw4CqbS)

### Test-Time Compute Scaling
- [Scaling LLM Test-Time Compute Optimally (ICLR 2025)](https://openreview.net/forum?id=4FWAwZtd2n)
- [The Art of Scaling Test-Time Compute (arXiv 2512.02008)](https://arxiv.org/abs/2512.02008)
- [Reasoning on a Budget Survey (arXiv 2507.02076)](https://arxiv.org/abs/2507.02076)
- [Optimal Self-Consistency (arXiv 2511.12309)](https://arxiv.org/abs/2511.12309)

### Reasoning Distillation
- [Reasoning Scaffolding (arXiv 2509.23619)](https://arxiv.org/abs/2509.23619)
- [D-COT (arXiv 2602.21786)](https://arxiv.org/abs/2602.21786)
- [Skip-Thinking (arXiv 2505.18642)](https://arxiv.org/abs/2505.18642)

### Google Reasoning Models
- [SELF-DISCOVER (arXiv 2402.03620, NeurIPS 2024)](https://arxiv.org/abs/2402.03620)
- [Gemini 2.5 Technical Report (arXiv 2507.06261)](https://arxiv.org/abs/2507.06261)
- [GitHub: Think-Deep-Not-Long Implementation](https://github.com/compchap/Think-Deep-Not-Long)

---

*Research compiled: 2026-04-15*
