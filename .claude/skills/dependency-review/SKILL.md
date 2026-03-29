---
name: dependency-review
description: GEODE 6-Layer architecture dependency health review. Reverse layer violations, circular imports, eager/lazy loading, TYPE_CHECKING guards. Triggered by "dependency", "import", "dependencies" ("의존성"), "layer" ("레이어"), "circular" ("순환"), "lazy", "eager" keywords.
user-invocable: false
---

# Dependency & Layer Review Lens

Review the dependency health of the GEODE 6-Layer architecture.

## Layer Rules (Violations Prohibited)

```
L0: CLI & AGENT       → L1, L2, L3 (OK)
L1: INFRASTRUCTURE    → Ports only (no inter-implementation dependencies)
L2: MEMORY            → L1 Ports (OK), L0 direct import (VIOLATION)
L3: ORCHESTRATION     → L1 Ports, L2 Ports (OK)
L4: EXTENSIBILITY     → L1 Ports (OK), L0/L3 direct import (VIOLATION)
L5: DOMAIN PLUGINS    → L1 Ports, DomainPort Protocol (OK)
```

Allowed:
- Upper layer → Lower layer Port (Protocol)
- Dependency injection via ContextVar DI

Prohibited:
- Lower layer → Upper layer implementations
- Direct import bypassing Port
- Circular dependency (A → B → A)

## Review Checklist

### 1. Reverse Layer Violations

```bash
# L1(infrastructure) → L0(cli) violation
grep -rn "from core\.cli" core/infrastructure/ --include="*.py"

# L2(memory) → L0(cli) violation
grep -rn "from core\.cli" core/memory/ --include="*.py"

# L4(extensibility) → L0(cli) violation
grep -rn "from core\.cli" core/extensibility/ --include="*.py"

# L1 direct dependency between implementations (between adapters)
grep -rn "from core\.infrastructure\.adapters\." core/infrastructure/adapters/ --include="*.py" | grep -v "__init__"
```

### 2. Circular Import Detection

```bash
# Bidirectional import patterns
# Case where A imports B and B imports A
grep -rn "from core\.memory" core/orchestration/ --include="*.py"
grep -rn "from core\.orchestration" core/memory/ --include="*.py"

# TYPE_CHECKING guard for circular avoidance verification
grep -rn "if TYPE_CHECKING" core/ --include="*.py"
```

### 3. Heavy Import (Eager Loading)

```bash
# Heavy packages loaded at module level
grep -rn "^import anthropic\|^import openai\|^import langgraph" core/ --include="*.py"
grep -rn "^from anthropic\|^from openai\|^from langgraph" core/ --include="*.py" | grep -v "TYPE_CHECKING"

# Lazy import pattern inside functions
grep -rn "def.*:" core/ --include="*.py" -A3 | grep "import "
```

Rules:
- Heavy SDKs like `anthropic`, `openai`, `langgraph` should use TYPE_CHECKING guard or lazy import inside functions
- Lightweight packages like `Pydantic`, `dataclasses`, `typing` are OK at module level

### 4. Port Bypass Detection

```bash
# Direct import of implementations without Port Protocol
grep -rn "from core\.llm\.client import" core/nodes/ --include="*.py"
grep -rn "from core\.memory\.session import" core/nodes/ --include="*.py"
grep -rn "from core\.memory\.organization import" core/nodes/ --include="*.py"

# Correct pattern: access through Port
grep -rn "from core\.infrastructure\.ports" core/ --include="*.py"
```

## GEODE Existing Findings

| Pattern | Status | Notes |
|---------|--------|-------|
| ContextVar DI | Normal | `set_llm_callable()`, `set_domain()`, etc. |
| Port/Adapter separation | Normal | Protocol defined in `ports/` directory |
| TYPE_CHECKING guard | Partially applied | Applied in `runtime.py`, `sub_agent.py` |
| Lazy import | Partially applied | Deferred loading in `_build_*` methods |
