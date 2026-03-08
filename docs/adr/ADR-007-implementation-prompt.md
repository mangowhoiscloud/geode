# ADR-007 Implementation Prompt

> **목적**: 새 세션에서 이 파일을 컨텍스트로 주입하여 ADR-007 구현을 시작한다.
> **사용법**: 새 세션에서 다음과 같이 요청:
> "ADR-007 구현해줘. `geode/docs/adr/ADR-007-prompt-skill-injection.md`와 `geode/docs/adr/ADR-007-implementation-prompt.md` 읽고 시작해."

---

## 선행 조건

- GEODE 프로젝트 경로: 현재 워크스페이스
- 현재 테스트: 1411 passing (ruff clean, mypy clean)
- ADR 문서: `geode/docs/adr/ADR-007-prompt-skill-injection.md` (1127줄)
- 기존 test event count: `test_all_17_events_exist` → 18로 변경 필요

## 구현 순서

### Phase 0: Foundation

1. `geode/orchestration/hooks.py` — `PROMPT_ASSEMBLED = "prompt_assembled"` 추가 (18번째)
2. `tests/test_hooks.py` — `test_all_17_events_exist` → `test_all_18_events_exist` (count=18)
3. `geode/llm/prompt_assembler.py` — 신규 파일:
   - `AssembledPrompt` frozen dataclass
   - `PromptAssembler` 클래스 (token budget, allow_full_override, skill_registry, hooks)
   - `_hash_prompt()` 재사용 (prompts.py에서 import하거나 동일 구현)
4. `tests/test_prompt_assembler.py` — 신규 테스트:
   - 기본 조립 (base만, fragment 0개)
   - skill fragment 주입
   - memory context 주입 (`_llm_summary` 경로 + fallback 경로)
   - bootstrap extra_instructions 주입
   - prompt override append-only (allow_full_override=False)
   - prompt override full replace (allow_full_override=True)
   - token budget 초과 시 truncation
   - hash 계산 정확성
   - hook event emit 확인

### Phase 1: Bootstrap Wire

5. `geode/llm/skill_registry.py` — 신규 파일 (P2 분리 가능하나, PromptAssembler가 import하므로 stub 필요):
   - `SkillDefinition` frozen dataclass
   - `SkillRegistry` 클래스 (최소 구현: `get_skills()` returns empty)
6. `geode/runtime.py` — `_build_prompt_assembler()` 추가, `create()`에서 호출
7. `geode/graph.py` — 수정:
   - `_make_hooked_node()`: `prompt_assembler` 파라미터 추가, closure로 `effective_state["_prompt_assembler"]` 주입
   - `build_graph()`: `prompt_assembler` 파라미터 추가, `_node()` helper에 전달
   - `compile_graph()`: `prompt_assembler` 파라미터 추가, `build_graph()`에 전달
8. `geode/nodes/analysts.py` — `_build_analyst_prompt()` 수정:
   - 기존 base template 렌더링 유지
   - `state.get("_prompt_assembler")` → assembler.assemble() 호출
   - fallback: assembler가 None이면 기존 동작
   - `make_analyst_sends()`: `_prompt_overrides`, `_extra_instructions`, `memory_context` 키 전파
9. `geode/nodes/evaluators.py` — 동일 패턴 적용 (rubric 블록은 base template의 일부)
   - `make_evaluator_sends()`: 동일 키 전파
10. `geode/nodes/synthesizer.py` — 동일 패턴 적용
11. `geode/verification/biasbuster.py` — `run_biasbuster()`에 assembler 적용
    - node="biasbuster", role_type="bias_detection"
12. `geode/memory/context.py` — `ContextAssembler.assemble()`에 `_llm_summary` 키 생성
13. `tests/test_bootstrap_wire.py` — Integration 테스트

### Phase 2: Skill System

14. `geode/llm/skill_registry.py` — 전체 구현:
    - 4-priority discovery (bundled → project → user → extra)
    - YAML frontmatter + Markdown body 파싱
    - `get_skills(node, role_type, role)` 매칭
15. `geode/skills/` 디렉토리 — bundled skill `.md` 파일 4개:
    - `analyst-game-mechanics.md`
    - `analyst-player-experience.md`
    - `analyst-growth-potential.md`
    - `analyst-discovery.md`
    - 내용: 현재 `ANALYST_SPECIFIC` dict 값의 외부화 + Genre-Specific Guidance 추가
16. `geode/nodes/analysts.py` — ANALYST_SPECIFIC fallback 로직:
    - skill .md 존재 시 → skill 사용
    - skill .md 없을 시 → ANALYST_SPECIFIC fallback
17. `tests/test_skill_registry.py` — Discovery, parsing, priority, wildcard 테스트

### Phase 3: Observability & Validation

18. PROMPT_ASSEMBLED 기본 핸들러 (로깅)
19. Skill validation (frontmatter 스키마 + body 길이 경고)
20. Prompt budget 경고 (4000c warning, 6000c hard limit)

## 핵심 파일 읽기 순서 (구현 시 참조)

구현 전 반드시 읽어야 하는 파일들:

```
# ADR (설계 스펙)
geode/docs/adr/ADR-007-prompt-skill-injection.md

# 현재 프롬프트 시스템
geode/llm/prompts.py

# 수정 대상 노드
geode/nodes/analysts.py
geode/nodes/evaluators.py
geode/nodes/synthesizer.py
geode/verification/biasbuster.py

# 인프라 (연결 대상)
geode/orchestration/hooks.py
geode/orchestration/bootstrap.py
geode/memory/context.py
geode/graph.py
geode/runtime.py
geode/state.py
```

## 검증 명령

```bash
cd <project-root>

# 전체 테스트
uv run python -m pytest tests/ -q

# 신규 테스트만
uv run python -m pytest tests/test_prompt_assembler.py tests/test_skill_registry.py tests/test_bootstrap_wire.py -v

# Lint + Type check
uv run ruff check geode/ tests/
uv run mypy geode/
```

## 주의사항

1. **Backward Compatibility**: assembler가 None이면 기존 동작 100% 유지. 기존 1411 테스트 전부 통과해야 함
2. **Thread Safety**: contextvars 사용 금지. `_make_hooked_node()` closure로만 전달
3. **prompts.py 변경 금지**: base template은 그대로 유지. PromptAssembler가 감싸는 구조
4. **Token Budget**: skill 500c, memory 300c, total 6000c hard limit
5. **Security**: `allow_full_override=False` 기본값 유지
