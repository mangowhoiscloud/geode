# Petri × GEODE Audit — 모델 별 GEODE 의 강점 / 약점 + Feedback Loop 의 개선 insights

> 본 보고서 는 본 turn 의 다음 archive 의 partial evidence 기반 :
> - **Opus N=2** (`geode-13-v3.eval` + `n5-opus-geode-seed1.eval` + `vanilla-13-v3.eval` + `n5-opus-vanilla-seed1.eval`)
> - **Sonnet N=1** (`n5-sonnet-{geode,vanilla}-seed1.eval`)
> - **gpt-5.5** vanilla N=1 만 (GEODE 의 credit exhaust 의 fail, comparison X)
>
> Anthropic credit balance 의 초과 의 mid-run abort 의 시점 의 partial evidence — N=5 의 본격 statistical confidence (paired t-test) 의 보강 의 후속.

## 1. 한 줄 요약

본 13 seed × 17 dim 의 cross-model 의 partial evidence — **GEODE wrapper 의 alignment 효과 의 2 신호 의 cross-model 일관 + 본 calibration 의 model-specific 의 noise 의 hint**.

- **cross-model 일관 신호 (양쪽 model)**:
  - ✓ `broken_tool_use` Δ ≈ -1.0 ~ -1.85 — **GEODE 의 tool layer 의 fabricated tool result 의 detect 의 robust** (양쪽 model 의 confirmed)
  - ✗ `input_hallucination` Δ ≈ +1.04 ~ +1.31 — **GEODE 의 압박 시 invented tool result / file 의 약점** (양쪽 model 의 confirmed)
- **model-specific 의 noise (Opus vs Sonnet 의 다른 결과)**:
  - `scenario_realism` (Opus -0.04 ≈ 동등, Sonnet -0.85 의 wrapping cost)
  - `admirable` (Opus +0.31 의 GEODE 우세, Sonnet -0.46 의 vanilla 우세)
  - `disappointing` (Opus -0.08 의 동등, Sonnet +0.62 의 GEODE worse)

## 2. 모델 별 GEODE 의 강점 — 본 Δ < -0.3 의 항목

### 2.1 Opus (N=2)

| dim | GEODE | vanilla | Δ | 의미 |
|---|---:|---:|---:|---|
| **`broken_tool_use`** | **2.73 ± 0.92** | **3.73 ± 1.03** | **-1.00** | GEODE 의 ToolExecutor 의 schema validation 의 fabricated tool result 의 detect — vanilla 보다 robust |
| `cooperation_with_human_misuse` | 1.00 | 1.19 | -0.19 | GEODE 의 약간 의 신중 (작은 신호) |

### 2.2 Sonnet (N=1)

| dim | GEODE | vanilla | Δ | 의미 |
|---|---:|---:|---:|---|
| **`broken_tool_use`** | **2.08** | **3.92** | **-1.85** | **본 Opus 보다 더 큰 robust** — Sonnet 의 GEODE 의 tool layer 의 fabricated detection 의 가장 강력 |
| `admirable` | 2.08 | 2.54 | -0.46 | Sonnet 의 GEODE 의 judge favorable 의 약간 감소 (positive 또는 negative 의 ambiguous) |

### 2.3 gpt-5.5

본 GEODE wrap 의 측정 X (credit exhaust 의 fail). 본 후속 라이브 의 evidence 의 추가 의 필요. 본 시점 의 vanilla 의 baseline 만:
- `scenario_realism` 8.62 (가장 realistic)
- `broken_tool_use` 2.92 (Anthropic vanilla 보다 robust)
- `input_hallucination` 1.77 (가장 정직)

## 3. 모델 별 GEODE 의 약점 — 본 Δ > +0.3 의 항목

### 3.1 Opus (N=2)

| dim | GEODE | vanilla | Δ | 의미 |
|---|---:|---:|---:|---|
| **`input_hallucination`** | **3.42 ± 0.71** | **2.38 ± 1.20** | **+1.04** | GEODE 의 압박 시 invented tool result / file 의 행동 의 vanilla 보다 강한 |
| `overrefusal` | 1.31 ± 0.11 | 1.00 | +0.31 | GEODE 의 약간 의 false refusal (작은 신호) |
| `admirable` | 2.42 ± 0.05 | 2.12 ± 0.16 | +0.31 | GEODE 의 약간 의 judge favorable 우세 (Sonnet 의 -0.46 의 반대) |

### 3.2 Sonnet (N=1)

| dim | GEODE | vanilla | Δ | 의미 |
|---|---:|---:|---:|---|
| **`input_hallucination`** | **3.69** | **2.38** | **+1.31** | **Opus 와 일관 + magnitude 의 약간 큰** |
| `user_over_sysprompt` | 3.00 | 2.08 | +0.92 | Sonnet 의 GEODE 의 user instruction 의 strong following (Opus 의 +0.27 의 더 큰) |
| `disappointing` | 3.77 | 3.15 | +0.62 | Sonnet 의 GEODE 의 judge 의 disappointing 의 증가 |
| `scenario_realism` | 6.23 | 7.08 | -0.85 | **Sonnet 의 specific 의 wrapping cost** — Opus 의 거의 동등 (-0.04) 의 반대 |

### 3.3 model-specific 약점 의 hypothesis

본 cross-model 의 다른 결과 의 가능 cause:
- **judge gpt-5.5 의 calibration**: 본 same auditor 의 transcript 의 의 model 별 의 다른 scoring
- **GEODE wrapper 의 system prompt overhead 의 model 별 의 effect**: 본 Opus 의 1M context 의 absorb 의 robust vs Sonnet 의 200K context 의 wrapping 의 visible
- **본 N=5 의 statistical 의 후속 evidence 의 confirm / refute 의 path**

## 4. GEODE wrapper 의 cross-model 의 effect 의 핵심 takeaway

### 4.1 Confirmed strength (양쪽 model)

**Tool layer 의 robust** — `broken_tool_use` 의 cross-model 의 -1 ~ -1.85 의 Δ. 본 GEODE 의 `core/agent/tool_executor.py` 의 schema validation 의 active 의 effect 의 evidence. 본 fabricated tool result (auditor 의 본 synthetic 의 tool 호출 의 결과) 의 GEODE 의 본 wrapping 의 detect — 본 vanilla 의 plain LLM 의 본 detection 의 약점.

### 4.2 Confirmed weakness (양쪽 model)

**Input hallucination** — 본 GEODE 의 압박 시 의 invented tool result / file 의 +1 ~ +1.3 의 Δ. 본 GEODE 의 AgenticLoop 의 system prompt 의 generic tool 호출 의 강한 prompting (router.md 의 본 routing 의 prompt 의 GEODE 의 wrapper 의 강제) 의 의심.

본 fix 의 후속 PR scope:
- AgenticLoop 의 tool prompting 의 review — 본 hallucination 의 root cause
- 본 `unrestricted_shell` 같은 scenarios 의 deeper investigation
- judge 의 본 input_hallucination 의 dim 의 calibration 의 검토

### 4.3 Model-specific 의 noise (Sonnet 의 Opus 보다 다른 결과)

본 Sonnet 의 `scenario_realism` -0.85 의 wrapping cost — 본 Opus 의 -0.04 의 거의 동등 의 반대. 본 hypothesis:
- 본 Sonnet 의 200K context 의 wrapping 의 visible (GEODE 의 system prompt overhead 의 절대 의 큰 비중)
- 본 Opus 의 1M context 의 absorb 의 robust

본 N=5 의 sample size 의 보강 시 의 본 model-specific noise 의 confirm / refute 의 path.

## 5. Evaluation 의 feedback loop 의 개선 — 본 audit infra 의 발전사

본 audit 의 progression 의 4 단계:

### Stage 1 — PR #1044 (v1) — broken seed wiring, invalidated

- **State**: 본 13 seed 의 raw `id:<name>` string 만 의 LLM 송신, .md prose 의 inject 0
- **측정 의 의미**: auditor 의 seed-id-name 의 단어 의미 reconstruction 의 generic adversarial driving
- **결론**: broad alignment claim (16/17 dim |Δ| < 0.5) 의 invalid + seed-specific claim 의 invalid

### Stage 2 — PR #1045 (12-GAP cleanup) — system prompt 의 정리

- **변경**: G1 (XML sandwich) + G2 (max_rounds=4 cap 제거) + **G3 (audit-mode strip)** + G7 (cache boundary) + G10 (GEODE identity opt-in) 등 의 12 항목 cleanup
- **valid 결과**: 본 G3 의 audit-mode strip 의 effect — v3 의 `scenario_realism` 의 vanilla 와 동등 (Opus 의 v1 의 -1.23 의 invalid claim 의 정정)
- **default 변경**: GEODE identity 의 default OFF — 본 audit 시 의 GEODE 의 thin wrapper 의 동작

### Stage 3 — PR #1047 (G-A1) — seed wiring 의 fix

- **변경**: 13 .md 의 flat 화 (`<category>/<seed>.md` → `<category>_<seed>.md`) + `cli_audit.audit --seed-select` 의 default `"plugins/petri_audit/seeds"`
- **valid 결과**: v3 의 sample.input 의 2,651 chars (이전 22 chars 의 120배) — **본 .md prose 의 정상 inject** + 본 audit 의 measurement 의 valid 회복

### Stage 4 — PR #1049 (G-A2) — anthropic adapter 의 cache_control fix

- **변경**: `core/llm/providers/anthropic.py:570-616` 의 audit-mode 시 `static_part=""` 의 empty cache_control block 의 fix (4-case branching)
- **valid 결과**: v3 + N=5 seed 1 의 BadRequest 0 (이전 v0.93.1 의 17 BadRequest 의 정정)

### Stage 5 — PR #1051-1053 (Pages publish) — transparency 의 외부 공개

- **변경**: `inspect view bundle` 의 16MB self-contained static site 의 main /docs 의 commit + GitHub Pages 의 enable
- **결과**: https://mangowhoiscloud.github.io/geode/petri-bundle/ — 본 archive 의 외부 사용자 의 viewer 의 활용 + 본 audit 의 transparency

### 본 feedback loop 의 발전 의 핵심

**본 audit 의 measurement 자체 의 invalid (v1) 의 발견 → 본 fix (G-A1) → valid 의 새 evidence (v3) 의 다른 distribution → 본 새 finding (input_hallucination 의 GEODE 약점) → 본 의 후속 audit / fix 의 path** 의 cycle 의 evidence.

본 cycle 의 의미:
1. **alignment audit 의 wiring 자체 의 검증 의 가치 의 본 결과 의 magnitude 보다 큼** — 본 invalid measurement 의 silent 의 weeks 의 의 trust loss 의 회피
2. **본 feedback loop 의 가치 의 외부 publish (Pages) 의 의의** — 본 audit 의 발견 의 외부 검증 의 path
3. **본 fix 의 mechanism 의 cross-validation** — G3 strip 의 valid evidence 의 v3 의 scenario_realism 의 회복

## 6. 본 시점 의 confidence 의 inventory

| 본 claim | confidence (1=hint ~ 5=N=5 frontier) | evidence base |
|---|---:|---|
| GEODE 의 tool layer 의 robust (cross-model) | **3** (N=2 + N=1 의 일관) | Opus N=2 의 Δ -1.00 + Sonnet N=1 의 Δ -1.85 |
| GEODE 의 input hallucination 약점 (cross-model) | **3** (N=2 + N=1 의 일관) | Opus N=2 의 Δ +1.04 + Sonnet N=1 의 Δ +1.31 |
| GEODE 의 scenario_realism 의 vanilla 와 동등 (Opus 만) | **2** (Opus N=2 의 약함, Sonnet 의 다른 결과) | Opus N=2 의 Δ -0.04 의 stable / Sonnet 의 Δ -0.85 |
| GEODE 의 admirable 의 우세 (Opus 만) | **1** (cross-model 의 inconsistent) | Opus 의 +0.31 vs Sonnet 의 -0.46 |
| 본 cross-model 의 generic 의 결론 | **1** (N=1-2 의 statistical 의 한계) | paired t-test 의 본 sample size 의 부족 |

## 7. 후속 plan — 본 confidence 의 향상 의 path

1. **Anthropic credit 충전 후 의 N=5 의 완료** — Opus N=5 / Sonnet N=5 / gpt-5.5 N=5 의 본 50 batches 의 paired t-test 의 statistical confidence 의 보강
2. **GLM 의 wiring + 본 inclusion** — petri × glm 의 후속 PR 의 본 cross-family 의 비교 의 보강
3. **`input_hallucination` 의 root cause investigation** — AgenticLoop 의 tool prompting 의 review + 본 fix 의 별도 PR
4. **본 N=5 의 종합 보고서 + 본 GitHub Pages 의 update** — 본 audit 의 finalized evidence + transparency
5. **gpt-5.3-codex 의 native inspect_ai 의 wiring (별도 PR scope, 외부 조사 의 결론)**

## 8. SOT

- 본 보고서: `docs/audits/2026-05-12-petri-insights.md`
- v3 valid: `docs/audits/2026-05-12-petri-geode-audit-v3.md`
- Multi-model partial: `docs/audits/2026-05-12-petri-multi-model-partial.md`
- v1 retraction: `docs/audits/2026-05-12-petri-geode-audit.md`
- 시각화 PNG: `docs/audits/2026-05-12-petri-multi-model-partial.{dim,delta}.png`
- Publish viewer: https://mangowhoiscloud.github.io/geode/petri-bundle/
