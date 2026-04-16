# Plan: [Feature Name]

> Copy this template to `docs/plans/<feature-name>.md` when planning a new feature.
> Move to `docs/plans/_done/` when implementation is complete.

## Problem

What problem does this solve? What breaks without it?

## Socratic Gate

| # | Question | Answer |
|---|----------|--------|
| Q1 | Does it already exist in code? | |
| Q2 | What breaks if we don't do this? | |
| Q3 | How do we measure the effect? | |
| Q4 | What is the simplest implementation? | |
| Q5 | Is this pattern in 3+ frontier systems? | |

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

```bash
uv run ruff check core/ tests/
uv run mypy core/
uv run pytest tests/ -m "not live"
```

## References

- Related issue: #
- Frontier precedent: (Claude Code / Codex / OpenClaw / autoresearch)
