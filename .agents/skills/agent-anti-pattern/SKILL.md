---
name: agent-anti-pattern
description: Audit agent runtimes and their tests for lifecycle inference, capability overload, context pollution, correlated verification, prompt-only control, false success, dead compatibility paths, test-only seams, and complexity without contribution. Use for whole-repository agent audits, slop or dead-code triage, test contribution reviews, large refactors, tool/context simplification, and cleanup requests that need proof before deleting code or tests.
---

# Agent Anti-Pattern Audit

Treat a static hit as a candidate, never as a finding. Prove the failure
mechanism, affected consumer, and safe correction before changing code.

Read [references/field-guide.md](references/field-guide.md) before triage. It
defines the source grades, six anti-pattern families, false-positive
boundaries, finding record, and deletion gate.

## Workflow

1. Freeze the base commit, tracked scope, exclusions, and generated inventory.
2. Reuse existing linters, dependency checks, slop scans, and test collectors.
   Do not create another scanner for a check they already perform.
3. Trace each candidate through static callers plus entrypoints, registries,
   decorators, import-by-string, side-effect imports, subprocess workers,
   schemas, public exports, persisted data, and compatibility contracts.
4. Apply AP-1 through AP-6 from the field guide. Record a harmful consequence
   or measured non-contribution; size, duplication, or unfamiliarity alone is
   insufficient.
5. Map affected tests to behavior and invariants. Detect source-string false
   positives, broad-exception false greens, private-shape pinning, environment
   leakage, duplicated scenarios, and tests that exist only to keep dead
   production seams alive.
6. Report every candidate as `KEEP`, `SHRINK`, `DELETE`, `MEASURE`, or `DEFER`.
   Stop for review before a whole-repository audit edits production or tests.
7. Apply accepted cleanup in small causal groups. Preserve one canonical
   implementation and rerun objective gates after every group.

## Verdicts

| Verdict | Meaning |
|---|---|
| `KEEP` | A named behavior, safety, evidence, compatibility, or operational consumer justifies the surface. |
| `SHRINK` | The contract is real, but a wrapper, branch, payload, capability, or test can be narrowed. |
| `DELETE` | The complete deletion gate passes and no contribution remains. |
| `MEASURE` | A suspected problem has a falsifiable hypothesis but insufficient evidence. |
| `DEFER` | The problem is real but ownership, migration, dependency, or approval blocks safe change. |

## GEODE Routing

Use the repository's existing surfaces when present:

- `.geode/skills/slop-audit/SKILL.md` and `scripts/slop_audit.py` for
  discovery-only heuristics;
- `.claude/skills/codebase-audit/SKILL.md` for general refactor workflow;
- `.claude/skills/anti-deception-checklist/SKILL.md` after every cleanup diff;
- Ruff, mypy, deptry, import-linter, architecture baseline, and pytest for
  deterministic verification.

Do not copy their instructions into this skill. Their results remain separate
authorities because they scan different scopes and definitions.

## Boundaries

- Do not impose universal tool-count, context-token, file-size, parameter, or
  line-count thresholds. Treat published numbers as setup-specific unless the
  target contract makes them normative.
- Do not infer dead code from zero textual imports. Check dynamic and external
  consumers first.
- Do not infer duplication from a shared method name or protocol signature.
- Do not delete tests together with code and call the resulting green suite
  proof. Name the surviving invariant.
- Do not convert a safety, migration, evidence, redaction, or rollback surface
  into slop merely because it adds code.
- Do not add a framework, store, registry, schema, dashboard, or automation
  without a named consumer and a repeated deterministic gap.
- Fail closed to `MEASURE` or `DEFER` when evidence is incomplete.

## Output

Report:

1. base SHA, included/excluded inventory, and checks actually run;
2. coverage by audit bucket, without claiming every line was manually read;
3. findings with exact paths, evidence, falsifier, verdict, and smallest fix;
4. explicit false positives and retained surfaces;
5. cleanup order, verification, skipped/live gates, and remaining uncertainty.
