---
name: geode-gitflow
description: GEODE 브랜치 전략 및 PR 규칙. feature → develop → main 머지 플로우, Pre-PR Quality Gate (CI 가드레일 + docs-sync 반복 루프), Post-PR CI 래칫 (gh pr checks --watch 필수), 한글 PR, assignee 설정. "branch", "git", "pr", "merge", "커밋", "풀리퀘스트" 키워드로 트리거.
---

# GEODE Git & PR Workflow

## Merge Flow (필수)

**feature → develop → main** 순서. 직접 main push 금지 — 반드시 PR 경유.

```
feature/xxx ──PR──→ develop ──PR──→ main
```

## 전체 워크플로우

> **원칙 1**: 모든 작업 단위는 **worktree open(alloc)으로 시작, worktree close(free)로 종료**.
> 본 레포에서 직접 `git checkout feature/*` 금지. 예외 없음.
>
> **원칙 2**: develop merge는 **큐 방식** — 한 번에 하나만. merge 후 다음 worktree rebase.

```
0.  ★ Frontier Research (신규 인프라 기능 시)
    DISCOVER → COMPARE → DECIDE → DOCUMENT
1.  worktree open + feature 브랜치 생성  ← alloc
2.  코드 변경 (worktree 내에서)
3.  ★ Pre-PR Quality Gate (반복)
4.  커밋 (코드 + docs 함께)
5.  PR 생성 (feature → develop)
6.  ★★ Post-PR CI 래칫 (필수)
7.  merge (feature → develop)            ← 큐: 한 번에 하나만
8.  develop → main PR 생성 (배치 가능)
9.  ★★ Post-PR CI 래칫 (필수)
10. merge (develop → main)
11. ★★★ Docs-Sync 최종 검증
12. worktree close + 브랜치 삭제          ← free
```

> **Step 0 적용 기준**: 새 인프라 기능(Gap, 아키텍처 변경) 구현 시 필수.
> 단순 버그 수정, 문서 업데이트, 기존 패턴 반복에는 생략 가능.

### Develop Merge Queue (병렬 worktree 운용 시)

여러 worktree를 동시에 열어 작업할 때, develop merge는 순차 큐로 관리한다.

```
Worktree A (fix/xxx)  ──→ PR → CI pass → merge #1 ──┐
                                                      │ develop 갱신
Worktree B (fix/yyy)  ──→ PR → CI pass ──→ rebase ──→ merge #2 ──┐
                                                                   │
Worktree C (fix/zzz)  ──→ PR → CI pass ──→ rebase ──→ merge #3 ──┘
                                                                   │
                                              develop → main PR (배치)
```

**큐 규칙:**
- develop에 merge는 한 번에 하나만 (충돌 방지)
- merge 후 대기 중인 다음 worktree는 develop rebase 후 push
- CI 재실행 후 merge (rebase로 코드가 바뀌었으므로)
- develop → main은 여러 feature를 모아 배치 가능

```bash
# 큐 순서 관리 — 다음 worktree rebase
cd .claude/worktrees/<다음-작업명>
git fetch origin develop
git rebase origin/develop
git push --force-with-lease
# → CI 재트리거 → pass 확인 → merge
```

---

## Step 0: ★ Frontier Research (구현 전 필수 리서치)

> 적용 기준: 새 인프라 기능(Gap, 아키텍처 변경) 구현 시 필수. 단순 버그 수정에는 생략 가능.

프론티어 하네스(Claude Code, Codex CLI, OpenClaw, Aider, autoresearch 등)에서
주제 관련 구현을 조사하고 비교 매트릭스를 만든 후 설계 판단을 기록한다.

```
DISCOVER (병렬 Agent로 하네스 조사)
  → COMPARE (기능 × 하네스 매트릭스)
  → DECIDE (Option A/B/C + 선택 근거)
  → DOCUMENT (docs/plans/research-<topic>.md)
```

> 오픈소스(Codex, Aider, autoresearch, OpenClaw)는 `gh api`로 소스 직접 검증.
> 비공개(Claude Code만)는 공식 문서/2차 소스 — 검증 한계 명시.

---

## Step 1: Worktree Open (alloc)

**모든 작업 단위**는 worktree를 열어서 시작한다. 예외 없음.

```bash
# 1. develop 최신화 (본 레포에서)
git checkout develop && git pull origin develop

# 2. worktree 생성 = 작업 공간 할당
git worktree add .claude/worktrees/<작업명> -b feature/<브랜치명> develop

# 3. 작업 디렉터리 이동
cd .claude/worktrees/<작업명>

# → 이후 Step 2~11은 모두 이 worktree 안에서 수행
```

**Worktree 규칙:**
- `.claude/worktrees/`는 `.gitignore`에 포함
- worktree 내에서 `git checkout` 금지 (HEAD 충돌)
- 본 레포에서 `git checkout feature/*` 금지 — 반드시 worktree로만 접근
- 누수 점검: `git worktree list`로 닫히지 않은 worktree 확인

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
│                                         │
│  ※ 점검 렌즈 상세: code-review-workflow  │
│    (구조·의존성·보안·마이그레이션·성능)  │
└────────────────┬────────────────────────┘
                 │ 전부 통과
                 ▼
┌─────────────────────────────────────────┐
│  Step 2: Docs 작성 (코드 변경 시 필수)   │
│                                         │
│  □ CHANGELOG.md [Unreleased]에 항목 추가 │
│    - Added / Changed / Fixed / Removed  │
│    - 코드 변경 없으면 생략 가능          │
│                                         │
│  □ CLAUDE.md 수치 동기화 (해당 시)       │
│    - Tests, Modules 변경 시             │
│                                         │
│  □ docs/progress.md 오늘 날짜 섹션 갱신  │
│    - 완료 테이블 + 누락/잔여 테이블      │
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
| **CI 미확인 상태에서 merge** | **깨진 코드가 main 진입** | **gh pr checks --watch 필수** |

---

## ★★ Post-PR CI 래칫 — Merge 전 필수 (CRITICAL)

> **Karpathy P4**: 래칫 = 검증 통과해야 전진, 실패하면 롤백.
> CI green이 아닌 PR을 merge하는 것은 **래칫 위반**이다.

### 절대 규칙

**`gh pr merge`를 실행하기 전에 반드시 `gh pr checks`로 CI 상태를 확인하라.**
CI가 아직 실행 중이거나 실패 상태이면 merge 금지.

### Merge 래칫 루프

```
PR 생성 완료
   │
   ▼
┌──────────────────────────────────────────────────┐
│  Step A: CI 완료 대기 + 결과 확인                  │
│                                                  │
│  gh pr checks <PR#> --watch --repo <owner/repo>  │
│                                                  │
│  → 전부 pass  → Step B로 진행                     │
│  → 하나라도 fail → Step C로 진행                  │
│  → pending/running → 대기 (--watch가 자동 대기)   │
└────────────────┬─────────────────────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌──────────────┐  ┌──────────────────────────────┐
│  Step B:     │  │  Step C: 실패 수정 루프        │
│  Merge 실행  │  │                                │
│              │  │  1. gh run view --log-failed   │
│  gh pr merge │  │     → 실패 원인 확인            │
│  <PR#>       │  │  2. 로컬에서 원인 수정          │
│  --merge     │  │  3. 커밋 + push (같은 브랜치)   │
│              │  │  4. CI 자동 재트리거            │
│              │  │  5. Step A로 복귀               │
│              │  │                                │
│              │  │  (통과할 때까지 무한 반복)       │
└──────────────┘  └──────────────────────────────┘
```

### Merge 명령 템플릿 (복사해서 사용)

```bash
# ── feature → develop ──

# 1. PR 생성
gh pr create --base develop --assignee mangowhoiscloud \
  --title "<type>: <한글 설명>" \
  --body "<본문 상세 템플릿>"

# 2. ★★ CI 래칫: checks 통과 대기 (MUST — 생략 절대 금지)
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode

# 3. 전부 pass 확인 후에만 merge
gh pr merge <PR#> --merge --repo mangowhoiscloud/geode

# ── develop → main ──

# 4. PR 생성
gh pr create --base main --head develop --assignee mangowhoiscloud \
  --title "<type>: <설명> (develop → main)" \
  --body "<develop → main 템플릿>"

# 5. ★★ CI 래칫: checks 통과 대기 (MUST — 생략 절대 금지)
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode

# 6. 전부 pass 확인 후에만 merge
gh pr merge <PR#> --merge --repo mangowhoiscloud/geode
```

### CI 실패 시 수정 루프

```bash
# 실패 로그 확인
gh pr checks <PR#> --repo mangowhoiscloud/geode
gh run view <run_id> --log-failed

# 로컬 수정 → push → CI 자동 재실행
# ... 수정 ...
git add -A && git commit -m "fix: <CI 실패 원인 수정>"
git push

# 다시 래칫 확인
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode
# pass → merge
```

### 흔한 CI 실패 원인과 대응

| 실패 | 대응 |
|------|------|
| `ruff` lint 에러 | `uv run ruff check --fix core/ tests/` + `uv run ruff format core/ tests/` |
| `mypy` 타입 에러 | 타입 수정, `# type: ignore` 최소화 |
| `bandit` 보안 경고 | `# nosec` 또는 pyproject.toml skips에 추가 (정당한 경우만) |
| `pytest` 실패 | 테스트 코드 수정, 새 코드에 테스트 추가 |
| `coverage < 75%` | 커버리지 부족 모듈에 테스트 추가 |

---

## PR 작성 규칙

| 항목 | 규칙 |
|------|------|
| **언어** | **한글** (제목 + 본문 모두) |
| **제목** | `<type>: <한글 설명>` (70자 이내) |
| **Assignee** | `--assignee mangowhoiscloud` (항상) |
| **Base** | feature → `develop`, develop → `main` |

### ★ PR 본문 빌드 규칙 (CRITICAL — 반드시 준수)

> **PR 본문이 부실하면 리뷰어가 변경 의도를 파악할 수 없다.**
> 1-3줄짜리 PR 본문은 **안티패턴**이다. 아래 템플릿의 모든 필수 섹션을 빠짐없이 채워라.

**PR body 생성 전 반드시 수행할 것:**
1. `git diff develop...HEAD`로 전체 diff를 확인하라
2. 변경된 **모든 파일**을 핵심/부수/문서로 분류하라
3. 각 파일 변경에 대해 **왜(Why)** 이렇게 바꿨는지 한 줄 근거를 작성하라
4. 테스트 결과 수치는 **실제 실행 출력**에서 복사하라 (XXXX 자리표시자 금지)
5. HEREDOC 포맷으로 전달하라 (줄바꿈/마크다운 깨짐 방지)

### 안티패턴 vs 올바른 PR 본문

| 안티패턴 (금지) | 올바른 방식 |
|----------------|------------|
| `"progress hooks"` (3단어) | 요약 + 변경사항 + 영향범위 + QG 전부 작성 |
| `"develop → main 머지. X 변경."` (1줄) | develop→main도 포함된 PR 번호, CI 확인 결과 명시 |
| 변경 파일 나열 없이 요약만 | 파일별 AS-IS → TO-BE + 근거 한 줄 |
| `XXXX passed` (자리표시자) | `2168 passed` (실제 수치) |
| Quality Gate 체크리스트 생략 | 5개 CI 도구 + 4개 docs 항목 전부 체크 |

## PR 본문 상세 템플릿 (feature → develop)

**모든 섹션이 필수이다. 해당 없으면 "해당 없음"으로 명시하라.**

```markdown
## 요약
<!-- 필수. 2-3줄. "무엇을" + "왜" 변경했는지. 배경 동기 포함. -->

<변경의 핵심을 2-3문장으로. 어떤 문제가 있었고, 이 PR이 어떻게 해결하는지.>

## 변경 사항

### 핵심 변경 (코드)
<!-- 필수. 모든 변경 파일을 빠짐없이 나열. -->
- `파일경로:라인범위`: 변경 내용 — AS-IS → TO-BE
  - 근거: 왜 이렇게 바꿨는지 한 줄 설명

### 부수 변경 (코드)
<!-- 해당 없으면 "없음" 명시 -->
- `파일경로`: 리네임/포맷/타입 수정 등

### 문서/설정 변경
<!-- 필수. 코드 변경이 있으면 CHANGELOG은 반드시 포함. -->
- `CHANGELOG.md`: [Unreleased] > Fixed/Added/Changed에 추가한 항목
- `CLAUDE.md`: 갱신 항목 (해당 시)
- `pyproject.toml`: 의존성/설정 변경 (해당 시)

## 영향 범위
<!-- 필수. -->
- **영향받는 모듈**: <core/cli, core/ui 등 구체적 경로>
- **하위 호환성**: 유지 / 깨짐 (깨지면 마이그레이션 가이드 첨부)
- **테스트 변경**: 추가 N개 / 수정 N개 / 삭제 N개

## 설계 판단
<!-- 구조적 변경 시 필수. 단순 버그 수정은 "단순 수정, 설계 판단 불필요" 명시. -->
- 왜 A 방식 대신 B 방식을 선택했는가?
- 프론티어 하네스 사례 참조 시: `docs/plans/research-<topic>.md` 링크
- 대안 비교: Option A(장점/단점) vs Option B(장점/단점) → 선택 근거

## Pre-PR Quality Gate (필수 — 실제 실행 결과 복사)
- [x] `ruff check` — 0 errors
- [x] `ruff format --check` — OK (N files)
- [x] `mypy core/` — Success (N source files)
- [x] `bandit -r core/` — 0 issues
- [x] `pytest -m "not live"` — **N passed** in Xs
- [x] CHANGELOG.md [Unreleased] 항목 추가됨
- [x] README.md 수치 정합성 확인됨
- [ ] CLAUDE.md 동기화 (해당 시)
- [x] docs/progress.md 오늘 날짜 섹션 갱신됨

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## PR 본문 템플릿 (develop → main)

```markdown
## 요약
develop → main 머지. <주요 변경 1-2줄 요약. 어떤 기능/수정이 포함되었는지.>

## 포함된 변경
<!-- 필수. 모든 feature PR을 번호와 제목 포함하여 나열. -->
- #번호 `<type>: <제목>` — 핵심 변경 1줄 요약
- #번호 `<type>: <제목>` — 핵심 변경 1줄 요약

## 변경 수치
- **파일**: N개 변경
- **테스트**: N passed (이전 대비 +N/-N)
- **모듈**: N개 (변동 시 명시)

## 테스트
- [x] CI 전체 통과 (`gh pr checks --watch` 확인 완료)
- [x] feature → develop CI 통과 확인됨

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### gh pr create 명령 — HEREDOC 필수

PR 본문은 반드시 **HEREDOC** 포맷으로 전달한다. 인라인 `--body "..."` 사용 금지.

```bash
# ✅ 올바른 방식: HEREDOC
gh pr create --base develop --assignee mangowhoiscloud \
  --title "<type>: <한글 설명>" \
  --body "$(cat <<'PRBODY'
## 요약
...전체 템플릿 채우기...

🤖 Generated with [Claude Code](https://claude.com/claude-code)
PRBODY
)"

# ❌ 금지: 인라인 (줄바꿈 깨짐, 내용 축약 유발)
gh pr create --body "한 줄 요약"
```

---

## ★★★ Docs-Sync 최종 검증 (main 머지 후, 정리 전)

> 작업 단위가 main까지 마무리된 후 수행한다.
> Pre-PR Step 2에서 docs를 작성했더라도, 머지 과정에서 수치가 달라질 수 있으므로 최종 검증이 필요하다.

### 검증 체크리스트

```
main 머지 완료 (step 10)
   │
   ▼
┌──────────────────────────────────────────────────┐
│  □ README.md 수치 정합성                          │
│    - modules: find core/ -name "*.py" | wc -l    │
│    - tests: uv run pytest --co 2>&1 | wc -l      │
│    - tools 수, 버전                              │
│                                                  │
│  □ CLAUDE.md 수치 정합성                          │
│    - Tests, Modules 동일 기준으로 확인            │
│                                                  │
│  □ CHANGELOG.md [Unreleased] 누락 여부            │
│    - main에 들어간 변경이 기록되어 있는가         │
│                                                  │
│  □ docs/progress.md 오늘 날짜 섹션 존재 여부      │
│    - 없으면 추가 후 커밋                          │
│                                                  │
│  □ pyproject.toml coverage omit                   │
│    - 새 모듈이 omit에 빠져서 coverage 깨지는지    │
│                                                  │
│  → 불일치 발견 시:                                │
│    docs(sync) 커밋 → feature → develop → main    │
│    (동일한 gitflow 루프 적용)                     │
│  → 문제 없으면: step 12 (작업 공간 정리) 진행     │
└──────────────────────────────────────────────────┘
```

### Pre-PR Step 2 vs Docs-Sync 최종 검증

| 단계 | 시점 | 역할 |
|------|------|------|
| Pre-PR Step 2 | 커밋 전 | docs **작성** (CHANGELOG 항목, CLAUDE.md 수치) |
| Docs-Sync 최종 검증 | main 머지 후 | docs **검증** (README 수치, coverage omit, 누락 확인) |

Pre-PR에서 docs를 작성하고, main 머지 후 최종 검증으로 빠진 것을 잡는 2중 구조.

---

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

## CI Pipeline (GitHub Actions)

```
lint ─────┐
typecheck ─┤
test ──────┼──→ gate (전부 통과해야 merge 가능)
security ──┘
```

```bash
# 로컬 CI 가드레일 (Pre-PR)
uv run ruff check core/ tests/
uv run ruff format --check core/ tests/
uv run mypy core/
uv run bandit -r core/ -c pyproject.toml
uv run pytest tests/ -m "not live" -q

# GitHub CI 래칫 (Post-PR, merge 전 필수)
gh pr checks <PR#> --watch --repo mangowhoiscloud/geode
```

## Step 12: Worktree Close (free)

**merge 완료 후** 반드시 worktree를 닫는다. 예외 없음.

```bash
# 1. 본 레포로 복귀
cd /Users/mango/workspace/geode

# 2. develop/main 최신화
git checkout develop && git pull origin develop

# 3. worktree 제거 = 작업 공간 해제
git worktree remove .claude/worktrees/<작업명>

# 4. 브랜치 정리 (로컬 + 리모트)
git branch -d feature/<브랜치명>
git push origin --delete feature/<브랜치명>

# 5. 누수 점검
git worktree list   # 닫히지 않은 worktree 없어야 함
```

---

## 로컬 머지 (PR 생성 불가 시 예외)

GitHub "No commits between" 오류 등 PR 생성 불가 시에만 로컬 머지 허용:

```bash
git stash
git checkout develop && git merge feature/<name> --no-edit && git push origin develop
git checkout main && git merge develop --no-edit && git push origin main
git checkout feature/<name> && git stash pop
```
