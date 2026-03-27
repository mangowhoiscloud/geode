# Context Long-Session Plan

> 장시간 운용을 위한 컨텍스트 관리 고도화 — GAP-1~5 일괄 해소

## Frontier Research Summary

### Claude Code (3-Layer Compaction)
- **Microcompaction**: tool result 조기 정리 (clear_tool_uses)
- **Auto-compaction**: ~95% 도달 시 LLM 요약 → 새 세션 + 요약 주입
- **Manual compaction**: `/compact [instructions]` — 사용자 지정 요약 힌트
- **API**: `compact_20260112` 서버사이드 compaction (beta `compact-2026-01-12`)
  - trigger: input_tokens 기반 (기본 150K, 최소 50K)
  - instructions: 커스텀 요약 프롬프트
  - pause_after_compaction: 요약 후 추가 블록 삽입 가능
  - 응답에 `compaction` 블록 포함 → 다음 요청에서 이전 메시지 자동 드롭

### Codex CLI
- token threshold 기반 자동 트리거 (모델별 180K-244K)
- history + compaction prompt → LLM 요약 → initial context + recent 20K + summary
- 명시적 경고: "multiple compactions can cause the model to be less accurate"

### OpenClaw
- 4단계 Failover: Auth Rotation → Thinking Fallback → Context Overflow → Model Failover
- Context Overflow: 감지 → Auto-compaction → 압축 후 재시도

### Key Insight (공통 패턴)
1. **서버사이드 우선**: 가능하면 API가 처리 (Anthropic compact/clear_tool_uses)
2. **클라이언트 폴백**: 서버사이드 없는 프로바이더는 LLM 요약 기반 클라이언트 compaction
3. **투명성**: compaction 발생 사실을 LLM에 알림 (summary injection)
4. **85-90% 조기 트리거**: 95%보다 일찍 발동이 안정적 (커뮤니티 피드백)

## Current State (AS-IS)

| 구간 | Anthropic | OpenAI/GLM |
|------|-----------|------------|
| <80% | 정상 | 정상 |
| 80-95% | clear_tool_uses (서버) | **무방비** ← GAP-1 |
| 95%+ | prune_oldest (단순 삭제) | prune_oldest (단순 삭제) |
| 정보 보존 | 없음 (삭제만) ← GAP-2 | 없음 ← GAP-2 |
| LLM 인지 | 없음 ← GAP-4 | 없음 ← GAP-4 |
| 전략 분화 | 없음 ← GAP-5 | 없음 ← GAP-5 |

## Target State (TO-BE)

| 구간 | Anthropic | OpenAI/GLM |
|------|-----------|------------|
| <80% | 정상 | 정상 |
| 80% | clear_tool_uses + compact_20260112 (서버) | 클라이언트 LLM 요약 compaction 발동 |
| 95%+ | 서버사이드가 이미 처리 (safety net만 유지) | 클라이언트 emergency prune (기존) |
| 정보 보존 | 서버사이드 summary | 클라이언트 LLM summary |
| LLM 인지 | compaction 블록 자동 | "[compacted]" 마커 주입 |
| 전략 분화 | provider-aware hook | provider-aware hook |

## Implementation

### Task 1: Anthropic provider에 서버사이드 compaction 추가

**파일**: `core/llm/providers/anthropic.py`

현재 `context_management`에 `clear_tool_uses`만 있음. `compact_20260112` 추가:

```python
extra_headers={
    "anthropic-beta": "context-management-2025-06-27,compact-2026-01-12",
},
extra_body={
    "context_management": {
        "edits": [
            {
                "type": "clear_tool_uses_20250919",
                "keep": {"type": "tool_uses", "value": 5},
            },
            {
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": trigger_tokens},
            },
        ]
    }
},
```

- trigger 값: 모델 context_window의 80% (동적 계산)
- compaction 블록이 응답에 포함 → 클라이언트는 그대로 append
- conversation.py의 add_assistant_message가 compaction 블록을 보존해야 함

### Task 2: OpenAI/GLM 클라이언트사이드 compaction

**파일**: `core/orchestration/compaction.py` (신규)

서버사이드 compaction이 없는 프로바이더용 클라이언트 구현:

```python
async def compact_conversation(
    messages: list[dict],
    model: str,
    provider: str,
    context_window: int,
) -> tuple[list[dict], str]:
    """LLM 요약 기반 compaction. (summary, new_messages) 반환."""
```

1. 요약 프롬프트로 LLM 호출 (현재 provider 사용)
2. 요약 + 최근 N개 메시지로 새 대화 구성
3. 요약을 system message가 아닌 첫 번째 user message로 주입

### Task 3: context_action hook 프로바이더별 전략 분화

**파일**: `core/hooks/context_action.py`

현재 strategy = "prune" or "none"만 반환. "compact" 추가:

```python
def _decide_strategy(event, data):
    provider = data.get("provider", "anthropic")
    if provider == "anthropic":
        return {"strategy": "none"}  # 서버사이드가 처리
    # OpenAI/GLM: 80%부터 클라이언트 compaction
    if usage_pct >= 80:
        return {"strategy": "compact", "keep_recent": 10}
    if usage_pct >= 95:
        return {"strategy": "prune", "keep_recent": 10}
    return {"strategy": "none"}
```

### Task 4: compaction 알림 (LLM 인지)

**Anthropic**: 서버사이드 compaction 블록이 자동으로 포함됨 — 추가 작업 불필요.

**OpenAI/GLM**: 클라이언트 compaction 후 마커 주입:

```python
{
    "role": "user",
    "content": "[This conversation was automatically compacted. Previous context has been summarized above. Some details from earlier messages may no longer be available.]"
}
```

### Task 5: 테스트 + docs-sync

- `tests/test_compaction.py` — compaction 유닛 테스트
- `tests/test_context_action.py` — 프로바이더별 전략 분화 테스트
- CLAUDE.md + CHANGELOG 갱신
