---
name: geode-gitflow
description: GEODE 브랜치 전략 및 PR 규칙. feature → develop → main 머지 플로우, Pre-PR Quality Gate (CI 가드레일 + docs-sync 반복 루프), 한글 PR, assignee 설정. "branch", "git", "pr", "merge", "커밋", "풀리퀘스트" 키워드로 트리거.
---

# GEODE Git & PR Workflow

## Merge Flow (필수)

**feature → develop → main** 순서. 직접 main push 금지 — 반드시 PR 경유.

```
feature/xxx ──PR──→ develop ──PR──→ main
```

## 전체 워크플로우

```
1. feature 브랜치 생성 (develop에서)
2. 코드 변경
3. ★ Pre-PR Quality Gate (반복)  ← 이 루프를 통과해야 PR 생성 가능
4. 커밋 (코드 + docs 함께)
5. PR 생성 (feature → develop)
6. CI 통과 확인 → merge
7. develop → main PR → merge
```

---

## ★ Pre-PR Quality Gate (커밋 전 필수 루프)

**코드 변경 후, 커밋/PR 전에 반드시 이 루프를 통과해야 한다.**

```
코드 변경 완료
   │
   ▼
┌─────────────────────────────────────────┐
│  Step 1: CI 가드레일 (전부 통과해야 진행) │
│                                         │
│  uv run ruff check core/ tests/         │ → 실패 시: ruff --fix 후 재실행
│  uv run ruff format --check core/ tests/│ → 실패 시: ruff format 후 재실행
│  uv run mypy core/                      │ → 실패 시: 타입 수정 후 재실행
│  uv run bandit -r core/ -c pyproject.toml│ → 실패 시: 보안 수정 후 재실행
│  uv run pytest tests/ -m "not live" -q  │ → 실패 시: 테스트 수정 후 재실행
│                                         │
│  하나라도 실패 → 수정 → Step 1 재실행    │
└────────────────┬────────────────────────┘
                 │ 전부 통과
                 ▼
┌─────────────────────────────────────────┐
│  Step 2: Docs-Sync (코드 변경 시 필수)   │
│                                         │
│  □ CHANGELOG.md [Unreleased]에 항목 추가 │
│    - Added / Changed / Fixed 분류       │
│    - 코드 변경 없으면 생략 가능          │
│                                         │
│  □ README.md 수치 정합성 확인            │
│    - 버전, 테스트 수, 모듈 수, 도구 수   │
│    - grep "v0\.\|2168\|131 module" 등   │
│                                         │
│  □ CLAUDE.md 수치 동기화 (해당 시)       │
│    - Tests, Modules 변경 시             │
│                                         │
│  □ pyproject.toml / core/__init__.py     │
│    - 버전 범프 필요 시 (릴리스)          │
│                                         │
│  누락 발견 → 수정 → Step 1 재실행        │
└────────────────┬────────────────────────┘
                 │ 모두 완료
                 ▼
┌─────────────────────────────────────────┐
│  Step 3: 커밋                            │
│                                         │
│  코드 + docs를 하나의 커밋에 포함        │
│  docs만 별도 커밋 금지 (정합성 유지)     │
│                                         │
│  git add <코드파일> CHANGELOG.md ...     │
│  git commit -m "<type>: <설명>"          │
└────────────────┬────────────────────────┘
                 │
                 ▼
           PR 생성 가능
```

### Quality Gate 위반 시 안티패턴

| 안티패턴 | 결과 | 올바른 방식 |
|---------|------|------------|
| CI 실패 상태에서 PR 생성 | 리뷰어 시간 낭비 | 로컬에서 전부 통과 후 PR |
| 코드만 커밋, docs 별도 PR | CHANGELOG 누락, 버전 불일치 | 코드 + docs 동일 커밋 |
| main에 직접 push | gitflow 위반, 이력 오염 | 반드시 PR 경유 |
| docs-sync 생략 | README/CHANGELOG 낙후 | Step 2 체크리스트 필수 |

---

## PR 생성 → CI → Merge 절차

```bash
# 1. feature 브랜치에서 커밋 + 푸시 (Quality Gate 통과 후)
git push origin feature/<name>

# 2. feature → develop PR 생성 (한글, assignee 자신)
gh pr create --base develop --assignee mangowhoiscloud \
  --title "<type>: <한글 설명>" \
  --body "<본문 상세 템플릿 적용>"

# 3. CI 통과 확인 → merge
gh pr merge <PR#> --merge

# 4. develop → main PR 생성 + merge
gh pr create --base main --head develop --assignee mangowhoiscloud \
  --title "<type>: <동일 설명> (develop → main)" \
  --body "<develop → main 템플릿>"
gh pr merge <PR#> --merge
```

---

## PR 작성 규칙

| 항목 | 규칙 |
|------|------|
| **언어** | **한글** (제목 + 본문 모두) |
| **제목** | `<type>: <한글 설명>` (70자 이내) |
| **Assignee** | `--assignee mangowhoiscloud` (항상) |
| **Base** | feature → `develop`, develop → `main` |

## PR 본문 상세 템플릿 (feature → develop)

**반드시 이 구조를 따른다. 각 섹션을 빠짐없이 채운다.**

```markdown
## 요약
<1-3줄. 무엇을 왜 변경했는지 핵심만. 배경 동기 포함.>

## 변경 사항

### 핵심 변경 (코드)
- `파일경로`: 변경 내용 — AS-IS → TO-BE 간략 설명
  - 왜 이렇게 바꿨는지 한 줄 근거

### 부수 변경 (코드)
- `파일경로`: 리네임/포맷/타입 수정 등

### 문서/설정 변경
- `CHANGELOG.md`: 추가된 항목
- `CLAUDE.md`: 갱신 항목 (해당 시)
- `pyproject.toml`: 의존성/설정 변경 (해당 시)

## 영향 범위
- **영향받는 모듈**: <목록>
- **하위 호환성**: 유지 / 깨짐

## 설계 판단 (해당 시)
- 왜 A 방식 대신 B 방식을 선택했는가?

## Pre-PR Quality Gate (필수 — 실제 실행 결과)
- [x] `uv run ruff check core/ tests/` — 0 errors
- [x] `uv run ruff format --check core/ tests/` — OK
- [x] `uv run mypy core/` — 0 errors
- [x] `uv run bandit -r core/` — 0 issues
- [x] `uv run pytest -m "not live"` — XXXX passed
- [x] CHANGELOG.md [Unreleased] 항목 추가됨
- [x] README.md 수치 정합성 확인됨
- [ ] CLAUDE.md 동기화 (해당 시)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## PR 본문 템플릿 (develop → main)

```markdown
## 요약
develop → main 머지. <주요 변경 1줄 요약>.

## 포함된 변경
- <feature PR 제목 #번호>

## 테스트
- [x] CI 전체 통과

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

---

## CI 실패 시 수정 루프 (PR 생성 후)

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
| `ruff` lint 에러 | `uv run ruff check --fix core/ tests/` + `uv run ruff format core/ tests/` |
| `mypy` 타입 에러 | 타입 수정, `# type: ignore` 최소화 |
| `bandit` 보안 경고 | `# nosec` 또는 pyproject.toml skips에 추가 (정당한 경우만) |
| `coverage < 75%` | 커버리지 부족 모듈에 테스트 추가 |
| pre-commit stash 충돌 | `git stash` → 커밋 → `git stash pop` |

---

## Worktree 작업 공간 분할

병렬 작업이나 독립 기능 개발 시 git worktree로 격리된 작업 공간을 생성한다.

```bash
# 생성
git worktree add .claude/worktrees/<작업명> -b feature/<브랜치명>
cd .claude/worktrees/<작업명>

# 작업 완료 후 정리 (worktree + 브랜치 삭제)
git push origin feature/<브랜치명>
cd /path/to/original/repo
git worktree remove .claude/worktrees/<작업명>
git branch -d feature/<브랜치명>
```

- worktree 내에서 `git checkout` 금지
- `.claude/worktrees/`는 `.gitignore`에 포함

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
uv run ruff check core/ tests/       # 0 errors
uv run ruff format --check core/ tests/ # all formatted
uv run mypy core/                    # 0 errors
uv run bandit -r core/ -c pyproject.toml  # 0 errors
uv run pytest tests/ -m "not live" -q # 2168+ pass
```

## 로컬 머지 (PR 생성 불가 시 예외)

GitHub "No commits between" 오류 등 PR 생성 불가 시에만 로컬 머지 허용:

```bash
git stash
git checkout develop && git merge feature/<name> --no-edit && git push origin develop
git checkout main && git merge develop --no-edit && git push origin main
git checkout feature/<name> && git stash pop
```
