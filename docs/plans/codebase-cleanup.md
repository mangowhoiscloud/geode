# Plan: 코드베이스 정리 — 데드코드 삭제 + 설계 개선

## 감사 결과 요약

| 카테고리 | 발견 | 심각도 |
|---------|------|:------:|
| 데드코드 | 10 파일, 1,642줄 | MEDIUM |
| _build_tool_handlers wrapper | __init__.py에 불필요한 위임 함수 | LOW |
| God Object | __init__.py 2,554줄 | CRITICAL (별도 이슈) |
| Parameter Bloat | GeodeRuntime 30 params | HIGH (별도 이슈) |

## 이번 작업 범위

God Object 분할과 Parameter Bloat은 대규모 리팩토링 → 별도 이슈.
이번에는 **안전하게 삭제 가능한 데드코드 + wrapper 정리**만 수행.

## F1: 데드코드 삭제 (10파일)

삭제 전 각 파일의 import 여부를 재확인.

| 파일 | 줄 | 삭제 근거 |
|------|-----|---------|
| core/cli/repl.py | 487 | 어디서도 import 안 됨 |
| core/orchestration/context_compactor.py | 189 | __init__.py에서 80% compaction 제거로 호출처 없음 |
| core/orchestration/hook_discovery.py | 376 | 어디서도 import 안 됨 |
| core/orchestration/planner.py | 326 | 어디서도 import 안 됨 |
| core/orchestration/agent_reflection.py | 111 | 어디서도 import 안 됨 |
| core/automation/trigger_endpoint.py | 313 | 어디서도 import 안 됨 |
| core/mcp_server.py | 184 | CLI entrypoint이지만 import 안 됨 |
| core/infrastructure/adapters/mcp/linkedin_adapter.py | 88 | 어디서도 import 안 됨 |
| core/infrastructure/adapters/mcp/memory_adapter.py | 55 | 어디서도 import 안 됨 |

**주의**: core/mcp_server.py는 `python -m core.mcp_server`로 독립 실행할 수 있는 FastMCP 서버.
CLAUDE.md에 문서화됨. 이건 삭제하지 않음.

**주의**: context_compactor.py는 /compact 슬래시 커맨드에서 사용될 수 있음. 확인 필요.

## F2: _build_tool_handlers wrapper 제거

__init__.py L1542-1558의 위임 함수를 삭제하고, 호출자가 직접 import.

## 검증

1. ruff check → 0 errors
2. pytest tests/ -m "not live" → 전체 pass
3. 삭제된 파일의 테스트가 import error → 해당 테스트도 삭제
