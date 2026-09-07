---
name: pr-reviewer
visibility: public
triggers: review, PR 리뷰, 코드 리뷰, diff, 풀리퀘스트 검토
description: Automated Git PR review — diff analysis + quality checks.
tools: run_bash, memory_save
risk: safe
---

# PR Reviewer

Review code changes against the current repository contracts. A review request
does not authorize code edits, PR mutations, or memory writes. Use only
available, permitted read-only inspection; a supplied diff can be reviewed
without shell access, with any missing context stated explicitly.

## Review Perspectives (5-lens)

### 1. Consistency

- Do changes match the PR title/description
- Are changes within the scope specified in plan documents (docs/plans/)
- Are there unrelated changes mixed in

### 2. Safety

- Are there DANGEROUS tool additions/modifications
- Secret/key exposure risks
- SQL injection, command injection patterns

### 3. Testing

- Are there corresponding tests for the changed code
- Have tests been deleted/disabled (anti-deception)
- Coverage regression

### 4. Architecture

- `core/`, `evals/`, and `evolve/` ownership and dependency-direction
  violations; use `AGENTS.md` and `docs/architecture/package-classification.md`
  for the current contract, not the retired 6-layer map
- Circular import introduction
- God Object bloat

### 5. Style

- ruff/mypy pass status
- Naming consistency
- Unnecessary comments/docstrings

## Usage

```
Review PR #520
```

or

```
Review the last 3 commits
```

## Output Format

```markdown
## PR Review — #NNN

### Summary
- Files changed: N
- Additions/Deletions: +XX / -YY

### Findings
| Severity | File:Line | Issue |
|----------|-----------|-------|
| HIGH | core/x.py:42 | ... |
| LOW | tests/y.py:10 | ... |

### Verdict
- [ ] Consistency OK
- [ ] Safety OK
- [ ] Testing OK
- [ ] Architecture OK
- [ ] Style OK
```

## Guidelines

- Review based on actual diff via `git diff` or `gh pr diff`
- No guessing — read the code and judge
- Severity levels: HIGH (blocks merge), MEDIUM (recommended fix), LOW (improvement suggestion)
- If no findings, say so with the inspected scope and verification limits;
  do not imply unrun tests passed or the PR is ready to merge
