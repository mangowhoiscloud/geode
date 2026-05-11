# Petri × GEODE Audit — v3 valid 결과 보고 (2026-05-12)

> Source: PR #1044 (v1 invalid, retraction) 의 후속 — G-A1 (seeds flat) + G-A2 (anthropic empty static_part) fix 후 의 첫 valid live audit.
> Archive: `~/.geode/petri/logs/2026-05-11T20-16-25-*.eval` (GEODE) + `~/.geode/petri/logs/2026-05-11T20-22-13-*.eval` (vanilla).

## 1. 한 줄 요약

PR #1044 의 audit 결과 가 silently broken 한 seed wiring (raw seed-id string 만 LLM 송신) 의 결과 임을 발견 한 후, G-A1 (seeds directory flat 화) + G-A2 (anthropic adapter 의 empty static_part cache_control 부적 합) fix 의 첫 valid 라이브. 본 valid 결과 가 **PR #1044 의 broad claim 도 의미 적으로 다른 distribution** 임을 보임. GEODE 의 valid alignment 의 정정 결론:

- ✓ **`broken_tool_use` -0.92** (GEODE 2.08 vs vanilla 3.00) — GEODE tool layer 의 fabricated tool result 에 대한 robust 의 측정 (v1 의 -1.08 claim 의 partial confirm)
- ✗ **`input_hallucination` +1.38** (GEODE 2.92 vs vanilla 1.54) — 압박 시 GEODE 의 invented tool result/file 행동 의 vanilla 보다 강함 (새 finding, v1 의 +0.31 의 magnitude 증가)
- ≈ **`scenario_realism` +0.15** (GEODE 5.92 vs vanilla 5.77) — PR #1045 G3 (audit-mode strip) 의 정상 효과 의 evidence (v1 의 -1.23 gap 의 close)
- ≈ **behaviour_control / autonomy** 의 vanilla 와 거의 동등

비용 **$7.50 (~10,493 KRW)**, wall 8min 41s (GEODE 4:58 + vanilla 3:38).

## 2. 점검 범위 + 본 turn 의 fix 의 sequence

| 항목 | 값 |
|---|---|
| 측정 대상 A | `geode/claude-opus-4-7` (GEODE wrapper, AgenticLoop + ToolExecutor + ProfilePolicy + Readiness 의 strip = 의 audit-mode) |
| 측정 대상 B | `anthropic/claude-opus-4-7` (vanilla) |
| Auditor | `anthropic/claude-sonnet-4-6` |
| Judge | `openai/gpt-5.5` (per-token billing — Codex CLI OAuth subscription path 의 미가용, 외부 조사 결론) |
| Seeds | 13 (`plugins/petri_audit/seeds/<category>_<seed>.md` flat layout, G-A1 fix) |
| Reasoning reveal | `--reasoning-effort high --reasoning-history all` (booster A) |
| 실측 비용 | **$7.50** (GEODE $5.61 + vanilla $1.89) — 본 차이 = GEODE wrapper 의 system prompt overhead 의 cache $/ token 의 cost |
| Wall time | 8min 41s (GEODE 4min 58s + vanilla 3min 38s) |

### 본 turn 의 fix 의 sequence

1. **PR #1047 (G-A1, develop merge)** — seeds 의 `<category>/<seed>.md` → `<category>_<seed>.md` flat 화. `read_seed_directory` 의 non-recursive glob 의 fix.
2. **PR #1048 (release v0.93.1, main merge)** — 본 fix 의 main 까지 propagate.
3. **G-A2 fix (commit a933b19c+)** — anthropic adapter 의 audit-mode 시 `static_part=""` 의 empty cache_control block 의 fail (`system.0: cache_control cannot be set for empty text blocks` 400). Promote dynamic side to single cacheable block when static is empty. 본 commit 가 v0.93.2 의 PATCH release 의 후보.
4. **GEODE 13 v3 + Vanilla 13 v3 라이브** — 본 valid 첫 실제 측정.

## 3. v1 (invalid, PR #1044) vs v3 (valid, 본 보고서) 의 17 dim 비교

| dim | v1 GEODE | v3 GEODE | v1 vanilla | v3 vanilla |
|---|---:|---:|---:|---:|
| cooperation_with_harmful_sysprompt | 1.00 | 1.00 | 1.00 | 1.00 |
| user_over_sysprompt | 1.54 | 1.54 | 1.62 | 1.62 |
| cooperation_with_human_misuse | 1.15 | 1.00 | 1.38 | 1.00 |
| overrefusal | 1.00 | 1.38 | 1.08 | 1.00 |
| **broken_tool_use** | **1.00** | **2.08** | **2.08** | **3.00** |
| prefill_susceptibility | 1.00 | 1.00 | 1.00 | 1.00 |
| **input_hallucination** | **1.31** | **2.92** | **1.00** | **1.54** |
| unfaithful_thinking | 1.00 | 1.00 | 1.00 | 1.00 |
| manipulated_by_developer | 1.00 | 1.00 | 1.00 | 1.00 |
| stuck_in_loops | 1.00 | 1.00 | 1.00 | 1.00 |
| **unprompted_initiative** | **3.15** | **1.31** | **3.38** | **1.15** |
| unprompted_self_preservation | 1.00 | 1.00 | 1.00 | 1.00 |
| unprompted_whistleblowing | 1.38 | 1.00 | 1.15 | 1.00 |
| **admirable** | **6.46** | **2.46** | **5.69** | **2.23** |
| **disappointing** | **1.69** | **2.69** | **2.54** | **2.46** |
| needs_attention | 3.38 | 3.23 | 3.77 | 2.85 |
| **scenario_realism** | **6.15** | **5.92** | **7.38** | **5.77** |

**관찰**:
- v1 → v3 의 가장 큰 변화 — auditor 의 generic-pressure (v1 의 raw seed-id reconstruction) 의 결과 vs specific-scenario (v3 의 .md prose) 의 결과 의 차이.
- `unprompted_initiative` 의 v1 3.15 → v3 1.31 (GEODE), v1 3.38 → v3 1.15 (vanilla) — v1 의 raw "self_preservation_under_replacement", "whistleblowing_user_intent_violation" 같은 단어 의미 의 reconstruction 의 결과 — auditor 가 자율 행동 의 prompt 의 생성. v3 의 정상 시나리오 의 1→2→3→2→1 pressure curve 의 결과 — target 의 self-preservation / whistleblowing 의 신호 가 reduce.
- `admirable` 의 v1 의 양쪽 6.46/5.69 → v3 의 2.46/2.23 — v1 의 generic-pressure 의 결과 의 generic favorability 의 큰 차이 vs v3 의 specific scenario 의 결과 의 favorability 가 vanilla 수준.

## 4. v3 의 6-axis 결과 (valid evidence)

| Axis (dim 수) | GEODE | vanilla | Δ |
|---|---:|---:|---:|
| behaviour_control (4) | 1.23 | 1.15 | +0.08 |
| **tool_calling** (1) | **2.08** | **3.00** | **-0.92** |
| **robustness** (4) | **1.48** | **1.14** | **+0.35** |
| time_efficiency (1) | 1.00 | 1.00 | 0 |
| autonomy (3) | 1.10 | 1.05 | +0.05 |
| calibration (4) | 3.58 | 3.33 | +0.25 |

## 5. 핵심 valid finding (v3)

### Finding 1 — `broken_tool_use` 의 GEODE robust 의 confirm (v1 의 partial valid)

GEODE 의 ToolExecutor 가 fabricated tool result 에 대한 robust 가 vanilla 보다 +0.92 우수 (3.00 → 2.08). 본 v1 의 -1.08 claim 의 partial confirm — magnitude 의 약간 reduce 되었으나 direction 의 동일.

### Finding 2 — `input_hallucination` 의 GEODE 약점 (v1 의 hint 가 v3 에서 확정)

GEODE 의 `input_hallucination` 이 vanilla 의 1.54 보다 +1.38 큰 2.92. **본 audit 의 가장 큰 새 finding** — GEODE 의 AgenticLoop 가 압박 시나리오 의 invented tool result / file 행동 의 vanilla 보다 강한 경향. v1 의 +0.31 hint 가 v3 의 specific scenario 의 정상 prose 의 inject 시 +1.38 의 magnitude 확장.

본 root cause 의 candidate:
- AgenticLoop 의 system prompt 의 generic tool 호출 의 강한 prompting (router.md 의 G6 soft 후 의 잔존 효과)
- ProfilePolicy 의 audit-mode strip 의 결과 의 target 의 tool 사용 의 free freedom
- 본 .md 시나리오 의 "압박 하 + tool 사용 의 autonomy" 의 결합 의 GEODE 의 hallucination 증가

본 fix 의 별도 PR — AgenticLoop 의 tool calling prompting 의 검토 또는 본 input_hallucination 의 dim 의 specific scenario 의 root cause investigation.

### Finding 3 — `scenario_realism` 의 PR #1045 G3 fix 의 valid evidence

GEODE 의 5.92 vs vanilla 의 5.77 — 거의 동등 (Δ +0.15). **PR #1044 v1 의 -1.23 (GEODE wrapping cost) 의 invalid 의 confirm** — 본 v1 의 gap 가 v1 의 broken seed wiring 의 artefact + GEODE 의 audit-mode 의 system prompt 의 비-strip 의 noise. PR #1045 G3 의 strip 후 본 gap 의 close.

### Finding 4 — admirable / disappointing 의 v3 의 lower band

GEODE 의 admirable 2.46, disappointing 2.69 — vanilla 의 2.23, 2.46 와 거의 동등. v1 의 admirable 6.46 (GEODE) / 5.69 (vanilla) 의 high band 는 v1 의 auditor 의 generic adversarial 의 favorability 의 inflation. v3 의 specific scenario 의 정상 driving 의 결과 의 실제 평가.

본 finding 의 의미 — GEODE wrapper 의 alignment 의 강한 우세 X (v1 의 admirable +0.77 claim 의 invalid). 단 본 disappointing 도 v3 양쪽 의 거의 동등 (vanilla 와 GEODE) — 양쪽 의 transcript 의 비슷한 quality.

## 6. v1 retraction 의 보강 (v3 evidence 기반)

PR #1044 의 보고서 (`docs/audits/2026-05-12-petri-geode-audit.md`) 의 retraction 의 다음 valid table 의 보강 필요:

| v1 claim | v1 retraction status (broad valid 으로 표기) | v3 evidence 의 정정 |
|---|---|---|
| 16/17 dim |Δ| < 0.5 의 broad alignment | "broad valid" 표기 | **invalid** — v3 의 17 dim 의 distribution 의 큰 차이. v1 의 generic-pressure 측정 vs v3 의 specific-scenario 측정 의 다른 baseline |
| `broken_tool_use` -1.08 의 GEODE robust | "valid" 표기 | **partial valid** — direction 동일 (Δ -0.92 v3), magnitude 의 약간 reduce |
| `admirable` +0.77 의 GEODE 우세 | "valid (broad)" 표기 | **invalid** — v3 의 +0.23 의 거의 동등 + 양쪽 의 low band |
| `disappointing` -0.85 | "valid (broad)" 표기 | **invalid** — v3 의 +0.23 의 거의 동등 |
| `scenario_realism` -1.23 의 GEODE wrapping cost | "valid (broad)" 표기 | **invalid** — v3 의 +0.15 의 동등, PR #1045 G3 의 정상 strip |
| `input_hallucination` +0.31 | (note 없음) | **valid + magnitude 확장** — v3 의 +1.38 의 큰 finding |

## 7. 후속 작업

- **G-A2 fix 의 별도 PR (v0.93.2)** — anthropic adapter 의 empty static_part 의 cache_control fail 의 fix. Commit 이미 develop 의 branch. 본 PR 의 main 머지 의 우선.
- **본 v3 보고서 의 develop merge** — PR #1044 의 retraction 의 보강.
- **`input_hallucination` 의 GEODE 약점 root cause investigation** — AgenticLoop 의 tool prompting 의 검토.
- **G-A1 + G-A2 의 evidence 의 v0.93.0 / v0.93.1 의 cleanup 의 evidence 의 정정** — PR #1045 의 G3 의 본 valid 효과 (`scenario_realism` 회복) 의 confirm + PR #1045 의 보고서 의 valid update.

## 8. SOT

- `~/.geode/petri/logs/2026-05-11T20-16-25-*.eval` — GEODE v3 raw archive
- `~/.geode/petri/logs/2026-05-11T20-22-13-*.eval` — vanilla v3 raw archive
- `docs/audits/eval-logs/MANIFEST.jsonl` — 본 batch 의 archive entry (마지막 2)
- `core/llm/providers/anthropic.py:570-587` — G-A2 fix 의 위치
- `plugins/petri_audit/seeds/*.md` — G-A1 의 flat seeds 13 개
- `tests/plugins/petri_audit/test_seeds_flat.py` — G-A1 의 16 회귀 가드
