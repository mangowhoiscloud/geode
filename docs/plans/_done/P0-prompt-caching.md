# P0: Prompt Caching 도입

> Priority: P0 | Effort: Low | Impact: 비용 40-60% 절감

## 현황

- Anthropic SDK 0.83.0+ 에 `cache_control` 자동 프롬프트 캐싱 지원
- GEODE는 동일한 system prompt를 반복 호출 (4 analysts × 같은 ANALYST_SYSTEM, 3 evaluators × 같은 EVALUATOR_SYSTEM)
- 현재 캐싱 미적용 → 매 호출마다 full input 토큰 과금

## 목표

- System prompt에 `cache_control: {"type": "ephemeral"}` 적용
- Analyst 4회 호출 중 3회는 캐시 히트 (75% 절감)
- Evaluator 3회 호출 중 2회는 캐시 히트 (67% 절감)

## 구현 계획

### 1. `call_llm()` / `call_llm_parsed()` 수정 (`geode/llm/client.py`)

```python
# Before
messages = [{"role": "user", "content": user}]
response = client.messages.create(
    model=model,
    system=system,
    messages=messages,
    ...
)

# After
messages = [{"role": "user", "content": user}]
response = client.messages.create(
    model=model,
    system=[{
        "type": "text",
        "text": system,
        "cache_control": {"type": "ephemeral"},
    }],
    messages=messages,
    ...
)
```

### 2. Adapter 레벨 적용 (`claude_adapter.py`)

- `generate()`, `generate_parsed()`, `generate_structured()` 모두 system을 content block으로 변환
- OpenAI adapter는 변경 불필요 (OpenAI 자체 캐싱 제공)

### 3. 비용 절감 추정

| 구간 | 호출 수 | 캐시 히트 | 절감 |
|---|---|---|---|
| Analyst ×4 | 4 | 3 (75%) | ~75% system 토큰 |
| Evaluator ×3 | 3 | 2 (67%) | ~67% system 토큰 |
| Synthesizer | 1 | 0 | 없음 |
| BiasBuster | 1 | 0 | 없음 |
| **전체** | **9** | **5** | **~40-50%** |

### 4. 검증

- `uv run pytest tests/ -q` 통과
- LLM 호출 시 `usage.cache_creation_input_tokens`, `usage.cache_read_input_tokens` 확인
- 비용 비교: 캐싱 전 vs 후

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/llm/client.py` | system 파라미터를 content block으로 변환 |
| `geode/infrastructure/adapters/llm/claude_adapter.py` | `cache_control` 주입 |
| `pyproject.toml` | `anthropic>=0.84.0` 범프 |
