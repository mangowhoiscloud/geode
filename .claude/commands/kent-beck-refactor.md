# Kent Beck Refactoring — 탐색-진단-추출 워크플로우

> "Make the change easy, then make the easy change."
> 이 스킬은 중복 코드 탐지 → 아키텍처 진단 → 팩토리 추출을 자동화합니다.

## 트리거

`refactor`, `kent beck`, `중복 제거`, `DRY`, `팩토리`, `factory`, `god object`, `통합`

## 워크플로우

### Phase 1: 탐색 (Explore)

Explore 에이전트로 중복 패턴을 탐색합니다.

1. **대상 파일 식별**: 사용자가 지정한 파일 또는 관련 모듈 전체
2. **패턴 반복 횟수**: 동일 빌드/초기화 패턴이 몇 곳에서 반복되는지 카운트
3. **차이점 매트릭스**: 반복되는 코드 블록 간 EXACT 차이를 표로 정리

| 관점 | Path A | Path B | Path C |
|------|--------|--------|--------|
| param_1 | default | explicit_X | explicit_Y |
| param_2 | ... | ... | ... |

4. **다른 소비자**: 같은 패턴을 사용하는 곳이 더 있는지 (sub-agent, batch, test 등)

### Phase 2: 진단 (Kent Beck 4 Rules)

| Rule | 질문 | 판정 |
|------|------|------|
| 1. Passes tests | 현재 테스트가 통과하는가? | |
| 2. Reveals intention | 반복되는 코드가 의도를 숨기는가? | |
| 3. No duplication | 아이디어 수준의 중복인가? (우연의 일치 vs 구조적) | |
| 4. Fewest elements | 추출 후 구성 요소가 줄어드는가? | |

**핵심 판단**: 중복이 **우연의 일치**인가 **구조적**인가?
- 우연의 일치: 비슷해 보이지만 독립적으로 진화할 코드 → 그대로 둠
- 구조적: 동일한 빌드 의사결정을 반복 → 팩토리 추출

### Phase 3: 추출

**팩토리 함수 설계 원칙**:

1. **차이점만 파라미터**: 공통 부분은 함수 내부에, 차이점만 인자로 노출
2. **합리적 기본값**: REPL(가장 일반적인 경우)이 기본값이 되도록
3. **명시적 차이**: 각 호출부에서 **의도적 차이**가 한눈에 보이도록
4. **lazy import**: 팩토리 내부에서 import하여 순환 참조 방지

```python
# BEFORE: 17줄 x 3곳 = 51줄
handlers = _build_handlers(...)
sub_mgr = _build_sub_mgr(...)
executor = Executor(..., special_param=X)
loop = Loop(..., another_param=Y)

# AFTER: 팩토리 1곳 + 호출부 3줄
ref, executor, loop = _build_stack(
    ctx,
    special_param=X,    # INTENTIONAL DIFFERENCE
    another_param=Y,    # INTENTIONAL DIFFERENCE
)
```

5. **반환 타입**: 호출부가 필요한 것만 반환 (보통 `(ref, executor, instance)` 튜플)
6. **이름**: `_build_<무엇>_stack()` — "stack"은 여러 레이어를 조립한다는 의미

### Phase 4: 검증

1. 품질 게이트 실행 (lint, type, test)
2. **반복 코드 삭제 확인**: diff에서 `-` 줄이 `+` 줄보다 많아야 함
3. **차이점 가시성**: 각 호출부에서 의도적 차이가 파라미터로 명시되는지 확인

## Anti-patterns

| Anti-pattern | 증상 | 처방 |
|---|---|---|
| **God Factory** | 팩토리가 20개 이상 파라미터 | 관심사별로 분리 (Stack + Config) |
| **Premature Extraction** | 2곳 미만 중복에서 추출 | 3곳 이상일 때만 추출 (Rule of Three) |
| **Leaky Abstraction** | 팩토리 내부 구현이 호출부에 누출 | 반환 타입을 Protocol/ABC로 |
| **Parameter Object Fever** | Config dataclass가 너무 많은 필드 | 합리적 기본값 + 필수 인자만 |

## 실증 사례

### GEODE Gateway-REPL 통합 (#461)

**Before**: `_build_tool_handlers → _build_sub_agent_manager → ToolExecutor → AgenticLoop` 패턴이 REPL/Batch/Gateway 3곳에서 43줄씩 반복.

**차이점 매트릭스**:
| 관점 | REPL | Gateway | Batch |
|------|------|---------|-------|
| hitl_level | 2 (default) | 0 (autonomous) | 2 |
| system_suffix | "" | _GATEWAY_SUFFIX | "" |
| quiet | False | True | False |
| max_rounds | 50 | config.toml에서 | 50 |

**After**: `_build_agentic_stack()` 팩토리 1개. 각 호출부에서 차이만 명시.
**결과**: -55줄, 의도적 차이 가시성 확보, 동작 동일성 보장.
