---
name: geode-scoring
description: GEODE scoring formula guide. PSM Engine (ATT, Z-value, Rosenbaum Gamma), 14-axis rubric, Final Score weights, Tier classification, 6-subscore calculation. Ensures architecture-v6 §13.8 SOT consistency. Triggers on "score", "scoring", "psm", "tier", "rubric", "formula", "가중치", "점수".
---

# GEODE Scoring System

> SOT: `architecture-v6.md` §13.8

## Final Score Formula (§13.8.1)

```python
base = (
    0.25 * exposure_lift      +  # PSM ATT → 0-100
    0.20 * quality             +  # (A+B+C+B1+C1+C2+M+N)/8 × 20
    0.18 * recovery_potential  +  # (E+F-2)/8 × 100, D excluded
    0.12 * growth              +  # 0.4×trend + 0.4×expand + 0.2×dev
    0.20 * community_momentum  +  # (J+K+L-3)/12 × 100
    0.05 * developer_track        # dedicated rubric or quality×0.8
)
final = base × (0.7 + 0.3 × analyst_confidence / 100)
```

Weights sum = 1.00. Confidence multiplier range: [0.7, 1.0].

## Tier Classification

| Tier | Score | Meaning |
|------|-------|---------|
| **S** | >= 80 | Must-develop |
| **A** | >= 60 | Strong candidate |
| **B** | >= 40 | Conditional |
| **C** | < 40 | Pass |

## 14-Axis Rubric

### Quality Judge (8 axes)

| Axis | Name | Measures |
|------|------|----------|
| A | Core Mechanics | Gameplay loop quality |
| B | IP Integration | How well IP translates |
| C | Engagement | Retention hooks |
| B1 | Trailer Engagement | YouTube CTR |
| C1 | Conversion Intent | Pairwise preference |
| C2 | Experience Quality | Review sentiment |
| M | Polish | Technical baseline |
| N | Fun Factor | Entertainment value |

### Hidden Value (3 axes)

| Axis | Name | Role |
|------|------|------|
| D | Acquisition Gap | Cause classification only (excluded from recovery) |
| E | Monetization Gap | Recovery potential |
| F | Expansion Potential | Recovery potential |

### Community Momentum (3 axes)

| Axis | Name |
|------|------|
| J | Growth Velocity |
| K | Social Resonance |
| L | Platform Momentum |

## PSM Engine

```
ATT% → exposure_lift = clamp(ATT×1.5 + 30, 0, 100)
Z > 1.645     → statistically significant
Γ ≤ 2.0      → robust to hidden bias
Max SMD < 0.1 → covariates balanced
```

## Key Files

| File | Content |
|------|---------|
| `geode/nodes/scoring.py` | PSM + subscores + final + tier |
| `geode/nodes/evaluators.py` | 14-axis rubric |
| `geode/state.py` | PSMResult, EvaluatorResult |

## References

- **Detailed formulas**: See [formulas.md](./references/formulas.md)
