# GEODE Scoring Formulas Reference

> SOT: `architecture-v6.md` §13.8.1-§13.8.5

## 1. Final Score (§13.8.1)

```python
def calc_final_score(
    exposure_lift, quality, recovery_potential,
    growth, community_momentum, developer_track,
    analyst_confidence
) -> float:
    base = (
        0.25 * exposure_lift +
        0.20 * quality +
        0.18 * recovery_potential +
        0.12 * growth +
        0.20 * community_momentum +
        0.05 * developer_track
    )
    multiplier = 0.7 + (0.3 * analyst_confidence / 100)
    return base * multiplier
```

| Weight | Subscore | Source |
|--------|----------|--------|
| 0.25 | exposure_lift | PSM ATT |
| 0.20 | quality | Quality Judge composite |
| 0.18 | recovery_potential | Hidden Value E+F |
| 0.12 | growth | Trend+Expand+Dev |
| 0.20 | community_momentum | J+K+L |
| 0.05 | developer_track | Developer rubric |

## 2. Recovery Potential (§13.8.2)

```python
recovery = (E + F - 2) / 8 * 100
```

- Input: E (Monetization Gap) + F (Expansion Potential), each 1-5
- D axis EXCLUDED (used only in cause classification §13.9.2)
- Reason: D and PSM exposure_lift measure same dimension (marketing/exposure)

## 3. Growth Score (§13.8.3)

```python
growth = 0.40 * trend_alignment + 0.40 * ip_expandability + 0.20 * developer_score
```

- trend_alignment: Community Momentum composite as proxy
- ip_expandability: `(F - 1) / 4 * 100`
- developer_score: Fixture value or `quality * 0.8` fallback

## 4. Community Momentum (§13.8.4)

```python
momentum = (J + K + L - 3) / 12 * 100
```

- J: Growth Velocity (MoM growth)
- K: Social Resonance (UGC, virality)
- L: Platform Momentum (streaming trend)

## 5. Analyst Confidence (§13.8.5)

```python
CV = std(scores) / mean(scores)
confidence = max(0, min(100, (1 - CV) * 100))
```

- 4 analyst scores → CV (Coefficient of Variation)
- Low CV = high agreement = high confidence
- Applied as multiplier: `0.7 + 0.3 * confidence / 100`

## 6. PSM Exposure Lift

```python
exposure_lift = min(100, max(0, ATT_pct * 1.5 + 30))
```

Validity checks:
- Z-value > 1.645 (95% significance)
- Rosenbaum Gamma <= 2.0 (hidden bias robustness)
- Max SMD < 0.1 (covariate balance)

## 7. Quality Judge Composite

```python
composite = ((A + B + C + B1 + C1 + C2 + M + N) / 8) * 20
```

8 axes, each 1-5. Average scaled to 0-100.

## Expected Results (Fixture Validation)

| IP | Quality | Recovery | Momentum | Final | Tier | Cause |
|----|---------|----------|----------|-------|------|-------|
| Berserk | 80 | 81.3 | 91.7 | 82.2 | S | conversion_failure |
| Cowboy Bebop | 82 | 25.0 | 76.7 | 69.4 | A | undermarketed |
| Ghost in the Shell | 72 | 0.0 | 56.7 | 54.0 | B | discovery_failure |
