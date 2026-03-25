---
name: dependency-review
description: GEODE 6-Layer 아키텍처 의존성 건전성 리뷰. 레이어 역방향 위반, 순환 import, eager/lazy loading, TYPE_CHECKING 가드. "dependency", "import", "의존성", "레이어", "circular", "순환", "lazy", "eager" 키워드로 트리거.
user-invocable: false
---

# Dependency & Layer Review Lens

GEODE 6-Layer 아키텍처의 의존성 건전성을 리뷰한다.

## 레이어 규칙 (위반 금지)

```
L0: CLI & AGENT       → L1, L2, L3 (OK)
L1: INFRASTRUCTURE    → Ports만 (구현체 간 의존 금지)
L2: MEMORY            → L1 Ports (OK), L0 직접 import (VIOLATION)
L3: ORCHESTRATION     → L1 Ports, L2 Ports (OK)
L4: EXTENSIBILITY     → L1 Ports (OK), L0/L3 직접 import (VIOLATION)
L5: DOMAIN PLUGINS    → L1 Ports, DomainPort Protocol (OK)
```

허용:
- 상위 레이어 → 하위 레이어 Port (Protocol)
- ContextVar DI를 통한 의존성 주입

금지:
- 하위 레이어 → 상위 레이어 구현체
- Port를 우회한 직접 import
- 순환 의존 (A → B → A)

## 리뷰 체크리스트

### 1. 레이어 역방향 위반

```bash
# L1(infrastructure) → L0(cli) 위반
grep -rn "from core\.cli" core/infrastructure/ --include="*.py"

# L2(memory) → L0(cli) 위반
grep -rn "from core\.cli" core/memory/ --include="*.py"

# L4(extensibility) → L0(cli) 위반
grep -rn "from core\.cli" core/extensibility/ --include="*.py"

# L1 구현체 간 직접 의존 (adapters 간)
grep -rn "from core\.infrastructure\.adapters\." core/infrastructure/adapters/ --include="*.py" | grep -v "__init__"
```

### 2. 순환 import 탐지

```bash
# 양방향 import 패턴
# A가 B를 import하고 B가 A를 import하는 경우
grep -rn "from core\.memory" core/orchestration/ --include="*.py"
grep -rn "from core\.orchestration" core/memory/ --include="*.py"

# TYPE_CHECKING 가드로 순환 회피 확인
grep -rn "if TYPE_CHECKING" core/ --include="*.py"
```

### 3. Heavy Import (Eager Loading)

```bash
# module-level에서 무거운 패키지 로딩
grep -rn "^import anthropic\|^import openai\|^import langgraph" core/ --include="*.py"
grep -rn "^from anthropic\|^from openai\|^from langgraph" core/ --include="*.py" | grep -v "TYPE_CHECKING"

# 함수 내 lazy import 패턴 확인
grep -rn "def.*:" core/ --include="*.py" -A3 | grep "import "
```

규칙:
- `anthropic`, `openai`, `langgraph` 등 무거운 SDK는 TYPE_CHECKING 가드 또는 함수 내 lazy import
- `Pydantic`, `dataclasses`, `typing` 등 경량 패키지는 module-level OK

### 4. Port 우회 탐지

```bash
# Port Protocol 없이 구현체 직접 import
grep -rn "from core\.llm\.client import" core/nodes/ --include="*.py"
grep -rn "from core\.memory\.session import" core/nodes/ --include="*.py"
grep -rn "from core\.memory\.organization import" core/nodes/ --include="*.py"

# 올바른 패턴: Port를 통한 접근
grep -rn "from core\.infrastructure\.ports" core/ --include="*.py"
```

## GEODE 기존 발견 사항

| 패턴 | 상태 | 비고 |
|------|------|------|
| ContextVar DI | 정상 | `set_llm_callable()`, `set_domain()` 등 |
| Port/Adapter 분리 | 정상 | `ports/` 디렉토리에 Protocol 정의 |
| TYPE_CHECKING 가드 | 부분 적용 | `runtime.py`, `sub_agent.py` 적용됨 |
| Lazy import | 부분 적용 | `_build_*` 메서드 내 지연 로딩 |
