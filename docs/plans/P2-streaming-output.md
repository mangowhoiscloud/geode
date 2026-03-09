# P2: Streaming Output (실시간 분석 출력)

> Priority: P2 | Effort: Medium | Impact: UX 체감 속도 대폭 향상

## 현황

- 파이프라인 전체 완료까지 30-60초 대기 후 결과 일괄 출력
- `generate_stream()` 어댑터 메서드 존재하지만 노드에서 미사용
- CLI에서 Rich Progress bar로 단계별 진행만 표시

## 목표

- Synthesizer 내러티브를 토큰 단위 스트리밍 출력
- Analyst/Evaluator 완료 시 즉시 결과 표시 (점진적 렌더링)
- 체감 대기 시간 50% 이상 단축

## 구현 계획

### 1. Streaming Synthesizer

```python
# synthesizer.py
def synthesizer_node_streaming(state: GeodeState) -> dict[str, Any]:
    """스트리밍 모드: 내러티브를 청크 단위로 yield."""
    ...
    stream_fn = get_llm_stream()
    chunks = []
    for chunk in stream_fn(system, user):
        chunks.append(chunk)
        yield {"_stream_chunk": chunk}  # CLI가 실시간 출력

    full_text = "".join(chunks)
    return {"synthesis": SynthesisResult(
        value_narrative=full_text,
        ...
    )}
```

### 2. CLI 점진적 렌더링

```python
# cli/__init__.py
from rich.live import Live

with Live(refresh_per_second=10) as live:
    for event in graph.stream(state, config=config, stream_mode="updates"):
        node, data = next(iter(event.items()))
        if "_stream_chunk" in data:
            live.update(panel.append_text(data["_stream_chunk"]))
        elif node == "analyst":
            display_analyst_result(data["analyses"][-1])
        elif node == "evaluator":
            display_evaluator_result(data["evaluations"])
```

### 3. LangGraph stream_mode 활용

```python
# graph.stream()의 stream_mode="updates" 사용
# 각 노드 완료 시 즉시 이벤트 발생
for event in compiled.stream(state, config=config, stream_mode="updates"):
    # event = {"analyst": {"analyses": [...]}} 형태
    ...
```

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/nodes/synthesizer.py` | 스트리밍 경로 추가 |
| `geode/cli/__init__.py` | Rich Live 렌더링 |
| `geode/graph.py` | stream_mode 파라미터 전파 |
