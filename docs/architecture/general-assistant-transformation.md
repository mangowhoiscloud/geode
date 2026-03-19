# GEODE General Assistant Transformation

> **PR**: #32 (`feature/nl-router-quality` → `develop`)
> **Date**: 2026-03-11
> **Scope**: 5-phase transformation from IP-analysis-only agent to general-purpose assistant

---

## Overview

GEODE를 IP 분석 전용 에이전트에서 범용 비서로 전환하는 작업. Claude Code 패턴을 참고하여 offline 모드 제거, key registration gate, 새 도구 추가, MCP 통합을 수행.

## Phase 1: Offline 모드 제거 + Key Registration Gate

### 변경사항

| 파일 | 변경 |
|------|------|
| `core/cli/startup.py` | `key_registration_gate()`, `_mask_key()`, `_upsert_env()` 추가. `ReadinessReport.blocked` 필드 추가 |
| `core/cli/__init__.py` | Key gate 호출, `force_offline` 제거, MCP manager 초기화 |
| `core/cli/agentic_loop.py` | `offline_mode` 파라미터, `_run_offline()` (~60줄), `_ACTION_TO_TOOL` dict 제거 |
| `tests/test_agentic_loop.py` | offline 테스트 → key gate 테스트 교체 |
| `tests/test_e2e_live_llm.py` | `TestOfflineModeLive` → `TestKeyRegistrationGateLive` |

### 동작

- API key 없이 시작 → Panel UI로 key 등록 유도
- `/key <API_KEY>` → `.env`에 저장 후 진입
- `/quit` → 종료
- `_offline_fallback()` (nl_router.py)은 LLM 실패 시 graceful degradation용으로 보존

## Phase 2: 시스템 프롬프트 범용화

### 변경사항

| 파일 | 변경 |
|------|------|
| `core/llm/prompts/router.md` | 범용 비서 + IP 전문가 이중 역할 프롬프트 |

### 핵심 변경

- Identity: "undervalued IP discovery agent" → "AI assistant with deep expertise in game IP analysis"
- 일반 대화/질문은 도구 호출 없이 텍스트 응답
- URL/문서 처리, 웹 검색, 노트 기능 라우팅 룰 추가
- `show_help`는 명시적 요청 시에만 호출

## Phase 3: 새 도구 추가

### 신규 파일

| 파일 | 도구 |
|------|------|
| `core/tools/web_tools.py` | `WebFetchTool` (URL→text), `GeneralWebSearchTool` (Anthropic native) |
| `core/tools/document_tools.py` | `ReadDocumentTool` (로컬 파일 읽기, 프로젝트 경계 보안) |
| `core/tools/memory_tools.py` | `NoteSaveTool`, `NoteReadTool` (ProjectMemory 연동) |

### 기존 파일 수정

| 파일 | 변경 |
|------|------|
| `core/tools/definitions.json` | 9개 도구 스키마 추가 (21→30) |
| `core/cli/__init__.py` | 9개 핸들러 함수 등록 |
| `core/cli/tool_executor.py` | SAFE_TOOLS에 `web_fetch`, `general_web_search`, `note_read`, `read_document` 추가 |

### 의존성

- `beautifulsoup4>=4.12.0` (pyproject.toml 추가)
- `httpx>=0.27.0` (pyproject.toml 추가)

## Phase 4: MCP 서버 통합

### 신규 파일

| 파일 | 역할 |
|------|------|
| `core/infrastructure/adapters/mcp/stdio_client.py` | JSON-RPC over subprocess stdin/stdout |
| `core/infrastructure/adapters/mcp/manager.py` | 설정 로드, 클라이언트 관리, 도구 디스패치 |
| `.claude/mcp_servers.json` | MCP 서버 설정 (brave-search 예시) |

### 기존 파일 수정

| 파일 | 변경 |
|------|------|
| `core/cli/agentic_loop.py` | `mcp_manager` 파라미터, MCP 도구 merge |
| `core/cli/tool_executor.py` | MCP fallback 경로 (handler 없으면 MCP에서 실행) |
| `core/cli/commands.py` | `/mcp` 명령 (서버 목록 조회) |

### MCP 프로토콜

```
Client → Server: initialize (JSON-RPC)
Client → Server: notifications/initialized
Client → Server: tools/list → cached
Client → Server: tools/call (on demand)
```

## Phase 5: Signal 도구 활성화

### 변경사항

| 파일 | 변경 |
|------|------|
| `core/tools/definitions.json` | `youtube_search`, `reddit_sentiment`, `steam_info`, `google_trends` 스키마 추가 |
| `core/cli/__init__.py` | 4개 signal 도구 핸들러 등록 |

---

## 버그 수정 (코드 리뷰 발견)

| # | 심각도 | 문제 | 수정 |
|---|--------|------|------|
| 1 | CRITICAL | `_CONFIG_PATH` parent 4개 → `core/`까지만 도달 | parent 5개로 수정 |
| 2 | CRITICAL | `mcp_manager`가 AgenticLoop/ToolExecutor에 전달 안됨 | `_interactive_loop()`에 초기화 추가 |
| 3 | MEDIUM | `router.md`에서 `web_search` → 실제 도구명 `general_web_search` 불일치 | 프롬프트 수정 |
| 4 | LOW | `beautifulsoup4` pyproject.toml 누락 | 추가 |
| 5 | LOW | `httpx` pyproject.toml 누락 | 추가 |

## LangSmith 추적 수정

### 문제

`.env`의 `LANGCHAIN_*` 변수가 `os.environ`에 로드되지 않음. pydantic-settings가 정의된 필드만 로드하고 `LANGCHAIN_*`는 무시. `@_maybe_traceable` 데코레이터가 모듈 import 시 평가되어 항상 no-op.

### 수정

`tests/conftest.py` 생성: `load_dotenv()` 호출로 테스트 시 환경변수 선 로드.

---

## E2E 평가 결과 (7개 테스트)

| # | 시나리오 | 결과 | 비고 |
|---|----------|------|------|
| 1 | Plan creation (분석 계획 수립) | PASS | 도구 선정 + 순서 정확 |
| 2 | Multi-intent (IP 목록 + 비교) | PASS | list_ips → compare_ips 라우팅 |
| 3 | URL Fetch | PASS | web_fetch 호출 성공 |
| 4 | Note save/read | PARTIAL | ProjectMemory ContextVar 미초기화 (스크립트 모드) |
| 5 | Signal multi-tool | PASS | youtube_search + reddit_sentiment 병렬 |
| 6 | Multi-turn context | PASS | 대화 컨텍스트 유지 |
| 7 | General knowledge | PASS | 도구 없이 텍스트 응답 |

## 리포트 생성 테스트

| 포맷 | 템플릿 | IP | 결과 |
|------|--------|----|----|
| Markdown | Summary | Berserk | PASS — S티어 81.3점 |
| Markdown | Detailed | Berserk | PASS — 6차원 서브스코어 + 검증 포함 |

---

## 테스트 현황

- 전체: 2033+ tests passing
- Pre-commit hooks: ruff lint, ruff format, mypy strict, bandit — all passing
- 신규 테스트: key gate 2개 (`test_key_gate_blocks_without_key`, `test_key_gate_accepts_valid_key`)
