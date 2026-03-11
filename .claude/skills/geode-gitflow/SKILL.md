---
name: geode-gitflow
description: GEODE 브랜치 전략 및 PR 규칙. feature → develop → main 머지 플로우, 한글 PR, assignee 설정, CI 실패 수정 루프. "branch", "git", "pr", "merge", "커밋", "풀리퀘스트" 키워드로 트리거.
---

# GEODE Git & PR Workflow

## Merge Flow (필수)

**feature → develop → main** 순서. 직접 로컬 머지 금지 — 반드시 PR 생성 → CI 통과 → merge.

```
feature/xxx ──PR──→ develop ──PR──→ main
```

## PR 생성 → CI → Merge 절차

```bash
# 1. feature 브랜치에서 커밋 + 푸시
git push origin feature/<name>

# 2. feature → develop PR 생성 (한글, assignee 자신)
gh pr create --base develop --assignee mangowhoiscloud \
  --title "<type>: <한글 설명>" \
  --body "$(cat <<'EOF'
## 요약
<1-3줄 요약>

## 변경 사항
- 항목 1
- 항목 2

## 테스트
- [ ] `uv run pytest tests/ -q` 통과
- [ ] `uv run ruff check core/ tests/` 통과
- [ ] `uv run mypy core/` 통과

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"

# 3. CI 통과 대기
gh pr checks <PR#> --watch

# 4. CI 통과 → merge
gh pr merge <PR#> --merge

# 5. develop → main PR 생성 (동일 형식)
gh pr create --base main --head develop --assignee mangowhoiscloud \
  --title "<type>: <동일 한글 설명>" \
  --body "$(cat <<'EOF'
## 요약
develop → main 동기화. <요약>

## 테스트
- [ ] CI 통과

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"

# 6. CI 통과 → merge
gh pr checks <PR#> --watch
gh pr merge <PR#> --merge
```

## CI 실패 시 수정 루프

```
PR 생성 → CI 실행 → 실패?
  ├─ Yes → 로그 확인 (gh pr checks / gh run view)
  │        → 원인 수정 (lint/type/test/coverage)
  │        → 커밋 + 푸시 (같은 브랜치)
  │        → CI 자동 재실행 → 실패? (통과할 때까지 반복)
  └─ No  → gh pr merge --merge
```

### 흔한 CI 실패 원인과 대응

| 실패 | 대응 |
|------|------|
| `coverage < 75%` | 커버리지 부족 모듈에 테스트 추가 |
| `ruff` lint 에러 | `uv run ruff check --fix core/ tests/` + `uv run ruff format core/ tests/` |
| `mypy` 타입 에러 | 타입 수정, `# type: ignore` 최소화 |
| `bandit` 보안 경고 | `# nosec` 또는 pyproject.toml skips에 추가 (정당한 경우만) |
| pre-commit stash 충돌 | `git stash` → 커밋 → `git stash pop` |

## PR 작성 규칙

| 항목 | 규칙 |
|------|------|
| **언어** | **한글** (제목 + 본문) |
| **제목** | `<type>: <한글 설명>` (70자 이내) |
| **Assignee** | `--assignee mangowhoiscloud` (항상) |
| **본문** | `## 요약` → `## 변경 사항` → `## 테스트` |
| **Base** | feature → `develop`, develop → `main` |

## Branch Structure

```
main ─────────────────────────── production (stable, tagged)
  │
  └── develop ────────────────── integration (CI 필수)
        │
        ├── feature/<name> ───── 기능 개발
        ├── hotfix/<name> ────── 긴급 수정 (main에서 분기)
        └── release/v<semver> ── 릴리스 준비
```

## Commit Convention

```
<type>(<scope>): <description>

Types: feat, fix, refactor, test, docs, ci, chore
Scopes: pipeline, scoring, analysis, verification, cli, memory, tools, llm

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
```

## CI 게이트 (모든 PR)

```bash
uv run pytest tests/ -q              # 1950+ pass, coverage ≥ 75%
uv run ruff check core/ tests/       # 0 errors
uv run mypy core/                    # 0 errors
uv run bandit -r core/ -c pyproject.toml  # 0 errors
```

## 로컬 머지 (PR 생성 불가 시 예외)

GitHub "No commits between" 오류 등 PR 생성 불가 시에만 로컬 머지 허용:

```bash
git stash
git checkout develop && git merge feature/<name> --no-edit && git push origin develop
git checkout main && git merge develop --no-edit && git push origin main
git checkout feature/<name> && git stash pop
```
