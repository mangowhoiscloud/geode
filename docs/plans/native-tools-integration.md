# Native Tools Integration Plan

> **task_id**: native-tools
> **branch**: feature/native-tools
> **worktree**: .claude/worktrees/native-tools
> **status**: GAP Audit + Socratic Gate 완료, 구현 미착수
> **date**: 2026-03-26

## 배경

3사 Agent SDK 네이티브 도구를 GEODE AgenticLoop에 패스스루 통합.
현재 Anthropic `web_search_20250305`만 사용 중 — 나머지 미구현.

## 3사 네이티브 도구 최신 현황 (2026-03-26 실측)

### Anthropic (Messages API)

| Tool | Latest Type | Previous | Status |
|------|-------------|----------|--------|
| **web_search** | `web_search_20260209` | `web_search_20250305` | GA |
| **web_fetch** | `web_fetch_20260209` | `web_fetch_20250910` | GA |
| **code_execution** | `code_execution_20250825` | `code_execution_20250522` | GA |
| **computer** | `computer_20251124` | `computer_20250124` | Beta |
| **text_editor** | `text_editor_20250728` | — | GA |
| **bash** | `bash_20250124` | — | GA |
| **memory** | `memory_20250818` | — | GA |

- `20260209` 버전: dynamic filtering 지원 (Opus 4.6/Sonnet 4.6)
- code_execution: web_search/web_fetch와 함께 사용 시 무료

### OpenAI (Agents SDK v0.13.1)

| Tool Class | Type | Category |
|-----------|------|----------|
| `WebSearchTool` | `web_search` | Hosted |
| `FileSearchTool` | `file_search` | Hosted |
| `CodeInterpreterTool` | `code_interpreter` | Hosted |
| `ImageGenerationTool` | `image_generation` | Hosted |
| `HostedMCPTool` | `hosted_mcp` | Hosted |
| `ToolSearchTool` | `tool_search` | Hosted (v0.11.0 신규) |
| `ComputerTool` | `computer_use_preview` | Local |
| `ShellTool` | `shell` | Local/Hosted |
| `ApplyPatchTool` | `apply_patch` | Local |

- Responses API 필요 (Chat Completions 불가)
- `openai>=2.26.0` 필수
- `web_search_preview` → `web_search` (GA)

### ZhipuAI GLM-5

| Tool Type | Description |
|-----------|-------------|
| `web_search` | 네이티브 웹 검색 (무료) |
| `code_interpreter` | 샌드박스 코드 실행 |
| `drawing_tool` | 시각화/차트 생성 |

```python
# GLM-5 web_search 설정 형식
tools=[{
    "type": "web_search",
    "web_search": {
        "enable": True,
        "search_engine": "search-prime",
        "search_result": True,
        "count": 10,
        "search_recency_filter": "oneMonth",
    }
}]
```

- `zhipuai==2.1.5.20250825` (최신 SDK)
- GEODE는 OpenAI-compatible 엔드포인트 사용 → 네이티브 도구 수동 구성 필요

## GAP Audit 결과

| Item | 현재 상태 | 필요 변경 |
|------|----------|----------|
| Anthropic web_search | `20250305` 하드코딩 | → `20260209` |
| Anthropic web_fetch | httpx 커스텀 구현 | 네이티브 `web_fetch_20260209` 옵션 추가 |
| Anthropic code_exec | 없음 | `code_execution_20250825` 추가 |
| OpenAI 네이티브 | Chat Completions만 | Responses API 패스스루 or 네이티브 도구 타입 감지 |
| GLM-5 web_search | MCP fallback | 네이티브 `web_search` 패스스루 |
| 도구 정의 | `type` 필드 없음 | 네이티브 도구 구분용 `native_type` 추가 |

## Socratic Gate 통과

- Q1: 미구현 확인 ✅
- Q2: 웹검색이 Anthropic 전용 → 범용 에이전트에서 치명적 ✅
- Q3: 단위 테스트 + E2E dry-run 무변동 ✅
- Q4: 어댑터 패스스루만 추가 (최소 변경) ✅
- Q5: Claude Code + OpenAI Agents SDK + Codex CLI 3종 동일 패턴 ✅

## 구현 계획 (4 Tasks)

### Task 1: Anthropic 네이티브 도구 버전 업데이트
- `web_tools.py`: `web_search_20250305` → `web_search_20260209`
- `signal_tools.py`: 동일 업데이트
- `web_fetch` 네이티브 옵션 추가 (기존 httpx 유지, 네이티브 선택 가능)
- `claude_agentic_adapter.py`: `_API_ALLOWED_KEYS`에 네이티브 도구 타입 패스스루 확인

### Task 2: OpenAI 네이티브 웹검색 패스스루
- `openai_agentic_adapter.py`: `_tools_to_openai()`에서 네이티브 도구 타입 감지
- 네이티브 도구는 function 변환하지 않고 그대로 패스스루
- Chat Completions → Responses API 전환 검토 (or 네이티브 도구만 별도 처리)

### Task 3: GLM-5 네이티브 web_search 패스스루
- `glm_agentic_adapter.py`: `agentic_call()` 오버라이드
- tools에서 네이티브 도구 분리 → `{"type": "web_search", "web_search": {...}}` 형태 주입
- OpenAI-compatible 엔드포인트에 네이티브 타입 직접 전달

### Task 4: 단위 테스트 + 품질 게이트
- 3사 네이티브 도구 패스스루 테스트
- lint/type/test 전체 통과
- E2E dry-run 무변동 확인

## 수정 대상 파일

```
core/tools/web_tools.py              # web_search 버전 업데이트
core/tools/signal_tools.py           # web_search 버전 업데이트
core/infrastructure/adapters/llm/claude_agentic_adapter.py   # 네이티브 도구 패스스루
core/infrastructure/adapters/llm/openai_agentic_adapter.py   # Responses API / 네이티브 감지
core/infrastructure/adapters/llm/glm_agentic_adapter.py      # 네이티브 web_search
core/agent/agentic_loop.py           # get_agentic_tools()에 네이티브 도구 구분
tests/unit/test_native_tools.py      # 신규 테스트
```
