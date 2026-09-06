---
name: dependency-review
description: Review GEODE dependency direction, composition boundaries, circular imports, and optional-dependency loading when changing package or subsystem dependencies.
---

# Dependency & Layer Review Lens

Review against [code conventions](../../../docs/architecture/naming-conventions.md)
and the executable import-linter contracts in [pyproject.toml](../../../pyproject.toml).
The historical six-layer/plugin map is not the current dependency contract.

## Ownership and direction

```text
evolve -> evals -> core
evolve --------> core
```

`core` owns the runtime; `evals` measures it; `evolve` searches over runtime
evidence. Neither `core -> evals/evolve` nor `evals -> evolve` is allowed.
Within `core`, follow the named process/capability contracts rather than
inventing a numeric layer order.

- `core.wiring` composes services through constructors and existing typed contexts.
- Use a narrow, named Protocol at a real consumer/provider boundary. A concrete
  import inside the owning subsystem is not automatically a port violation;
  one implementation does not invalidate an existing isolation boundary.
- ContextVars carry request identity, diagnostics, or request-local state, not
  service-locator DI. Do not hide a forbidden dependency behind a late import.

## Review Checklist

### 1. Trace imports against the active contracts

```bash
rg -n '^(from|import) (evals|evolve)' core/ -g '*.py'
rg -n '^(from|import) evolve' evals/ -g '*.py'
uv run lint-imports
```

Search results are candidates: inspect guarded, dynamic, and transitive imports
and the importing caller. The gate owns the declared forbidden directions.

### 2. Check cycles and composition

```bash
rg -n 'from core\.memory' core/orchestration/ -g '*.py'
rg -n 'from core\.orchestration' core/memory/ -g '*.py'
rg -n 'TYPE_CHECKING|ContextVar|Protocol' core/ -g '*.py'
```

For each suspected cycle, trace the actual import chain and the service's
construction, binding, and teardown. A `TYPE_CHECKING` guard is not evidence
that runtime composition is safe, and a Protocol count is not a quality score.

### 3. Verify optional and cold-start imports

Keep imports at module level unless an optional dependency, a measured startup
cost, or a genuine cycle justifies deferral. Load optional SDKs at their owning
adapter boundary. A fresh-interpreter check must fail if the forbidden eager
import occurs; do not skip merely because the SDK is already imported.

### 4. Report ownership and the surviving contract

Name the caller, dependency owner, violated contract, smallest correction, and
the behavioral/import test that must survive. Use current source evidence;
historical architecture inventories are not automatic deletion instructions.
