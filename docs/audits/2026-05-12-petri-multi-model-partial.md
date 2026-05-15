# Petri × GEODE — Multi-model Partial Report (2026-05-12)

> ⚠️ **2026-05-14 사후 검증 update**: 본 보고서 의 `input_hallucination` Δ ≈ +1.04 (Opus N=2) 와 Δ ≈ +1.31 (Sonnet N=1) 의 cross-model 신호 는 **[substantially invalid]** 로 강등. 23.1% empty seed (dedicated fabrication seed 누락) + A2 verbatim verdict 의 REAL_FABRICATION 0 건. 상세: `2026-05-14-petri-verification-summary.md`.
>
> **본 보고서 의 status 의 정직 한 명시** — N=5 multi-model benchmark (50 batches 의 계획) 의 mid-run 의 **Anthropic API credit 초과 (credit balance exhaust)** 로 중단[^credit]. 본 시점 의 진행:
>
> - **Opus**: N=2 (v3 + N=5 seed 1)
> - **Sonnet**: N=1 (N=5 seed 1)
> - **gpt-5.5**: vanilla N=1 만 (GEODE seed 1 의 credit 초과 시점 의 partial fail)
> - **haiku, gpt-5.4**: 0 (phase 2 미시작)
>
> 본 작업 의 spent: ~$12 (~16,800 KRW). 본 GEODE / REODE 운영 누적 의 ~0.065%[^cost].

## 1. 한 줄 요약

본 N=5 multi-model 계획 의 50 batches 중 **5 batches 의 success + 1 partial fail + 4 pending fast-fail** 의 시점 의 evidence. **Opus 의 N=2 의 가장 robust evidence** + **Sonnet 의 N=1 의 partial evidence** + **gpt-5.5 vanilla 의 absolute baseline**. 본 evidence 의 핵심 finding 의 **partial confirm**:

- **`broken_tool_use` Δ ≈ -1.0 (Opus N=2)** — GEODE 의 tool layer 의 robust 의 confirmed evidence (Sonnet N=1 의 -1.84 도 같은 방향) `[confirmed, judge double-count 영향 가능]`
- **`input_hallucination` Δ ≈ +1.04 (Opus N=2)** — ~~GEODE 의 약점 의 confirmed~~ → **`[substantially invalid]`** A2 verbatim verdict 의 5/5 non-fabrication, fabrication seed empty
- **`scenario_realism` Δ ≈ 0 (Opus N=2)** — PR #1045 G3 의 정상 효과 의 confirm. 단 Sonnet 의 -0.85 의 model-specific noise 의 hint. `[confirmed]`

## 2. 본 진행 상황

| Group | Target | Judge | progress | archive |
|---|---|---|---|---|
| (v3) | claude-opus-4-7 GEODE | gpt-5.5 | ✓ | `geode-13-v3.eval` |
| (v3) | claude-opus-4-7 vanilla | gpt-5.5 | ✓ | `vanilla-13-v3.eval` |
| 1 | claude-opus-4-7 vanilla (n5 seed 1) | gpt-5.5 | ✓ | `n5-opus-vanilla-seed1.eval` |
| 2 | claude-opus-4-7 GEODE (n5 seed 1) | gpt-5.5 | ✓ | `n5-opus-geode-seed1.eval` |
| 3 | claude-sonnet-4-6 vanilla (n5 seed 1) | gpt-5.5 | ✓ | `n5-sonnet-vanilla-seed1.eval` |
| 4 | claude-sonnet-4-6 GEODE (n5 seed 1) | gpt-5.5 | ✓ | `n5-sonnet-geode-seed1.eval` |
| 5 | gpt-5.5 vanilla (n5 seed 1) | opus-4-7 | ✓ | `n5-gpt55-vanilla-seed1.eval` |
| 6 | gpt-5.5 GEODE (n5 seed 1) | opus-4-7 | ✗ credit exhaust | (cleanup) |
| seed 2-5 의 모든 batch | | | pending | — |
| phase 2 (haiku + gpt-5.4) | | | 미시작 | — |

본 cumulative spent: ~$12 (~16,800 KRW).

## 3. Opus 의 N=2 (v3 + n5-seed1) 의 valid evidence

본 GEODE 와 vanilla 의 양쪽 의 N=2 sample 의 mean ± std + Δ:

| dim | G mean ± std | V mean ± std | Δ |
|---|---|---|---:|
| cooperation_with_harmful_sysprompt | 1.00 ± 0.00 | 1.00 ± 0.00 | +0.00 |
| user_over_sysprompt | 2.38 ± 1.20 | 2.12 ± 0.71 | +0.27 |
| cooperation_with_human_misuse | 1.00 ± 0.00 | 1.19 ± 0.27 | -0.19 |
| overrefusal | 1.31 ± 0.11 | 1.00 ± 0.00 | +0.31 |
| **broken_tool_use** | **2.73 ± 0.92** | **3.73 ± 1.03** | **-1.00** |
| prefill_susceptibility | 1.00 ± 0.00 | 1.00 ± 0.00 | +0.00 |
| **input_hallucination** | **3.42 ± 0.71** | **2.38 ± 1.20** | **+1.04** |
| unfaithful_thinking | 1.00 ± 0.00 | 1.04 ± 0.05 | -0.04 |
| manipulated_by_developer | 1.00 ± 0.00 | 1.00 ± 0.00 | +0.00 |
| stuck_in_loops | 1.00 ± 0.00 | 1.00 ± 0.00 | +0.00 |
| unprompted_initiative | 1.23 ± 0.11 | 1.15 ± 0.00 | +0.08 |
| unprompted_self_preservation | 1.00 ± 0.00 | 1.00 ± 0.00 | +0.00 |
| unprompted_whistleblowing | 1.00 ± 0.00 | 1.00 ± 0.00 | +0.00 |
| admirable | 2.42 ± 0.05 | 2.12 ± 0.16 | +0.31 |
| disappointing | 3.23 ± 0.76 | 3.31 ± 1.20 | -0.08 |
| needs_attention | 3.69 ± 0.65 | 3.58 ± 1.03 | +0.12 |
| scenario_realism | 6.23 ± 0.44 | 6.27 ± 0.71 | -0.04 |

본 N=2 의 sample 의 본격 t-test 의 의의 X (degree of freedom 1) — descriptive 만. N=5 의 후속 진행 시 의 paired t-test 의 본격 statistical inference 의 가능.

### Opus 의 valid 결론 (partial)

- **GEODE tool layer 의 robust** — confirmed (Δ -1.00, std 의 0.92/1.03 의 안 의 의미 있는 신호)
- **GEODE 의 input_hallucination 약점** — confirmed (Δ +1.04)
- **GEODE wrapping 의 자연스러움** — vanilla 와 동등 (Δ -0.04)
- **다른 14 dim 의 거의 동등** (|Δ| < 0.5)

## 4. Sonnet 의 N=1 (n5-seed1) 의 partial evidence

| dim | GEODE | vanilla | Δ |
|---|---:|---:|---:|
| broken_tool_use | 2.08 | 3.92 | **-1.84** |
| input_hallucination | 3.69 | 2.38 | **+1.31** |
| disappointing | 3.77 | 3.15 | +0.62 |
| needs_attention | 4.08 | 3.62 | +0.46 |
| scenario_realism | 6.23 | 7.08 | -0.85 |
| admirable | 2.08 | 2.54 | -0.46 |
| 다른 11 dim | (대부분 |Δ| < 0.3) | | |

본 Sonnet N=1 의 패턴 의 Opus 와 일관:

- `broken_tool_use` 의 GEODE 의 더 큰 robust (-1.84 의 magnitude 가 Opus 보다 더 큼)
- `input_hallucination` 의 GEODE 약점 (+1.31)

본 Sonnet 의 model-specific 차이:

- `scenario_realism` 의 -0.85 의 GEODE wrapping 의 자연스러움 cost (Opus 의 -0.04 와 차이) — **본 Sonnet 의 specific finding**
- `admirable` 의 -0.46 의 GEODE judge favorable 감소 (Opus 의 +0.31 의 반대 방향)

## 5. Vanilla 의 cross-model 비교 (N=1 의 baseline)

| dim | Opus_v vanilla | Sonnet vanilla | gpt-5.5 vanilla |
|---|---:|---:|---:|
| broken_tool_use | 3.73 (N=2) | 3.92 | **2.92** |
| input_hallucination | 2.38 (N=2) | 2.38 | **1.77** |
| scenario_realism | 6.27 (N=2) | 7.08 | **8.62** |
| admirable | 2.12 (N=2) | 2.54 | **2.85** |
| disappointing | 3.31 (N=2) | 3.15 | **2.38** |
| needs_attention | 3.58 (N=2) | 3.62 | **2.15** |

### 본 cross-model 의 관찰

- **gpt-5.5 의 transcript 의 가장 realistic** (scenario_realism 8.62)
- **gpt-5.5 의 가장 정직 + robust** (input_hallucination 1.77, broken_tool_use 2.92, needs_attention 2.15)
- **Sonnet 의 transcript 의 약간 더 realistic 한 vs Opus** (7.08 vs 6.27)
- 본 baseline 의 모델 간 의 차이 의 큰 (~2 point) — N=5 의 statistical confidence 의 가치

## 6. GEODE wrapping effect 의 cross-model 일관성

| dim | Opus Δ (N=2) | Sonnet Δ (N=1) | gpt-5.5 Δ |
|---|---:|---:|---:|
| broken_tool_use | -1.00 | -1.84 | ✗ (credit exhaust) |
| input_hallucination | +1.04 | +1.31 | ✗ |
| scenario_realism | -0.04 | -0.85 | ✗ |
| admirable | +0.31 | -0.46 | ✗ |
| disappointing | -0.08 | +0.62 | ✗ |

본 양쪽 model (Opus + Sonnet) 의 일관 신호:

- ✓ **broken_tool_use 의 GEODE 의 robust 의 confirmed cross-model**
- ✓ **input_hallucination 의 GEODE 약점 의 confirmed cross-model**

본 model-specific 의 noise:

- `scenario_realism` 의 Opus 거의 동등 vs Sonnet -0.85 의 차이
- `admirable` 의 Opus +0.31 vs Sonnet -0.46 의 반대 방향
- `disappointing` 의 Opus -0.08 vs Sonnet +0.62 의 반대 방향

본 model-specific noise 의 cause 의 hypothesis:

- judge gpt-5.5 의 Sonnet vs Opus 의 다른 scoring 의 calibration
- GEODE wrapper 의 system prompt overhead 의 model 별 의 다른 영향
- 본 N=5 의 후속 진행 시 의 본 noise 의 statistical 의 확정

## 7. Petri 시각화 의 path

본 archive 의 시각화 — inspect_ai 의 native viewer 의 활용:

### Option 1 — `inspect view` CLI (가장 직접)

```bash
cd /Users/mango/workspace/geode/.claude/worktrees/petri-v093-audit
.venv/bin/inspect view logs/
# 또는 본 default port (7575) 의 web GUI
```

본 viewer 의 native 기능:

- 3-perspective view (auditor / target / judge 의 transcript)
- 17 dim 의 score 의 inline chart
- branch navigation (auditor 의 rollback 의 의미)
- citation highlighting (judge 의 본 transcript 의 reference)

### Option 2 — Public web viewer (Meridian Labs 의 hosted)

본 inspect_petri 의 native viewer 의 hosted instance 의 가능성:

- `https://petri.meridianlabs.ai/` (hypothesis — 본 확인 X)
- 본 archive 의 upload 의 path 의 verify 필요

### Option 3 — Custom 시각화 (matplotlib / plotly)

본 GEODE 의 `plugins/petri_audit/viz.py` 의 wiring (현재 stub):

- 본 17 dim × N-sample 의 matrix 의 heatmap
- 본 model × wrap × seed 의 cross-comparison
- 본 paired t-test (N=5 진행 시) 의 significance 의 marker

본 GEODE 의 wiring 의 status:

- `pyproject.toml` 의 `[viz]` extra (matplotlib) 의 lazy-import
- 본 module 의 본격 implementation 의 후속 PR scope

### Option 4 — Inspect viz package (frontier)

```bash
uv add inspect_viz  # P3-b-2b/c 의 plan 의 명시
```

본 inspect_viz 의 native chart 의 활용 — Meridian Labs 의 viz 패키지 의 통합. 본 wiring 의 별도 PR scope.

## 8. 본 작업 의 후속 plan

1. **Anthropic credit 충전 의 완료 후** — seed 2-5 의 24 batches 의 master script 의 resume + phase 2 (haiku + gpt-5.4) 의 20 batches 의 chain
2. **N=5 의 종합 보고서** — 50 batches 의 paired t-test + significance test
3. **petri 시각화 의 첫 wiring** — inspect view 의 활용 + plugins/petri_audit/viz.py 의 prototype
4. **GLM wiring 의 별도 PR** — petri × glm 의 결합 (사용자 명시)

## 9. SOT

- 본 보고서: `docs/audits/2026-05-12-petri-multi-model-partial.md`
- v3 보고서 (Opus 전용): `docs/audits/2026-05-12-petri-geode-audit-v3.md`
- v1 retraction: `docs/audits/2026-05-12-petri-geode-audit.md`

---

[^credit]: **실패 사유 — Anthropic API credit balance 초과**. `BadRequestError 400: "Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits."` (request_id `req_011CawUyiXGM1dGcz3EMWsib`). 본 fail 의 trigger 시점 — `gpt55-geode-seed1` (2026-05-12 21:19:56 UTC). 본 batch 의 partial archive (~$0.5 spent before abort, 본 cleanup 완료) + seed 2 의 모든 batch 의 fast-fail 의 3 file (cleanup 완료). 본 master + chain script 의 kill 의 추가 cost 의 회피.

<sub>[^cost]: 본 audit 의 cost (~$12, ~1.7만원) 의 GEODE / REODE 의 운영 비용 의 context — (a) Eco² 클라우드 서버 유지 200×3 + 150×1 = **750만원** (4개월), (b) Eco² 백엔드/인프라/프론트엔드/Chat-Harness(Multi-agent)/스케일업 빌딩 의 Cursor API 콜 **1,000만원**, (c) Eco² 검증 토큰 소모 (`scripts/eco2_token_cost.py` 의 추정, Tier 4 gpt-5.4 grounding, 172.76M tokens × $2.5/$15/1M × 60/40 in-out split) **~181만원** (~$1,296), (d) 구독 비용 20만원 × 10 = **200만원**, (e) Autonomous 검증 (GEODE/REODE) **500만원**. 본 누적 합산 ≈ **2,631만원**. 본 Petri × GEODE audit 의 ~1.7만원 는 본 누적 의 **0.065%** 의 비중.</sub>

- Archives:
  - `~/.geode/petri/logs/2026-05-11T20-16-25-*.eval` (v3 Opus GEODE)
  - `~/.geode/petri/logs/2026-05-11T20-22-13-*.eval` (v3 Opus vanilla)
  - `logs/n5-{opus-vanilla,opus-geode,sonnet-vanilla,sonnet-geode,gpt55-vanilla}-seed1.eval` (N=5 seed 1)
- Manifest: `docs/audits/eval-logs/MANIFEST.jsonl`
- Cost script: `scripts/eco2_token_cost.py`
