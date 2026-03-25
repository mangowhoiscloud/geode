# action-summary-system

## 목적
GEODE가 수행한 Action(도구 호출, Bash, 판단 과정)을 유저에게 직관적으로 요약 전달. 유저 피드백: "에이전트가 뭘 했는지 한눈에 보고 싶다."

## 현황
- 실시간 도구 표시 있음: `▸ tool(args)` → `✓ tool → result` (agentic_ui.py)
- 사후 행동 요약 없음. 시스템 프롬프트에 요약 지시 없음.
- `AgenticResult.tool_calls`에 `[{tool, input, result}]` 로그 존재 (ToolCallProcessor)

## 리서치 결과

### 프론티어 비교
| 하네스 | 실시간 표시 | 사후 요약 | 방식 |
|--------|-----------|----------|------|
| Claude Code | ▸/✓/✗ + Ctrl+O | session transcript | 결정론적 |
| Codex CLI | plan → 승인 | JSONL event stream | 결정론적 |
| Cursor | sidebar | checkpoint + todo | 결정론적 |
| Aider | diff | git history | 결정론적 (git-native) |

### 핵심 논문/연구
- **JetBrains NeurIPS 2025** (arXiv 2508.21433): LLM 요약은 trajectory elongation 13-15% 유발. 결정론적 observation masking이 비용 50% 절감 + 동등 성능.
- **CSCW 2025**: 투명성 높을수록 신뢰·만족도·재사용 의향 유의미 증가. Planning/Execution/Summarization 3-phase.
- **Klocek "Transparency is not Trust" (2025)**: CoT는 "generated narrative, not literal trace." 진짜 신뢰는 pre-utterance reliability(guardrails).

### 설계 결론
**하이브리드**: Tier 1(결정론적, 항상) + Tier 2(LLM 내러티브, opt-in)

## 소크라틱 게이트 (통과)

| Q | 결과 |
|---|------|
| Q1 코드에 있는가? | tool_log 데이터 있음, 요약 로직 없음 |
| Q2 안 하면 깨지는가? | 유저 신뢰 문제 (피드백 접수됨) |
| Q3 측정 방법? | 요약 정확도 테스트 + 토큰 오버헤드 |
| Q4 가장 단순한? | Tier 1(결정론적 템플릿) 먼저, Tier 2는 opt-in |
| Q5 프론티어 패턴? | 4종 모두 결정론적 실시간. LLM 사후 요약은 GEODE 차별점 |

## 설계

```
AgenticLoop.arun() 완료
    ↓
tool_log (결정론적)
    ↓
Tier 1: Compact Summary (기본, 항상, 토큰 비용 0)
    ↓ (유저 요청 시)
Tier 2: LLM Narrative (opt-in, Budget LLM 1회)
```

### Tier 1: Compact Summary (결정론적)

```
──── Action Summary ────
3 rounds · 5 tools · 12.4s · $0.012

  web_search("ML Engineer 채용")     → 3건 검색
  memory_get("user_profile")         → 프로필 로드
  analyze_ip("Ghost in the Shell")   → Tier A · 72.1
  memory_save(key="analysis_result") → 저장 완료
  web_fetch("linkedin.com/...")      → 200 OK
────────────────────────
```

### Tier 2: LLM Narrative (opt-in)

```
"프로필 기반으로 ML Engineer 등 3건의 채용 공고를 검색했습니다.
web_search로 LinkedIn/Indeed를 조회하고, 유저 프로필 매칭 점수를
계산하여 상위 3건을 선별했습니다."
```

## 구현 범위

| 파일 | 변경 | 설명 |
|------|------|------|
| `core/cli/ui/agentic_ui.py` | `render_action_summary()` 추가 | Tier 1 결정론적 요약 |
| `core/agent/agentic_loop.py` | `arun()` 반환 전 summary render | Tier 1 자동 표시 |
| `core/agent/agentic_loop.py` | `_generate_narrative()` 추가 | Tier 2 LLM 내러티브 |
| `core/cli/commands.py` | `/replay` 커맨드 확장 | Tier 2 트리거 |
| `core/llm/prompts/action_summary.md` | 신규 | Tier 2 프롬프트 템플릿 |
| `AgenticResult` | `summary: str` 필드 추가 | 요약 저장 |

## 비용 분석

| Tier | 추가 토큰 | 비용 | 시기 |
|------|----------|------|------|
| Tier 1 | 0 | $0 | 항상 |
| Tier 2 | ~700 | ~$0.001 (Haiku) | opt-in |

## 구현 순서
1. Tier 1 — `render_action_summary()` + `AgenticResult.summary`
2. Tier 2 — `/replay` 확장 + `action_summary.md` 프롬프트
3. 설정 — `config.toml`에서 Tier 2 기본 on/off 제어
