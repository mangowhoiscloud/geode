# GEODE Orchestration Layer — Design Decision

> **결론**: LangGraph StateGraph 자체가 오케스트레이션 레이어. 별도 레이어 불필요.

## 조사 대상

| 시스템 | 패턴 | GEODE 적용 |
|--------|------|------------|
| **OpenClaw** | Hub-and-spoke Gateway, Lane Queue, Skills | 부적합 — 개인 비서 자동화 목적, 직렬 우선 설계 |
| **Claude Code** | Master loop (while tool_calls), Sub-agent Task tool, Context compressor | 부적합 — 대화형 tool-use 에이전트용, 구조화된 파이프라인과 다름 |
| **LangGraph** | StateGraph, Send API, Conditional Edges, Checkpoint | **현재 사용 중 — 최적** |

## LangGraph가 최적인 이유

1. **Typed State**: `GeodeState(TypedDict)` + Pydantic BaseModel → 타입 안전
2. **Send API**: 4 Analysts 병렬 실행 + Clean Context (앵커링 방지)
3. **Conditional Edges**: Router 6-mode 분기, Verification 후 조건부 Synthesizer
4. **Reducer Pattern**: `Annotated[list[AnalysisResult], operator.add]` → 병렬 결과 자동 병합
5. **Checkpoint**: SqliteSaver 지원 (장기 실행 시 복구)

## OpenClaw에서 차용한 패턴

| OpenClaw 패턴 | GEODE 적용 |
|---------------|------------|
| Progressive Disclosure (Skills) | `--verbose`, `--dry-run` 플래그 |
| Session Isolation | Send API Clean Context (Analyst 간 점수 격리) |
| Gateway routing | Router node + `route_after_router` conditional edges |

## Claude Code에서 차용한 패턴

| Claude Code 패턴 | GEODE 적용 |
|-------------------|------------|
| Sub-agent isolated context | Send API: 각 Analyst는 독립 state로 실행 |
| Step-by-step progress | `graph.stream()` 기반 progress indicator |
| Effective Harnesses | Fixture-based dry-run (LLM 없이 전체 파이프라인 검증) |

## 아키텍처 비교

```
OpenClaw:  Gateway → Lane Queue → Skill → Agent (직렬 기본)
Claude:    while(tool_calls) { execute(tool) } (대화 루프)
GEODE:     StateGraph: START → Route → Gather → Send(Analyst×4) → Evaluate → Score → Verify → Synthesize → END
```

GEODE는 **구조화된 분석 파이프라인**으로, 대화형 에이전트(OpenClaw/Claude)와 근본적으로 다른 토폴로지.
LangGraph의 StateGraph가 이 패턴에 1:1 대응하므로 별도 오케스트레이션 레이어 불필요.
