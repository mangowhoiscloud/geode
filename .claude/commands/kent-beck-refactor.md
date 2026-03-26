# Kent Beck Refactoring 2.0

> "Make the change easy, then make the easy change."

대상: `$ARGUMENTS` (파일/모듈 경로). 생략 시 최근 변경 파일 자동 탐지.

## 모드

- **Quick** (기본): `$ARGUMENTS` 또는 최근 `git diff` 대상만 리뷰
- **Deep** (`--deep`): 지정 모듈 전체 스캔 + Severity 분류
- **Audit** (`--audit`): 코드베이스 전역 God Object / 중복 탐지

---

## Phase 1: DISCOVER

대상 파일을 식별한다. `$ARGUMENTS`가 있으면 해당 파일, 없으면 최근 변경.

```
Quick: git diff --name-only HEAD~3 -- '*.py'
Deep:  find <target>/ -name "*.py" -exec wc -l {} + | sort -rn | head -20
Audit: find core/ -name "*.py" -exec wc -l {} + | sort -rn | head -30
```

**Explore 에이전트**로 다음을 파악한다:
1. 동일 빌드/초기화 패턴이 **몇 곳에서 반복**되는지 카운트
2. 반복 블록 간 **EXACT 차이**를 매트릭스로 정리
3. **다른 소비자**가 있는지 (sub-agent, batch, test, CLI 등)

**차이점 매트릭스** (모든 리팩토링의 핵심 산출물):

| 관점 | Path A | Path B | Path C |
|------|--------|--------|--------|
| param_1 | default | explicit_X | explicit_Y |
| param_2 | ... | ... | ... |

## Phase 2: DIAGNOSE

### Kent Beck 4 Rules 진단

| Rule | 질문 | 판정 |
|------|------|------|
| 1. Passes tests | 현재 테스트가 통과하는가? | |
| 2. Reveals intention | 반복 코드가 의도를 숨기는가? | |
| 3. No duplication | **구조적** 중복인가, 우연의 일치인가? | |
| 4. Fewest elements | 추출 후 구성 요소가 줄어드는가? | |

**핵심 판단**: 중복이 **우연의 일치**인가 **구조적**인가?
- 우연의 일치: 비슷해 보이지만 독립적으로 진화할 코드 → **그대로 둠**
- 구조적: 동일한 빌드 의사결정을 반복 → **팩토리 추출**
- 2곳 미만이면 Rule of Three 위반 → **추출하지 않음**

### Severity 분류 (Deep/Audit 모드)

| Severity | 기준 | 액션 |
|----------|------|------|
| CRITICAL | 1000+줄, 10+ 책임 | 즉시 분할 |
| HIGH | 500+줄, 5+ 책임, 깊은 중첩 | 분할 계획 |
| MEDIUM | 3곳+ 중복, 불명확한 네이밍 | 현 이터레이션에서 처리 |
| LOW | 사소한 네이밍, 작은 DRY 기회 | Backlog |

## Phase 3: PLAN

팩토리 함수 설계. **변경하기 쉽게 만든 다음, 쉬운 변경을 한다.**

**설계 원칙**:
1. **차이점만 파라미터**: 공통 부분은 함수 내부에, 차이점만 인자로 노출
2. **합리적 기본값**: 가장 일반적인 경로(REPL 등)가 기본값
3. **명시적 차이**: 각 호출부에서 `# INTENTIONAL DIFFERENCE` 주석 불필요할 정도로 자명하게
4. **lazy import**: 팩토리 내부에서 import → 순환 참조 방지
5. **반환 타입**: 호출부가 필요한 것만 반환
6. **이름**: `_build_<무엇>_stack()` — "stack"은 여러 레이어 조립 의미

```python
# BEFORE: 17줄 x 3곳
handlers = _build_handlers(...)
sub_mgr = _build_sub_mgr(...)
executor = Executor(..., special_param=X)
loop = Loop(..., another_param=Y)

# AFTER: 팩토리 1곳 + 호출부 3줄
ref, executor, loop = _build_stack(
    ctx,
    special_param=X,
    another_param=Y,
)
```

## Phase 4: EXECUTE

한 번에 하나의 리팩토링만 실행한다.

1. 팩토리 함수 추출
2. 첫 번째 호출부 교체 → 품질 게이트
3. 두 번째 호출부 교체 → 품질 게이트
4. 반복

## Phase 5: VERIFY

매 단계 후 실행:
```bash
uv run ruff check core/ tests/
uv run ruff format --check core/ tests/
uv run mypy <changed-files>
uv run pytest tests/ -m "not live" -q
```

**검증 기준**:
- diff에서 `-` 줄이 `+` 줄보다 많아야 함 (코드 감소)
- 각 호출부에서 의도적 차이가 파라미터로 명시되는지 확인
- 기존 테스트 전부 통과 + 새 테스트 불필요 (행동 변경 없으므로)

---

## Red Flags — 즉시 중단

다음 상황이 발생하면 멈추고 접근을 재평가한다:

- 리팩토링 도중 **행동이 변경**됨 (테스트 실패)
- **3연속 품질 게이트 실패** → 아키텍처 문제, 패치로 해결 불가
- 하나의 단계에서 **2개 이상의 관심사**를 동시에 변경
- 원본 함수와 추출된 함수가 **둘 다 남아있음** (가장 위험)
- 구현체가 1개뿐인 **추상화 생성** (Premature Abstraction)

## Anti-patterns

| Anti-pattern | 증상 | 처방 |
|---|---|---|
| **God Factory** | 파라미터 20개+ | 관심사별 분리 (Stack + Config) |
| **Premature Extraction** | 2곳 미만에서 추출 | Rule of Three: 3곳 이상일 때만 |
| **Leaky Abstraction** | 내부 구현이 호출부에 누출 | Protocol/ABC로 반환 타입 제한 |
| **Behavioral Change** | 리팩토링 중 로직 수정 | "구조만 변경, 동작은 보존" 원칙 |
| **Big Bang Extraction** | 3곳을 한 커밋에 전부 교체 | 호출부 1곳씩 순차 교체 + 검증 |

---

## 실증 사례: GEODE Gateway-REPL 통합 (#461)

**Before**: `handlers → sub_mgr → executor → AgenticLoop` 43줄 x 3곳 반복.

**차이점 매트릭스**:
| 관점 | REPL | Gateway | Batch |
|------|------|---------|-------|
| hitl_level | 2 (default) | 0 (autonomous) | 2 |
| system_suffix | "" | _GATEWAY_SUFFIX | "" |
| quiet | False | True | False |
| max_rounds | 50 | config.toml | 50 |

**After**: `_build_agentic_stack()` 1개. 호출부에서 차이만 명시.
**결과**: -55줄, CI 5/5 통과, 동작 동일성 보장.
