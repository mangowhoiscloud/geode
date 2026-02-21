---
name: geode-gitflow
description: GEODE 프로젝트 Gitflow 브랜치 전략 가이드. feature/release/hotfix 브랜치 생성, PR 규칙, 커밋 컨벤션, CI 워크플로우. "branch", "git", "gitflow", "feature", "release", "hotfix", "pr", "merge", "커밋" 키워드로 트리거.
---

# GEODE Gitflow Strategy

## Branch Structure

```
main ──────────────────────────────────── production (tag: v6.x.x)
  │
  └── develop ─────────────────────────── integration
        │
        ├── feature/feedback-loop ──────── GAP-1 구현
        ├── feature/tool-system ────────── Tool Protocol + Registry
        ├── feature/memory-layer ───────── L2 Memory
        ├── release/v6.1.0 ─────────────── 릴리스 준비
        └── hotfix/scoring-fix ─────────── 긴급 수정
```

## Branch Rules

| Branch | From | Merge To | PR Required | CI Must Pass |
|--------|------|----------|-------------|--------------|
| `main` | — | — | Yes (from release/hotfix) | Yes |
| `develop` | main | — | Yes (from feature) | Yes |
| `feature/*` | develop | develop | Yes | Yes |
| `release/*` | develop | main + develop | Yes | Yes |
| `hotfix/*` | main | main + develop | Yes | Yes |

## Branch Naming

```
feature/<short-description>    # feature/feedback-loop
feature/<issue-id>-<desc>      # feature/GAP-1-verify-loop
release/v<semver>              # release/v6.1.0
hotfix/<description>           # hotfix/scoring-weight-fix
```

## Commit Convention

```
<type>(<scope>): <description>

Types: feat, fix, refactor, test, docs, ci, chore
Scopes: pipeline, scoring, analysis, verification, cli, memory, tools
```

Examples:
```
feat(pipeline): add VERIFY→GATHER feedback loop
fix(scoring): correct D-axis exclusion from recovery
test(analysis): add clean context isolation tests
ci: add mypy to GitHub Actions workflow
docs: update CLAUDE.md with gitflow skill
```

## Workflow Commands

### Start feature
```bash
git checkout develop
git pull origin develop
git checkout -b feature/<name>
```

### Complete feature
```bash
git push -u origin feature/<name>
gh pr create --base develop --title "feat: <description>"
```

### Start release
```bash
git checkout develop
git checkout -b release/v6.x.0
# bump version in pyproject.toml
# test, fix, then PR to main + develop
```

### Hotfix
```bash
git checkout main
git checkout -b hotfix/<name>
# fix, then PR to main + develop
```

## CI Requirements

All PRs must pass:
1. `ruff check` — lint
2. `ruff format --check` — formatting
3. `mypy` — type checking
4. `pytest` — 98+ tests pass

## Priority Feature Branches (from layer-implementation-plan.md)

| Priority | Branch | GAP |
|----------|--------|-----|
| P0 | `feature/feedback-loop` | GAP-1: VERIFY→GATHER 루프 |
| P0 | `feature/tool-system` | Tool Protocol + Registry |
| P0 | `feature/llm-port` | LLMClientPort multi-provider |
| P1 | `feature/cross-llm` | GAP-4: Cross-LLM 실제 구현 |
| P1 | `feature/planner` | L4 Planner (Gemini Flash) |
| P1 | `feature/memory-layer` | L2 Memory 3-tier |
