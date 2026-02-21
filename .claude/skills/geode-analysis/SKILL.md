---
name: geode-analysis
description: GEODE Analyst/Evaluator 구현 가이드. 4 Analysts (game_mechanics, player_experience, growth_potential, discovery), 3 Evaluators (quality_judge, hidden_value, community_momentum), Clean Context 앵커링 방지, Structured JSON Output. "analyst", "evaluator", "분석", "clean context", "앵커링", "루브릭" 키워드로 트리거.
---

# GEODE Analysis Layer

## 4 Analysts (Claude Opus, Send API)

| Analyst | Focus |
|---------|-------|
| **game_mechanics** | Core loop, combat, progression, replay |
| **player_experience** | Narrative, character, immersion, journey |
| **growth_potential** | Community, engagement, UGC, viral signals |
| **discovery** | Market positioning, genre-fit, timing, USP |

### Clean Context

Each analyst receives state WITHOUT `analyses` → prevents score anchoring.

```python
base = {k: v for k, v in state.items() if k not in ("analyses", "_analyst_type")}
Send("analyst", {**base, "_analyst_type": analyst_type})
```

### Output Schema

```json
{
  "analyst_type": "game_mechanics",
  "score": 4.2,
  "key_finding": "one-line summary",
  "reasoning": "2-3 sentences",
  "evidence": ["evidence1"],
  "confidence": 85.0
}
```

Validated by `AnalysisResult(BaseModel)` — score `[1,5]`, confidence `[0,100]`.

## 3 Evaluators (14-Axis Rubric)

| Evaluator | Axes | Composite |
|-----------|------|-----------|
| **quality_judge** | A,B,C,B1,C1,C2,M,N | `(sum/8)×20` |
| **hidden_value** | D,E,F | `(E+F-2)/8×100` |
| **community_momentum** | J,K,L | `(J+K+L-3)/12×100` |

### Axis Validation

`EvaluatorResult` model_validator: keys must match evaluator_type, values in `[1.0, 5.0]`.

## Prompt Design

- **Analyst**: System(role + JSON schema + isolation) + User(IP + MonoLake + signals + focus)
- **Evaluator**: System(type + dynamic axes schema) + User(IP + analyst findings + signals)

Key instruction: "Do NOT reference other analysts or their scores."

## Dry-Run Mode

IP-specific mock results: Cowboy Bebop D5/E2/F4, Berserk D4/E4.5/F4.5, Ghost D2/E2/F2.

## Key Files

| File | Content |
|------|---------|
| `geode/nodes/analysts.py` | 4 analysts + Send API |
| `geode/nodes/evaluators.py` | 3 evaluators + rubric |
| `geode/llm/prompts.py` | All prompt templates |

## References

- **Full prompt templates**: See [prompts.md](./references/prompts.md)
