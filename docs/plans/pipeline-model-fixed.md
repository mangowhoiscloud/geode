# pipeline-model-fixed

## 문제
파이프라인 노드(Analyst/Evaluator/Synthesizer)가 유저 REPL 모델(`settings.model`)을 상속.
glm-5 사용 시 RateLimitError → Circuit Breaker → 파이프라인 전체 실패.

## 근인
`get_node_model("analyst")` → routing.toml 미설정 → None 반환 →
`call_llm_parsed(model=None)` → `model or settings.model` → "glm-5"

## 수정 2건

### Fix 1: 파이프라인 모델 기본값 고정
`core/config.py`에 `_PIPELINE_NODE_DEFAULTS` 추가:
- analyst: claude-opus-4-6
- evaluator: claude-opus-4-6
- scoring: claude-opus-4-6
- synthesizer: claude-opus-4-6
- secondary (cross-LLM): gpt-5.4 (기존 설정 확인)

routing.toml로 오버라이드 가능하되, 미설정 시 절대 settings.model로 폴백 안 함.

### Fix 2: 실행 전 유저 안내
tool_handlers.py의 handle_analyze_ip()에서 dry_run이 아닐 때:
- 사용 모델, 예상 비용, 예상 시간 안내
- AgenticLoop 컨텍스트 고려 (tool_use 중 interactive prompt 불가)
- 안내 메시지를 tool result에 포함하여 LLM이 유저에게 전달

## 소크라틱 게이트: 통과
