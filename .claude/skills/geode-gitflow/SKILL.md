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
<본문 상세 템플릿 적용 — 아래 참조>
EOF
)"

# 3. CI 통과 대기
gh pr checks <PR#> --watch

# 4. CI 통과 → merge
gh pr merge <PR#> --merge

# 5. develop → main PR 생성
gh pr create --base main --head develop --assignee mangowhoiscloud \
  --title "<type>: <동일 한글 설명>" \
  --body "$(cat <<'EOF'
<develop → main 템플릿 적용 — 아래 참조>
EOF
)"

# 6. CI 통과 → merge
gh pr checks <PR#> --watch
gh pr merge <PR#> --merge
```

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
- `파일경로`: 변경 내용
  - 근거

### 부수 변경 (코드)
- `파일경로`: 리네임/포맷/타입 수정 등

### 문서/설정 변경
- `CHANGELOG.md`: 추가된 항목
- `CLAUDE.md`: 갱신 항목 (해당 시)
- `pyproject.toml`: 의존성/설정 변경 (해당 시)

## 영향 범위
- **영향받는 모듈**: <목록 — 예: pipeline 노드 전체, CLI, MCP Server>
- **하위 호환성**: 유지 / 깨짐
  - 깨짐 시: 무엇이 깨지고, 마이그레이션 방법은?

## 설계 판단 (해당 시)
- 왜 A 방식 대신 B 방식을 선택했는가?
- 고려했으나 채택하지 않은 대안은?
- 향후 확장 시 주의할 점은?

## Docs-Sync (필수)
- [ ] `CHANGELOG.md` `[Unreleased]`에 변경 항목 추가됨 (Added/Changed/Fixed)
- [ ] `CLAUDE.md` 수치 동기화 (Tests, Modules — 변경 시)
- [ ] `README.md` 수치 동기화 (변경 시)

## 테스트
- [ ] `uv run ruff check core/ tests/` — 0 errors
- [ ] `uv run mypy core/` — 0 errors
- [ ] `uv run pytest tests/ -q` — XXXX+ pass
- [ ] CLI dry-run 정상: `uv run geode analyze "Berserk" --dry-run`
- [ ] pre-commit hooks 전체 통과
- [ ] 신규 테스트 추가: X개 (해당 시)
- [ ] 기존 테스트 수정: X개 (해당 시 — 왜 수정했는지 명시)

## 검증 체크리스트 (해당 시)
- [ ] `grep -r "이전_이름" core/ tests/` — 0 hits (리네임 완전성)
- [ ] get_domain_or_none() != None (도메인 와이어링)
- [ ] LangSmith 트레이스 정상 (라이브 테스트 시)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### PR 본문 작성 지침

1. **요약**: "무엇을" + "왜"를 반드시 포함. 코드 변경 나열이 아닌 동기(motivation) 중심.
2. **핵심 변경**: 파일 단위로 나열하되, 각 변경의 **근거(왜?)** 를 한 줄 덧붙인다.
3. **부수 변경**: 리네임, 포맷, import 정리 등 핵심이 아닌 변경은 분리.
4. **영향 범위**: 리뷰어가 "어디를 중점 확인해야 하는지" 판단할 수 있게.
5. **설계 판단**: 비자명한 선택이 있으면 근거를 남긴다. 면접에서도 쓸 수 있는 기록.
6. **테스트**: 체크박스는 실제 실행 결과로 채운다 (XXXX → 실제 숫자).
7. **검증 체크리스트**: 이번 PR 특유의 검증 항목 (리네임이면 grep 0 hits 등).

### PR 본문 안티패턴

| 안티패턴 | 올바른 방식 |
|---------|------------|
| "여러 파일 수정" | 파일별 구체적 변경 내용 |
| "테스트 통과" | 실제 테스트 수 + pass 수 |
| "리팩터링" | 무엇을 왜 리팩터링했는지 |
| 변경 사항만 나열 | 왜 변경했는지 동기 포함 |
| 영향 범위 생략 | 영향받는 모듈 명시 |

## PR 본문 템플릿 (develop → main)

```markdown
## 요약
develop → main 머지. <주요 변경 1줄 요약>.

## 포함된 변경
- <feature PR 제목 #번호>
- (여러 PR이 누적된 경우 모두 나열)

## 테스트
- [x] CI 전체 통과 (<체크 항목 나열>)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
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
uv run pytest tests/ -q              # 2168+ pass, coverage ≥ 75%
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
