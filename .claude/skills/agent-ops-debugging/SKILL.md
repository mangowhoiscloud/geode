---
name: agent-ops-debugging
description: 자율 에이전트 시스템 운영 디버깅 패턴. Safe Default Anti-pattern, Multi-gap 근본 원인 분석, ContextVar DI 생명주기, 클로저 캡처 패턴, Graceful Degradation vs Correctness 구분. "디버깅", "debugging", "safe default", "contextvar", "dry-run", "운영", "degradation", "multi-gap", "클로저 캡처" 키워드로 트리거.
user-invocable: false
---

# Agent Ops Debugging — 자율 에이전트 운영 디버깅 패턴

> **출처**: GEODE 운영 디버깅 세션에서 증류 (2026-03-14)
> **철학**: "crash하지 않는다"와 "올바르게 동작한다"는 다른 문제다.
> **상세**: [Blog 25](docs/blogs/25-operational-debugging-four-layer-fix.md) · [ADR-008](docs/plans/ADR-008-subagent-dry-run-bypass.md)

## 5대 패턴 개요

| # | 패턴 | 한줄 원칙 | 적용 레이어 |
|---|------|----------|------------|
| D1 | Safe Default Anti-pattern | 안전한 기본값은 안정성은 보장하지만 정확성은 보장하지 않는다 | 전 레이어 |
| D2 | Multi-gap Root Cause | 단일 gap은 무해하나 N개 겹치면 발현 — 개별 테스트로 못 잡는다 | 파이프라인 |
| D3 | ContextVar Lifecycle | ContextVar DI는 모든 진입점에서 초기화해야 한다 | DI 레이어 |
| D4 | Closure Capture Bypass | 스레드 격리된 ContextVar는 클로저 캡처로 우회한다 | DI + 동시성 |
| D5 | Degradation ≠ Correctness | graceful skip/fallback과 기능 정확성을 별도로 검증한다 | 검증 |

---

## D1. Safe Default Anti-pattern

### 원칙

기본값이 `True`, `None`, `""` 같은 안전한 값으로 설정되면 시스템은 crash하지 않지만, **의도한 동작과 다른 결과**를 반환한다. 이 유형의 버그는 에러 로그에 나타나지 않으므로 발견이 늦다.

### 진단 기준

```
Q: 이 코드 경로에서 기본값으로 동작하면 "정상"인가, "열화"인가?
```

| 기본값 유형 | 정상 사례 | 열화 사례 |
|------------|----------|----------|
| `dry_run=True` | API 키 없을 때 fixture 반환 | API 키 있는데도 fixture만 반환 |
| `return None` | 선택적 기능 미사용 | 필수 기능이 조용히 비활성화 |
| `log.debug(skip)` | 선택적 외부 연동 skip | 필수 연동이 silent fail |

### 적용 패턴

```python
# BAD — 항상 안전하지만 항상 열화
dry_run = args.get("dry_run", True)

# GOOD — 시스템 상태에 따라 기본값 결정
dry_run = args.get("dry_run", force_dry_run)  # force_dry_run은 readiness 기반
```

> 기본값을 하드코딩하지 말고, 시스템 상태(readiness, config, env)에서 도출하라.

---

## D2. Multi-gap Root Cause Analysis

### 원칙

운영 버그 중 가장 찾기 어려운 유형은 **N개의 독립적 gap이 동시에 존재해야 발현**하는 버그다. 각 gap은 단독으로는 무해하거나 별도의 안전장치가 있어서 단위 테스트로 발견되지 않는다.

### 분석 프레임워크

```
1. 증상 정의: "어떤 경로에서, 어떤 조건일 때, 기대와 다른 결과"
2. 경로 비교: "정상 동작하는 경로와 비교하여 분기점 식별"
3. Gap 열거: "분기점마다 독립적으로 gap이 있는지 검증"
4. 겹침 판정: "모든 gap이 동시에 존재해야 버그가 발현하는가?"
```

### 사례: 서브에이전트 dry-run (3-gap)

```
Gap 1: 핸들러 default = True (하드코딩)
  → 단독: LLM이 dry_run=False 전달하면 해결 가능
Gap 2: 도구 스키마에 dry_run 미정의
  → 단독: LLM이 파라미터를 알 수 없음
Gap 3: ContextVar 스레드 격리
  → 단독: 핸들러가 readiness 조회 불가

3개 모두 존재 → 서브에이전트 경로는 항상 dry-run
```

> Multi-gap 버그의 수정 전략: **가장 근본적인 gap 하나를 해소**하면 나머지 gap은 무해해진다. 3개 모두 고칠 필요 없다.

---

## D3. ContextVar DI Lifecycle

### 원칙

Python `contextvars.ContextVar`를 DI 컨테이너로 사용할 때, **모든 진입점**에서 초기화해야 한다. 하나의 진입점에서만 설정하면 다른 진입점에서는 `None`이 반환된다.

### 진입점 체크리스트

```
에이전트 시스템의 전형적 진입점:
[ ] CLI 단발 명령 (e.g., `geode analyze "Berserk"`)
[ ] REPL 대화형 루프 (e.g., `geode` → interactive)
[ ] 파이프라인 내부 (e.g., GeodeRuntime.run())
[ ] 서브에이전트 스레드 (e.g., delegate_task → 별도 스레드)
[ ] HTTP 엔드포인트 (e.g., trigger_endpoint)
[ ] 테스트 fixture (e.g., pytest conftest.py)
```

### 안전 패턴

```python
# 방법 1: 각 진입점에서 명시적 초기화
def _interactive_loop():
    set_project_memory(ProjectMemory())
    set_org_memory(MonoLakeOrganizationMemory())
    ...

# 방법 2: Bootstrap 레이어에서 일괄 초기화 (규모가 커지면 권장)
class Bootstrap:
    def init_all_contextvars(self):
        set_project_memory(ProjectMemory())
        set_org_memory(MonoLakeOrganizationMemory())
        set_readiness(ReadinessReport(...))
```

> 진입점이 3개 이상이면 Bootstrap 레이어를 도입하여 초기화 로직 중복을 제거하라.

---

## D4. Closure Capture Bypass

### 원칙

ContextVar는 **설정한 스레드/태스크 내에서만 유효**하다. 별도 스레드에서 실행되는 핸들러가 ContextVar에 접근해야 하면, **핸들러 생성 시점에 클로저로 캡처**한다.

### 패턴

```python
def make_handler(*, force_dry_run: bool = True):
    """force_dry_run이 클로저에 캡처됨 — 어떤 스레드에서 실행되든 동일."""
    def handler(task_type: str, args: dict) -> dict:
        dry_run = args.get("dry_run", force_dry_run)
        ...
    return handler

# 호출부: 생성 시점에 readiness 상태를 고정
readiness = _get_readiness()
handler = make_handler(force_dry_run=readiness.force_dry_run)
```

### 대안 비교

| 방법 | 복잡도 | 스레드 안전 | 테스트 용이 |
|------|--------|-----------|------------|
| 클로저 캡처 | 낮음 | 안전 (불변 값) | 파라미터로 주입 가능 |
| `contextvars.copy_context()` | 중간 | 안전 (컨텍스트 복사) | 설정 필요 |
| Global 변수 | 낮음 | 불안전 (경합) | 테스트 격리 깨짐 |
| Thread-local | 중간 | 안전 | asyncio 미호환 |

> 값이 핸들러 생성 후 변하지 않으면 클로저 캡처가 최선이다. 런타임 중 값이 변할 수 있으면 `copy_context()`를 사용하라.

---

## D5. Degradation ≠ Correctness

### 원칙

Graceful degradation(우아한 열화)은 시스템 **안정성** 패턴이다. 기능 **정확성**과는 별개로 검증해야 한다.

### 검증 매트릭스

```
모든 외부 의존성에 대해:

| 의존성 | 있을 때 기대 동작 | 없을 때 기대 동작 | 실제 동작 |
|--------|-----------------|-----------------|----------|
| API 키 | live LLM 호출   | fixture 반환     | ???      |
| MCP    | 도구 목록 로드    | skip + 경고      | ???      |
| Redis  | L1 캐시 사용     | L2 직접 조회      | ???      |
```

> "없을 때" 열의 동작만 테스트하면 안 된다. "있을 때" 열이 정말로 live 경로를 타는지 별도 검증하라.

### 구분 기준

```
안정성 테스트: "의존성 X가 없을 때 시스템이 crash하지 않는가?"
정확성 테스트: "의존성 X가 있을 때 시스템이 X를 실제로 사용하는가?"
```

두 질문 모두 "예"여야 시스템이 건강하다.

---

## 디버깅 워크플로우

운영 중 "동작은 하는데 제대로가 아닌" 증상 발견 시:

```
1. 증상 → 영향받는 레이어 식별 (인프라/UI/DI/파이프라인)
2. 정상 경로와 비교하여 분기점 찾기
3. 분기점에서 기본값(default) 점검 — D1 Safe Default 해당?
4. 단일 원인 vs Multi-gap 판별 — D2 해당?
5. ContextVar 접근 실패? — D3/D4 해당?
6. 수정 후 "있을 때" + "없을 때" 모두 검증 — D5
```
