---
name: geode-portfolio
visibility: unlisted
description: GEODE 포트폴리오 페이지 SOT 정합성 가이드. architecture-v6.md 및 submit/task2_GEODE.pdf를 기준으로 categories, modals 데이터의 정확성을 보장. "geode", "categories", "modal", "정합성", "SOT", "accuracy" 키워드로 트리거.
---

# GEODE Portfolio SOT Accuracy Guide

> SOT 문서:
> - `ppt-workspace/task2/docs/architecture-v6.md` — Full spec (§13.8 Scoring, §13.9 Judgment, §13.11 Rubric, §13.12 Expert, §13.13 Feedback)
> - `submit/task2_GEODE.pdf` — 3-slide submission (Slide 1: PSM+Rubric, Slide 2: Agent System, Slide 3: Feedback Loop)
> - `ppt-workspace/task2/slides/FINAL-SLIDES.md` — Slide content spec

## Portfolio File Map

| File | Content | SOT Sections |
|------|---------|--------------|
| `src/data/geode/categories.ts` | 8 category cards | All layers |
| `src/data/modals/geode-modals.ts` | 27 detail modals | §13.8-§13.13 |
| `src/data/geode/stats.ts` | Hero metrics | Summary |
| `src/data/geode/pipeline-nodes.ts` | XyFlow diagram | §4 L3 Agentic Core |
| `src/data/geode/tech-stack.ts` | Tech stack | §2 Foundation |

## SOT Critical Numbers (Always verify against these)

### Scoring (§13.8.1)
```
Final = (0.25×PSM + 0.20×Quality + 0.18×Recovery + 0.12×Growth + 0.20×Momentum + 0.05×Dev)
        × (0.7 + 0.3 × Confidence/100)
Tier: S≥80, A≥60, B≥40, C<40
```

### 14-Axis Rubric (§13.11.1)
- Quality: A, B, C, B.1, C.1, C.2, M, N (8 axes)
- Hidden Value: D, E, F (3 axes) — D excluded from recovery
- Momentum: J, K, L (3 axes)

### 6 Causes (§13.9.2) — Code-based, NOT LLM
| Cause | D-E-F | Action |
|-------|-------|--------|
| timing_mismatch | D≥3 + timing_issue | timing_optimization |
| conversion_failure | D≥3, E≥3 | marketing_boost |
| undermarketed | D≥3, E<3 | marketing_boost |
| monetization_misfit | D≤2, E≥3 | monetization_pivot |
| niche_gem | D≤2, E≤2, F≥3 | platform_expansion |
| discovery_failure | D≤2, E≤2, F≤2 | community_activation |

### LLM Deployment (현행)
| Model | Role |
|-------|------|
| Claude Opus 4.6 (1M) | Primary — Pipeline + AgenticLoop |
| Claude Sonnet 4.6 (1M) | Fallback |
| Claude Haiku 4.5 (200K) | Budget — Guardrail, i18n |
| GPT-5.4 (1M) | Cross-LLM Secondary |

### 42 Hook Events (SOT HookEvent enum)
Pipeline(3), Node(4), Analysis(3), Verification(2), Automation(6), Memory(4), SubAgent(5), ToolRecovery(2), Context(4), Session(2), LLM(3), ToolApproval(2), ModelSwitch(1), TurnComplete(1)

### PSM Engine (§13.8)
- 14 covariates: IP속성(5) + 시장환경(4) + IP특성(5)
- ATT estimand, SMD<0.1, Z>1.645, Γ≤2.0, Caliper=0.2×SD(PS)

### Feedback Loop (§13.13)
- 5 phases: PREDICTION(T+0) → OUTCOME(T+30/90/180d) → CORRELATION → TUNE → RLAIF
- KPI: ρ≥0.50, τ≥0.45, P@10≥0.60, S-Tier Lift≥1.5x, α≥0.80

### Expert Panel (§13.12)
- Tier 3: Score≥0.85, ρ≥0.50, ≥30건 (3-5명)
- Tier 2: Score≥0.70, ρ≥0.40, ≥10건 (5-10명)
- Tier 1: Score≥0.50, 경력≥3년 (무제한)

### Fixture Results
| IP | Score | Tier | Cause |
|----|-------|------|-------|
| Berserk | 81.2 | S | conversion_failure |
| Cowboy Bebop | 68.4 | A | undermarketed |
| Ghost in the Shell | 51.7 | B | discovery_failure |

## Verification Checklist

When updating GEODE portfolio content, always verify:
1. [ ] All formulas match SOT §13.8 exactly
2. [ ] Tier thresholds: S≥80, A≥60, B≥40, C<40
3. [ ] 6 causes complete (including timing_mismatch)
4. [ ] D-axis excluded from recovery_potential
5. [ ] 42 hook events — full enum in core/hooks/system.py
6. [ ] Cross-LLM metric: Krippendorff's α (not Cohen's κ)
7. [ ] Feedback phases include T+180d
8. [ ] 4 models — Claude Opus/Sonnet/Haiku + GPT-5.4
9. [ ] PSM: 14 covariates, not 12 or 15
10. [ ] Clean Context: analyses field removed (not other fields)

## Slide ↔ Modal Mapping

| Slide | Content | Modal IDs |
|-------|---------|-----------|
| Slide 1 (WHY) | PSM, Rubric, Decision Tree, Final Score | modal-geode-scoring, modal-geode-prompts, modal-geode-decision-tree, modal-geode-structured-output |
| Slide 2 (HOW) | Agent Loop, Tool System, Orchestration | modal-geode-stategraph, modal-geode-send-api, modal-geode-hooks, modal-geode-cli |
| Slide 3 (WHAT) | Feedback Loop, Expert Panel, Guardrails, CUSUM | modal-geode-feedback, modal-geode-expert-panel, modal-geode-guardrails, modal-geode-outcome-tracking |
