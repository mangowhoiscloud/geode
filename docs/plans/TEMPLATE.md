# Plan: [Feature Name]

> Optional for work needing durable research, decisions, or cross-session
> resumption. A bounded change can keep the same information in its issue/PR.
> Omit inapplicable sections. Keep completed evidence at its linked path.
> Architecture/extensibility plans must reference a stable GAP ID from
> `docs/architecture/extensibility-roadmap.md`; that roadmap alone owns program
> status and closure evidence.

## Problem

What problem does this solve? What breaks without it?

## Scope and acceptance

Name the requirement owner, allowed changes, preserved behavior, non-goals,
observable acceptance, and checker. Separate conformance from product usefulness
and comparison validity. See the [convention](../architecture/naming-conventions.md#requirements-plans-and-evidence).

## Existing behavior and evidence

Trace callers and readers before choosing the smallest change. For backend
work, follow request/turn/session identity, failure, persistence, retry, and
readback boundaries. Record confirmed, rejected, and unresolved claims.
Research only relevant primary sources; source count is not an adoption gate.

## Design

### Approach

Describe the implementation approach.

### Affected Files

| File | Change |
|------|--------|
| `core/...` | |

### Alternatives Considered

What other approaches were evaluated and why they were rejected.

## Implementation Checklist

- [ ] Implementation
- [ ] Tests
- [ ] Lint + Type check
- [ ] Documentation update (if applicable)
- [ ] CHANGELOG entry

## Verification

Choose checks from the [verification reference](../../.agents/skills/geode-workflow/references/verification-gates.md).
Before execution, list planned checks. After execution, record revision,
environment, commands, outcomes, failures, and skipped scope separately.

## Progress and decisions

Keep completed work, remaining work, discoveries, requirement changes, and
keep/change/remove decisions distinguishable. A checked box is a status label;
link the observation that supports it. Record rollback/recovery when affected.

## References

- Related issue: #
- Frontier precedent: (Claude Code / Codex / OpenClaw / autoresearch)
