---
name: explore-reason-act
description: 코드 수정 전 탐색-추론-실행 3단계 필수 워크플로우. Read-before-Write 강제, 근본 원인 가설 수립, 최소 변경 적용. "explore", "탐색", "reason", "추론", "read before write", "근본 원인", "root cause" 키워드로 트리거.
user-invocable: false
---

# Explore-Reason-Act Methodology

코드를 수정하기 전에 반드시 **Explore -> Reason -> Act** 사이클을 따른다.
탐색 없이 수정하는 것이 잘못된 수정과 반복 실패의 #1 원인이다.

## Phase 1: Explore (Read Before Write)

코드 변경 전 필수 탐색 패턴:

```bash
# 1. 에러 컨텍스트 파악 (실패 파일 + 주변 라인)
grep -rn "ERROR_SYMBOL" core/ tests/ --include="*.py" -l

# 2. 변경 대상 심볼의 모든 사용처 확인
grep -rn "ClassName\|function_name" core/ tests/ --include="*.py"

# 3. 의존성 체인 확인
grep -rn "from.*import.*ClassName" core/ --include="*.py"

# 4. 테스트 기대값 확인
grep -rn "ClassName\|function_name" tests/ --include="*.py"
```

규칙:
- 읽지 않은 파일을 편집하지 않는다
- grep 확인 없이 심볼 존재를 가정하지 않는다
- 에러 라인만이 아닌 전체 함수/클래스를 읽는다
- 최소 2단계 호출자/피호출자를 확인한다
- 10개 이상 파일에서 동일 에러 시 공통 근본 원인을 찾는다

## Phase 2: Reason (가설 수립)

수정 코드를 작성하기 전에 명시한다:

1. **관찰**: "파일 A, B, C에서 X를 확인했다"
2. **가설**: "근본 원인은 Y이다. 근거: Z"
3. **예측**: "Y를 수정하면 A, B, C의 에러가 동시에 해결된다"
4. **영향 범위**: "이 변경은 N개 파일 / M개 호출 지점에 영향"

금지 패턴:
- 공통 근본 원인이 있는데 컴파일러 에러를 개별 수정
- 소스나 문서를 읽지 않고 API 시그니처 추측
- pyproject.toml/config 확인 없이 의존성 버전 가정

## Phase 3: Act (최소 변경 적용)

1. 근본 원인에 대한 최소 변경만 적용
2. 변경 직후 즉시 빌드/테스트 실행
3. 새 에러 발생 시 Phase 1로 복귀 (수정 스택 금지)
4. 3회 반복 후에도 미해결 시 에스컬레이션

## Output Contract

모든 수정 시도는 반드시 포함:
- `exploration_summary`: 무엇을 읽었고 무엇을 발견했는지
- `hypothesis`: 증거 기반 근본 원인 가설
- `change_description`: 무엇을 왜 변경했는지
- `verification`: 변경 후 빌드/테스트 결과

## GEODE 적용

| 상황 | Explore | Reason | Act |
|------|---------|--------|-----|
| 파이프라인 노드 수정 | `graph.py` + 노드 파일 + state.py 전부 읽기 | Reducer 충돌 가설 | 노드 1개만 수정, stream 테스트 |
| 도구 추가 | `definitions.json` + `tool_handlers.py` + `tool_executor.py` 읽기 | 기존 도구 패턴 분석 | 패턴 준수 구현, 단위 테스트 |
| 메모리 변경 | `context.py` + session/project/org 계층 읽기 | 4-tier 조립 순서 확인 | 해당 tier만 수정, 조립 테스트 |
