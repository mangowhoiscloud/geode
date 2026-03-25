---
name: kent-beck-review
description: Kent Beck Simple Design 4규칙 관점 코드 리뷰. God Object 분할, SRP, 중복 제거, 네이밍, 순환 복잡도. "kent beck", "simple design", "simplify", "리팩토링", "refactor", "god object", "SRP" 키워드로 트리거.
user-invocable: false
---

# Kent Beck Code Review Lens

> "Make the change easy, then make the easy change."

## Four Rules of Simple Design (우선순위순)

1. **Passes tests** -- 테스트 통과
2. **Reveals intention** -- 이름과 구조가 의도를 드러냄
3. **No duplication** -- 아이디어 수준의 중복 제거
4. **Fewest elements** -- 최소 구성 요소

## 리뷰 체크리스트

### 파일 크기

```bash
# 500줄+ 파일 탐지 (God Object 후보)
find core/ -name "*.py" -exec wc -l {} + | sort -rn | head -20
```

기준:
- 500줄 이상: 분할 검토
- 1000줄 이상: 즉시 분할 필요
- GEODE 현황: `cli/__init__.py`(2800줄+)는 이미 분할 진행 중

### 메서드 크기 & 복잡도

```bash
# 50줄+ 함수 탐지
grep -n "def " core/ -r --include="*.py" | while read line; do
  echo "$line"
done

# 중첩 깊이 4+ 탐지
grep -rn "if\|for\|while\|with\|try" core/ --include="*.py" | grep -c "        " # 4 indent levels
```

기준:
- 함수 50줄 이상: 추출 검토
- 중첩 4단계 이상: 조기 반환 또는 추출
- 분기 10개 이상: 전략 패턴 또는 디스패치 테이블

### 의도 드러내기 (Reveals Intention)

| 안티패턴 | 개선 |
|---------|------|
| `def process(data)` | `def score_analyst_response(response)` |
| `result = fn(x, y, z)` | 의미 있는 변수명 사용 |
| `# 이 함수는 X를 한다` | 함수명으로 드러내고 주석 제거 |
| `magic number 0.7` | `CONFIDENCE_THRESHOLD = 0.7` |

### 중복 제거 (No Duplication)

아이디어 수준 중복을 탐지한다 (copy-paste뿐 아니라 추상화 누락):

```bash
# 유사 패턴 반복
grep -rn "def _call_llm_" core/ --include="*.py"  # 3개 provider별 유사 함수
grep -rn "def _build_" core/runtime.py  # 10개+ 빌더 유사 패턴
```

기준:
- 3회 이상 반복: 추출 검토
- 구조적 유사성: Protocol/제네릭으로 통합 검토

### 최소 구성 (Fewest Elements)

| 불필요 요소 | 기준 |
|-----------|------|
| 미사용 파라미터 | `**kwargs` 전달만 하는 래퍼 |
| 단일 구현 ABC | Protocol이면 충분 |
| 빈 `__init__.py` | re-export 없으면 제거 |
| 미사용 import | ruff F401로 자동 탐지 |

## GEODE 코드베이스 기존 발견

| 항목 | 파일 | 상태 |
|------|------|------|
| `cli/__init__.py` 2800줄+ | L0 | 분할 진행 중 (repl.py, commands.py 추출 완료) |
| `agentic_loop.py` 1400줄+ | L0 | `_process_tool_calls` 88줄 — 추출 검토 대상 |
| `runtime.py` 1400줄+ | DI | 10개+ `_build_*` 빌더 — 패턴 통일 검토 |
| `policy.py` 430줄 | L4 | 적정 범위 |
