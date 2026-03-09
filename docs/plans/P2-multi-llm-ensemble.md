# P2: Multi-LLM Ensemble 분석

> Priority: P2 | Effort: Medium | Impact: 분석 신뢰도 + 편향 검출 강화

## 현황

- 기본: Claude Opus 4.6 단일 모델 분석
- Cross-LLM Verification은 결과 비교만 수행 (temperature 0.1)
- OpenAI adapter 존재하지만 분석에 미사용

## 목표

- Analyst 4명 중 2명을 OpenAI GPT-5.4로 실행 (교차 검증)
- 동일 IP에 대해 2개 모델의 점수 분포 비교
- Inter-model agreement score 산출

## 구현 계획

### 1. Analyst 모델 할당 전략

```python
# 4 Analysts × 2 Models = 교차 배치
ANALYST_MODEL_MAP = {
    "game_mechanics":    "claude-opus-4-6",
    "player_experience": "gpt-5.4",        # Cross-model
    "growth_potential":  "claude-opus-4-6",
    "discovery":         "gpt-5.4",        # Cross-model
}
```

### 2. Secondary Adapter 활용

```python
# analysts.py
def _run_analyst(analyst_type: str, state: GeodeState) -> AnalysisResult:
    model = ANALYST_MODEL_MAP.get(analyst_type, "claude-opus-4-6")

    if model.startswith("gpt"):
        parsed_fn = get_secondary_llm_parsed()
    else:
        parsed_fn = get_llm_parsed()

    result = parsed_fn(system, user, output_model=AnalysisResult, temperature=0.5)
    ...
```

### 3. Inter-Model Agreement Score

```python
def _compute_agreement(analyses: list[AnalysisResult]) -> float:
    """Claude vs GPT 점수 일치도 (0-1)."""
    claude_scores = [a.score for a in analyses if a.model == "claude"]
    gpt_scores = [a.score for a in analyses if a.model == "gpt"]

    if not claude_scores or not gpt_scores:
        return 1.0  # 단일 모델 → 일치

    mean_diff = abs(np.mean(claude_scores) - np.mean(gpt_scores))
    return max(0, 1 - mean_diff / 5.0)  # 5점 스케일 정규화
```

### 4. BiasBuster 연동

```python
# Agreement < 0.7 → BiasBuster에 경고 플래그 전달
if agreement < 0.7:
    state["_model_disagreement"] = True
    state["_agreement_score"] = agreement
```

## 설정

```env
# 기본: Claude only
ENSEMBLE_MODE=single    # single | cross | full

# cross: 2+2 교차
# full: 4+4 = 8 analysts (비용 2배)
```

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/nodes/analysts.py` | 모델 할당 + secondary adapter 호출 |
| `geode/infrastructure/ports/llm_port.py` | `get_secondary_llm_parsed()` 추가 |
| `geode/verification/biasbuster.py` | model disagreement 플래그 처리 |
| `geode/config.py` | `ensemble_mode` 설정 |
| `geode/runtime.py` | secondary adapter contextvar 주입 |
