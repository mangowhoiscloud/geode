# GEODE Pipeline Flexibility — AS-IS / TO-BE

## C2: Analyst 타입 YAML 동적 로드

| | 상세 |
|---|---|
| AS-IS | `ANALYST_TYPES = ["game_mechanics", "player_experience", "growth_potential", "discovery"]` (하드코딩) |
| TO-BE | `ANALYST_TYPES: list[str] = list(ANALYST_SPECIFIC.keys())` — YAML(`evaluator_axes.yaml`)에서 동적 로드 |
| 변경 파일 | `core/nodes/analysts.py` (1줄) |
| 확장 방법 | `evaluator_axes.yaml`의 `analyst_specific` 섹션에 키 추가만으로 analyst 추가 |

## C3: 중간 사용자 개입 (interrupt_before)

| | 상세 |
|---|---|
| AS-IS | `compile_graph()`의 `interrupt_before` 파라미터 미사용, 일괄 실행 |
| TO-BE | `Settings.interrupt_nodes` 설정 → `GeodeRuntime.compile_graph()` → `interrupt_before` 전달 |
| 변경 파일 | `core/config.py`, `core/runtime.py`, `core/cli/__init__.py` |
| 사용 방법 | `GEODE_INTERRUPT_NODES=verification,scoring` 환경변수 또는 `.env` 설정 |
| CLI 동작 | interrupt 시 현재 상태 출력 → `[C]ontinue / [A]bort` 프롬프트 → Continue면 재개, Abort면 부분 결과 반환 |

## C4: 동적 Tool 추가 (ToolRegistry 연동)

| | 상세 |
|---|---|
| AS-IS | `AGENTIC_TOOLS = json.loads(...)` — 모듈 임포트 시 고정 |
| TO-BE | `_BASE_TOOLS` (기존 JSON) + `get_agentic_tools(registry)` 함수로 ToolRegistry 도구 병합 |
| 변경 파일 | `core/cli/agentic_loop.py` |
| AgenticLoop | `tool_registry: ToolRegistry | None` 파라미터 추가 → `self._tools` 인스턴스 변수로 사용 |
| 호환성 | `AGENTIC_TOOLS` 별칭 유지 (기존 테스트/import 호환) |

## C5: LLM 없이 AgenticLoop (offline_mode)

| | 상세 |
|---|---|
| AS-IS | API KEY 없으면 `_call_llm()` → `None` → `AgenticResult(error="llm_call_failed")` |
| TO-BE | `AgenticLoop(offline_mode=True)` → `_run_offline()` → `_offline_fallback()` regex 10패턴 재사용 |
| 변경 파일 | `core/cli/agentic_loop.py`, `core/cli/__init__.py` |
| CLI 연동 | `force_dry_run` 시 자동으로 `offline_mode=True` 전달 |
| 동작 | 1 round 결정론적 실행 (LLM 불필요), regex로 intent 파싱 → ToolExecutor로 실행 |
