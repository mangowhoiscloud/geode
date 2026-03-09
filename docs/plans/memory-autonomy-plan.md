# Memory Autonomy Plan — 에이전트 자율 메모리 관리

> Date: 2026-03-10 | Status: **COMPLETE** (P0+P1 done, P2 deferred)

## 목표

GEODE 에이전트가 Claude Code처럼 자연어 명령 또는 자체 판단으로 메모리/규칙을 읽고, 쓰고, 생성/수정할 수 있도록 한다.

## 우선순위 정렬

| P | 조치 | 상태 | 파일 |
|---|---|---|---|
| P0 | NL Router에 메모리 Tool 3개 노출 | ✅ | `geode/cli/nl_router.py` |
| P0 | ProjectMemory 규칙 CRUD 메서드 추가 | ✅ | `geode/memory/project.py` |
| P0 | Hook 이벤트 3개 추가 | ✅ | `geode/orchestration/hooks.py` |
| P1 | MemorySearchTool project/org tier 확장 | ✅ | `geode/tools/memory_tools.py` |
| P1 | 규칙 관리 Tool 추가 (RuleCreateTool, RuleListTool) | ✅ | `geode/tools/memory_tools.py` |
| P1 | NL Router 시스템 프롬프트에 메모리 컨텍스트 주입 | ✅ | `geode/cli/nl_router.py` |
| P1 | Runtime에 새 Tool 등록 + ContextVar 와이어링 | ✅ | `geode/runtime.py` |
| P1 | CLI "memory" 액션 핸들러 추가 | ✅ | `geode/cli/__init__.py` |
| P2 | Pipeline 노드에 메모리 Tool 주입 확장 | 🔜 | — |

## 변경 요약

### P0-A: NL Router 메모리 Tool 노출
- `_TOOLS`에 `memory_search`, `memory_save`, `manage_rule` 3개 추가
- `VALID_ACTIONS`에 `"memory"` 추가
- `_TOOL_ACTION_MAP`과 `_TOOL_ARGS_MAP`에 매핑 추가

### P0-B: ProjectMemory 규칙 CRUD
- `create_rule(name, paths, content) -> bool`
- `update_rule(name, content) -> bool`
- `delete_rule(name) -> bool`
- `list_rules() -> list[dict]`

### P0-C: Hook 이벤트 추가 (19→22)
- `MEMORY_SAVED`, `RULE_CREATED`, `RULE_UPDATED`

### P1-A: MemorySearchTool 3-tier 확장
- `tier="project"` → MEMORY.md 라인 검색 + 규칙 검색
- `tier="organization"` → fixture IP 컨텍스트 검색
- ContextVar(`set_project_memory`, `set_org_memory`)로 DI

### P1-B: 규칙 관리 Tool (17→19 tools)
- `RuleCreateTool`: agent-driven 규칙 자동 생성
- `RuleListTool`: 활성 규칙 목록 조회

### P1-C: 시스템 프롬프트 메모리 컨텍스트
- `_build_memory_context()`: 최근 인사이트 5건 + 활성 규칙 5건 요약
- `_build_system_prompt()`에 자동 주입

### P1-D: Runtime 와이어링 + CLI 핸들러
- `_build_default_registry()`에 RuleCreateTool, RuleListTool 등록
- `_build_memory()`에서 `set_project_memory()`, `set_org_memory()` 호출
- `_handle_memory_action()` CLI 핸들러 구현

## 검증 결과

1. ✅ `uv run pytest tests/` — 1782 tests passed
2. ✅ `uv run mypy geode/` — no errors
3. ✅ `uv run ruff check geode/` — all checks passed
