---
name: geode-code-conventions
description: Apply GEODE's measured architecture, module and symbol naming, Python type/class, persisted schema, test, site, and versioning conventions. Use when adding or moving modules, choosing dataclass/Pydantic/Protocol/ABC forms, naming classes or files, designing stored data, reviewing convention compliance, or deciding compatibility and release version treatment.
---

# GEODE Code Conventions

Use this skill to make a convention decision against the current repository,
not against a generic Python style guide.

## Canonical reference

Read `docs/architecture/naming-conventions.md` completely before changing code.
It is the detailed convention SOT. Do not copy its tables into this skill.

Executable configuration remains authoritative:

- `pyproject.toml` for Ruff, mypy, pytest, import-linter, dependency, security,
  and coverage gates;
- `AGENTS.md` and `docs/workflow.md` for repository workflow;
- `site/DESIGN.md`, `site/tsconfig.json`, and `site/eslint.config.mjs` for the
  public site;
- the subsystem contract nearest the changed code for local invariants.

## Workflow

1. **Locate ownership.** Identify the top-level root and the package that owns
   the decision. Confirm allowed dependency direction before naming anything.
2. **Inspect siblings.** Search the nearest canonical modules, their tests, and
   their public imports. Classify an apparent pattern as required, preferred,
   compatibility-only, or historical.
3. **Choose the smallest form.** Prefer a function, focused module, dataclass,
   or concrete class before adding a Protocol, registry, factory, or package.
4. **Separate identities.** Keep module names, Python types, persisted schema
   IDs, protocol versions, algorithm versions, and package versions as distinct
   decisions.
5. **Apply symmetrically.** Update imports, exports, tests, registries, schema
   validators, docs, and generated mirrors that share the contract. Do not add
   an alias unless a released consumer needs the documented grace period.
6. **Audit the diff.** Search for the old name, parent-relative imports, generic
   catch-all names, unbounded `Any`, hidden mutation, missing teardown, stale
   schema IDs, and version stamp drift.
7. **Verify proportionally.** Run the targeted behavior test and the exact
   static/build gates for every touched language and layer. Report what did not
   run.

## Decision rules

- Package context removes redundant filename prefixes; persisted artifact
  identity does not change merely because a module moved.
- Protocol is the normal structural port. Use ABC only for a shared template
  algorithm with real subclass hooks.
- Use frozen/slotted dataclasses for immutable internal values, Pydantic at
  validated external/config/LLM boundaries, TypedDict for deliberately
  dict-shaped bridges, and StrEnum for reusable closed persisted vocabularies.
- Keep `Any` at the untyped boundary and narrow it immediately.
- Use absolute imports across boundaries; allow only level-one relative imports
  inside a tightly coupled local package.
- Give every persisted record one authority, schema identity, validator, and
  version axis. Writers emit current schemas; legacy readers are explicit.
- Treat observed zero/false/empty values separately from missing `None`/`null`.
- Keep direct output in CLIs and scripts; library modules use structured,
  redacted logging.
- Mirror production package paths in tests and prove wiring pairs together.
- Routine post-1.0 releases are PATCH; MINOR/MAJOR require operator approval.

## Specialist routing

Use this skill with, rather than instead of:

| Need | Skill or SOT |
|---|---|
| implementation and GitFlow | `$geode-workflow` |
| dependency cycles or layer violations | `$dependency-review` |
| Python quality and lifecycle review | `$code-review-quality` |
| schema/log/event/trajectory consistency | `$geode-workflow` observability reference |
| evaluation artifacts | `$geode-eval` |
| model-facing prompt text | `$prompt-writing` |
| changelog or release version | `$geode-changelog` |

## Output contract

State the ownership, selected convention, local precedent, compatibility
impact, and verification evidence. If deviating, name the exact rule, explain
why the local contract is stronger, and keep the exception scoped to the
introducing change.
