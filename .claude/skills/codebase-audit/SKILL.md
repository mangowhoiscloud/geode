---
name: codebase-audit
description: 코드베이스 감사 + 리팩토링 워크플로우. 데드코드 탐지, God Object 분할, 중복 함수 제거, 설계 결함 파악, 프론티어 비교 검증. "audit", "감사", "dead code", "데드코드", "refactor", "리팩토링", "god object", "중복", "설계 결함" 키워드로 트리거.
user-invocable: false
---

# Codebase Audit & Refactoring Workflow

코드베이스 전체를 체계적으로 감사하고 개선하는 워크플로우.
GEODE v0.24.0 세션에서 실증된 절차 (3,205줄 삭감, __init__.py -57%).

## 워크플로우

```
1. 감사 (Audit)
   → 데드코드 + 중복 + God Object + Parameter Bloat 탐지
2. 분류 (Triage)
   → 즉시 삭제 / 리팩토링 / 보류 판정
3. 칸반 등록
   → Backlog에 우선순위별 등록
4. 작업공간 분리
   → worktree 격리
5. 구현 + 검증
   → 삭제/추출/전환 후 lint + test
6. docs-sync + main
   → CHANGELOG, progress.md, 글로벌 재설치
```

## Phase 1: 감사 (Audit)

### 데드코드 탐지

```bash
# 모듈별 import 여부 확인
for f in $(find core/ -name "*.py" -not -name "__init__.py" -not -path "*__pycache__*"); do
    basename=$(basename $f .py)
    # 실제 import 경로로 확인 (basename 일치만으로는 false positive)
    module_path=$(echo $f | sed 's/\.py$//' | tr '/' '.')
    count=$(grep -rn "from ${module_path}\|import ${module_path}" core/ --include="*.py" | grep -v "$f" | wc -l)
    if [ "$count" -eq 0 ]; then
        echo "DEAD: $f ($(wc -l < $f) lines)"
    fi
done
```

주의: basename이 아닌 **full module path**로 검색해야 false positive 방지.

### 동명 함수 탐지

```bash
grep -rn "^def " core/ --include="*.py" | awk -F: '{split($NF,a," "); print a[2]}' | sort | uniq -c | sort -rn | head -10
```

동명 함수가 2곳 이상이면 **어느 것이 호출되는지 실행 시점까지 알 수 없음** — 설계 결함.

### God Object 탐지 (Kent Beck 기준)

```bash
find core/ -name "*.py" -not -path "*__pycache__*" -exec wc -l {} + | sort -rn | head -10
```

- 500줄 이상: 분할 검토
- 1000줄 이상: 즉시 분할
- `grep -c "^def " FILE` 으로 책임 수 파악

### Parameter Bloat 탐지

```bash
grep -rn "def __init__" core/ --include="*.py" -A20 | grep -B1 "def __init__" | head -20
# 7개 이상 파라미터 = 리팩토링 대상
```

## Phase 2: 분류 (Triage)

| 분류 | 판정 기준 | 조치 |
|------|----------|------|
| **즉시 삭제** | import 0, 테스트만 존재 | 파일 + 테스트 삭제 |
| **리팩토링** | 500줄+, 3+ 책임 | 모듈 추출 |
| **보류** | 향후 사용 예정, 또는 대규모 변경 필요 | 칸반 Backlog |

## Phase 3: 모듈 추출 패턴

### 순환 import 방지

```python
# 새 모듈에서 원래 모듈의 함수 참조 시 → deferred import
def extracted_function():
    from core.cli import _original_helper  # 함수 내 lazy import
    return _original_helper()
```

### 얇은 위임 함수 (Thin Wrapper)

원래 모듈에서 추출한 함수를 계속 export해야 할 때:

```python
# core/cli/__init__.py
def _build_tool_handlers(**kwargs):
    """Delegate to tool_handlers (single source)."""
    from core.cli.tool_handlers import _build_tool_handlers as _build
    return _build(**kwargs)
```

### re-export (ruff F401 방지)

```python
from core.cli.pipeline_executor import _run_analysis as _run_analysis  # explicit re-export
```

## Phase 4: 검증

```bash
# 1. Lint
uv run ruff check core/

# 2. Type check (변경 파일만)
uv run mypy core/cli/__init__.py core/cli/new_module.py

# 3. 전체 테스트
uv run pytest tests/ -m "not live" -q

# 4. 삭제된 모듈의 테스트 → import error → 해당 테스트도 삭제
```

## GEODE 실증 결과

| 작업 | 삭감 |
|------|------|
| 인라인 handler 삭제 (데드코드) | -898줄 |
| 데드 모듈 6개 삭제 | -1,243줄 |
| 데드 테스트 5개 삭제 | -1,064줄 |
| God Object 분할 (pipeline_executor + report_renderer) | -786줄 |
| **총계** | **-3,991줄** |

## 안티패턴

1. **basename으로 import 검색** → false positive (예: "repl"이 "REPL" 문자열에 매칭)
2. **동명 함수 방치** → 어느 것이 호출되는지 실행 시점까지 불명
3. **리팩토링 후 원본 미삭제** → 가장 위험한 패턴, serve에서 구버전 호출하여 장시간 디버깅
4. **`uv tool install . --force`로 충분하다는 가정** → `--reinstall`이 필요한 경우 있음
