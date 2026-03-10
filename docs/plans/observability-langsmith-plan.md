# GEODE Observability & LangSmith 통합 계획

## 리서치 요약

### 참고 시스템

| 시스템 | 핵심 패턴 |
|--------|----------|
| **Eco²** | `LANGCHAIN_TRACING_V2` + `LANGCHAIN_API_KEY` + `LANGCHAIN_PROJECT` 3변수 표준. `is_langsmith_enabled()` 게이트. `track_token_usage()` 헬퍼로 RunTree.extra.metrics 수동 주입. LangGraph auto-trace + LLM 클라이언트 레이어 수동 trace. |
| **OpenClaw** | JSONL RunLog (maxBytes=2MB, keepLines=2000, atomic tmp+rename). 이미 GEODE에 `core/orchestration/run_log.py`로 포팅 완료. |
| **LangGraph** | `LANGCHAIN_TRACING_V2=true` 설정만으로 모든 노드 자동 추적. `config={"run_name": ..., "tags": [...], "metadata": {...}}` 전달로 trace 컨텍스트 enrichment. |
| **Claude Code** | `_maybe_traceable` 조건부 데코레이터 (API KEY 있으면 적용, 없으면 passthrough). 이미 GEODE에서 차용. |

### GEODE AS-IS 갭 분석

| # | 갭 | 심각도 | 설명 |
|---|---|--------|------|
| G1 | 비표준 환경변수 | High | `LANGSMITH_API_KEY` 사용 → LangChain 표준 `LANGCHAIN_API_KEY` + `LANGCHAIN_TRACING_V2` 불일치 |
| G2 | `call_llm_streaming` 미추적 | Medium | 스트리밍 LLM 호출에 `@_maybe_traceable` 없음 |
| G3 | run_id 미전파 | Medium | JSONL RunLog의 `run_id`가 LangSmith trace와 연결 안 됨 |
| G4 | OpenAI adapter 미추적 | Medium | 크로스 앙상블 OpenAI 호출이 LangSmith span에 안 잡힘 |
| G5 | `_langsmith_enabled` 미사용 | Low | 글로벌 플래그 설정만 하고 읽는 곳 없음 |
| G6 | 프로젝트명 미설정 | Low | `LANGCHAIN_PROJECT` 지원 없어 기본 프로젝트에 모든 trace 집중 |
| G7 | thread_config에 메타데이터 없음 | Low | `run_name`, `tags`, `metadata` 없이 `thread_id`만 전달 |

## 구현 계획

### Phase A: 환경변수 표준화 + 헬퍼 함수 (G1, G5, G6)

**파일**: `core/llm/client.py`

1. `_maybe_traceable()` 환경변수 체크를 `LANGCHAIN_TRACING_V2=true` AND `LANGCHAIN_API_KEY` 존재로 변경
2. `LANGSMITH_API_KEY` 하위호환: fallback으로 유지
3. `is_langsmith_enabled() -> bool` 퍼블릭 헬퍼 추가
4. `track_token_usage(model, input_tokens, output_tokens)` 헬퍼 추가

### Phase B: 미추적 경로 보강 (G2, G4)

1. `call_llm_streaming`에 `@_maybe_traceable` 추가
2. `OpenAIAdapter.generate`/`generate_json`/`generate_parsed`에 `@_maybe_traceable` 추가

### Phase C: Trace 컨텍스트 enrichment (G3, G7)

1. `build_thread_config()`에 `run_name`, `tags`, `metadata` 추가
2. `core/graph.py` Phase 5-B도 `LANGCHAIN_TRACING_V2` 표준으로 정렬

### 비변경 사항
- RunLog (JSONL) — 이미 OpenClaw 패턴 완벽 구현, 변경 불필요
- HookSystem 25 이벤트 → RunLog 파이프 — 변경 불필요
- Python `logging` 구조 — 변경 불필요
