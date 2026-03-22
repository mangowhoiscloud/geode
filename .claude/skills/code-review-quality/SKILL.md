---
name: code-review-quality
description: Python 코드 품질 리뷰 렌즈. SOLID 원칙, 데드코드, 예외 처리, 리소스 누수, 스레드 안전성, 성능. "quality", "품질", "SOLID", "dead code", "데드코드", "exception", "resource leak", "thread safety" 키워드로 트리거.
user-invocable: false
---

# Code Review Quality Lens

자동화 도구가 놓치는 품질 이슈를 6가지 관점에서 리뷰한다.

## Check 1: 데드코드 탐지

```bash
# 미사용 import
uv run ruff check core/ --select F401

# 미사용 변수
uv run ruff check core/ --select F841

# TODO/FIXME/HACK 잔류
grep -rn "TODO\|FIXME\|HACK\|XXX" core/ --include="*.py"

# 빈 함수 바디 (pass만 있는 스텁)
grep -rn "def.*:" core/ --include="*.py" -A1 | grep -B1 "^\s*pass$"
```

## Check 2: 예외 처리 안티패턴

```bash
# 빈 except 블록 (예외 삼킴)
grep -rn "except.*:" core/ --include="*.py" -A1 | grep -B1 "^\s*pass$"

# catch-all Exception (너무 넓은 except)
grep -rn "except Exception" core/ --include="*.py" | grep -v "# noqa"

# bare except (타입 없는 except)
grep -rn "except:" core/ --include="*.py"
```

규칙:
- 빈 except: 최소 logging, 또는 래핑 재발생
- except Exception: 정당한 사유 명시 필수
- bare except: 금지 — 최소 Exception 타입 명시

## Check 3: 리소스 누수 탐지

```bash
# 파일 핸들 (with 문 없이)
grep -rn "open(" core/ --include="*.py" | grep -v "with " | grep -v "# noqa"

# subprocess 핸들 미회수
grep -rn "subprocess\.Popen" core/ --include="*.py" | grep -v "with "

# 임시 파일 미정리
grep -rn "tempfile\.\|NamedTemporaryFile\|mktemp" core/ --include="*.py"
```

규칙: 모든 `Closeable`은 `with` 문으로 래핑

## Check 4: 스레드 안전성

```bash
# 글로벌 뮤터블 상태
grep -rn "^[A-Z_]*\s*=\s*\[\|^[A-Z_]*\s*=\s*{" core/ --include="*.py" | grep -v "frozenset\|tuple\|Final"

# Lock 없는 공유 상태 변경
grep -rn "threading\.\|asyncio\.\|concurrent\." core/ --include="*.py"

# ContextVar 사용 패턴 확인
grep -rn "ContextVar\|contextvars" core/ --include="*.py"
```

GEODE 맥락:
- ContextVar DI는 스레드 안전 (Sub-Agent 격리)
- 모듈 레벨 dict/list는 Lock 또는 frozenset 사용
- `_announce_queue`는 `_announce_lock`으로 보호 (검증됨)

## Check 5: SOLID 원칙

| 원칙 | 위반 징후 | 탐지 |
|------|---------|------|
| **SRP** | 500줄+ 파일, 클래스에 5+ 책임 | `wc -l core/**/*.py \| sort -rn \| head` |
| **OCP** | if/elif 체인 10+ 분기 | grep -rn "elif" 카운트 |
| **LSP** | 서브클래스에서 NotImplementedError | grep -rn "NotImplementedError" |
| **ISP** | Protocol에 10+ 메서드 | ports/ 디렉토리 확인 |
| **DIP** | 구현체 직접 import (Port 우회) | 레이어 위반 탐지 |

## Check 6: 성능

```bash
# N+1 패턴 (루프 내 I/O)
grep -rn "for.*in.*:" core/ --include="*.py" -A5 | grep "\.get\|\.fetch\|\.call\|\.execute"

# 불필요한 리스트 생성 (generator 가능)
grep -rn "\[.*for.*in.*\]" core/ --include="*.py" | grep -v "test"

# 중복 계산 (동일 함수 반복 호출)
# (수동 리뷰 필요)
```
