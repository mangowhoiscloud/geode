---
name: geode-verification
description: GEODE verification system guide. Guardrails G1-G4 (Schema, Range, Grounding, Consistency), BiasBuster (Confirmation, Recency, Anchoring bias), Cross-LLM cross-verification, Cause Classification Decision Tree (6 types → 5 actions). Triggers on "verification", "guardrail", "bias", "biasbuster", "cross-llm", "cause", "검증", "decision tree".
---

# GEODE Verification System

## Guardrails G1-G4 (DELETED — historical reference)

> PR-CLEANUP-D3A (2026-06-10, operator decision): `core/state.py` +
> `core/verification/` were removed — the G1-G4 implementation targeted the
> deleted Game-IP analysis pipeline's GeodeState and had zero production
> callers. Live verification surfaces are **turn-verify** (TURN_VERIFY_*
> events) and **contract-eval** (contract_results gate). The tables below
> are retained as design reference only; restore from git history if a
> pipeline-shaped verifier returns.

## Guardrails G1-G4 (design reference)

| Guard | Name | Check |
|-------|------|-------|
| **G1** | Schema | Pydantic model validation |
| **G2** | Range | Score [1,5], composite [0,100] |
| **G3** | Grounding | Evidence list non-empty |
| **G4** | Consistency | Score-text alignment |

Returns `GuardrailResult(all_passed=bool, details=[...])`.

## BiasBuster

| Bias | Detection | Threshold |
|------|-----------|-----------|
| **Confirmation** | All scores same direction | All 4 agree |
| **Recency** | Recent data over-weighted | Heuristic |
| **Anchoring** | Low score variance (CV) | CV < 0.05 |

```python
CV = std / mean
anchoring_bias = CV < 0.05  # Too similar = anchor
```

## Cause Classification (Decision Tree)

Code-based, NOT LLM. Uses D-E-F profile:

```
D>=3 + timing_issue → timing_mismatch
D>=3, E>=3          → conversion_failure
D>=3, E<3           → undermarketed
D<=2, E>=3          → monetization_misfit
D<=2, E<=2, F>=3    → niche_gem
D<=2, E<=2, F<=2    → discovery_failure
```

### Cause → Action

| Cause | Action |
|-------|--------|
| undermarketed | marketing_boost |
| conversion_failure | marketing_boost |
| monetization_misfit | monetization_pivot |
| niche_gem | platform_expansion |
| timing_mismatch | timing_optimization |
| discovery_failure | community_activation |

## Pipeline Position

`scoring → verification → synthesizer`. Failed guardrails log warning, proceed in demo mode.

## Key Files

| File | Content |
|------|---------|
| `geode/verification/guardrails.py` | G1-G4 |
| `geode/verification/biasbuster.py` | Bias detection |
| `geode/verification/cross_llm.py` | Cross-LLM (placeholder) |
| `geode/nodes/synthesizer.py` | Decision Tree + Cause→Action |

## References

- **Decision tree details**: See [decision-tree.md](./references/decision-tree.md)
